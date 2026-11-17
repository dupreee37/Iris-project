from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    iris_mode: Literal["demo", "live"] = "demo"
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    xai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    elevenlabs_api_key: SecretStr = SecretStr("")
    # auto = ElevenLabs si hay clave y voz, si no OpenAI si hay clave, si no Windows/Vosk.
    iris_tts: Literal["auto", "windows", "elevenlabs", "openai"] = "auto"
    iris_stt: Literal["auto", "vosk", "elevenlabs", "openai"] = "auto"
    iris_stt_keyterms: list[str] = ["Iris"]  # Palabras que el oído debe favorecer (ElevenLabs)
    iris_stt_min_logprob: float = -2.0  # Confianza media mínima por palabra; más bajo = descarta menos
    # natural = Claude abre lo que le pedís sin preguntar; strict = espera un «sí/dale» en el turno siguiente
    iris_confirm_actions: Literal["natural", "strict"] = "natural"
    iris_fillers: bool = True  # «Mmm», «a ver…» mientras piensa, para no quedarse en silencio
    iris_barge_in: bool = True  # Cortar a IRIS cuando hablás encima (con parlantes puede cortarse sola)
    iris_stt_hangover_seconds: float = Field(0.5, ge=0, le=3)  # Silencio que cierra una frase; más alto = no te corta
    iris_awake_seconds: int = Field(60, ge=5, le=600)  # Sin hablar este tiempo, vuelve a pedir «Iris»
    iris_elevenlabs_voice_id: str = ""
    iris_elevenlabs_model: str = "eleven_flash_v2_5"
    iris_openai_tts_model: str = "gpt-4o-mini-tts"
    iris_openai_tts_voice: str = "marin"
    iris_claude_model: str = "claude-sonnet-5-5"
    iris_claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    iris_claude_max_turns: int = Field(8, ge=1, le=20)
    iris_claude_fallbacks: bool = True
    iris_claude_web: bool = True
    # Nombre hablado -> ejecutable. Sólo estas apps puede abrir IRIS (con confirmación).
    iris_allowed_apps: dict[str, str] = {"bloc de notas": "notepad.exe", "calculadora": "calc.exe", "explorador": "explorer.exe"}
    iris_voice_model: str = "gpt-realtime-2.1"
    iris_voice_reasoning: Literal["default", "minimal", "low", "medium", "high", "xhigh"] = "low"
    iris_vad_eagerness: Literal["low", "medium", "high", "auto"] = "medium"
    iris_transcription_model: str = "gpt-transcribe"
    iris_reason_model: str = "gpt-5.6-terra"
    iris_research_provider: Literal["gemini", "xai"] = "gemini"
    iris_gemini_model: str = "gemini-3.8-flash"
    iris_xai_model: str = "grok-4.7"
    iris_tool_timeout_seconds: float = Field(45, gt=0, le=120)
    iris_max_active_jobs: int = Field(4, ge=1, le=16)
