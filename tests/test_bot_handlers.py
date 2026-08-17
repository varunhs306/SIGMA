import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, MessageEntity, Update, User

from sigma.bot import price_handler


def _command_message(**kwargs) -> Message:
    return Message(
        message_id=1,
        date=dt.datetime.now(dt.UTC),
        chat=Chat(id=1, type="group", title="t"),
        text="/price AAPL",
        entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        **kwargs,
    )


def _ctx():
    ctx = MagicMock()
    ctx.args = ["AAPL"]
    return ctx


@pytest.fixture
def stub_bot(monkeypatch):
    replies = AsyncMock()
    monkeypatch.setattr(Message, "reply_text", replies)
    monkeypatch.setattr("sigma.bot.fetch_ticker", AsyncMock(return_value={"symbol": "AAPL"}))
    return replies


async def test_edited_command_does_not_crash(stub_bot):
    user = User(id=7, first_name="u", is_bot=False)
    update = Update(update_id=1, edited_message=_command_message(from_user=user))

    assert update.message is None
    assert update.effective_message is not None

    await price_handler(update, _ctx())
    assert stub_bot.await_count > 0


async def test_channel_post_without_a_user_does_not_crash(stub_bot):
    update = Update(update_id=2, channel_post=_command_message())

    assert update.effective_user is None
    assert update.effective_message is not None

    await price_handler(update, _ctx())
    assert stub_bot.await_count > 0


async def test_update_with_no_message_returns_quietly():
    await price_handler(Update(update_id=3), _ctx())
