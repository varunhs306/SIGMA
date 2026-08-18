import datetime as dt

from sigma.domain import CompanyProfile, PriceBar, Quote, TickerSnapshot

FAKE_BOT_ID = "1111111111"


def fake_telegram_token(bot_id: str = FAKE_BOT_ID) -> str:
    return bot_id + ":" + "AA" + ("Zz09_-" * 6)[:33]


def fake_google_key() -> str:
    return "AI" + "za" + ("Sy" + "0Aa_-Zz9" * 5)[:35]


def fake_bars(
    closes: tuple[float, ...], start: dt.date = dt.date(2026, 7, 1)
) -> tuple[PriceBar, ...]:
    """One bar per close, consecutive days, OHLC collapsed onto the close."""
    return tuple(
        PriceBar(
            date=start + dt.timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
        )
        for i, close in enumerate(closes)
    )


def fake_snapshot(
    symbol: str = "AAPL",
    *,
    closes: tuple[float, ...] = (100.0, 110.0),
    **quote_fields: object,
) -> TickerSnapshot:
    """A valid snapshot. Every field a caller does not care about is real anyway."""
    return TickerSnapshot(
        profile=CompanyProfile(symbol=symbol, name="Apple Inc.", sector="Technology"),
        quote=Quote(symbol=symbol, price=110.0, **quote_fields),  # type: ignore[arg-type]
        bars=fake_bars(closes),
    )
