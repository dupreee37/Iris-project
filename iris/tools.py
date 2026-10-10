import asyncio
import platform
import webbrowser
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .providers import Providers


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchArgs(Arguments):
    query: str = Field(min_length=1, max_length=4000)


class ReasonArgs(Arguments):
    task: str = Field(min_length=1, max_length=8000)


class EmptyArgs(Arguments):
    pass


class OpenUrlArgs(Arguments):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def web_only(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError("Se requiere una URL http(s) sin credenciales.")
        return value


ToolName = Literal["research_web", "deep_reason", "device_status", "open_url"]
SPECS = {
    "research_web": (ResearchArgs, "Investigar información actual con fuentes web. Incluí el contexto necesario en query."),
    "deep_reason": (ReasonArgs, "Delegar una tarea compleja a GPT. Incluí todo el contexto en task. No usar para una charla simple."),
    "device_status": (EmptyArgs, "Consultar sistema operativo y hora del equipo anfitrión. No lee sensores del ESP32."),
    "open_url": (OpenUrlArgs, "Solicitar abrir una URL. Requiere que el usuario diga literalmente «confirmo abrir» durante el turno actual."),
}


def definitions() -> list[dict]:
    return [{"type": "function", "name": name, "description": description, "parameters": args.model_json_schema()} for name, (args, description) in SPECS.items()]


class ToolManager:
    def __init__(self, providers: Providers):
        self.providers = providers

    def validate(self, name: str, arguments: dict) -> dict:
        if name not in SPECS:
            raise ValueError("Herramienta desconocida.")
        return SPECS[name][0].model_validate(arguments).model_dump()

    async def execute(self, name: str, arguments: dict, *, approved=False) -> dict:
        arguments = self.validate(name, arguments)
        if name == "research_web":
            return await self.providers.research(arguments["query"])
        if name == "deep_reason":
            return await self.providers.reason(arguments["task"])
        if name == "device_status":
            return {"os": platform.system(), "python": platform.python_version(), "utc": datetime.now(timezone.utc).isoformat(), "esp32_connected": False}
        if not approved:
            raise PermissionError("Abrir una URL requiere confirmación del usuario.")
        if self.providers.settings.iris_mode == "demo":
            return {"opened": False, "simulated": True, "url": arguments["url"]}
        opened = await asyncio.to_thread(webbrowser.open, arguments["url"], new=2)
        return {"opened": opened, "url": arguments["url"]}
