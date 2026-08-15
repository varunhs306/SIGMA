import pytest

from sigma.config import get_settings

_SIGMA_VARS = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "LOG_LEVEL")


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def clean_env(monkeypatch):
    for var in _SIGMA_VARS:
        monkeypatch.delenv(var, raising=False)