import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from iris.audio import AudioDevice, Playback
from iris.brain import Brain
from iris.config import Settings
from iris.demo_voice import DemoConversation
from iris.dialogue import DemoDialogue
from iris.realtime_voice import NativeConversation
from iris.tools import SPECS
from iris.voice import session_config


def test_offline_dialogue_clarifies_and_remembers_topic():
    dialogue = DemoDialogue()
    assert not dialogue.hear("conversación de fondo").text
    reply = dialogue.hear("Iris, necesito que investigues algo por mí")
    assert "tema" in reply.text and reply.query is None
    assert dialogue.hear("sobre baterías para un robot").query == "baterias para un robot"
    assert dialogue.hear("Iris, dormí").sleep
    assert not dialogue.hear("investigá algo").text


def test_playback_interruption_discards_unheard_audio_and_tracks_position():
    playback = Playback(rate=24000)
    playback.add("answer", 0, b"\x01\x00" * 24000)
    assert playback.read(480) == b"\x01\x00" * 480
    assert playback.interrupt() == ("answer", 0, 20)
    assert playback.read(480) == b"\0" * 960
    assert not playback.busy


def test_new_audio_not_played_is_truncated_at_zero():
    playback = Playback()
    playback.add("old", 0, b"\x01\x00" * 2)
    playback.read(2)
    playback.until = 0
    playback.add("new", 0, b"\x02\x00" * 20)
    assert playback.interrupt() == ("new", 0, 0)


def test_audio_buffers_are_bounded_and_muted_input_is_not_queued():
    playback = Playback(rate=100, max_seconds=1)
    with pytest.raises(BufferError):
        playback.add("a", 0, b"\0" * 202)
    with pytest.raises(ValueError):
        playback.add("a", 0, b"\0")
    device = AudioDevice(muted=lambda: True)
    device._capture(b"\0" * 640, 320, None, None)
    assert device.input.empty() and device.fault is None


def test_cleanup_closes_all_devices_even_if_one_abort_fails():
    class Stream:
        closed = False
        def abort(self): raise RuntimeError("Device unplugged")
        def close(self): self.closed = True
    device = AudioDevice()
    input_stream, output_stream = Stream(), Stream()
    device.streams = [input_stream, output_stream]
    device.__exit__(None, None, None)
    assert input_stream.closed and output_stream.closed


class Manager:
    def __init__(self):
        self.release = asyncio.Event()
        self.calls = []

    def validate(self, name, args):
        return SPECS[name][0].model_validate(args).model_dump()

    async def execute(self, name, args, *, approved=False):
        self.calls.append((name, args, approved))
        if name == "research_web":
            await self.release.wait()
        return {"text": "Resultado de prueba", "grounding": {"private": "big metadata"}}


def native_fixture():
    events = []
    async def send(event):
        events.append(event)
    manager = Manager()
    brain = Brain(manager)
    audio = SimpleNamespace(playback=Playback())
    return NativeConversation(send, audio, brain, log=lambda _: None), manager, events


async def test_native_waits_for_complete_turn_then_requests_spoken_response():
    conversation, _, events = native_fixture()
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "u1"})
    await conversation.result("tool", {"text": "arrived while user speaks"})
    assert not any(e["type"] == "response.create" for e in events)
    await conversation.event({"type": "input_audio_buffer.speech_stopped"})
    assert not any(e["type"] == "response.create" for e in events)
    await conversation.event({"type": "input_audio_buffer.committed", "item_id": "u1"})
    assert events[-1]["type"] == "response.create"
    await conversation.close()


async def test_native_interrupts_playback_and_drops_stale_audio():
    conversation, _, events = native_fixture()
    await conversation.event({"type": "response.created", "response": {"id": "r1"}})
    delta = {"type": "response.output_audio.delta", "response_id": "r1", "item_id": "a1", "delta": base64.b64encode(b"\1\0" * 1000).decode()}
    await conversation.event(delta)
    conversation.audio.playback.read(480)
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
    assert events[-1] == {"type": "conversation.item.truncate", "item_id": "a1", "content_index": 0, "audio_end_ms": 20}
    await conversation.event({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
    await conversation.event(delta)
    assert not conversation.audio.playback.busy
    await conversation.close()


async def test_slow_research_does_not_block_conversation_and_returns_to_voice():
    conversation, manager, events = native_fixture()
    tool = {"type": "function_call", "call_id": "call1", "name": "research_web", "arguments": '{"query":"robot"}'}
    await conversation.event({"type": "response.done", "response": {"id": "r1", "status": "completed", "output": [tool]}})
    await asyncio.sleep(0)
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
    assert conversation.speaking and conversation.workers
    manager.release.set()
    await asyncio.gather(*conversation.workers)
    output = [e for e in events if e["type"] == "conversation.item.create"][-1]
    assert "Resultado" in output["item"]["output"] and "grounding" not in output["item"]["output"]
    assert not any(e["type"] == "response.create" for e in events)
    await conversation.close()


async def test_tool_output_connection_failure_stops_session_for_cleanup():
    conversation, manager, _ = native_fixture()
    async def disconnected(_): raise ConnectionError("Disconnected")
    conversation.send = disconnected
    manager.release.set()
    tool = {"type": "function_call", "call_id": "lost", "name": "research_web", "arguments": '{"query":"robot"}'}
    await conversation.event({"type": "response.done", "response": {"status": "completed", "output": [tool]}})
    await asyncio.wait_for(conversation.done.wait(), timeout=1)
    assert isinstance(conversation.failure, ConnectionError)
    assert not conversation.workers
    await conversation.close()


async def test_voice_approval_requires_current_confirmed_user_utterance():
    conversation, manager, events = native_fixture()
    conversation.user_item = "original"
    tool = {"call_id": "open1", "name": "open_url", "arguments": '{"url":"https://example.com"}'}
    worker = asyncio.create_task(conversation._tool(tool))
    await asyncio.sleep(0)
    job = conversation.approval
    assert job.status == "awaiting_approval" and not manager.calls
    await conversation.event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "old", "transcript": "confirmo abrir"})
    assert job.status == "awaiting_approval"
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "confirmation"})
    await conversation.event({"type": "input_audio_buffer.speech_stopped"})
    await conversation.event({"type": "input_audio_buffer.committed", "item_id": "confirmation"})
    await conversation.event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "confirmation", "transcript": "Confirmo abrir."})
    await worker
    assert manager.calls == [("open_url", {"url": "https://example.com"}, True)]
    await conversation.close()


async def test_nonconfirmation_cancels_action_instead_of_treating_any_yes_as_consent():
    conversation, manager, _ = native_fixture()
    worker = asyncio.create_task(conversation._tool({"call_id": "open", "name": "open_url", "arguments": '{"url":"https://example.com"}'}))
    await asyncio.sleep(0)
    job = conversation.approval
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "new"})
    await conversation.event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "new", "transcript": "sí pero antes investigá otra cosa"})
    await worker
    assert job.status == "cancelled" and not manager.calls
    await conversation.close()


async def test_cancelled_url_does_not_leave_a_stale_spoken_approval_prompt():
    conversation, _, events = native_fixture()
    conversation.generating = True
    worker = asyncio.create_task(conversation._tool({"call_id": "open", "name": "open_url", "arguments": '{"url":"https://example.com"}'}))
    await asyncio.sleep(0)
    conversation.brain.cancel(conversation.approval)
    await worker
    conversation.generating = False
    await conversation.tick()
    response = [event for event in events if event["type"] == "response.create"][-1]
    assert "confirmación" not in response["response"].get("instructions", "")
    await conversation.close()


async def test_spoken_demo_acknowledges_work_and_reads_completion_without_cloud():
    class Speaker:
        def __init__(self): self.spoken = []
        async def say(self, text): self.spoken.append(text)
    manager, speaker = Manager(), Speaker()
    brain = Brain(manager)
    demo = DemoConversation(brain, speaker, log=lambda _: None)
    await demo.hear("Iris necesito que investigues algo por mí")
    await demo.hear("sobre robótica")
    assert "tema" in speaker.spoken[0] and "Inicio" in speaker.spoken[1]
    manager.release.set()
    await demo.current
    assert "no consulté internet" in speaker.spoken[-1]
    await demo.cancel()
    await brain.close()


def test_native_prompt_and_tools_have_no_required_visual_step():
    config = session_config(Settings(_env_file=None))
    assert "confirmación visual" not in config["instructions"]
    assert "confirmación hablada" in config["instructions"]
    assert config["audio"]["input"]["format"]["rate"] == 24000
    assert config["audio"]["output"]["format"]["type"] == "audio/pcm"
    assert "cancel_research" in {tool["name"] for tool in config["tools"]}
