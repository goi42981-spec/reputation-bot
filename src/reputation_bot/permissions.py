"""Permission checks for group owner and moderator commands."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from .config import Config
from .database import Database


async def is_chat_owner(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Return True if the user is the Telegram chat owner (creator)."""
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status == ChatMemberStatus.CREATOR


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Return True if the user is a Telegram chat owner or administrator."""
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


async def can_manage_reputation(
    bot: Bot,
    db: Database,
    config: Config,
    chat_id: int,
    user_id: int,
) -> bool:
    """Check if the user may change reputation.

    Allowed: super_owner (env OWNER_ID), chat owner, chat admin, granted moderators.
    """
    if config.super_owner_id is not None and user_id == config.super_owner_id:
        return True
    if await is_chat_admin(bot, chat_id, user_id):
        return True
    return await db.is_moderator(chat_id, user_id)


async def can_grant_moderators(
    bot: Bot,
    config: Config,
    chat_id: int,
    user_id: int,
) -> bool:
    """Check if the user may grant/revoke moderator rights.

    Only the chat owner (creator) or the super_owner from env may do this.
    """
    if config.super_owner_id is not None and user_id == config.super_owner_id:
        return True
    return await is_chat_owner(bot, chat_id, user_id)
