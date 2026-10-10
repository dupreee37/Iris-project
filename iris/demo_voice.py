import asyncio
import uuid

from .dialogue import DemoDialogue
from .feedback import Feedback


class DemoConversation:
    def __init__(self, brain, speaker, log=print, *, feedback=None):
        self.brain, self.speaker, self.log = brain, speaker, log
        self.feedback = feedback or Feedback()
        self.voices = 0
        self.dialogue = DemoDialogue()
        self.current = None
        self.job = None
        self.version = 0

    async def say(self, text):
        self.log(f"IRIS: {text}")
        self.feedback.transcript("IRIS", text)
        self.voices += 1
        self.feedback.update(speaking=True)
        try:
            await self.speaker.say(text)
        finally:
            self.voices -= 1
            self.feedback.update(speaking=bool(self.voices))

    async def cancel(self):
        self.version += 1
        if self.job:
            self.brain.cancel(self.job)
            self.feedback.task(self.job.id, self.job.name, self.job.status)
        if self.current:
            self.current.cancel()
            await asyncio.gather(self.current, return_exceptions=True)
        self.current = self.job = None

    async def hear(self, text):
        self.log(f"Vos: {text}")
        self.feedback.transcript("Vos", text)
        reply = self.dialogue.hear(text)
        self.feedback.update(awake=self.dialogue.awake)
        if reply.cancel or reply.query:
            await self.cancel()
        if reply.text:
            await self.say(reply.text)
        if reply.query:
            self.job = self.brain.submit("voice-demo", uuid.uuid4().hex, "research_web", {"query": reply.query})
            self.feedback.task(self.job.id, self.job.name, self.job.status)
            self.current = asyncio.create_task(self._result(self.job, self.version))

    async def _result(self, job, version):
        await job.task
        self.feedback.task(job.id, job.name, job.status)
        if self.version != version or job.status == "cancelled":
            return
        if job.status == "completed":
            await self.say("Terminé la prueba. El pedido llegó al cerebro y volvió correctamente. Como estamos sin claves, no consulté internet ni tengo hallazgos reales para darte.")
        else:
            await self.say("No pude terminar la tarea. Podés pedirme que lo intente otra vez.")


async def run_demo(settings, model_path, input_device=None, *, feedback=None):
    import httpx
    from .audio import AudioDevice
    from .brain import Brain
    from .local_speech import LocalRecognizer, WindowsSpeaker
    from .providers import Providers
    from .tools import ToolManager

    # Explicit demo always overrides .env; it cannot incur provider charges.
    settings = settings.model_copy(update={"iris_mode": "demo"})
    recognizer = LocalRecognizer(model_path)
    speaker = WindowsSpeaker()
    feedback = feedback or Feedback()
    async with httpx.AsyncClient() as client:
        brain = Brain(ToolManager(Providers(settings, client)))
        conversation = DemoConversation(brain, speaker, feedback=feedback)
        try:
            feedback.update(ready=True)
            await conversation.say("Iris está lista en modo de prueba. Decí: Iris, necesito que investigues algo por mí.")
            print("[Micrófono local activo. Sin envío a APIs. Ctrl+C para salir.]")
            with AudioDevice(input_device=input_device, muted=speaker.busy.is_set) as device:
                feedback.update(capturing=True)
                muted = False
                while True:
                    chunk = await device.read()
                    # Demo uses half duplex to prevent the Windows voice triggering itself.
                    if speaker.busy.is_set():
                        recognizer.reset()
                        muted = True
                        continue
                    if muted:
                        device.discard_input()
                        recognizer.reset()
                        muted = False
                        continue
                    text = recognizer.accept(chunk)
                    if text:
                        await conversation.hear(text)
                        device.discard_input()
                        recognizer.reset()
        finally:
            await conversation.cancel()
            await brain.close()
            speaker.close()
            feedback.stop()
