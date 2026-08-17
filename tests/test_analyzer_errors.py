import pytest
from google.genai import errors as genai_errors

from sigma.analyzer import _translate
from sigma.exceptions import LLMAuthError, LLMError, LLMRateLimited, LLMUnavailable


def _api_error(code):
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"message": "x"}})


@pytest.mark.parametrize(
    "code, expected, retryable",
    [
        (429, LLMRateLimited, True),
        (401, LLMAuthError, False),
        (403, LLMAuthError, False),
        (500, LLMUnavailable, True),
        (503, LLMUnavailable, True),
        (400, LLMError, False),
        (418, LLMError, False),
    ],
)
def test_translation_and_retryability(code, expected, retryable):
    err = _translate(_api_error(code))
    assert type(err) is expected
    assert err.retryable is retryable


def test_chaining_is_preserved(monkeypatch):
    original = _api_error(429)
    try:
        raise _translate(original) from original
    except LLMRateLimited as e:
        assert e.__cause__ is original
