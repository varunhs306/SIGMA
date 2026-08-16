from collections import namedtuple

import pytest

from sigma.logging.redaction import (
    MASK, _scrub, clear_secrets, redact_processor, register_secret,
)
from tests.fakes import fake_google_key, fake_telegram_token

TOKEN = fake_telegram_token()
KEY = fake_google_key()


@pytest.fixture(autouse=True)
def _register():
    clear_secrets()
    register_secret(TOKEN)
    register_secret(KEY)
    yield
    clear_secrets()


def test_the_day_01_leak_shape():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    assert TOKEN not in _scrub(url)
    assert MASK in _scrub(url)


@pytest.mark.parametrize("value", [
    TOKEN,
    {"auth": {"data": KEY}},
    ["a", {"b": [TOKEN]}],
    (KEY,),
    f"prefix {TOKEN} suffix",
])
def test_secrets_are_scrubbed_at_any_depth(value):
    assert TOKEN not in str(_scrub(value))
    assert KEY not in str(_scrub(value))


def test_non_strings_pass_through_unchanged():
    assert _scrub(42) == 42
    assert _scrub(None) is None


def test_bytes_are_scrubbed():
    assert KEY.encode() not in _scrub(f"body={KEY}".encode())


def test_namedtuple_does_not_raise():
    P = namedtuple("P", "a b")
    assert _scrub(P(KEY, "b")) == P(MASK, "b")


def test_short_values_are_not_registered():
    register_secret("")
    register_secret("abc")
    assert _scrub("abc def") == "abc def"


@pytest.mark.parametrize("key", [
    "token", "secret", "password", "api_key", "apikey", "authorization",
    "bot_token", "gemini_api_key", "private_key", "db_password",
])
def test_sensitive_field_names_are_masked_whatever_the_value(key):
    out = _scrub({key: "a-completely-unrecognised-credential-format"})
    assert out[key] == MASK


@pytest.mark.parametrize("key", ["author", "authority", "keyboard", "monkey", "event"])
def test_lookalike_field_names_are_not_masked(key):
    assert _scrub({key: "harmless"})[key] == "harmless"


def test_sensitive_key_propagates_into_containers():
    out = _scrub({"token": ["one", "two"]})
    assert out["token"] == [MASK, MASK]


def test_unregistered_token_in_a_telegram_url_path_is_masked():
    out = _scrub("GET https://api.telegram.org/bot" + "x" * 40 + "/sendMessage")
    assert "x" * 40 not in out
    assert MASK in out


def test_bots_path_is_not_over_masked():
    assert _scrub("https://example.com/bots/list") == "https://example.com/bots/list"


@pytest.mark.parametrize("param", ["key", "api_key", "api-key", "access_token", "auth"])
def test_credential_query_parameters_are_masked(param):
    out = _scrub(f"https://api.example.com/v1/models?{param}=some-unknown-value&x=1")
    assert "some-unknown-value" not in out
    assert "x=1" in out


def test_url_userinfo_password_is_masked():
    out = _scrub("postgres://sigma:hunter2@db.internal:5432/sigma")
    assert "hunter2" not in out
    assert "sigma" in out


def test_unregistered_values_still_match_the_pattern_backstop():
    never_registered = fake_google_key().replace("Sy", "Qx")
    assert never_registered not in _scrub(f"leaked {never_registered} here")


@pytest.mark.parametrize("bot_id", ["11111111", "111111111", "1111111111", "11111111111"])
def test_telegram_pattern_covers_every_bot_id_length(bot_id):
    token = fake_telegram_token(bot_id)
    assert token not in _scrub(f"url=https://x/{token}")


def test_telegram_pattern_does_not_depend_on_the_AA_prefix():
    token = "1111111111:" + ("Qz09_-" * 6)[:35]
    assert token not in _scrub(f"token is {token}")


def test_processor_returns_the_event_dict():
    out = redact_processor(None, "info", {"event": "x", "url": TOKEN})
    assert out["event"] == "x"
    assert TOKEN not in out["url"]
