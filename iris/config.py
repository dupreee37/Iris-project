from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    iris_mode: Literal["demo", "live"] = "demo"
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    xai_api_key: SecretStr = SecretStr("")
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
