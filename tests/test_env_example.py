import re
from pathlib import Path

from sigma.config import Settings

_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE = _ROOT / ".env.example"


def _documented() -> set[str]:
    text = _EXAMPLE.read_text(encoding="utf-8")
    return {m.group(1).lower() for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M)}


def test_every_setting_appears_in_env_example():
    missing = set(Settings.model_fields) - _documented()
    assert not missing, (
        f"add these to .env.example: {sorted(missing)}. "
        "A field nobody can discover is a field nobody sets."
    )


def test_env_example_documents_nothing_that_is_not_a_setting():
    extra = _documented() - set(Settings.model_fields)
    assert not extra, (
        f".env.example lists {sorted(extra)}, which Settings does not accept. "
        "extra='forbid' means copying it to .env fails at startup."
    )


def test_env_example_holds_no_real_values():
    for line in _EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith(("GEMINI_API_KEY=", "TELEGRAM_BOT_TOKEN=")):
            value = line.split("=", 1)[1]
            assert value.startswith("<"), (
                f"{line.split('=')[0]} looks like a real value, not a placeholder"
            )
