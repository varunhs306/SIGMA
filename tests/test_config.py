import pytest
from pydantic import ValidationError

from sigma.config import LogLevel, Settings, get_settings

CREDS = dict(gemini_api_key="test-key", telegram_bot_token="test-token", _env_file=None)


def test_constructs_with_defaults():
    s = Settings(**CREDS)
    assert s.llm_temperature == 0.3
    assert s.llm_max_retries == 3
    assert s.history_period == "1mo"


def test_log_level_defaults_to_info_and_compares_equal_to_str():
    s = Settings(**CREDS)
    assert s.log_level is LogLevel.INFO
    assert s.log_level == "INFO"
    assert s.log_level.upper() == "INFO"


@pytest.mark.parametrize(
    "override, field",
    [
        ({"log_level": "WARN"}, "log_level"),
        ({"llm_temperature": 3.0}, "llm_temperature"),
        ({"llm_temperature": -0.1}, "llm_temperature"),
        ({"llm_max_retries": 0}, "llm_max_retries"),
        ({"gemini_api_keys": "typo"}, "gemini_api_keys"),
    ],
)
def test_invalid_values_raise_and_name_the_field(override, field):
    with pytest.raises(ValidationError) as exc:
        Settings(**{**CREDS, **override})
    assert field in str(exc.value)


def test_missing_credential_raises(clean_env):
    with pytest.raises(ValidationError) as exc:
        Settings(telegram_bot_token="t", _env_file=None)
    assert "gemini_api_key" in str(exc.value)


def test_secret_is_masked_everywhere_it_could_leak():
    s = Settings(**CREDS)
    assert "test-key" not in repr(s)
    assert str(s.gemini_api_key) == "**********"
    assert s.gemini_api_key.get_secret_value() == "test-key"
    # model_dump() keeps the SecretStr OBJECT; mode="json" gives the masked string.
    assert "test-key" not in str(s.model_dump())
    assert s.model_dump(mode="json")["gemini_api_key"] == "**********"


def test_root_points_at_the_repository_root():
    from sigma.config import _ROOT

    assert (_ROOT / "pyproject.toml").exists(), f"_ROOT resolved to {_ROOT}"


def test_get_settings_is_cached_and_clearable(clean_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    first = get_settings()
    assert first is get_settings()
    get_settings.cache_clear()
    assert get_settings() is not first
