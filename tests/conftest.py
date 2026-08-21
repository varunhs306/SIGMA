import logging
import socket

import pytest
from curl_cffi import requests as curl

from sigma.config import Settings, get_settings
from tests.fakes import fake_google_key, fake_telegram_token

_SIGMA_VARS = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "LOG_LEVEL")


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def clean_env(monkeypatch):
    for var in _SIGMA_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_logging():
    import sigma.logging.setup as s

    s._CONFIGURED = False
    yield
    s._CONFIGURED = False
    logging.getLogger().handlers.clear()


@pytest.fixture
def settings_factory():
    def _make(**overrides):
        return Settings(
            gemini_api_key=fake_google_key(),
            telegram_bot_token=fake_telegram_token(),
            _env_file=None,
            **overrides,
        )

    return _make


# --------------------------------------------------------------------------
# The no-network guard
# --------------------------------------------------------------------------


class NetworkAccessDenied(BaseException):
    """A test tried to reach the network. Record a fixture instead.

    BaseException, not RuntimeError, and for the same reason KeyboardInterrupt
    is: every provider in this project translates vendor failures with a broad
    `except Exception`, so a RuntimeError here comes back as
    `ProviderError: Failed to fetch data for AAPL` with the real cause visible
    only in the log line. This is not an application error to be handled - it is
    the harness refusing - so it declines to be caught by code under test.
    """


# Loopback is exempt, and the exemption is load-bearing rather than a
# convenience: asyncio's Windows ProactorEventLoop builds its self-pipe out of a
# loopback socketpair, so a total ban kills every async test inside asyncio with
# "'ProactorEventLoop' object has no attribute '_ssock'" - an error that names
# neither the guard nor the test that tripped it.
# S104 reads "0.0.0.0" as a bind address. It is a membership test: the OS
# routes a connect() to it back to this host, so it belongs with the others.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", ""})  # noqa: S104
_INET = (socket.AF_INET, socket.AF_INET6)

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _is_local(host: object) -> bool:
    # None is what bind() passes for "any interface".
    return host is None or (isinstance(host, str) and host in _LOOPBACK)


def _leaves_the_machine(sock: socket.socket, address: object) -> bool:
    if sock.family not in _INET:
        return False  # AF_UNIX and friends cannot reach another host
    return not _is_local(address[0] if isinstance(address, tuple) else address)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail any test that opens a connection, at both layers that can open one.

    Patching `socket` alone is the trap. It stops httpx, and it does not stop
    yfinance: yfinance 1.2 speaks through curl_cffi, which is libcurl in C and
    never touches Python's socket module. A suite guarded only at the socket
    layer reports a clean run while talking to Yahoo on every ticker test.

    Opt out with `@pytest.mark.network` for a test that is *about* reaching the
    network - there is exactly one, and it is skipped unless asked for.
    """
    if request.node.get_closest_marker("network"):
        yield
        return

    def deny_connect(self, address, /):
        if _leaves_the_machine(self, address):
            raise NetworkAccessDenied(f"socket connect to {address!r}")
        return _real_connect(self, address)

    def deny_connect_ex(self, address, /):
        if _leaves_the_machine(self, address):
            raise NetworkAccessDenied(f"socket connect_ex to {address!r}")
        return _real_connect_ex(self, address)

    def deny_getaddrinfo(host, *args, **kwargs):
        # Resolution is blocked as well as connection, for two reasons: a DNS
        # query is already traffic, and a host that does not resolve fails with
        # a getaddrinfo errno that looks nothing like "a test hit the network".
        if _is_local(host):
            return _real_getaddrinfo(host, *args, **kwargs)
        raise NetworkAccessDenied(f"DNS lookup for {host!r}")

    def deny_curl(self, method, url, *args, **kwargs):
        raise NetworkAccessDenied(f"curl_cffi {method} {url}")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", deny_getaddrinfo)
    monkeypatch.setattr(curl.Session, "request", deny_curl)
    monkeypatch.setattr(curl.AsyncSession, "request", deny_curl)
    yield
