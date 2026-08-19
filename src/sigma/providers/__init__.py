"""Adapters. Everything that speaks a vendor's dialect lives under here.

Importing this package must not import a vendor SDK - `sigma.providers.yahoo`
pulls in yfinance, pandas and numpy, and the composition root is the only
module that should pay for that.
"""

from sigma.providers.base import MarketDataProvider
from sigma.providers.fake import BrokenProvider, FakeProvider

__all__ = ["BrokenProvider", "FakeProvider", "MarketDataProvider"]
