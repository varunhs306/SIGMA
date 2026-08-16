import logging

import pytest

from sigma.config import Settings, get_settings
from tests.fakes import fake_google_key, fake_telegram_token

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


@pytest.fixture(autouse=True)
def _reset_logging():
    import sigma.logging.setup as s

    s._CONFIGURED = False
    yield
    s._CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.fixture
def settings_factory():
    def _make(**overrides):
        return Settings(
            gemini_api_key=fake_google_key(),
            telegram_bot_token=fake_telegram_token(),
            _env_file=None,
            **overrides,
        )

    return _make
