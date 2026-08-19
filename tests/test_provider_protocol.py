import ast
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from sigma.providers import BrokenProvider, FakeProvider, MarketDataProvider
from sigma.providers.corpactions import BseProvider, CorporateActionProvider, NseProvider
from sigma.providers.yahoo import YahooProvider
from tests.fakes import fake_snapshot

_SRC = Path(__file__).resolve().parents[1] / "src" / "sigma"


@pytest.mark.parametrize("provider", [YahooProvider(), FakeProvider(), BrokenProvider()])
def test_every_market_data_provider_satisfies_the_protocol(provider):
    # Structural, not nominal: none of these inherit anything. runtime_checkable
    # verifies the members exist; mypy is what verifies the signatures.
    assert isinstance(provider, MarketDataProvider)


def test_corporate_action_providers_satisfy_their_protocol():
    client = httpx.AsyncClient()
    assert isinstance(NseProvider(client), CorporateActionProvider)
    assert isinstance(BseProvider(client), CorporateActionProvider)


def test_the_two_protocols_are_not_interchangeable():
    # Both are "providers" in English and neither can stand in for the other.
    assert not isinstance(FakeProvider(), CorporateActionProvider)


async def test_the_fake_answers_with_what_it_was_given():
    snapshot = fake_snapshot("MSFT")
    provider = FakeProvider({"MSFT": snapshot})
    assert await provider.get_snapshot("msft") is snapshot
    assert provider.calls == ["msft"]


async def test_the_fake_fails_the_way_production_fails():
    from sigma.exceptions import SymbolNotFoundError

    with pytest.raises(SymbolNotFoundError):
        await FakeProvider().get_snapshot("NOPE")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("vendor", ["yfinance", "pandas"])
def test_only_the_yahoo_package_names_the_vendor(vendor):
    # The test that makes the layering real. Deleting providers/yahoo/ should
    # be a one-directory change, which is only true while this passes.
    offenders = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if vendor in _imports(path) and path.parent.name != "yahoo"
    )
    assert not offenders, f"{vendor} is imported outside providers/yahoo/: {offenders}"


def test_only_the_corpactions_package_names_httpx():
    allowed = {
        "providers/corpactions/http.py",
        "providers/corpactions/nse.py",
        "providers/corpactions/bse.py",
        "composition.py",
    }
    offenders = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if "httpx" in _imports(path) and path.relative_to(_SRC).as_posix() not in allowed
    )
    assert not offenders, f"httpx is imported outside the adapters: {offenders}"


def test_importing_the_bot_does_not_import_yfinance():
    # A subprocess, not a sys.modules purge: the claim is about a fresh
    # interpreter, and unimporting sigma inside this one leaves every other
    # test holding a stale module object.
    probe = "import sigma.bot, sys; print('yfinance' in sys.modules)"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    # The interface layer depends on a protocol, so the vendor SDK - and the
    # pandas and numpy behind it - is never loaded to run a handler.
    assert result.stdout.strip() == "False"
