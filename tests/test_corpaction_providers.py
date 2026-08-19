import datetime as dt

import httpx
import pytest

from sigma.domain import EventType, Exchange
from sigma.exceptions import (
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from sigma.providers.corpactions import BseProvider, NseProvider

START = dt.date(2026, 8, 1)
END = dt.date(2026, 9, 30)

# Two rows per exchange, copied field for field from a live response. Day 09
# turns the full payloads into recorded fixtures; two rows is enough to pin the
# mapping, and small enough to read.
NSE_ROWS = [
    {
        "bcEndDate": "-",
        "bcStartDate": "-",
        "caBroadcastDate": None,
        "comp": "Kirloskar Pneumatic Company Limited",
        "exDate": "18-Aug-2026",
        "faceVal": "2",
        "ind": "-",
        "isin": "INE811A01020",
        "ndEndDate": "-",
        "ndStartDate": "-",
        "recDate": "18-Aug-2026",
        "series": "EQ",
        "subject": "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share",
        "symbol": "KIRLPNU",
    },
    {
        "bcEndDate": "-",
        "bcStartDate": "-",
        "caBroadcastDate": None,
        "comp": "Coforge Limited",
        "exDate": "03-Aug-2026",
        "faceVal": "2",
        "ind": "-",
        "isin": "INE591G01017",
        "ndEndDate": "-",
        "ndStartDate": "-",
        "recDate": "-",
        "series": "EQ",
        "subject": "Interim Dividend - Rs 4 Per Share",
        "symbol": "COFORGE",
    },
]

BSE_ROWS = [
    {
        "scrip_code": 505283,
        "short_name": "KIRLPNU",
        "Ex_date": "18 Aug 2026",
        "Purpose": "Stock  Split From Rs.2/- to Rs.1/-",
        "RD_Date": "18 Aug 2026",
        "BCRD_FROM": "",
        "BCRD_TO": "",
        "ND_START_DATE": "18 Aug 2026",
        "ND_END_DATE": "18 Aug 2026",
        "payment_date": "",
        "exdate": "20260818",
        "long_name": "Kirloskar Pneumatic Company Ltd",
    },
    {
        "scrip_code": 532541,
        "short_name": "COFORGE",
        "Ex_date": "03 Aug 2026",
        "Purpose": "Interim Dividend - Rs. - 4.0000",
        "RD_Date": "03 Aug 2026",
        "BCRD_FROM": "",
        "BCRD_TO": "",
        "ND_START_DATE": "03 Aug 2026",
        "ND_END_DATE": "03 Aug 2026",
        "payment_date": "",
        "exdate": "20260803",
        "long_name": "Coforge Ltd",
    },
]


def _client(handler) -> httpx.AsyncClient:
    """A real AsyncClient over a transport that never opens a socket."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _serving(payload, status=200, **response_kwargs):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if response_kwargs:
            return httpx.Response(status, **response_kwargs)
        return httpx.Response(status, json=payload)

    return handler, seen


async def test_nse_maps_a_row_onto_the_domain():
    handler, _ = _serving(NSE_ROWS)
    async with _client(handler) as client:
        actions = await NseProvider(client).fetch(START, END)

    split, dividend = actions
    assert split.exchange is Exchange.NSE
    assert split.symbol == "KIRLPNU"
    assert split.ticker == "KIRLPNU.NS"
    assert split.isin == "INE811A01020"
    assert split.detail.type is EventType.SPLIT
    assert split.ex_date == dt.date(2026, 8, 18)
    # NSE writes an absent record date as a dash, which is not a date.
    assert dividend.record_date is None
    assert dividend.detail.amount == 4.0


async def test_bse_addresses_the_company_by_scrip_code():
    handler, _ = _serving(BSE_ROWS)
    async with _client(handler) as client:
        actions = await BseProvider(client).fetch(START, END)

    split = actions[0]
    # short_name is KIRLPNU and KIRLPNU.BO resolves to nothing. This assertion
    # is the whole reason the BSE mapper never reads that field.
    assert split.symbol == "505283"
    assert split.ticker == "505283.BO"
    assert split.detail.split_factor == 2.0
    # BSE sends no ISIN at all, and Day 08b declines to fetch a second source.
    assert split.isin is None


async def test_both_exchanges_report_the_same_split_independently():
    nse_handler, _ = _serving(NSE_ROWS)
    bse_handler, _ = _serving(BSE_ROWS)
    async with _client(nse_handler) as nc, _client(bse_handler) as bc:
        nse = (await NseProvider(nc).fetch(START, END))[0]
        bse = (await BseProvider(bc).fetch(START, END))[0]

    assert nse.detail == bse.detail
    assert nse.ex_date == bse.ex_date
    # Same event, two rows, two keys. No cross-exchange deduplication.
    assert nse.key != bse.key


async def test_nse_always_sends_the_window():
    # Omitting the dates returns ~20 rows from a two-day default window with a
    # 200 status. The signature is what makes that call unexpressible.
    handler, seen = _serving(NSE_ROWS)
    async with _client(handler) as client:
        await NseProvider(client).fetch(START, END)

    params = seen[0].url.params
    assert params["from_date"] == "01-08-2026"
    assert params["to_date"] == "30-09-2026"
    assert params["index"] == "equities"
    # No event-type filter: sending one narrows the response to that type.
    assert "subject" not in params


async def test_bse_sends_the_referer_that_stops_the_301():
    handler, seen = _serving(BSE_ROWS)
    async with _client(handler) as client:
        await BseProvider(client).fetch(START, END)

    request = seen[0]
    assert request.headers["Referer"] == "https://www.bseindia.com/"
    assert request.url.params["Fdate"] == "20260801"
    assert request.url.params["TDate"] == "20260930"
    # Blank filters are what return the whole calendar rather than one type.
    assert request.url.params["scripcode"] == ""


async def test_a_redirect_that_survives_following_is_an_error():
    # What BSE actually does without the Referer: 301, empty body, no Location.
    handler, _ = _serving(None, 301, text="")
    async with _client(handler) as client:
        with pytest.raises(ProviderError, match="redirected"):
            await BseProvider(client).fetch(START, END)


async def test_html_with_a_200_is_not_success():
    handler, _ = _serving(None, 200, text="<html><body>Access Denied</body></html>")
    async with _client(handler) as client:
        with pytest.raises(ProviderError, match="not JSON"):
            await NseProvider(client).fetch(START, END)


async def test_a_json_object_where_a_list_was_promised_is_an_error():
    handler, _ = _serving({"message": "no data"})
    async with _client(handler) as client:
        with pytest.raises(ProviderError, match="expected a list"):
            await NseProvider(client).fetch(START, END)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, ProviderRateLimited), (503, ProviderUnavailable), (404, ProviderError)],
)
async def test_status_codes_become_the_project_taxonomy(status, expected):
    handler, _ = _serving(None, status, text="")
    async with _client(handler) as client:
        with pytest.raises(expected):
            await NseProvider(client).fetch(START, END)


async def test_transport_failures_become_the_project_taxonomy():
    def timing_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with _client(timing_out) as client:
        with pytest.raises(ProviderTimeout):
            await BseProvider(client).fetch(START, END)
    async with _client(unreachable) as client:
        with pytest.raises(ProviderUnavailable):
            await BseProvider(client).fetch(START, END)


async def test_one_unusable_row_does_not_cost_the_others():
    rows = [{"symbol": "GOOD", "exDate": "18-Aug-2026", "subject": "Buy Back"}, {"symbol": "BAD"}]
    handler, _ = _serving(rows)
    async with _client(handler) as client:
        actions = await NseProvider(client).fetch(START, END)

    assert [a.symbol for a in actions] == ["GOOD"]


async def test_an_unparsed_purpose_is_still_stored():
    rows = [{"symbol": "X", "exDate": "18-Aug-2026", "subject": "Scheme of Arrangement"}]
    handler, _ = _serving(rows)
    async with _client(handler) as client:
        action = (await NseProvider(client).fetch(START, END))[0]

    assert action.detail.type is EventType.UNKNOWN
    assert action.raw == "Scheme of Arrangement"
