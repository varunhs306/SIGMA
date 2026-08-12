from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    gemini_api_key: str
    telegram_bot_token: str
    log_level: str = 'INFO'

    model_config = SettingsConfigDict(env_file=_ROOT / '.env')

settings = Settings()