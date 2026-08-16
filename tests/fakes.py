FAKE_BOT_ID = "1111111111"


def fake_telegram_token(bot_id: str = FAKE_BOT_ID) -> str:
    return bot_id + ":" + "AA" + ("Zz09_-" * 6)[:33]


def fake_google_key() -> str:
    return "AI" + "za" + ("Sy" + "0Aa_-Zz9" * 5)[:35]
