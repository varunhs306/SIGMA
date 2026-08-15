class SigmaError(Exception):

    retryable: bool = False

    default_user_message = "Something went wrong. Please try again."

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or self.default_user_message


class ConfigurationError(SigmaError):
    """Unrecoverable. Fail at startup — there is no degraded mode."""


# ---- data providers ----
class ProviderError(SigmaError):
    default_user_message = "Could not reach the market data provider."

class SymbolNotFoundError(ProviderError):
    default_user_message = "I could not find that symbol."

class ProviderRateLimited(ProviderError):
    retryable = True
    default_user_message = "The data provider is busy. Try again shortly."

class ProviderUnavailable(ProviderError):
    retryable = True

class ProviderTimeout(ProviderError):
    retryable = True


# ---- the LLM ----
class LLMError(SigmaError):
    default_user_message = "The analysis service failed. Try again shortly."

class LLMRateLimited(LLMError):
    retryable = True
    default_user_message = "Gemini is busy. Try again in a moment."

class LLMUnavailable(LLMError):
    retryable = True

class LLMAuthError(LLMError):
    """Bad or missing API key. Retrying cannot help."""

class LLMInvalidResponse(LLMError):
    """Empty candidates, truncated output, or nothing usable returned."""