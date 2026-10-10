"""Trabajos independientes del transporte de voz; idempotencia y cancelación."""
import asyncio
import time
import uuid
from dataclasses import dataclass, field

from .tools import ToolManager

TERMINAL = {"completed", "failed", "cancelled"}


@dataclass
class Job:
    owner: str
    call_id: str
    name: str
    arguments: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "running"
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    result: dict | None = None
    task: asyncio.Task | None = None

    def snapshot(self):
        return {"id": self.id, "call_id": self.call_id, "name": self.name, "arguments": self.arguments, "status": self.status, "result": self.result, "elapsed_ms": round(((self.finished or time.monotonic()) - self.created) * 1000)}


class Brain:
    def __init__(self, manager: ToolManager, *, timeout=45, max_active=4):
        self.manager, self.timeout, self.max_active = manager, timeout, max_active
        self.jobs: dict[str, Job] = {}

    def _prune(self):
        now = time.monotonic()
        for job in list(self.jobs.values()):
            if job.status == "awaiting_approval" and now - job.created > 120:
                self.cancel(job)
            if job.finished and now - job.finished > 600:
                del self.jobs[job.id]

    def submit(self, owner: str, call_id: str, name: str, arguments: dict) -> Job:
        self._prune()
        arguments = self.manager.validate(name, arguments)
        for job in self.jobs.values():
            if job.owner == owner and job.call_id == call_id:
                if job.name != name or job.arguments != arguments:
                    raise ValueError("call_id ya utilizado con otros argumentos.")
                return job
        if sum(j.owner == owner and j.status not in TERMINAL for j in self.jobs.values()) >= self.max_active:
            raise ValueError("Demasiadas tareas simultáneas; esperá o cancelá una.")
        if len(self.jobs) >= 512:
            raise ValueError("Registro de tareas lleno; reintentá en unos minutos.")
        job = Job(owner, call_id, name, arguments)
        self.jobs[job.id] = job
        if name == "open_url":
            job.status = "awaiting_approval"
        else:
            job.task = asyncio.create_task(self._run(job))
        return job

    def get(self, owner: str, job_id: str) -> Job:
        self._prune()
        job = self.jobs.get(job_id)
        if not job or job.owner != owner:
            raise KeyError(job_id)
        return job

    def approve(self, job: Job) -> Job:
        if job.status != "awaiting_approval":
            raise ValueError("Esta tarea no está esperando aprobación.")
        job.status = "running"
        job.task = asyncio.create_task(self._run(job, approved=True))
        return job

    def cancel(self, job: Job) -> Job:
        if job.status not in TERMINAL:
            job.status, job.result, job.finished = "cancelled", {"error": "Tarea cancelada. No anunciar un resultado."}, time.monotonic()
            if job.task:
                job.task.cancel()
        return job

    async def _run(self, job: Job, approved=False):
        from .providers import ProviderError
        import httpx
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.manager.execute(job.name, job.arguments, approved=approved)
            if job.status != "cancelled":
                job.result, job.status = result, "completed"
        except asyncio.CancelledError:
            self.cancel(job)
        except (TimeoutError, httpx.TimeoutException):
            job.status, job.result = "failed", {"error": "La tarea superó el tiempo máximo. Podés reintentar."}
        except ProviderError as exc:
            job.status, job.result = "failed", {"error": str(exc)}
        except Exception:
            job.status, job.result = "failed", {"error": "Falló la herramienta. No se obtuvo un resultado verificable."}
        finally:
            job.finished = time.monotonic()

    async def close(self):
        tasks = [j.task for j in self.jobs.values() if j.task]
        for job in self.jobs.values():
            self.cancel(job)
        await asyncio.gather(*tasks, return_exceptions=True)
