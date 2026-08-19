import datetime as dt

from sigma.domain import Exchange
from sigma.exceptions import ProviderUnavailable
from sigma.providers.corpactions import refresh
from sigma.store import EventStore
from tests.fakes import fake_action

START = dt.date(2026, 8, 1)
END = dt.date(2026, 9, 30)


class StubExchange:
    """A CorporateActionProvider that answers from a list."""

    def __init__(self, exchange: Exchange, actions=(), error: Exception | None = None) -> None:
        self.exchange = exchange
        self._actions = tuple(actions)
        self._error = error
        self.windows: list[tuple[dt.date, dt.date]] = []

    async def fetch(self, start: dt.date, end: dt.date):
        self.windows.append((start, end))
        if self._error is not None:
            raise self._error
        return self._actions


async def test_a_refresh_stores_every_exchange(tmp_path):
    store = EventStore(tmp_path / "sigma.db")
    providers = [
        StubExchange(Exchange.NSE, [fake_action(Exchange.NSE, "KIRLPNU")]),
        StubExchange(Exchange.BSE, [fake_action(Exchange.BSE, "505283")]),
    ]

    reports = await refresh(providers, store, START, END)

    assert [r.exchange for r in reports] == ["NSE", "BSE"]
    assert all(r.ok for r in reports)
    assert store.count() == 2


async def test_running_it_twice_is_running_it_once(tmp_path):
    store = EventStore(tmp_path / "sigma.db")
    providers = [StubExchange(Exchange.NSE, [fake_action()])]

    await refresh(providers, store, START, END)
    second = await refresh(providers, store, START, END)

    assert second[0].counts.inserted == 0
    assert second[0].counts.unchanged == 1
    assert store.count() == 1


async def test_backfill_and_incremental_are_the_same_call(tmp_path):
    # There is no separate backfill path to keep correct: a three-year window
    # and a two-day window are the same function with different arguments.
    store = EventStore(tmp_path / "sigma.db")
    provider = StubExchange(Exchange.NSE, [fake_action()])

    await refresh([provider], store, dt.date(2023, 1, 1), END)
    await refresh([provider], store, START, END)

    assert provider.windows == [(dt.date(2023, 1, 1), END), (START, END)]
    assert store.count() == 1


async def test_one_exchange_failing_does_not_cost_the_other(tmp_path):
    store = EventStore(tmp_path / "sigma.db")
    providers = [
        StubExchange(Exchange.NSE, error=ProviderUnavailable("NSE returned 503")),
        StubExchange(Exchange.BSE, [fake_action(Exchange.BSE, "505283")]),
    ]

    reports = await refresh(providers, store, START, END)

    # "NSE is down and BSE is fine" is a normal Tuesday, and the caller needs
    # both halves of that sentence rather than one exception.
    assert not reports[0].ok
    assert "503" in (reports[0].error or "")
    assert reports[1].ok
    assert store.count() == 1
