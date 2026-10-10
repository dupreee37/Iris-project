"""Audio nativo PCM16 mono; sin navegador ni servidor HTTP."""
import asyncio
import queue
import threading
import time
from collections import deque


class Playback:
    def __init__(self, rate=24000, max_seconds=30):
        self.rate = rate
        self.limit = rate * 2 * max_seconds
        self.chunks = deque()
        self.size = 0
        self.lock = threading.Lock()
        self.item = None
        self.index = 0
        self.played = 0
        self.until = 0.0

    def add(self, item, index, pcm):
        if len(pcm) % 2:
            raise ValueError("PCM16 incompleto")
        with self.lock:
            if self.size + len(pcm) > self.limit:
                raise BufferError("La salida de voz excedió el buffer; se detuvo la sesión.")
            if not self.size and time.monotonic() >= self.until and (item, index) != (self.item, self.index):
                self.item, self.index, self.played = item, index, 0
            self.chunks.append((item, index, pcm))
            self.size += len(pcm)

    def read(self, frames):
        output = bytearray()
        with self.lock:
            while self.chunks and len(output) < frames * 2:
                item, index, data = self.chunks.popleft()
                count = min(len(data), frames * 2 - len(output))
                output.extend(data[:count])
                self.size -= count
                if (self.item, self.index) != (item, index):
                    self.item, self.index, self.played = item, index, 0
                self.played += count // 2
                if count < len(data):
                    self.chunks.appendleft((item, index, data[count:]))
            if output:
                self.until = time.monotonic() + frames / self.rate
        return bytes(output).ljust(frames * 2, b"\0")

    @property
    def busy(self):
        with self.lock:
            return bool(self.size) or time.monotonic() < self.until

    def interrupt(self):
        """Return the played position; queued/unheard audio is discarded."""
        with self.lock:
            if self.item is None and self.chunks:
                self.item, self.index, _ = self.chunks[0]
            position = (self.item, self.index, int(self.played * 1000 / self.rate))
            self.chunks.clear()
            self.size = self.played = 0
            self.item, self.until = None, 0
            return position


class AudioDevice:
    def __init__(self, rate=16000, input_device=None, output_device=None, playback=False, muted=None):
        self.rate, self.input_device, self.output_device = rate, input_device, output_device
        self.with_output = playback
        self.input = queue.Queue(maxsize=250)  # 5 seconds at 20 ms; bounded.
        self.playback = Playback(rate)
        self.fault = None
        self.streams = []
        self.muted = muted or (lambda: False)

    def _capture(self, data, frames, timing, status):
        if self.muted():
            return
        if status.input_overflow:
            self.fault = "Se perdió audio del micrófono. Revisá el dispositivo o la carga del equipo."
        try:
            self.input.put_nowait(bytes(data))
        except queue.Full:
            self.fault = "La captura acumuló demasiado audio; se detuvo para no interpretar frases incompletas."

    def _play(self, out, frames, timing, status):
        out[:] = self.playback.read(frames)

    def __enter__(self):
        import sounddevice as sd
        try:
            stream = sd.RawInputStream(samplerate=self.rate, blocksize=self.rate // 50, device=self.input_device, channels=1, dtype="int16", callback=self._capture)
            self.streams.append(stream)
            if self.with_output:
                self.streams.append(sd.RawOutputStream(samplerate=self.rate, blocksize=self.rate // 50, device=self.output_device, channels=1, dtype="int16", callback=self._play))
            for stream in self.streams:
                stream.start()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    async def read(self):
        while True:
            if self.fault:
                raise RuntimeError(self.fault)
            try:
                return self.input.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)

    def discard_input(self):
        while True:
            try:
                self.input.get_nowait()
            except queue.Empty:
                break

    def __exit__(self, *_):
        for stream in reversed(self.streams):
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self.streams.clear()
