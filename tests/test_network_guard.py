"""Tests for the thing that makes every other test trustworthy.

A guard nobody tests is a guard that quietly stops working, and this one has
already failed once in a way that looked like success: patching `socket` blocks
httpx and does nothing at all to yfinance.
"""

import asyncio
import socket

import httpx
import pytest
from curl_cffi import requests as curl

from tests.conftest import NetworkAccessDenied

_UNREACHABLE = "https://example.invalid"


def test_a_plain_http_call_is_denied():
    # Denied at resolution, before a packet exists. Blocking only connect() left
    # this test measuring an NXDOMAIN errno instead of the guard.
    with pytest.raises(NetworkAccessDenied, match="DNS lookup"):
        httpx.get(_UNREACHABLE, timeout=5)


async def test_an_async_http_call_is_denied():
    async with httpx.AsyncClient() as client:
        with pytest.raises(NetworkAccessDenied):
            await client.get(_UNREACHABLE, timeout=5)


def test_a_connection_to_a_literal_address_is_denied():
    # A raw connect(), not create_connection(): the latter calls getaddrinfo even
    # for a dotted quad, so it never reaches the half of the guard under test.
    sock = socket.socket()
    with sock, pytest.raises(NetworkAccessDenied, match="socket connect"):
        sock.connect(("93.184.215.14", 80))


def test_curl_cffi_is_denied_at_its_own_layer():
    # The one that matters. libcurl resolves and connects in C, so this call
    # never reaches Python's socket module and the socket patch never sees it.
    with pytest.raises(NetworkAccessDenied, match="curl_cffi"):
        curl.Session().get(_UNREACHABLE)


def test_yfinance_cannot_reach_yahoo():
    import yfinance as yf

    # The guard reaches the vendor SDK, not just our own call sites: yfinance
    # asks for its auth crumb before anything else and never gets it.
    with pytest.raises(NetworkAccessDenied, match="getcrumb"):
        _ = yf.Ticker("AAPL").info


def test_both_layers_are_patched_and_not_just_one():
    # The structural version of the lesson above: a future refactor that drops
    # either patch leaves a guard that reports a clean run while talking to Yahoo.
    assert socket.socket.connect.__name__ == "deny_connect"
    assert curl.Session.request.__name__ == "deny_curl"


def test_loopback_is_still_allowed():
    # Not a courtesy. asyncio's Windows event loop builds its self-pipe from a
    # loopback socketpair, so banning loopback breaks every async test in the
    # suite with an AttributeError raised inside asyncio.
    left, right = socket.socketpair()
    with left, right:
        left.send(b"ping")
        assert right.recv(4) == b"ping"


async def test_an_async_test_still_gets_an_event_loop():
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().is_running()


@pytest.mark.network
def test_the_marker_lifts_the_guard_and_the_endpoints_still_answer():
    """Opt-in smoke test: `uv run pytest -m network`.

    This is the only test that reaches a real host. It exists so that fixture
    drift is discoverable on purpose rather than on the day a mapping silently
    starts returning nothing.
    """
    from sigma.domain import Exchange
    from sigma.providers.corpactions import bse, nse
    from tests import replay

    modules = {Exchange.NSE: nse, Exchange.BSE: bse}
    for exchange, module in modules.items():
        document = replay.corpactions(exchange)
        # The params come out of the fixture, so this sends what the provider
        # sent when the fixture was recorded rather than what a test author
        # remembers. Sending NSE's params without the dates answers 200 with a
        # two-day window, which is exactly the drift this test exists to catch.
        response = httpx.get(
            document["request"]["url"],
            params=document["request"]["params"],
            headers=module._HEADERS,
            timeout=30,
            follow_redirects=True,
        )
        assert response.status_code == httpx.codes.OK
        live = response.json()
        assert isinstance(live, list)

        # Every key the fixture holds is still a key the endpoint sends. A
        # renamed field is what silently empties a mapper.
        live_keys = {key for row in live if isinstance(row, dict) for key in row}
        recorded_keys = {key for row in document["records"] for key in row}
        assert recorded_keys <= live_keys, f"{exchange} dropped {recorded_keys - live_keys}"
