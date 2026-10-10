"""Guion local limitado para probar voz. No se presenta como un LLM."""
import re
import unicodedata
from dataclasses import dataclass


def normalized(text):
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def addressed(text):
    return re.match(r"^(?:hola\s+|hey\s+)?iris\b", normalized(text)) is not None


@dataclass
class Reply:
    text: str = ""
    query: str | None = None
    cancel: bool = False
    sleep: bool = False


class DemoDialogue:
    def __init__(self):
        self.awake = False
        self.needs_topic = False

    def hear(self, text):
        clean = normalized(text)
        if not self.awake and not addressed(text):
            return Reply()
        self.awake = True
        clean = re.sub(r"^(?:hola\s+|hey\s+)?iris\s*", "", clean).strip()
        if clean in {"dormi", "dormir", "descansa", "hasta luego"}:
            self.awake = self.needs_topic = False
            return Reply("Quedo en espera. Llamame Iris cuando me necesites.", cancel=True, sleep=True)
        if clean in {"cancela", "cancelar", "cancela la busqueda", "para", "detenete"}:
            self.needs_topic = False
            return Reply("Cancelé la tarea.", cancel=True)
        if self.needs_topic and clean:
            self.needs_topic = False
            query = re.sub(r"^(?:sobre|acerca de)\s+", "", clean)
            return Reply(f"Dale. Inicio la prueba de investigación sobre {query}.", query=query)
        if "investig" in clean or re.search(r"\bbusc", clean):
            topic = re.search(r"(?:sobre|acerca de)\s+(.+)", clean)
            if topic:
                return Reply(f"Dale. Inicio la prueba sobre {topic[1]}.", query=topic[1])
            self.needs_topic = True
            return Reply("Claro. ¿Sobre qué tema querés que investigue?")
        return Reply("Te escucho. En esta demo puedo probar una investigación. Decime qué tema querés consultar.")
