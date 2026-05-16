"""Telegram command and message handlers."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from .config import POINT_OPTIONS, REPUTATION_LIMIT, Config
from .database import Database, UserRecord
from .keyboards import parse_callback_data, reputation_keyboard
from .permissions import (
    can_grant_moderators,
    can_manage_reputation,
    is_chat_admin,
)

if TYPE_CHECKING:
    from aiogram.types import MessageEntity

logger = logging.getLogger(__name__)


# ---------- helpers ----------


def _format_user(record: UserRecord) -> str:
    if record.username:
        return f"@{record.username}"
    if record.full_name:
        return f"{record.full_name} (ID {record.user_id})"
    return f"ID {record.user_id}"


def _user_display(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or f"ID {user.id}"


async def _resolve_target_from_args(
    message: Message,
    db: Database,
    raw: str | None,
) -> UserRecord | None:
    """Resolve a target user from a command argument or a reply.

    Accepts ``@username``, plain ``username`` or a numeric user ID.
    Falls back to ``message.reply_to_message.from_user`` if no argument is provided.
    """
    chat_id = message.chat.id

    if raw:
        token = raw.strip().split()[0]
        if token.lstrip("-").isdigit():
            user = await db.get_user_by_id(chat_id, int(token))
            if user:
                return user
        return await db.get_user_by_username(chat_id, token)

    reply = message.reply_to_message
    if reply and reply.from_user:
        return await db.get_user_by_id(chat_id, reply.from_user.id)

    return None


def _mention_entities(entities: list[MessageEntity] | None) -> list[tuple[str, int | None]]:
    """Extract (mention_text_without_at, user_id) pairs from message entities.

    For ``@username`` mentions, user_id is None. For ``text_mention`` (when a user is
    mentioned without a public username), user_id is the Telegram user ID.
    """
    if not entities:
        return []
    results: list[tuple[str, int | None]] = []
    for entity in entities:
        if entity.type == "mention":
            # We'll resolve text in the caller from the offset/length.
            results.append(("", None))
        elif entity.type == "text_mention" and entity.user is not None:
            results.append((entity.user.full_name or "", entity.user.id))
    return results


# ---------- /start, /help ----------


HELP_TEXT = (
    "<b>Бот управления репутацией</b>\n\n"
    "<b>Использование:</b>\n"
    "• Упомяните бота и целевого пользователя в одном сообщении: "
    "<code>@имя_бота @username</code> — появится меню с кнопками "
    "<b>+/-</b> для изменения репутации.\n"
    "• Можно также ответить (reply) на сообщение пользователя текстом "
    "<code>@имя_бота</code>.\n\n"
    "<b>Команды:</b>\n"
    "<code>/add &lt;@username|ID&gt;</code> — добавить пользователя в базу (админ).\n"
    "<code>/delete &lt;@username|ID&gt;</code> — удалить пользователя из базы (админ).\n"
    "<code>/grant &lt;@username|ID&gt;</code> — выдать права модератора (только владелец группы).\n"
    "<code>/revoke &lt;@username|ID&gt;</code> — отозвать права модератора (только владелец).\n"
    "<code>/mods</code> — список модераторов.\n"
    "<code>/rep [@username|ID]</code> — посмотреть репутацию (по умолчанию — свою).\n"
    "<code>/top [N]</code> — топ участников по репутации (по умолчанию 10).\n"
    "<code>/chatid</code> — узнать ID текущего чата (для настройки whitelist).\n\n"
    f"<b>Лимит репутации:</b> ±{REPUTATION_LIMIT}.\n"
    f"<b>Доступные значения:</b> {', '.join(str(v) for v in POINT_OPTIONS)}."
)


def make_router(db: Database, config: Config) -> Router:
    """Build the aiogram Router with all handlers wired up."""
    router = Router(name="reputation")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(HELP_TEXT, parse_mode="HTML")

    @router.message(Command("chatid"))
    async def cmd_chatid(message: Message) -> None:
        """Reply with the current chat's ID.

        Used by the operator to discover chat IDs before adding them to
        ``ALLOWED_CHAT_IDS``. This command bypasses the chat whitelist so it
        works even from non-whitelisted chats.
        """
        chat = message.chat
        name_parts = [p for p in (chat.first_name, chat.last_name) if p]
        title = chat.title or " ".join(name_parts) or chat.username or "—"
        await message.reply(
            f"<b>Chat ID:</b> <code>{chat.id}</code>\n"
            f"<b>Type:</b> {chat.type}\n"
            f"<b>Title:</b> {title}",
            parse_mode="HTML",
        )

    @router.message(Command("add"))
    async def cmd_add(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None or message.chat.type == "private":
            return
        if not await is_chat_admin(bot, message.chat.id, message.from_user.id):
            return  # Silently ignore non-admin invocations as required.

        chat_id = message.chat.id
        added: list[str] = []

        # Resolve text_mention entities first (these carry user_id directly).
        for entity in message.entities or []:
            if entity.type == "text_mention" and entity.user is not None:
                tg_user = entity.user
                await db.upsert_user(
                    chat_id,
                    tg_user.id,
                    tg_user.username,
                    tg_user.full_name,
                )
                added.append(_user_display(tg_user))

        # Then handle reply target.
        if message.reply_to_message and message.reply_to_message.from_user:
            tg_user = message.reply_to_message.from_user
            await db.upsert_user(chat_id, tg_user.id, tg_user.username, tg_user.full_name)
            added.append(_user_display(tg_user))

        # Then handle plain arguments (@username / ID).
        if command.args:
            for token in command.args.split():
                token = token.strip()
                if not token:
                    continue
                if token.lstrip("-").isdigit():
                    user_id = int(token)
                    await db.upsert_user(chat_id, user_id, None, None)
                    added.append(f"ID {user_id}")
                else:
                    normalized = token.lstrip("@")
                    # Without a Telegram user ID we cannot create a real entry,
                    # but we record a placeholder keyed on a synthetic negative ID
                    # only if the user is already known. Otherwise warn.
                    existing = await db.get_user_by_username(chat_id, normalized)
                    if existing is None:
                        await message.reply(
                            f"Чтобы добавить @{normalized}, попросите его(её) написать что-то "
                            "в чат, а затем ответьте (reply) на это сообщение командой "
                            "<code>/add</code>. Telegram не позволяет ботам резолвить "
                            "@username без предварительного контакта.",
                            parse_mode="HTML",
                        )
                        continue
                    added.append(f"@{normalized}")

        if not added:
            await message.reply(
                "Использование: <code>/add @username</code>, "
                "<code>/add 123456789</code> или ответьте (reply) на сообщение "
                "пользователя командой <code>/add</code>.",
                parse_mode="HTML",
            )
            return

        await message.reply(f"Добавлены/обновлены: {', '.join(added)}.")

    @router.message(Command("delete", "del"))
    async def cmd_delete(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None or message.chat.type == "private":
            return
        if not await is_chat_admin(bot, message.chat.id, message.from_user.id):
            return

        target = await _resolve_target_from_args(message, db, command.args)
        if target is None:
            await message.reply(
                "Не нашёл пользователя. Использование: "
                "<code>/delete @username</code> или reply.",
                parse_mode="HTML",
            )
            return
        ok = await db.delete_user(target.chat_id, target.user_id)
        if ok:
            await message.reply(f"Пользователь {_format_user(target)} удалён из базы.")
        else:
            await message.reply("Этого пользователя нет в базе.")

    @router.message(Command("grant"))
    async def cmd_grant(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None or message.chat.type == "private":
            return
        if not await can_grant_moderators(bot, config, message.chat.id, message.from_user.id):
            return

        target = await _resolve_target_from_args(message, db, command.args)
        if target is None:
            await message.reply(
                "Не нашёл пользователя. Сначала добавьте его(её) через <code>/add</code>.",
                parse_mode="HTML",
            )
            return
        added = await db.add_moderator(target.chat_id, target.user_id, message.from_user.id)
        if added:
            await message.reply(f"{_format_user(target)} теперь модератор.")
        else:
            await message.reply(f"{_format_user(target)} уже модератор.")

    @router.message(Command("revoke"))
    async def cmd_revoke(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None or message.chat.type == "private":
            return
        if not await can_grant_moderators(bot, config, message.chat.id, message.from_user.id):
            return

        target = await _resolve_target_from_args(message, db, command.args)
        if target is None:
            await message.reply(
                "Не нашёл пользователя. Использование: <code>/revoke @username</code>.",
                parse_mode="HTML",
            )
            return
        removed = await db.remove_moderator(target.chat_id, target.user_id)
        if removed:
            await message.reply(f"С {_format_user(target)} сняты права модератора.")
        else:
            await message.reply(f"{_format_user(target)} не был модератором.")

    @router.message(Command("mods"))
    async def cmd_mods(message: Message) -> None:
        if message.chat.type == "private":
            return
        ids = await db.list_moderators(message.chat.id)
        if not ids:
            await message.reply("Модераторы не назначены.")
            return
        lines = []
        for uid in ids:
            rec = await db.get_user_by_id(message.chat.id, uid)
            lines.append(_format_user(rec) if rec else f"ID {uid}")
        await message.reply("Модераторы:\n• " + "\n• ".join(lines))

    @router.message(Command("rep"))
    async def cmd_rep(message: Message, command: CommandObject) -> None:
        if message.from_user is None or message.chat.type == "private":
            return
        target: UserRecord | None
        if command.args or message.reply_to_message:
            target = await _resolve_target_from_args(message, db, command.args)
        else:
            target = await db.get_user_by_id(message.chat.id, message.from_user.id)
        if target is None:
            await message.reply("Пользователь не найден в базе бота.")
            return
        await message.reply(f"Репутация {_format_user(target)}: <b>{target.reputation}</b>.",
                            parse_mode="HTML")

    @router.message(Command("top"))
    async def cmd_top(message: Message, command: CommandObject) -> None:
        if message.chat.type == "private":
            return
        limit = 10
        if command.args:
            with suppress(ValueError):
                limit = max(1, min(50, int(command.args.strip().split()[0])))
        users = await db.top_users(message.chat.id, limit)
        if not users:
            await message.reply("В базе пока нет пользователей. Добавьте через <code>/add</code>.",
                                parse_mode="HTML")
            return
        lines = [f"<b>Топ-{len(users)} по репутации:</b>"]
        for idx, rec in enumerate(users, start=1):
            lines.append(f"{idx}. {_format_user(rec)} — <b>{rec.reputation}</b>")
        await message.reply("\n".join(lines), parse_mode="HTML")

    # ---------- mention handler (bot + target user) ----------

    @router.message(F.entities)
    async def on_mention(message: Message, bot: Bot) -> None:
        """When the bot is mentioned with another user, show the reputation keyboard."""
        if message.from_user is None or message.chat.type == "private":
            return
        if not message.text and not message.caption:
            return
        text = message.text or message.caption or ""
        entities = message.entities or message.caption_entities or []

        me = await bot.me()
        me_username = (me.username or "").lower()

        bot_mentioned = False
        target_user_id: int | None = None
        target_username: str | None = None

        for entity in entities:
            if entity.type == "mention":
                mention_text = text[entity.offset + 1 : entity.offset + entity.length].lower()
                if mention_text == me_username:
                    bot_mentioned = True
                elif target_user_id is None and target_username is None:
                    target_username = mention_text
            elif entity.type == "text_mention" and entity.user is not None:
                if target_user_id is None and target_username is None:
                    target_user_id = entity.user.id
                    # Persist a fresh username / name snapshot.
                    await db.upsert_user(
                        message.chat.id,
                        entity.user.id,
                        entity.user.username,
                        entity.user.full_name,
                    )

        # Also allow a reply to a user's message with the bot mentioned.
        if (
            bot_mentioned
            and target_user_id is None
            and target_username is None
            and message.reply_to_message
            and message.reply_to_message.from_user
            and not message.reply_to_message.from_user.is_bot
        ):
            reply_user = message.reply_to_message.from_user
            target_user_id = reply_user.id
            await db.upsert_user(
                message.chat.id,
                reply_user.id,
                reply_user.username,
                reply_user.full_name,
            )

        if not bot_mentioned:
            return
        if target_user_id is None and target_username is None:
            return

        if not await can_manage_reputation(
            bot, db, config, message.chat.id, message.from_user.id
        ):
            return

        target: UserRecord | None = None
        if target_user_id is not None:
            target = await db.get_user_by_id(message.chat.id, target_user_id)
        elif target_username is not None:
            target = await db.get_user_by_username(message.chat.id, target_username)

        if target is None:
            await message.reply(
                "Не нашёл целевого пользователя в базе. Сначала добавьте его(её) "
                "через <code>/add</code> (можно reply на их сообщение).",
                parse_mode="HTML",
            )
            return

        # Refresh data of the initiator too, so /top shows recognisable names.
        await db.upsert_user(
            message.chat.id,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
        )

        await message.reply(
            f"Изменить репутацию {_format_user(target)} "
            f"(сейчас <b>{target.reputation}</b>):",
            reply_markup=reputation_keyboard(target.user_id),
            parse_mode="HTML",
        )

    # ---------- callback (button presses) ----------

    @router.callback_query(F.data.startswith("rep:"))
    async def on_reputation_button(query: CallbackQuery, bot: Bot) -> None:
        if query.message is None or query.from_user is None or query.data is None:
            await query.answer()
            return
        if not isinstance(query.message, Message):
            await query.answer()
            return

        chat_id = query.message.chat.id
        parsed = parse_callback_data(query.data)
        if parsed is None:
            await query.answer("Неверные данные кнопки.", show_alert=False)
            return
        target_user_id, action = parsed

        if not await can_manage_reputation(bot, db, config, chat_id, query.from_user.id):
            await query.answer("У вас нет прав изменять репутацию.", show_alert=True)
            return

        if action == "cancel":
            with suppress(TelegramBadRequest):
                await query.message.edit_text("Отменено.")
            await query.answer()
            return

        try:
            delta = int(action)
        except ValueError:
            await query.answer("Неверное значение.", show_alert=False)
            return

        try:
            new_value = await db.adjust_reputation(chat_id, target_user_id, delta)
        except LookupError:
            await query.answer("Пользователь не найден в базе.", show_alert=True)
            return

        target = await db.get_user_by_id(chat_id, target_user_id)
        target_label = _format_user(target) if target else f"ID {target_user_id}"

        sign = "+" if delta > 0 else ""
        result_text = (
            f"Репутация {target_label} изменена: {sign}{delta}. "
            f"Текущая: <b>{new_value}</b>."
        )

        with suppress(TelegramBadRequest):
            await query.message.edit_text(
                result_text,
                reply_markup=_continue_keyboard(target_user_id),
                parse_mode="HTML",
            )
        await query.answer()

    return router


def _continue_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    """Compact keyboard offered after a reputation adjustment.

    Lets the moderator keep tweaking the same target without re-mentioning the bot.
    """
    plus_row = [
        InlineKeyboardButton(text=f"+{a}", callback_data=f"rep:{target_user_id}:+{a}")
        for a in POINT_OPTIONS
    ]
    minus_row = [
        InlineKeyboardButton(text=f"-{a}", callback_data=f"rep:{target_user_id}:-{a}")
        for a in POINT_OPTIONS
    ]
    done_row = [
        InlineKeyboardButton(text="Готово", callback_data=f"rep:{target_user_id}:cancel"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[plus_row, minus_row, done_row])
