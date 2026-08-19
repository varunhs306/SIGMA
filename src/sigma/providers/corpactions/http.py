"""One GET, and the vendor-error translation both exchange adapters share.

These are undocumented endpoints on the same footing as yfinance: no contract,
no versioning, and no warning before a change. Everything they can do wrong
becomes a `SigmaError` subclass here, so nothing above this package imports
httpx or knows what a status code is.
"""

from typing import Any

import httpx

from sigma.domain import Exchange
from sigma.exceptions import (
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from sigma.logging import get_logger

logger = get_logger(__name__)

# TODO(day-10): this literal becomes the retry policy's timeout, applied to
# every outbound call rather than to the two in this package.
TIMEOUT_SECONDS = 20.0


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str],
    exchange: Exchange,
) -> list[dict[str, Any]]:
    log = logger.bind(exchange=exchange.value, url=url)

    try:
        response = await client.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    except httpx.TimeoutException as e:
        log.warning("corpactions_timeout", error=str(e))
        raise ProviderTimeout(f"{exchange} corporate actions timed out") from e
    except httpx.TransportError as e:
        log.warning("corpactions_transport_error", error=str(e))
        raise ProviderUnavailable(f"{exchange} corporate actions unreachable") from e

    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        log.warning("corpactions_rate_limited")
        raise ProviderRateLimited(f"{exchange} rate limit hit")
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        log.warning("corpactions_upstream_error", status=response.status_code)
        raise ProviderUnavailable(f"{exchange} returned {response.status_code}")
    if response.is_redirect:
        # A redirect that survived follow_redirects means the request was
        # rejected before it was routed. BSE does this - a 301 with an empty
        # body - when the Referer header is missing.
        log.error("corpactions_unfollowed_redirect", status=response.status_code)
        raise ProviderError(f"{exchange} redirected the request away ({response.status_code})")
    if response.status_code != httpx.codes.OK:
        log.error("corpactions_unexpected_status", status=response.status_code)
        raise ProviderError(f"{exchange} returned {response.status_code}")

    try:
        payload = response.json()
    except ValueError as e:
        # An HTML interstitial with a 200 status is the normal failure mode for
        # both of these hosts, and it is indistinguishable from success until
        # something tries to parse it.
        log.error("corpactions_not_json", content_type=response.headers.get("content-type"))
        raise ProviderError(f"{exchange} returned a body that is not JSON") from e

    if not isinstance(payload, list):
        log.error("corpactions_unexpected_shape", shape=type(payload).__name__)
        raise ProviderError(f"{exchange} returned {type(payload).__name__}, expected a list")

    rows: list[dict[str, Any]] = [row for row in payload if isinstance(row, dict)]
    if len(rows) != len(payload):
        log.warning("corpactions_non_object_rows", dropped=len(payload) - len(rows))
    return rows
