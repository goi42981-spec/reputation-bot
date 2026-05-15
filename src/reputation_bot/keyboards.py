"""Inline keyboards used by the bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import POINT_OPTIONS


def reputation_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    """Build the +/- reputation keyboard for the given target user.

    Callback data format: ``rep:<target_user_id>:<sign><amount>`` (e.g. ``rep:42:+10``).
    """
    plus_row = [
        InlineKeyboardButton(
            text=f"+{amount}",
            callback_data=f"rep:{target_user_id}:+{amount}",
        )
        for amount in POINT_OPTIONS
    ]
    minus_row = [
        InlineKeyboardButton(
            text=f"-{amount}",
            callback_data=f"rep:{target_user_id}:-{amount}",
        )
        for amount in POINT_OPTIONS
    ]
    cancel_row = [
        InlineKeyboardButton(text="Отмена", callback_data=f"rep:{target_user_id}:cancel"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[plus_row, minus_row, cancel_row])


def parse_callback_data(data: str) -> tuple[int, str] | None:
    """Parse callback data ``rep:<target_user_id>:<action>``.

    Returns ``(target_user_id, action)`` where action is one of ``"+1"``, ``"-5"``,
    ``"cancel"``, etc. Returns ``None`` if the data is malformed.
    """
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "rep":
        return None
    try:
        target_user_id = int(parts[1])
    except ValueError:
        return None
    action = parts[2]
    if action == "cancel":
        return target_user_id, action
    if len(action) < 2 or action[0] not in "+-":
        return None
    try:
        int(action[1:])
    except ValueError:
        return None
    return target_user_id, action
