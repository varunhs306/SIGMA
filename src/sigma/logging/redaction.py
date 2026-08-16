import re
from typing import Any

MASK = "***REDACTED***"

_SECRETS: set[str] = set()

_SENSITIVE_KEYS = frozenset({
    "authorization", "credential", "credentials", "passwd", "password",
    "secret", "token", "apikey", "api_key",
})
_SENSITIVE_SUFFIXES = ("_token", "_key", "_secret", "_password", "_credential")


def _is_sensitive_key(key) -> bool:
    k = str(key).lower()
    return k in _SENSITIVE_KEYS or k.endswith(_SENSITIVE_SUFFIXES)


_URL_RULES = [
    (re.compile(r"(/bot)([^/\s]{15,})"), r"\1" + MASK),
    (re.compile(r"(?i)([?&](?:api[_-]?key|key|token|access[_-]?token|auth)=)([^&\s\"']+)"),
     r"\1" + MASK),
    (re.compile(r"(://[^/\s:@]+:)([^@\s/]+)(@)"), r"\1" + MASK + r"\3"),
]

_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\b\d{8,12}:[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
]


def register_secret(value: str) -> None:
    if value and len(value) >= 8:
        _SECRETS.add(value)


def clear_secrets() -> None:
    _SECRETS.clear()


def _scrub_str(v: str) -> str:
    for s in _SECRETS:
        v = v.replace(s, MASK)
    for pattern, repl in _URL_RULES:
        v = pattern.sub(repl, v)
    for p in _PATTERNS:
        v = p.sub(MASK, v)
    return v


def _scrub(v: Any, key: Any = None) -> Any:
    if isinstance(v, str):
        return MASK if key is not None and _is_sensitive_key(key) else _scrub_str(v)
    if isinstance(v, bytes):
        return _scrub(v.decode("utf-8", "replace"), key).encode("utf-8")
    if isinstance(v, dict):
        return {k: _scrub(x, k) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        scrubbed = [_scrub(x, key) for x in v]
        if isinstance(v, tuple):
            make = getattr(type(v), "_make", None)
            return make(scrubbed) if make else tuple(scrubbed)
        return scrubbed
    return v


def redact_processor(logger, method_name, event_dict):
    return _scrub(event_dict)
