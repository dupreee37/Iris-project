"""Voz y oído en la nube, opcionales. Si fallan, IRIS sigue con la voz de Windows y Vosk."""
import asyncio
import io
import logging
import re
import threading
import wave
from collections import deque

import httpx

from .config import Settings
from .providers import ProviderError

log = logging.getLogger(__name__)
TTS_RATE = 24000  # Ambos proveedores se piden como PCM16 mono a 24 kHz.
MAX_UTTERANCE = 16000 * 2 * 30  # 30 s de PCM16; más que eso se descarta.


async def elevenlabs_pcm(client: httpx.AsyncClient, s: Settings, text: str):
    voice = s.iris_elevenlabs_voice_id
    if not re.fullmatch(r"[\w-]{1,64}", voice):
        raise ProviderError("Falta o es inválido IRIS_ELEVENLABS_VOICE_ID (probá: python -m iris --voices).")
    body = {"text": text, "model_id": s.iris_elevenlabs_model}
    if s.iris_elevenlabs_model != "eleven_multilingual_v2":
        body["language_code"] = "es"  # multilingual_v2 no admite language_code
    async with client.stream(
        "POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream", params={"output_format": "pcm_24000"},
        headers={"xi-api-key": s.elevenlabs_api_key.get_secret_value()}, json=body, timeout=30,
    ) as response:
        if response.is_error:
            raise ProviderError(f"ElevenLabs respondió HTTP {response.status_code}; revisá clave, voz y cuota.")
        async for chunk in response.aiter_bytes():
            yield chunk


async def openai_pcm(client: httpx.AsyncClient, s: Settings, text: str):
    body = {"model": s.iris_openai_tts_model, "input": text, "voice": s.iris_openai_tts_voice, "response_format": "pcm"}
    if s.iris_openai_tts_model.startswith("gpt-"):  # tts-1 no admite instructions
        body["instructions"] = "Hablá en español rioplatense, con tono cálido, natural y sin apuro."
    async with client.stream(
        "POST", "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {s.openai_api_key.get_secret_value()}"}, json=body, timeout=30,
    ) as response:
        if response.is_error:
            raise ProviderError(f"OpenAI respondió HTTP {response.status_code}; revisá clave, modelo y cuota.")
        async for chunk in response.aiter_bytes():
            yield chunk


class CloudSpeaker:
    """Reproduce PCM en streaming sin bloquear: cortar la voz es inmediato y nunca se cuelga.

    Las frases cortas (muletillas, «Te escucho.») se guardan para sonar sin esperar a la red.
    Si el proveedor falla antes de sonar, habla la voz de Windows.
    """

    def __init__(self, fetch, fallback, *, output_device=None):
        self.fetch, self.fallback, self.output_device = fetch, fallback, output_device
        self.busy = threading.Event()  # El bucle del micrófono sabe que lo que oye puede ser eco.
        self.cache: dict[str, bytes] = {}
        self.ahead: dict[str, asyncio.Task] = {}  # Frases siguientes que se sintetizan mientras habla

    def prefetch(self, text):
        """Pide el audio de una frase que va a sonar después, para que no haya pausa entre frases."""
        if text not in self.cache and text not in self.ahead and len(self.ahead) < 8:
            async def collect():
                return b"".join([c async for c in self.fetch(text)])
            self.ahead[text] = asyncio.create_task(collect())

    def drop_prefetch(self):
        for task in self.ahead.values():
            task.cancel()
        self.ahead.clear()

    async def preload(self, texts):
        for text in texts:
            if text not in self.cache:
                try:
                    self.cache[text] = b"".join([c async for c in self.fetch(text)])
                except (ProviderError, httpx.HTTPError) as exc:
                    log.warning("No se pudo precargar «%s»: %s", text, type(exc).__name__)

    async def say(self, text):
        self.busy.set()
        try:
            started = False
            try:
                async for _ in self._play(text):
                    started = True
            except (ProviderError, httpx.HTTPError, OSError, BufferError) as exc:
                log.warning("Voz en la nube falló: %s", exc if isinstance(exc, ProviderError) else type(exc).__name__)
                if not started:
                    await self.fallback.say(text)
        finally:
            await asyncio.sleep(0.2)  # Deja decaer la cola acústica.
            self.busy.clear()

    async def _source(self, text):
        if text in self.cache:
            yield self.cache[text]
            return
        if text in self.ahead:
            yield await self.ahead.pop(text)  # Si falló, el error sale acá y se usa la voz de respaldo
            return
        kept = []
        async for chunk in self.fetch(text):
            kept.append(chunk)
            yield chunk
        if len(text) <= 30 and len(self.cache) < 64:
            self.cache[text] = b"".join(kept)

    async def _play(self, text):
        import sounddevice as sd
        from .audio import Playback

        buffer = Playback(TTS_RATE, max_seconds=180)

        def callback(out, frames, timing, status):
            out[:] = buffer.read(frames)

        stream = sd.RawOutputStream(samplerate=TTS_RATE, blocksize=TTS_RATE // 50, channels=1, dtype="int16",
                                    device=self.output_device, callback=callback)
        stream.start()
        try:
            tail = b""
            async for chunk in self._source(text):
                data = tail + chunk
                cut = len(data) - len(data) % 2  # No partir una muestra de 16 bits.
                tail = data[cut:]
                if cut:
                    buffer.add(0, 0, data[:cut])
                    yield True
            while buffer.busy:  # Espera a que termine de sonar, sin bloquear el loop
                await asyncio.sleep(0.02)
        finally:
            buffer.interrupt()  # Al cancelar se vacía el buffer: la voz se corta en ~20 ms
            stream.abort()
            stream.close()

    def close(self):
        self.drop_prefetch()
        self.fallback.close()


def wav_bytes(pcm: bytes, rate=16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)
    return out.getvalue()


class CloudRecognizer:
    """Vosk detecta cuándo termina cada frase; ese audio se retranscribe con un modelo mejor.

    Sólo se envía la frase (con medio segundo previo), nunca el silencio. Si la nube falla,
    se usa el texto de Vosk.
    """

    keeps_audio = True  # El bucle no debe descartar audio mientras se transcribe: es la siguiente frase

    def __init__(self, local, client: httpx.AsyncClient, s: Settings, engine="openai"):
        self.local, self.client, self.settings, self.engine = local, client, s, engine
        self.pre = deque(maxlen=25)
        self._clear()

    def _clear(self):
        self.speech, self.parts, self.active, self.closing, self.silence = bytearray(), [], False, False, 0.0

    def reset(self):
        self.local.reset()
        self.pre.clear()
        self._clear()

    def accept(self, pcm):
        """Junta las frases que Vosk corta por pausas cortas; al callarte un rato devuelve la transcripción
        pendiente (una corrutina) para que el micrófono siga escuchando mientras viaja a la nube."""
        final = self.local.accept(pcm)
        speaking = final is None and bool(self.local.partial())
        if not self.active:
            if final is None and not speaking:
                self.pre.append(pcm)
                return None
            self.speech = bytearray(b"".join(self.pre))
            self.pre.clear()
            self.active = True
        self.speech += pcm
        if final is not None:  # Vosk cerró una frase: se espera por si seguís hablando
            self.parts += [final] if final else []
            self.closing, self.silence = True, 0.0
        elif speaking:
            self.closing, self.silence = False, 0.0
        else:
            self.silence += len(pcm) / 32000  # PCM16 mono a 16 kHz
        if not ((self.closing and self.silence >= self.settings.iris_stt_hangover_seconds) or len(self.speech) >= MAX_UTTERANCE):
            return None
        audio, text = bytes(self.speech), " ".join(self.parts)
        self._clear()
        if not text:
            return ""
        return self._finish(audio, text)

    async def _finish(self, audio, text):
        heard = await self.transcribe(audio)
        return text if heard is None else heard  # None = falló la nube; "" = no era voz clara

    async def transcribe(self, audio: bytes) -> str | None:
        try:
            return await (self._scribe if self.engine == "elevenlabs" else self._openai)(audio)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Transcripción en la nube falló: %s", type(exc).__name__)
            return None

    async def _scribe(self, audio: bytes) -> str:
        """ElevenLabs Scribe v2: sesgo a términos propios y descarte por baja confianza."""
        s = self.settings
        base = {"model_id": "scribe_v2", "language_code": "es", "tag_audio_events": "false", "no_verbatim": "true"}
        headers = {"xi-api-key": s.elevenlabs_api_key.get_secret_value()}
        for terms in (s.iris_stt_keyterms, []):
            response = await self.client.post(
                "https://api.elevenlabs.io/v1/speech-to-text", headers=headers, timeout=10,
                data={**base, **({"keyterms": terms} if terms else {})},
                files={"file": ("frase.wav", wav_bytes(audio), "audio/wav")})
            if response.status_code in (400, 422) and terms:
                continue  # Si rechaza el formato de keyterms, reintenta sin ellos
            break
        response.raise_for_status()
        body = response.json()
        words = [w["logprob"] for w in body.get("words", []) if w.get("type") == "word" and "logprob" in w]
        if words and sum(words) / len(words) < s.iris_stt_min_logprob:
            log.info("Frase descartada por baja confianza (%.2f)", sum(words) / len(words))
            return ""
        return str(body.get("text", "")).strip()

    async def _openai(self, audio: bytes) -> str:
        s = self.settings
        response = await self.client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {s.openai_api_key.get_secret_value()}"},
            data={"model": s.iris_transcription_model, "prompt": "Conversación en español con un asistente llamado Iris."},
            files={"file": ("frase.wav", wav_bytes(audio), "audio/wav")}, timeout=10,
        )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()


def choose_engines(s: Settings) -> tuple[str, str]:
    """Resuelve 'auto' según las claves presentes y valida las elecciones explícitas."""
    eleven = bool(s.elevenlabs_api_key.get_secret_value() and s.iris_elevenlabs_voice_id)
    openai = bool(s.openai_api_key.get_secret_value())
    tts = s.iris_tts
    if tts == "auto":
        tts = "elevenlabs" if eleven else "openai" if openai else "windows"
    if (tts == "elevenlabs" and not eleven) or (tts == "openai" and not openai):
        raise RuntimeError(f"IRIS_TTS={tts} necesita su clave en .env" + (" y IRIS_ELEVENLABS_VOICE_ID" if tts == "elevenlabs" else "") + ".")
    stt = s.iris_stt
    if stt == "auto":
        stt = "elevenlabs" if s.elevenlabs_api_key.get_secret_value() else "openai" if openai else "vosk"
    if stt == "openai" and not openai:
        raise RuntimeError("IRIS_STT=openai necesita OPENAI_API_KEY en .env.")
    if stt == "elevenlabs" and not s.elevenlabs_api_key.get_secret_value():
        raise RuntimeError("IRIS_STT=elevenlabs necesita ELEVENLABS_API_KEY en .env.")
    return tts, stt


def build_audio(s: Settings, client: httpx.AsyncClient, recognizer, windows_speaker, output_device=None):
    """Devuelve (recognizer, speaker, texto del banner) según la configuración."""
    tts, stt = choose_engines(s)
    if stt != "vosk":
        recognizer = CloudRecognizer(recognizer, client, s, stt)
    speaker = windows_speaker
    if tts != "windows":
        fetch = elevenlabs_pcm if tts == "elevenlabs" else openai_pcm
        speaker = CloudSpeaker(lambda text: fetch(client, s, text), windows_speaker, output_device=output_device)
    names = {"elevenlabs": "ElevenLabs", "openai": "OpenAI", "windows": "voz de Windows", "vosk": "Vosk local"}
    return recognizer, speaker, f"oído: {'Vosk local' if stt == 'vosk' else 'Vosk + ' + ('ElevenLabs Scribe v2' if stt == 'elevenlabs' else s.iris_transcription_model)}; voz: {names[tts]}"


async def list_elevenlabs_voices(s: Settings) -> list[str]:
    key = s.elevenlabs_api_key.get_secret_value()
    if not key:
        raise RuntimeError("Falta ELEVENLABS_API_KEY en .env.")
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.elevenlabs.io/v2/voices", params={"page_size": 100},
                                    headers={"xi-api-key": key}, timeout=20)
    if response.is_error:
        raise RuntimeError(f"ElevenLabs respondió HTTP {response.status_code}; revisá la clave.")
    return [f"{v['voice_id']}  {v.get('name', '?')}  ({v.get('category', '?')}; {', '.join(f'{k}={x}' for k, x in v.get('labels', {}).items())})"
            for v in response.json().get("voices", [])]
