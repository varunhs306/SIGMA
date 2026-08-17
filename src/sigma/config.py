from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    gemini_api_key: SecretStr
    telegram_bot_token: SecretStr

    llm_model: str = "gemini-2.5-flash-lite"
    llm_temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.3
    llm_max_output_tokens: Annotated[int, Field(ge=64, le=32768)] = 1024
    llm_max_retries: Annotated[int, Field(ge=1, le=10)] = 3

    history_period: str = "1mo"

    data_dir: Path = _ROOT / "data"

    log_level: LogLevel = LogLevel.INFO
    log_file: Path = _ROOT / "logs" / "sigma.log"
    log_max_bytes: Annotated[int, Field(ge=1024)] = 5 * 1024 * 1024
    log_backup_count: Annotated[int, Field(ge=0, le=100)] = 3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
