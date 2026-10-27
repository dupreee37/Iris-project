import asyncio
import inspect
import io
import json
import threading
import time
import sys
import wave
from types import SimpleNamespace as NS

import httpx
import pytest

from iris.config import Settings
from iris.providers import ProviderError
from iris.speech import CloudRecognizer, CloudSpeaker, choose_engines, elevenlabs_pcm, openai_pcm, wav_bytes


def settings(**values):
    values.setdefault("iris_stt_hangover_seconds", 0)  # sin espera: los tests alimentan chunks de a uno
    return Settings(_env_file=None, **values)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def acc(recognizer, chunk):
    """accept() es sincrónico; al cerrar una frase devuelve la transcripción pendiente."""
    out = recognizer.accept(chunk)
    return await out if inspect.isawaitable(out) else out


async def collect(generator):
    return b"".join([chunk async for chunk in generator])


def test_engine_choice_follows_keys_and_rejects_incomplete_config():
    assert choose_engines(settings()) == ("windows", "vosk")
    assert choose_engines(settings(openai_api_key="k")) == ("openai", "openai")
    assert choose_engines(settings(openai_api_key="k", elevenlabs_api_key="e", iris_elevenlabs_voice_id="v")) == ("elevenlabs", "elevenlabs")
    # Clave sin voz: ElevenLabs no se elige solo; pedirlo explícito falla con un mensaje claro.
    assert choose_engines(settings(elevenlabs_api_key="e")) == ("windows", "elevenlabs")
    with pytest.raises(RuntimeError, match="VOICE_ID"):
        choose_engines(settings(elevenlabs_api_key="e", iris_tts="elevenlabs"))
    with pytest.raises(RuntimeError):
        choose_engines(settings(iris_stt="openai"))
    assert choose_engines(settings(openai_api_key="k", iris_tts="windows", iris_stt="vosk")) == ("windows", "vosk")


async def test_elevenlabs_request_shape_and_error_hides_body():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers["xi-api-key"], body=json.loads(request.content))
        return httpx.Response(200, content=b"\x01\x02\x03\x04")

    s = settings(elevenlabs_api_key="secret", iris_elevenlabs_voice_id="abc-123")
    async with client(handler) as c:
        assert await collect(elevenlabs_pcm(c, s, "hola")) == b"\x01\x02\x03\x04"
    assert seen["url"] == "https://api.elevenlabs.io/v1/text-to-speech/abc-123/stream?output_format=pcm_24000"
    assert seen["key"] == "secret"
    assert seen["body"] == {"text": "hola", "model_id": "eleven_flash_v2_5", "language_code": "es"}

    async with client(lambda r: httpx.Response(401, text="secret-in-body")) as c:
        with pytest.raises(ProviderError) as info:
            await collect(elevenlabs_pcm(c, s, "hola"))
    assert "secret" not in str(info.value) and "401" in str(info.value)

    bad = settings(elevenlabs_api_key="secret", iris_elevenlabs_voice_id="../x")
    async with client(handler) as c:
        with pytest.raises(ProviderError):
            await collect(elevenlabs_pcm(c, bad, "hola"))


async def test_multilingual_v2_omits_language_code():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=b"")

    s = settings(elevenlabs_api_key="k", iris_elevenlabs_voice_id="v", iris_elevenlabs_model="eleven_multilingual_v2")
    async with client(handler) as c:
        await collect(elevenlabs_pcm(c, s, "hola"))
    assert "language_code" not in seen


async def test_openai_speech_request_shape():
    seen = {}

    def handler(request):
        seen.update(auth=request.headers["authorization"], body=json.loads(request.content))
        return httpx.Response(200, content=b"\x00\x00")

    async with client(handler) as c:
        await collect(openai_pcm(c, settings(openai_api_key="k"), "hola"))
        assert seen["auth"] == "Bearer k"
        assert seen["body"]["response_format"] == "pcm" and seen["body"]["voice"] == "marin" and "instructions" in seen["body"]
        await collect(openai_pcm(c, settings(openai_api_key="k", iris_openai_tts_model="tts-1"), "hola"))
        assert "instructions" not in seen["body"]


class FakeLocal:
    """Vosk simulado: devuelve (final, parcial) por cada chunk."""

    def __init__(self, script):
        self.script, self.resets = list(script), 0

    def accept(self, pcm):
        self.current = self.script.pop(0)
        return self.current[0]

    def partial(self):
        return self.current[1]

    def reset(self):
        self.resets += 1


async def test_recognizer_sends_only_the_utterance_and_prefers_cloud_text():
    sent = []

    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json={"text": "Iris, ¿qué hora es?"})

    local = FakeLocal([(None, ""), (None, "iris"), (None, "iris que"), ("iris que hora es", "")])
    async with client(handler) as c:
        r = CloudRecognizer(local, c, settings(openai_api_key="k"))
        assert [await acc(r, b"\x01\x00" * 320) for _ in range(3)] == [None, None, None]
        assert sent == []  # nada viaja hasta que Vosk cierra la frase
        assert await acc(r, b"\x02\x00" * 320) == "Iris, ¿qué hora es?"
    assert len(sent) == 1 and b"RIFF" in sent[0] and b"frase.wav" in sent[0]
    # Medio segundo previo (silencio) + 3 chunks de habla; el silencio posterior no existe.
    assert not r.active and not r.speech


async def test_recognizer_falls_back_to_vosk_text_when_cloud_fails():
    local = FakeLocal([("hola iris", "")])
    async with client(lambda request: httpx.Response(500, text="boom")) as c:
        r = CloudRecognizer(local, c, settings(openai_api_key="k"))
        assert await acc(r, b"\x00\x00" * 320) == "hola iris"


async def test_recognizer_empty_final_resets_without_calling_cloud():
    calls = []
    local = FakeLocal([(None, "x"), ("", "")])
    async with client(lambda request: calls.append(1) or httpx.Response(200, json={"text": "no"})) as c:
        r = CloudRecognizer(local, c, settings(openai_api_key="k"))
        assert await acc(r, b"\x00\x00") is None
        assert await acc(r, b"\x00\x00") == ""
    assert calls == [] and not r.active
    r.reset()
    assert local.resets == 1


def test_wav_bytes_is_valid_16k_mono():
    with wave.open(io.BytesIO(wav_bytes(b"\x00\x00" * 160))) as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()) == (1, 2, 16000, 160)


class FakeStream:
    instances = []

    def __init__(self, callback=None, blocksize=480, **kwargs):
        self.written, self.state, self.callback, self.blocksize = [], [], callback, blocksize
        self.running = False
        FakeStream.instances.append(self)

    def start(self):
        self.state.append("start")
        self.running = True
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):  # Llama al callback como lo haría PortAudio
        while self.running:
            out = bytearray(self.blocksize * 2)
            self.callback(out, self.blocksize, None, None)
            self.written.append(bytes(out))
            time.sleep(0.002)

    def stop(self):
        self.state.append("stop")

    def abort(self):
        self.running = False
        self.state.append("abort")

    def close(self):
        self.state.append("close")


class Fallback:
    def __init__(self):
        self.said, self.closed = [], False

    async def say(self, text):
        self.said.append(text)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_audio(monkeypatch):
    FakeStream.instances = []
    monkeypatch.setitem(sys.modules, "sounddevice", NS(RawOutputStream=FakeStream))
    return FakeStream


async def test_speaker_never_splits_a_sample_and_marks_busy(fake_audio):
    async def fetch(text):
        yield b"\x01\x02\x03"
        yield b"\x04\x05"
        yield b"\x06"

    fallback = Fallback()
    speaker = CloudSpeaker(fetch, fallback)
    await speaker.say("hola")
    stream = fake_audio.instances[0]
    played = b"".join(stream.written).strip(bytes(1))
    assert played == b"\x01\x02\x03\x04\x05\x06"  # completo y sin muestras partidas
    assert stream.state == ["start", "abort", "close"]
    assert fallback.said == [] and not speaker.busy.is_set()
    speaker.close()
    assert fallback.closed


async def test_speaker_uses_windows_voice_when_provider_fails_before_audio(fake_audio):
    async def fetch(text):
        raise ProviderError("sin cuota")
        yield  # pragma: no cover

    fallback = Fallback()
    speaker = CloudSpeaker(fetch, fallback)
    await speaker.say("hola")
    assert fallback.said == ["hola"] and not speaker.busy.is_set()


async def test_speaker_does_not_repeat_text_when_provider_fails_mid_speech(fake_audio):
    async def fetch(text):
        yield b"\x01\x02"
        raise httpx.ReadError("cortado")

    fallback = Fallback()
    speaker = CloudSpeaker(fetch, fallback)
    await speaker.say("hola")
    assert fallback.said == []


def scribe(words, text="hola iris"):
    return {"text": text, "words": [{"text": w, "type": "word", "logprob": lp} for w, lp in words]}


async def test_scribe_request_shape_and_keyterms():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers["xi-api-key"], body=request.content)
        return httpx.Response(200, json=scribe([("hola", -0.1), ("iris", -0.2)]))

    local = FakeLocal([("hola iris", "")])
    async with client(handler) as c:
        r = CloudRecognizer(local, c, settings(elevenlabs_api_key="e"), "elevenlabs")
        assert await acc(r, b"\x00\x00" * 320) == "hola iris"
    assert seen["url"] == "https://api.elevenlabs.io/v1/speech-to-text" and seen["key"] == "e"
    for part in (b"scribe_v2", b'name="language_code"', b"es", b'name="keyterms"', b"Iris", b"no_verbatim"):
        assert part in seen["body"]


async def test_scribe_drops_low_confidence_noise_but_keeps_clear_speech():
    local = FakeLocal([("ruido", ""), ("hola", "")])
    answers = iter([scribe([("ah", -6.0), ("eh", -5.0)], "ah eh"), scribe([("hola", -0.3)], "Hola")])
    async with client(lambda request: httpx.Response(200, json=next(answers))) as c:
        r = CloudRecognizer(local, c, settings(elevenlabs_api_key="e"), "elevenlabs")
        assert await acc(r, b"\x00\x00") == ""  # descartado: no llega a Claude
        assert await acc(r, b"\x00\x00") == "Hola"


async def test_scribe_retries_without_keyterms_if_rejected():
    bodies = []

    def handler(request):
        bodies.append(request.content)
        if b"keyterms" in request.content:
            return httpx.Response(422, json={"detail": "x"})
        return httpx.Response(200, json=scribe([("hola", -0.1)], "hola"))

    async with client(handler) as c:
        r = CloudRecognizer(FakeLocal([("hola", "")]), c, settings(elevenlabs_api_key="e"), "elevenlabs")
        assert await acc(r, b"\x00\x00") == "hola"
    assert len(bodies) == 2 and b"keyterms" not in bodies[1]


async def test_pauses_inside_a_sentence_do_not_split_it():
    """Vosk cierra «Bueno, escúchame» en la pausa; si seguís hablando, es la misma frase."""
    sent = []

    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json=scribe([("x", -0.1)], "Bueno, escúchame, ¿qué puedo hacer como modelo?"))

    chunk = b"\x00" * 320  # 20 ms
    local = FakeLocal([(None, "bueno"), ("bueno escuchame", ""), (None, ""), (None, "como"), ("como un modelo", "")]
                      + [(None, "")] * 50)
    async with client(handler) as c:
        r = CloudRecognizer(local, c, settings(elevenlabs_api_key="e", iris_stt_hangover_seconds=0.9), "elevenlabs")
        results = [await acc(r, chunk) for _ in range(5 + 44)]
        assert results == [None] * 49 and sent == []  # todavía esperando a que termines
        assert await acc(r, chunk) == "Bueno, escúchame, ¿qué puedo hacer como modelo?"
    assert len(sent) == 1  # una sola frase llegó a Scribe (y luego a Claude)


async def test_short_phrases_are_cached_and_cancel_is_instant(fake_audio):
    calls = []

    async def fetch(text):
        calls.append(text)
        yield b"\x01\x00" * 24000 * 3  # 3 segundos de audio

    speaker = CloudSpeaker(fetch, Fallback())
    await speaker.preload(["Mmm..."])
    assert calls == ["Mmm..."]
    task = asyncio.create_task(speaker.say("Mmm..."))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert time.monotonic() - started < 0.5  # cortar no espera a que termine la frase
    assert calls == ["Mmm..."]  # sonó desde la caché, sin volver a pedirla
    assert not speaker.busy.is_set()


async def test_next_sentence_is_prepared_while_the_current_one_plays(fake_audio):
    calls = []

    async def fetch(text):
        calls.append(text)
        yield b"\x01\x00" * 240

    speaker = CloudSpeaker(fetch, Fallback())
    speaker.prefetch("Segunda frase.")
    await asyncio.sleep(0.01)
    assert calls == ["Segunda frase."]  # ya se pidió antes de que le toque sonar
    await speaker.say("Segunda frase.")
    assert calls == ["Segunda frase."] and not speaker.ahead  # sonó lo preparado, sin pedirlo otra vez
    speaker.prefetch("Otra.")
    speaker.drop_prefetch()  # al interrumpir se descarta lo preparado
    assert not speaker.ahead
