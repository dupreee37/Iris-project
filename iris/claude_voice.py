"""Conversación por voz con Claude: oído -> ClaudeAgent (en streaming) -> voz, con interrupciones."""
import asyncio
import contextlib
import inspect
import os
import random
import re
import time
from collections import deque

from .dialogue import addressed, normalized
from .feedback import Feedback

SLEEP = {"dormi", "dormir", "descansa", "hasta luego"}
CANCEL = {"cancela", "cancelar", "para", "detenete", "basta"}
# Una sola palabra suelta casi siempre es ruido mal oído; sólo estas valen sin decir «Iris».
SHORT_OK = {"si", "no", "gracias", "dale", "listo"} | CANCEL | SLEEP
# Palabras que cortan a IRIS al instante aunque sean una sola.
STOP = {"para", "basta", "callate", "stop", "espera", "iris"}
# Muletillas mientras Claude piensa (se precargan: suenan sin esperar a la red).
FILLERS = ["Mmm...", "A ver...", "Ajá...", "Eh... dejame ver.", "Mmm, a ver...", "Entiendo..."]
LONG_FILLERS = ["Sigo en eso...", "Un segundito más...", "Ya casi lo tengo..."]


class ClaudeConversation:
    def __init__(self, agent, speaker, log=print, *, feedback=None):
        self.agent, self.speaker, self.log = agent, speaker, log
        self.feedback = feedback or Feedback()
        self.awake = False
        self.voices = 0
        self.current = None
        self.version = 0
        self.last = time.monotonic()
        self.unanswered = None  # Pedido cuyo turno se cortó: se une al siguiente
        self.spoken = deque(maxlen=4)  # Últimas frases dichas, para reconocer el eco propio
        self.spoke_at = 0.0  # Cuándo terminó de hablar por última vez
        self.inbox = None  # Transcripciones en vuelo, entregadas en orden
        self.last_filler = None

    async def say(self, text):
        self.log(f"IRIS: {text}")
        self.feedback.transcript("IRIS", text)
        self.spoken.append(text)
        self.voices += 1
        self.feedback.update(speaking=True)
        try:
            await self.speaker.say(text)
        finally:
            self.voices -= 1
            self.feedback.update(speaking=bool(self.voices))
            self.last = self.spoke_at = time.monotonic()

    async def cancel(self):
        self.version += 1
        if self.current:
            self.current.cancel()
            await asyncio.gather(self.current, return_exceptions=True)
        self.current = None
        if drop := getattr(self.speaker, "drop_prefetch", None):
            drop()
        self.feedback.update(thinking=False)

    def is_user_speech(self, heard: str) -> bool:
        """Mientras IRIS habla: ¿lo que oye el micrófono es la persona o el eco de su propia voz?

        Vosk transcribe mal el eco, así que hacen falta tres palabras que IRIS no dijo (o una de
        corte como «pará»), y que la mayoría de lo oído no coincida con lo que está diciendo.
        """
        words = [w for w in normalized(heard or "").split() if len(w) > 2 or w in STOP]
        echo = set(normalized(" ".join(self.spoken)).split())
        new = [w for w in words if w not in echo]
        if any(w in STOP for w in new):
            return True
        return len(new) >= 3 and len(new) >= 0.7 * len(words)

    def is_echo(self, text: str) -> bool:
        """Una frase entera que es casi lo que IRIS acaba de decir (oída por el parlante)."""
        if self.voices == 0 and time.monotonic() - self.spoke_at > 3:
            return False
        words = [w for w in normalized(text).split() if len(w) > 2]
        echo = set(normalized(" ".join(self.spoken)).split())
        # El eco llega deformado («calopsitas» → «cálculo»): alcanza con que más de la mitad coincida.
        return len(words) >= 2 and sum(w in echo for w in words) > 0.5 * len(words)

    def deliver(self, pending):
        """Recibe una transcripción que todavía viaja a la nube; la entrega en orden al llegar."""
        previous = self.inbox

        async def run():
            text = await pending
            if previous:
                await asyncio.gather(previous, return_exceptions=True)
            if text:
                await self.hear(text)
        self.inbox = asyncio.create_task(run())

    async def interrupt(self):
        self.log("[Te escucho: corto lo que estaba diciendo]")
        await self.cancel()

    async def hear(self, text):
        if self.is_echo(text):
            return  # Era su propia voz entrando por el micrófono
        if self.awake and time.monotonic() - self.last > self.agent.settings.iris_awake_seconds:
            self.awake = False  # Mucho rato sin hablar: vuelve a pedir «Iris»
            self.feedback.update(awake=False)
        if not addressed(text) and (not self.awake or (len(normalized(text).split()) < 2 and normalized(text) not in SHORT_OK)):
            return  # Sin activar, o ruido de una palabra: no se gasta ni un token
        self.last = time.monotonic()
        self.log(f"Vos: {text}")
        self.feedback.transcript("Vos", text)
        self.awake = True
        self.feedback.update(awake=True)
        request = re.sub(r"^\W*(?:hola\W+|hey\W+)?iris\b[\s,.:;!?-]*", "", text, flags=re.I).strip()
        clean = normalized(request)
        if clean in SLEEP:
            await self.cancel()
            self.unanswered = None
            self.agent.reset()
            self.awake = False
            self.feedback.update(awake=False)
            await self.say("Quedo en espera. Llamame Iris cuando me necesites.")
        elif clean in CANCEL:
            await self.cancel()
            self.unanswered = None
            await self.say("Cancelado.")
        elif not clean:
            await self.say("Te escucho.")
        else:
            await self.cancel()  # Un pedido nuevo reemplaza al que seguía pensando…
            if self.unanswered:  # …sin perderlo: si te corregiste o seguiste hablando, va todo junto
                request = f"{self.unanswered} {request}"
            self.unanswered = request
            self.current = asyncio.create_task(self._respond(request, self.version))

    async def _respond(self, request, version):
        """Claude escribe y la voz habla a la vez: cada frase suena apenas está completa."""
        self.feedback.update(thinking=True)
        queue = asyncio.Queue()

        async def produce():
            try:
                async with contextlib.aclosing(self.agent.stream(request)) as sentences:
                    async for sentence in sentences:
                        if self.voices and (prefetch := getattr(self.speaker, "prefetch", None)):
                            prefetch(sentence)  # Ya está hablando: preparar esta voz para que no haya pausa
                        queue.put_nowait(sentence)
                if self.unanswered == request:
                    self.unanswered = None  # El turno terminó y quedó en el historial
            finally:
                queue.put_nowait(None)

        producer = asyncio.create_task(produce())
        try:
            fillers = [0.45, 4.5] if self.agent.settings.iris_fillers else []
            while True:
                try:  # Si Claude tarda, una muletilla corta para no quedarse mudo
                    sentence = await asyncio.wait_for(queue.get(), fillers.pop(0)) if fillers else await queue.get()
                except TimeoutError:
                    await self.say(self.filler(long=not fillers))
                    continue
                fillers = []
                if sentence is None:
                    break
                if version == self.version:
                    self.feedback.update(thinking=False)
                await self.say(sentence)
            await producer
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            if version == self.version:
                self.feedback.update(thinking=False)

    def filler(self, long=False):
        options = [f for f in (LONG_FILLERS if long else FILLERS) if f != self.last_filler]
        self.last_filler = random.choice(options)
        return self.last_filler


async def feed(conversation, recognizer, chunk):
    text = recognizer.accept(chunk)
    if inspect.isawaitable(text):
        conversation.deliver(text)  # El micrófono sigue escuchando mientras se transcribe
    elif text:
        await conversation.hear(text)


async def listen_duplex(conversation, recognizer, speaker, feedback, input_device=None):
    """El micrófono sigue abierto mientras IRIS habla; si sos vos (no su eco), se calla y te escucha."""
    from .audio import AudioDevice

    local = getattr(recognizer, "local", recognizer)
    recent = deque(maxlen=30)  # 0,6 s: el comienzo de tu interrupción, sin arrastrar mucho eco
    with AudioDevice(input_device=input_device) as device:
        feedback.update(capturing=True)
        echo = barged = False
        while True:
            chunk = await device.read()
            busy = speaker.busy.is_set()
            if barged:  # La voz ya se cortó; ignorar la cola hasta que el parlante termine
                barged = busy
                busy = False
            if busy:
                echo = True
                recent.append(chunk)
                final = local.accept(chunk)
                if conversation.is_user_speech(final if final is not None else local.partial()):
                    await conversation.interrupt()
                    recognizer.reset()
                    replay = list(recent)
                    recent.clear()
                    echo, barged = False, speaker.busy.is_set()
                    for old in replay:
                        await feed(conversation, recognizer, old)
                continue
            if echo:  # Terminó de hablar sin interrupción: lo oído era su propia voz
                recognizer.reset()
                recent.clear()
                echo = False
            await feed(conversation, recognizer, chunk)


async def run_claude(settings, model_path, input_device=None, output_device=None, *, feedback=None):
    import httpx
    from .brain import Brain
    from .claude_agent import ClaudeAgent
    from .demo_voice import listen
    from .local_speech import LocalRecognizer, WindowsSpeaker
    from .providers import Providers
    from .speech import build_audio, choose_engines
    from .tools import ToolManager

    if not (settings.anthropic_api_key.get_secret_value() or os.environ.get("ANTHROPIC_API_KEY")):
        raise RuntimeError("Falta ANTHROPIC_API_KEY. Copiá .env.example a .env y pegá tu clave de la consola de Anthropic.")
    choose_engines(settings)  # Falla antes de abrir dispositivos si la configuración está incompleta.
    # Acá las acciones son reales (con confirmación): el modo demo las simula.
    settings = settings.model_copy(update={"iris_mode": "live"})
    local = LocalRecognizer(model_path)
    windows = WindowsSpeaker()
    speaker = windows
    feedback = feedback or Feedback()
    try:
        async with httpx.AsyncClient() as client:
            recognizer, speaker, engines = build_audio(settings, client, local, windows, output_device)
            brain = Brain(ToolManager(Providers(settings, client)), timeout=settings.iris_tool_timeout_seconds,
                          max_active=settings.iris_max_active_jobs)
            agent = ClaudeAgent(settings, brain, on_job=lambda job: feedback.task(job.id, job.name, job.status))
            conversation = ClaudeConversation(agent, speaker, feedback=feedback)
            try:
                feedback.update(ready=True)
                preload = getattr(speaker, "preload", None)
                if preload:  # Muletillas listas para sonar al instante
                    asyncio.create_task(preload(FILLERS + LONG_FILLERS + ["Te escucho.", "Cancelado."]))
                await conversation.say("Iris está lista con Claude. Decí: Iris, y lo que necesites.")
                print(f"[Micrófono activo · {engines} · cerebro: {settings.iris_claude_model} · "
                      f"interrupciones: {'sí' if settings.iris_barge_in else 'no'}. "
                      "Lo que digas se envía a esos servicios. Ctrl+C para salir.]")
                if settings.iris_barge_in:
                    await listen_duplex(conversation, recognizer, speaker, feedback, input_device)
                else:
                    await listen(conversation, recognizer, speaker, feedback, input_device)
            finally:
                await conversation.cancel()
                await agent.close()
                await brain.close()
    finally:
        speaker.close()
        feedback.stop()
