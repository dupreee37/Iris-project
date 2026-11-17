import asyncio
from types import SimpleNamespace

import pytest

from iris.audio import Playback
from iris.brain import Brain
from iris.demo_voice import DemoConversation
from iris.feedback import Feedback
from iris.monitor import with_monitor
from iris.realtime_voice import NativeConversation


def test_display_priority_keeps_voice_visible_during_background_work():
    feedback = Feedback()
    feedback.update(ready=True, capturing=True, awake=True)
    feedback.task("search", "research_web", "running")
    assert feedback.snapshot.expression == "thinking"
    feedback.update(hearing=True)
    assert feedback.snapshot.expression == "listening"
    feedback.update(speaking=True, hearing=False)
    assert feedback.snapshot.expression == "speaking"
    feedback.update(speaking=False)
    feedback.task("search", "research_web", "completed")
    assert feedback.snapshot.expression == "listening"
    feedback.stop()
    assert feedback.snapshot.expression == "idle" and not feedback.snapshot.capturing


def test_observer_failure_cannot_break_conversation_and_data_stays_bounded(caplog):
    feedback = Feedback()
    def broken(_):
        raise RuntimeError("display disconnected")
    unsubscribe = feedback.subscribe(broken)
    feedback.update(ready=True)
    assert "observador" in caplog.text
    unsubscribe()
    for i in range(50):
        feedback.transcript("Vos", str(i))
        feedback.task(str(i), "research_web", "completed")
    assert len(feedback.snapshot.messages) == 40
    assert len(feedback.snapshot.tasks) == 12
    assert feedback.snapshot.messages[-1] == ("Vos", "49")


async def test_closing_visual_monitor_cancels_session_and_runs_cleanup():
    feedback = Feedback()
    cleaned = asyncio.Event()
    views = []
    class View:
        def __init__(self, _):
            self.pumps, self.closed = 0, False
            views.append(self)
        def pump(self):
            self.pumps += 1
            return self.pumps < 2
        def close(self): self.closed = True
    async def session():
        feedback.update(capturing=True)
        try:
            await asyncio.Event().wait()
        finally:
            feedback.stop()
            cleaned.set()
    await with_monitor(session, feedback, View)
    assert cleaned.is_set() and views[0].closed and not feedback.snapshot.capturing


async def test_visual_runner_preserves_voice_errors_and_closes_window():
    view = SimpleNamespace(pump=lambda: True, close=lambda: setattr(view, "closed", True), closed=False)
    async def failed_session(): raise RuntimeError("voice device unavailable")
    with pytest.raises(RuntimeError, match="voice device"):
        await with_monitor(failed_session, Feedback(), lambda _: view)
    assert view.closed


async def test_monitor_reflects_played_audio_and_real_turn_events():
    feedback = Feedback(mode="live")
    feedback.update(ready=True, capturing=True, awake=True)
    async def send(_): pass
    class Manager:
        def validate(self, *_): pass
    audio = SimpleNamespace(playback=Playback())
    conversation = NativeConversation(send, audio, Brain(Manager()), log=lambda _: None, feedback=feedback)
    audio.playback.add("answer", 0, b"\1\0" * 1000)
    await conversation.tick()
    assert feedback.snapshot.expression == "speaking"
    await conversation.event({"type": "input_audio_buffer.speech_started", "item_id": "user"})
    assert feedback.snapshot.expression == "listening" and not feedback.snapshot.speaking
    await conversation.event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "user", "transcript": "Iris necesito ayuda"})
    assert feedback.snapshot.messages[-1] == ("Vos", "Iris necesito ayuda")
    await conversation.close()
    assert not feedback.snapshot.capturing


async def test_demo_observer_receives_actual_spoken_turns_and_job_completion():
    class Speaker:
        async def say(self, _):
            assert feedback.snapshot.expression == "speaking"
    class Manager:
        def validate(self, _, args): return args
        async def execute(self, *_args, **_kwargs): return {"text": "demo"}
    feedback = Feedback()
    feedback.update(ready=True, capturing=True)
    brain = Brain(Manager())
    conversation = DemoConversation(brain, Speaker(), log=lambda _: None, feedback=feedback)
    await conversation.hear("Iris necesito que investigues sobre robots")
    await conversation.current
    assert feedback.snapshot.tasks[-1].status == "completed"
    assert feedback.snapshot.awake and feedback.snapshot.expression == "listening"
    assert feedback.snapshot.messages[0][0] == "Vos"
    assert "no consulté internet" in feedback.snapshot.messages[-1][1]
    await conversation.cancel()
    await brain.close()
