"""Replay the recorded payloads through the real mappers.

Every other test in this suite feeds the mappers a dict a human wrote, which
tests the code against what we believe the upstream sends. These feed it what
the upstream actually sent, which is a different claim and the one that breaks.
"""

import datetime as dt

import pytest

from sigma.domain import EventType, Exchange
from sigma.providers.corpactions import BseProvider, NseProvider
from sigma.providers.yahoo.mapper import QUOTE_KEYS
from tests import replay

# A fixture is a photograph, not a contract: the upstream keeps moving and the
# file does not. A year is long enough that re-recording is not busywork and
# short enough that the suite cannot quietly certify a payload nobody has seen
# since. When this fails, run scripts/record_fixtures.py - do not raise it.
MAX_FIXTURE_AGE = dt.timedelta(days=365)

PROVIDERS = {Exchange.NSE: NseProvider, Exchange.BSE: BseProvider}


@pytest.mark.parametrize("exchange", list(Exchange))
async def test_every_recorded_row_maps_onto_the_domain(exchange):
    document = replay.corpactions(exchange)
    async with replay.corpaction_client(exchange) as client:
        actions = await PROVIDERS[exchange](client).fetch(dt.date(2026, 8, 1), dt.date(2026, 9, 30))

    # Not "most rows". A rejected row is a company that vanishes from a
    # market-wide feed, and it is silent by construction.
    assert len(actions) == len(document["records"])


@pytest.mark.parametrize("exchange", list(Exchange))
async def test_the_recorded_window_covers_every_event_type(exchange):
    async with replay.corpaction_client(exchange) as client:
        actions = await PROVIDERS[exchange](client).fetch(dt.date(2026, 8, 1), dt.date(2026, 9, 30))

    # The recorder trims per event type, so this is what proves the trim kept a
    # representative slice rather than 20 dividends.
    assert {action.detail.type for action in actions} == set(EventType)


@pytest.mark.parametrize("exchange", list(Exchange))
async def test_a_trimmed_fixture_still_reports_what_it_was_trimmed_from(exchange):
    document = replay.corpactions(exchange)
    # The row count in the file is 18-20; the window really held 331 and 672.
    # Losing that number is how a fixture starts looking like the whole truth.
    assert document["total_records"] > len(document["records"])


@pytest.mark.parametrize("exchange", list(Exchange))
async def test_the_recorded_request_is_the_one_the_provider_makes(exchange):
    document = replay.corpactions(exchange)
    params = document["request"]["params"]

    # The recorder drove the real provider, so these came off the real request.
    # If someone changes the params in nse.py, re-recording is the only way to
    # make this pass - which is the point.
    if exchange is Exchange.NSE:
        assert params["from_date"] == "01-08-2026"
        assert "subject" not in params  # an event-type filter narrows the feed
    else:
        assert params["Fdate"] == "20260801"
        assert params["scripcode"] == ""  # a blank filter is what returns everything


@pytest.mark.parametrize(
    "relative",
    ["nse_corporate_actions.json", "bse_corporate_actions.json", "yahoo/aapl.json"],
)
def test_fixtures_are_not_stale(relative):
    age = dt.date.today() - replay.recorded_at(replay.load(relative))
    assert age <= MAX_FIXTURE_AGE, (
        f"{relative} was recorded {age.days} days ago. Re-record the fixtures: "
        "uv run python scripts/record_fixtures.py --all"
    )


async def test_a_real_yahoo_payload_fills_every_quote_field():
    snapshot = await replay.yahoo_provider("AAPL").get_snapshot("AAPL")

    # 11 of 11. The hand-written dicts in test_yahoo_provider.py reach 3, and
    # the 3 are chosen to be invalid, so 8 mappings had never met real data.
    populated = [f for f in QUOTE_KEYS if getattr(snapshot.quote, f) is not None]
    assert len(populated) == len(QUOTE_KEYS), f"unmapped: {set(QUOTE_KEYS) - set(populated)}"
    assert snapshot.profile.name == "Apple Inc."
    assert len(snapshot.bars) == 23


async def test_an_index_prices_from_the_fallback_key():
    info, _ = replay.yahoo_payload("^GSPC")
    # The reason QUOTE_KEYS['price'] is a tuple and not a string.
    assert info.get("currentPrice") is None

    snapshot = await replay.yahoo_provider("^GSPC").get_snapshot("^GSPC")
    assert snapshot.quote.price == info["regularMarketPrice"]


async def test_a_bse_scrip_renders_no_name_rather_than_a_machine_identifier():
    info, _ = replay.yahoo_payload("531910.BO")
    # shortName here is '531910.BO,0P0000BRKR,244'-shaped junk, and PROFILE_KEYS
    # reads longName only. Yahoo sends no longName for this scrip at all.
    assert "longName" not in info

    snapshot = await replay.yahoo_provider("531910.BO").get_snapshot("531910.BO")
    assert snapshot.profile.name is None
    assert snapshot.quote.price > 0


async def test_an_ampersand_ticker_survives_the_symbol_pattern():
    # GVT&D.NS is a real NSE listing and the pre-Day-08b pattern rejected it.
    snapshot = await replay.yahoo_provider("GVT&D.NS").get_snapshot("GVT&D.NS")
    assert snapshot.symbol == "GVT&D.NS"
    assert snapshot.profile.name is not None


@pytest.mark.parametrize("symbol", ["AAPL", "RELIANCE.NS", "531910.BO", "^GSPC", "GVT&D.NS"])
async def test_every_recorded_symbol_produces_a_usable_snapshot(symbol):
    snapshot = await replay.yahoo_provider(symbol).get_snapshot(symbol)

    assert snapshot.quote.price > 0
    # >= 2 bars is what makes price_change_30d expressible, and every /price
    # reply renders it.
    assert len(snapshot.bars) >= 2
    assert snapshot.price_change_30d is not None
