"""Aiogram middlewares.

Currently this module hosts :class:`ChatWhitelistMiddleware`, which restricts the
bot to a configured set of chats. The ``/chatid`` command always bypasses the
whitelist so users can still discover chat IDs before adding them to the
allow-list.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


# Commands that always go through, even when the chat is not whitelisted.
# Keep this list minimal — every entry here is reachable from any chat.
_BYPASS_COMMANDS: frozenset[str] = frozenset({"/chatid"})


def _is_bypass_command(text: str | None) -> bool:
    if not text:
        return False
    head = text.lstrip().split(maxsplit=1)[0] if text.strip() else ""
    # Strip a "@botname" suffix if present (e.g. "/chatid@my_bot").
    head = head.split("@", 1)[0].lower()
    return head in _BYPASS_COMMANDS


class ChatWhitelistMiddleware(BaseMiddleware):
    """Drop updates whose chat is not in the allow-list.

    Empty ``allowed_chat_ids`` disables the filter entirely — useful while the
    operator is still discovering the chat ID via ``/chatid``.
    """

    def __init__(self, allowed_chat_ids: frozenset[int]) -> None:
        self.allowed_chat_ids = allowed_chat_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed_chat_ids:
            return await handler(event, data)

        chat_id: int | None = None
        text: str | None = None

        if isinstance(event, Message):
            chat_id = event.chat.id
            text = event.text or event.caption
        elif isinstance(event, CallbackQuery) and event.message is not None:
            chat_id = event.message.chat.id

        if chat_id is None:
            # Not a chat-bound update (e.g. inline query) — drop to be safe.
            return None

        if chat_id in self.allowed_chat_ids:
            return await handler(event, data)

        if isinstance(event, Message) and _is_bypass_command(text):
            return await handler(event, data)

        logger.debug("Dropping update from non-whitelisted chat %s", chat_id)
        return None
