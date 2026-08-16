import pathlib
import subprocess

import pytest

from sigma.logging.redaction import _PATTERNS

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SELF = pathlib.Path(__file__).name


def _pushable_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [_ROOT / f for f in out]


def test_no_credential_shaped_literal_is_pushable():
    findings = []
    for path in _pushable_files():
        if not path.is_file() or path.name == _SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                rel = path.relative_to(_ROOT)
                findings.append(f"{rel}: {match.group()[:12]}…")

    assert not findings, (
        "credential-shaped literals would be pushed:\n  "
        + "\n  ".join(findings)
        + "\n\nBuild test credentials with tests/fakes.py instead of writing literals."
    )


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.production"])
def test_env_files_are_never_pushable(name):
    assert (_ROOT / name) not in _pushable_files()
