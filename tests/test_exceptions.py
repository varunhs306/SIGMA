import pytest

from sigma.exceptions import (
    ConfigurationError, LLMAuthError, LLMRateLimited, LLMUnavailable,
    ProviderRateLimited, ProviderTimeout, ProviderUnavailable,
    SigmaError, SymbolNotFoundError,
)

ALL = [ConfigurationError, LLMAuthError, LLMRateLimited, LLMUnavailable,
       ProviderRateLimited, ProviderTimeout, ProviderUnavailable, SymbolNotFoundError]


@pytest.mark.parametrize("cls", ALL)
def test_every_exception_inherits_the_root(cls):
    assert issubclass(cls, SigmaError)


def test_user_message_defaults_and_overrides():
    assert SigmaError("technical").user_message
    assert SigmaError("technical", user_message="friendly").user_message == "friendly"


def test_technical_message_does_not_leak_into_user_message():
    e = SigmaError("connection refused: 10.0.0.4:5432, token=abc123")
    assert "10.0.0.4" not in e.user_message
    assert "abc123" not in e.user_message


@pytest.mark.parametrize("cls, expected", [
    (ProviderRateLimited, True), (ProviderUnavailable, True), (ProviderTimeout, True),
    (LLMRateLimited, True), (LLMUnavailable, True),
    (SymbolNotFoundError, False), (LLMAuthError, False), (ConfigurationError, False),
])
def test_retryable_classification(cls, expected):
    assert cls("x").retryable is expected