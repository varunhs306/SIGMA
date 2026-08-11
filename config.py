from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    telegram_bot_token: str
    log_level: str = 'INFO'

    model_config = SettingsConfigDict(env_file='.env')

settings = Settings() # type: ignore