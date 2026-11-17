"""Señales de observación compartidas por el monitor y futuros adaptadores físicos."""
from collections import deque
from dataclasses import dataclass, replace
import logging


TERMINAL = {"completed", "cancelled", "failed", "expired"}


@dataclass(frozen=True)
class TaskStatus:
    id: str
    name: str
    status: str


@dataclass(frozen=True)
class Snapshot:
    mode: str = "demo"
    ready: bool = False
    capturing: bool = False
    awake: bool = False
    hearing: bool = False
    thinking: bool = False
    speaking: bool = False
    messages: tuple[tuple[str, str], ...] = ()
    tasks: tuple[TaskStatus, ...] = ()

    @property
    def expression(self):
        # A background job must not hide a live listening/speaking expression.
        if self.speaking:
            return "speaking"
        if self.hearing:
            return "listening"
        if self.thinking or any(task.status not in TERMINAL for task in self.tasks):
            return "thinking"
        if self.ready and self.capturing and self.awake:
            return "listening"
        return "idle"


class Feedback:
    """Observador sin acceso a herramientas, audio ni decisiones del agente.

    Se usa desde el loop de conversación. subscribe() permite conectar otro
    consumidor de estados sin modificar las conversaciones ni el gestor.
    """
    def __init__(self, mode="demo"):
        self.snapshot = Snapshot(mode=mode)
        self.listeners = []

    def subscribe(self, listener):
        self.listeners.append(listener)
        def unsubscribe():
            if listener in self.listeners:
                self.listeners.remove(listener)
        return unsubscribe

    def _publish(self, snapshot):
        if snapshot == self.snapshot:
            return
        self.snapshot = snapshot
        for listener in tuple(self.listeners):
            try:
                listener(snapshot)
            except Exception:
                # Failure of a display must not break a spoken conversation.
                logging.getLogger(__name__).warning("Un observador de IRIS falló", exc_info=True)

    def update(self, **values):
        self._publish(replace(self.snapshot, **values))

    def transcript(self, role, text):
        if text:
            messages = deque(self.snapshot.messages, maxlen=40)
            messages.append((role, text[:4000]))
            self._publish(replace(self.snapshot, messages=tuple(messages)))

    def task(self, task_id, name, status):
        tasks = [task for task in self.snapshot.tasks if task.id != task_id]
        tasks.append(TaskStatus(task_id, name, status))
        while len(tasks) > 12:
            oldest = next((task for task in tasks if task.status in TERMINAL), None)
            if oldest is None:
                break
            tasks.remove(oldest)
        self._publish(replace(self.snapshot, tasks=tuple(tasks)))

    def stop(self):
        self.update(ready=False, capturing=False, awake=False, hearing=False,
                    thinking=False, speaking=False, tasks=())
