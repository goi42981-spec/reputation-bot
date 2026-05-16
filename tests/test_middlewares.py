"""Tests for the chat whitelist middleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from reputation_bot.middlewares import ChatWhitelistMiddleware, _is_bypass_command


def _fake_message(chat_id: int, text: str | None = None) -> MagicMock:
    from aiogram.types import Message

    msg = MagicMock(spec=Message)
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.caption = None
    return msg


def _fake_callback(chat_id: int) -> MagicMock:
    from aiogram.types import CallbackQuery

    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock()
    cb.message.chat = MagicMock()
    cb.message.chat.id = chat_id
    return cb


@pytest.mark.parametrize(
    "text, expected",
    [
        ("/chatid", True),
        ("/chatid@MyBot", True),
        ("/CHATID", True),
        ("/chatid extra args", True),
        ("/help", False),
        ("hello world", False),
        ("", False),
        (None, False),
    ],
)
def test_is_bypass_command(text: str | None, expected: bool) -> None:
    assert _is_bypass_command(text) is expected


async def test_empty_whitelist_allows_everything() -> None:
    mw = ChatWhitelistMiddleware(frozenset())
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    msg = _fake_message(chat_id=999, text="anything")
    result = await mw(handler, msg, {})
    assert result == "ok"
    assert called == [msg]


async def test_whitelisted_chat_is_allowed() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    msg = _fake_message(chat_id=-1001, text="/top")
    assert await mw(handler, msg, {}) == "ok"
    assert called == [msg]


async def test_non_whitelisted_chat_is_dropped() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    msg = _fake_message(chat_id=-9999, text="/top")
    assert await mw(handler, msg, {}) is None
    assert called == []


async def test_chatid_command_bypasses_whitelist() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    msg = _fake_message(chat_id=-9999, text="/chatid")
    assert await mw(handler, msg, {}) == "ok"
    assert called == [msg]


async def test_chatid_with_bot_suffix_bypasses_whitelist() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    msg = _fake_message(chat_id=-9999, text="/chatid@Homrepka_bot")
    assert await mw(handler, msg, {}) == "ok"
    assert called == [msg]


async def test_callback_from_whitelisted_chat_allowed() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    cb = _fake_callback(chat_id=-1001)
    assert await mw(handler, cb, {}) == "ok"
    assert called == [cb]


async def test_callback_from_non_whitelisted_chat_dropped() -> None:
    mw = ChatWhitelistMiddleware(frozenset({-1001}))
    called: list[Any] = []

    async def handler(event: Any, data: dict[str, Any]) -> str:
        called.append(event)
        return "ok"

    cb = _fake_callback(chat_id=-9999)
    assert await mw(handler, cb, {}) is None
    assert called == []
