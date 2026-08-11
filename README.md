# SIGMA

Telegram bot for equity analysis. Pulls market data from Yahoo Finance and generates
written analysis with Google Gemini.

## Commands

| Command | Description |
|---|---|
| `/price <TICKER>` | Price, market cap, P/E, 52-week range, 30-day change |
| `/analyze <TICKER>` | Valuation, key risks and short-term outlook |
| `/help` | List available commands |

## Setup

```bash
git clone https://github.com/varunhs306/sigma.git
cd sigma
pip install yfinance google-genai python-telegram-bot pydantic-settings structlog telegramify-markdown
cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/botfather) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |

Run:

```bash
python main.py
```

## License

MIT — see [LICENSE](LICENSE).
