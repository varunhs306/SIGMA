# SIGMA

[![CI](https://github.com/varunhs306/SIGMA/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/varunhs306/SIGMA/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](https://github.com/varunhs306/SIGMA/actions/workflows/ci.yml) [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A self-hosted Telegram bot for equity analysis. Deterministic metrics from Yahoo
Finance, written judgement from Google Gemini.

```
/price AAPL

Apple Inc. (AAPL)
Price: $305.59
Market Cap:$4.46T
P/E Ratio:35.04
52W High:$344.57
52W Low:$223.78
30D Change:-6.35%
```

`/analyze AAPL` sends the same metrics to Gemini and returns valuation, key risks and
a short-term outlook.

## Features

- Global tickers, including exchange suffixes (`RELIANCE.NS`, `SAP.DE`)
- JSON logging with a correlation ID per request and credential redaction
- Typed configuration validated at startup
- Missing data renders as `N/A`, never as zero
- Single container, no inbound ports, no database

## Commands

| Command | Description |
|---|---|
| `/price <TICKER>` | Price, market cap, P/E, 52-week range, 30-day change |
| `/analyze <TICKER>` | Valuation, key risks and short-term outlook |
| `/help` | List available commands |

## Quick start

Get a bot token from [@BotFather](https://t.me/botfather) and an API key from
[Google AI Studio](https://aistudio.google.com/apikey). Copy
[.env.example](.env.example) to `.env` and set both.

### Docker

```bash
docker compose up -d --build
docker compose logs -f
```

State lives on the `sigma-data` volume. Only one instance can run per bot token.

### Local

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync
uv run sigma
```

## Configuration

Set through the environment or `.env`.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | required | Google AI Studio API key |
| `TELEGRAM_BOT_TOKEN` | required | Bot token from @BotFather |
| `LLM_MODEL` | `gemini-2.5-flash-lite` | Gemini model id |
| `LLM_TEMPERATURE` | `0.3` | Sampling temperature, `0.0` to `2.0` |
| `LLM_MAX_OUTPUT_TOKENS` | `1024` | Response cap, `64` to `32768` |
| `LLM_MAX_RETRIES` | `3` | Retries on a transient Gemini error, `1` to `10` |
| `HISTORY_PERIOD` | `1mo` | Yahoo Finance history window |
| `DATA_DIR` | `./data` | Root for all writable state |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FILE` | `logs/sigma.log` | JSON log destination |
| `LOG_MAX_BYTES` | `5242880` | Rotation threshold |
| `LOG_BACKUP_COUNT` | `3` | Rotated files retained |

Unknown variables fail at startup.

## Architecture

```
Telegram ──▶ bot.py ──▶ fetcher.py ──▶ Yahoo Finance
                   └──▶ analyzer.py ─▶ Gemini
```

Vendor errors are translated at the provider boundary, so `bot.py` handles one
exception type and imports no provider SDK.

## Development

```bash
uv sync --extra dev
uv run pre-commit install
```

| Task | Command |
|---|---|
| Tests | `uv run pytest -q` |
| Lint | `uv run ruff check src/ tests/` |
| Format | `uv run ruff format src/ tests/` |
| Type check | `uv run mypy src/sigma/` |

## License

[MIT](LICENSE)
