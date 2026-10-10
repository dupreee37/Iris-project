"""Reconocimiento Vosk local y voz Windows SAPI para el modo de prueba."""
import asyncio
import hashlib
import json
import queue
import threading
import time
import zipfile
from pathlib import Path

import httpx

MODEL_NAME = "vosk-model-small-es-0.42"
MODEL_SHA256 = "09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f"
MODEL_ROOT = Path("work/models")


def download_model():
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    archive = MODEL_ROOT / f"{MODEL_NAME}.zip"
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != MODEL_SHA256:
        with httpx.stream("GET", f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip", timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            total = 0
            with archive.open("wb") as target:
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > 100_000_000:
                        raise RuntimeError("Descarga inesperadamente grande.")
                    target.write(chunk)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError("El archivo del modelo cambió; se requiere verificar su origen y versión.")
    root = MODEL_ROOT.resolve()
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not (root / entry.filename).resolve().is_relative_to(root):
                raise RuntimeError("Ruta inesperada dentro del modelo.")
        z.extractall(root)
    return root / MODEL_NAME


class LocalRecognizer:
    def __init__(self, path, rate=16000):
        from vosk import KaldiRecognizer, Model, SetLogLevel
        if not Path(path).is_dir():
            raise RuntimeError("Falta el modelo local. Ejecutá: python -m iris --download-model")
        SetLogLevel(-1)
        self.model = Model(str(path))
        self.recognizer = KaldiRecognizer(self.model, rate)

    def accept(self, pcm):
        if self.recognizer.AcceptWaveform(pcm):
            return json.loads(self.recognizer.Result()).get("text", "")
        return None

    def reset(self):
        self.recognizer.Reset()


def windows_voice():
    import win32com.client
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for candidate in voice.GetVoices():
        language = candidate.GetAttribute("Language").split(";")[0]
        if int(language, 16) & 0x3FF == 0x0A:  # Spanish LANGID, any region.
            voice.Voice = candidate
            return voice
    raise RuntimeError("No hay una voz española de Windows instalada.")


def render_wave(text, path):
    """Synthesize to a file only; does not use microphone or speakers."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        voice = windows_voice()
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Format.Type = 18  # SAPI: 16 kHz, 16-bit mono.
        stream.Open(str(Path(path).resolve()), 3, False)
        try:
            voice.AudioOutputStream = stream
            voice.Speak(text, 16)  # SVSFIsNotXML: provider text never becomes SSML.
        finally:
            stream.Close()
    finally:
        pythoncom.CoUninitialize()


class WindowsSpeaker:
    def __init__(self):
        self.requests = queue.Queue()
        self.stopping = threading.Event()
        self.busy = threading.Event()
        self.error = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.ready.wait(10)
        if not self.ready.is_set() or self.error:
            raise RuntimeError(self.error or "No se pudo iniciar la voz local.")

    def _worker(self):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            voice = windows_voice()
            self.ready.set()
            while not self.stopping.is_set():
                try:
                    text, loop, future = self.requests.get(timeout=0.05)
                except queue.Empty:
                    continue
                if future.cancelled():
                    continue
                self.busy.set()
                try:
                    voice.Speak(text, 17)  # Async + plain text, not XML.
                    while not voice.WaitUntilDone(20):
                        if self.stopping.is_set() or future.cancelled():
                            voice.Speak("", 19)  # Purge pending output.
                            break
                        pythoncom.PumpWaitingMessages()
                    loop.call_soon_threadsafe(self._settle, future, None)
                except Exception:
                    loop.call_soon_threadsafe(self._settle, future, RuntimeError("Falló la voz de Windows."))
                finally:
                    # Let the acoustic tail decay before local recognition resumes.
                    time.sleep(0.2)
                    self.busy.clear()
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            pythoncom.CoUninitialize()

    @staticmethod
    def _settle(future, error):
        if not future.done():
            if error:
                future.set_exception(error)
            else:
                future.set_result(None)

    async def say(self, text):
        if self.error:
            raise RuntimeError(self.error)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.requests.put((text, loop, future))
        await future

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
