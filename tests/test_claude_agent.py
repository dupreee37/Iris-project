import asyncio
import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from iris.brain import Brain
from iris.claude_agent import ClaudeAgent, explain, speakable
from iris.claude_voice import ClaudeConversation
from iris.config import Settings
from iris.providers import Providers
from iris.tools import ToolManager


def text(value):
    return NS(type="text", text=value)


def tool_use(name, **arguments):
    return NS(type="tool_use", id=f"toolu_{name}", name=name, input=arguments)


def response(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop)


class Stream:
    """Imita AsyncMessageStream: el texto llega en pedacitos, como en la API real."""

    def __init__(self, item):
        self.item = item

    async def __aenter__(self):
        if isinstance(self.item, Exception):
            raise self.item
        if callable(self.item):
            self.item = await self.item()
        return self

    async def __aexit__(self, *_):
        return False

    async def __aiter__(self):
        for block in self.item.content:
            if block.type == "text":
                for i in range(0, len(block.text), 7):
                    yield NS(type="text", text=block.text[i:i + 7])
            yield NS(type="content_block_stop")

    async def get_final_message(self):
        return self.item


class Messages:
    def __init__(self, scripted):
        self.scripted, self.requests = list(scripted), []

    def stream(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=lambda o: o.__dict__)))
        return Stream(self.scripted.pop(0))


class FakeClient:
    def __init__(self, *scripted):
        self.messages = Messages(scripted)
        self.beta = NS(messages=self.messages)


def make(*scripted, **settings):
    settings = Settings(_env_file=None, iris_mode="demo", iris_claude_fallbacks=False, **settings)
    client = httpx.AsyncClient()
    brain = Brain(ToolManager(Providers(settings, client)))
    fake = FakeClient(*scripted)
    return ClaudeAgent(settings, brain, fake), brain, fake, client


async def test_plain_reply_is_speakable_and_saved():
    agent, brain, fake, client = make(response(text("**Hola** vos, mirá https://x.org\n- listo")))
    assert await agent.reply("hola") == "Hola vos, mirá listo"
    assert [m["role"] for m in agent.history] == ["user", "assistant"]
    sent = fake.messages.requests[0]
    assert sent["model"] == "claude-sonnet-5-5" and sent["thinking"] == {"type": "adaptive"}
    assert {t.get("name") for t in sent["tools"]} == {"web_search", "web_fetch", "device_status", "open_url", "open_app"}
    await brain.close()
    await client.aclose()


async def test_local_tool_result_goes_back_with_matching_id():
    agent, brain, fake, client = make(
        response(tool_use("device_status"), stop="tool_use"), response(text("Estoy en Windows.")))
    assert await agent.reply("¿qué equipo sos?") == "Estoy en Windows."
    result = fake.messages.requests[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_device_status" and not result["is_error"]
    assert "esp32_connected" in result["content"]
    await brain.close()
    await client.aclose()


async def test_strict_mode_waits_for_a_casual_yes_then_runs():
    agent, brain, fake, client = make(iris_confirm_actions="strict", *(
        response(tool_use("open_app", app="Calculadora"), stop="tool_use"),
        response(text("¿La abro?")),
        response(text("Listo, la abrí."))))
    assert await agent.reply("abrí la calculadora") == "¿La abro?"
    assert agent.pending is not None and agent.pending.status == "awaiting_approval"
    assert "pendiente_de_confirmacion" in fake.messages.requests[1]["messages"][-1]["content"][0]["content"]
    job = agent.pending
    assert await agent.reply("Sí, dale, hacelo.") == "Listo, la abrí."
    assert job.status == "completed" and job.result["simulated"]
    note = fake.messages.requests[2]["messages"][-1]["content"][1]["text"]
    assert "Confirmó" in note and "open_app" in note
    await brain.close()
    await client.aclose()


async def test_a_no_cancels_pending_action():
    agent, brain, fake, client = make(iris_confirm_actions="strict", *(
        response(tool_use("open_url", url="https://example.com"), stop="tool_use"),
        response(text("¿La abro?")),
        response(text("Está bien, no la abro."))))
    await agent.reply("abrí example")
    job = agent.pending
    await agent.reply("no, mejor no")
    assert job.status == "cancelled" and agent.pending is None
    assert "se canceló" in fake.messages.requests[2]["messages"][-1]["content"][1]["text"]
    await brain.close()
    await client.aclose()


async def test_app_outside_allowlist_is_refused():
    agent, brain, fake, client = make(iris_confirm_actions="strict", *(
        response(tool_use("open_app", app="regedit"), stop="tool_use"), response(text("x")),
        response(text("No puedo."))))
    await agent.reply("abrí regedit")
    await agent.reply("confirmo")
    assert agent.pending is None
    # The refused result came back to Claude as data, not as an executed launch.
    last = fake.messages.requests[2]["messages"][-1]["content"][1]["text"]
    assert '"opened": false' in last and "fuera de la lista" in last
    await brain.close()
    await client.aclose()


async def test_pause_turn_continues_and_invalid_args_are_reported():
    agent, brain, fake, client = make(
        response(text("buscando"), stop="pause_turn"),
        response(tool_use("open_url", url="file:///c:/secreto"), stop="tool_use"),
        response(text("No pude abrir eso.")))
    # Lo que Claude dice antes de usar herramientas también se habla («buscando…»): da respuesta inmediata.
    assert await agent.reply("buscá algo") == "buscando No pude abrir eso."
    assert fake.messages.requests[2]["messages"][-1]["content"][0]["is_error"]
    assert agent.pending is None
    await brain.close()
    await client.aclose()


async def test_refusal_and_api_errors_do_not_touch_history():
    err = anthropic.RateLimitError("x", response=httpx.Response(429, request=httpx.Request("POST", "https://a")), body=None)
    agent, brain, fake, client = make(response(text(""), stop="refusal"), err)
    assert "no puedo" in (await agent.reply("algo")).lower()
    assert "cuota" in await agent.reply("otra")
    assert agent.history == []
    await brain.close()
    await client.aclose()


async def test_cancelled_turn_leaves_history_consistent():
    async def hang():
        await asyncio.Event().wait()
    agent, brain, fake, client = make(hang, response(text("ok")))
    task = asyncio.create_task(agent.reply("lento"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent.history == []
    assert await agent.reply("de nuevo") == "ok"
    assert len(agent.history) == 2
    await brain.close()
    await client.aclose()


def test_speakable_and_explain_never_leak_details():
    assert speakable("# Título\n* uno `dos` https://a.b/c") == "Título uno dos"
    request = httpx.Request("POST", "https://a")
    credit = anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=request), body=None)
    assert "créditos" in explain(credit)
    assert "sk-ant" not in explain(RuntimeError("sk-ant-secret"))


class Speaker:
    def __init__(self):
        self.said = []

    async def say(self, value):
        self.said.append(value)


async def test_conversation_needs_wake_word_and_sleep_resets():
    agent, brain, fake, client = make(response(text("Hace sol.")))
    speaker = Speaker()
    talk = ClaudeConversation(agent, speaker, log=lambda _: None)
    await talk.hear("qué hora es")  # sin «Iris» se ignora
    assert fake.messages.requests == []
    await talk.hear("Iris, ¿cómo está el clima?")
    await talk.current
    assert speaker.said == ["Hace sol."]
    assert fake.messages.requests[0]["messages"][0]["content"][0]["text"] == "¿cómo está el clima?"
    await talk.hear("Iris, dormí")
    assert agent.history == [] and not talk.awake
    await brain.close()
    await client.aclose()


async def test_history_keeps_only_what_was_said_not_search_or_tool_blocks():
    agent, brain, fake, client = make(
        response(tool_use("device_status"), stop="tool_use"), response(text("Estoy en Windows.")),
        response(text("De nada.")))
    await agent.reply("¿qué equipo sos?")
    assert [m["role"] for m in agent.history] == ["user", "assistant"]
    assert agent.history[1]["content"] == "Estoy en Windows."
    await agent.reply("gracias")
    # El segundo turno reenvía sólo el texto del primero, sin tool_use ni tool_result.
    assert fake.messages.requests[2]["messages"][1] == {"role": "assistant", "content": "Estoy en Windows."}
    await brain.close()
    await client.aclose()


async def test_noise_and_idle_do_not_reach_claude():
    agent, brain, fake, client = make(response(text("Hola.")), response(text("Sí.")), response(text("Dale.")))
    talk = ClaudeConversation(agent, Speaker(), log=lambda _: None)
    await talk.hear("Iris, hola")
    await talk.current
    await talk.hear("eh")  # una palabra suelta: ruido
    await talk.hear("mm mm")  # no activa nada nuevo aquí: dos palabras sí pasan
    await talk.current
    assert len(fake.messages.requests) == 2
    await talk.hear("sí")  # confirmación corta válida
    await talk.current
    assert len(fake.messages.requests) == 3
    talk.last -= 3600  # una hora sin hablar
    await talk.hear("contame algo largo")
    assert len(fake.messages.requests) == 3 and not talk.awake
    await brain.close()
    await client.aclose()


async def test_each_sentence_is_spoken_as_soon_as_it_is_complete():
    agent, brain, fake, client = make(response(text("Dale, lo busco. Tu sitio es alejomonardez.com y está online.")))
    speaker = Speaker()
    talk = ClaudeConversation(agent, speaker, log=lambda _: None)
    await talk.hear("Iris, buscá mi portafolio")
    await talk.current
    # Dos frases, dos llamadas a la voz; el dominio no se corta en el punto.
    assert speaker.said == ["Dale, lo busco.", "Tu sitio es alejomonardez.com y está online."]
    assert agent.history[1]["content"] == "Dale, lo busco. Tu sitio es alejomonardez.com y está online."
    await brain.close()
    await client.aclose()


async def test_correction_while_thinking_is_merged_with_the_first_request():
    async def slow():
        await asyncio.sleep(10)
    agent, brain, fake, client = make(slow, response(text("Abro alejomonardez.com.")))
    talk = ClaudeConversation(agent, Speaker(), log=lambda _: None)
    await talk.hear("Iris, investigá el portafolio de alejomonarrez.com")
    await asyncio.sleep(0.01)
    await talk.hear("no, monardez.com")  # te corregís mientras piensa
    await talk.current
    sent = fake.messages.requests[1]["messages"][-1]["content"][0]["text"]
    assert sent == "investigá el portafolio de alejomonarrez.com no, monardez.com"
    assert talk.unanswered is None and len(agent.history) == 2
    await brain.close()
    await client.aclose()


def test_echo_of_its_own_voice_does_not_count_as_interruption():
    talk = ClaudeConversation(NS(settings=Settings(_env_file=None)), Speaker(), log=lambda _: None)
    talk.spoken.append("Tu portafolio está publicado en alejomonardez punto com")
    assert not talk.is_user_speech("tu portafolio esta publicado")  # eco de lo que IRIS dice
    assert not talk.is_user_speech("tu portafolio publicado ayuda")  # eco mal oído: una sola palabra nueva
    assert not talk.is_user_speech("")
    assert talk.is_user_speech("pará")  # una palabra de corte alcanza
    assert talk.is_user_speech("no quiero eso abrí otra cosa")


async def test_interrupt_stops_speech_and_keeps_request_for_next_turn():
    agent, brain, fake, client = make(response(text("Una respuesta larguísima. Que sigue. Y sigue.")),
                                      response(text("Ok, cambio.")))

    class SlowSpeaker(Speaker):
        async def say(self, value):
            self.said.append(value)
            await asyncio.sleep(10)

    speaker = SlowSpeaker()
    talk = ClaudeConversation(agent, speaker, log=lambda _: None)
    await talk.hear("Iris, contame algo")
    await asyncio.sleep(0.05)
    assert speaker.said == ["Una respuesta larguísima."]
    await talk.interrupt()
    assert talk.current is None and speaker.said == ["Una respuesta larguísima."]
    # Claude ya había terminado de escribir: ese turno quedó en el historial y no se repite.
    assert talk.unanswered is None and len(agent.history) == 2
    await brain.close()
    await client.aclose()


async def test_natural_mode_opens_what_you_ask_without_a_magic_phrase():
    agent, brain, fake, client = make(
        response(tool_use("open_url", url="https://alejomonardez.com"), stop="tool_use"),
        response(text("Listo, te abrí el portafolio.")))
    assert await agent.reply("abrí el portafolio de alejomonardez.com") == "Listo, te abrí el portafolio."
    result = fake.messages.requests[1]["messages"][-1]["content"][0]
    assert not result["is_error"] and '"simulated": true' in result["content"]  # demo: se simula, no abre
    assert agent.pending is None
    system = fake.messages.requests[0]["system"]
    assert "abrilo directamente" in system and "confirmo abrir" not in system
    await brain.close()
    await client.aclose()


def test_casual_yes_detection():
    from iris.claude_agent import is_yes
    assert all(is_yes(t) for t in ["Sí", "dale", "Sí, hacelo", "de una", "confirmo abrir", "ok, abrilo"])
    assert not any(is_yes(t) for t in ["no", "no, dejá", "qué hora es", "", "sí pero no"])


async def test_filler_plays_while_claude_is_slow():
    async def slow():
        await asyncio.sleep(0.9)
        return response(text("Listo."))
    agent, brain, fake, client = make(slow)
    speaker = Speaker()
    talk = ClaudeConversation(agent, speaker, log=lambda _: None)
    await talk.hear("Iris, pensá algo difícil")
    await talk.current
    assert len(speaker.said) == 2 and speaker.said[1] == "Listo."
    assert speaker.said[0] in ("Mmm...", "A ver...", "Ajá...", "Eh... dejame ver.", "Mmm, a ver...", "Entiendo...")
    await brain.close()
    await client.aclose()


def test_own_voice_heard_back_is_ignored_right_after_speaking():
    import time
    talk = ClaudeConversation(NS(settings=Settings(_env_file=None)), Speaker(), log=lambda _: None)
    talk.spoken.append("¿En qué te puedo ayudar?")
    talk.spoke_at = time.monotonic()
    assert talk.is_echo("¿En qué te puedo ayudar?")
    assert not talk.is_echo("abrí mi portafolio")
    talk.spoke_at -= 10  # mucho después ya no se considera eco
    assert not talk.is_echo("¿En qué te puedo ayudar?")


def test_garbled_echo_from_the_speaker_is_recognized():
    import time
    talk = ClaudeConversation(NS(settings=Settings(_env_file=None)), Speaker(), log=lambda _: None)
    talk.spoken.append("Las búsquedas me tiraron resultados de calopsitas, las aves.")
    talk.spoke_at = time.monotonic()
    assert talk.is_echo("Me tiraron resultados de cálculo")  # caso real del registro
    assert not talk.is_user_speech("tiraron resultados calculo")  # tampoco corta a IRIS
