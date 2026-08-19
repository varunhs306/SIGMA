"""Bulk corporate-action calendars.

Yahoo answers one ticker at a time, which makes "what is happening across the
market" cost one request per listed company. NSE and BSE each publish the whole
calendar as a single dated query, so the same question costs two requests. That
inversion is what makes an exchange-wide subscription affordable at all.
"""

from sigma.providers.corpactions.base import CorporateActionProvider
from sigma.providers.corpactions.bse import BseProvider
from sigma.providers.corpactions.normalise import normalise
from sigma.providers.corpactions.nse import NseProvider
from sigma.providers.corpactions.refresh import RefreshReport, refresh

__all__ = [
    "BseProvider",
    "CorporateActionProvider",
    "NseProvider",
    "RefreshReport",
    "normalise",
    "refresh",
]
