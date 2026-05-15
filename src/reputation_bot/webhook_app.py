"""FastAPI webhook application for production deployment (e.g. Fly.io).

This exposes a single ``/webhook`` endpoint that Telegram POSTs updates to.
On startup, the app registers the webhook with Telegram; on shutdown it
deletes it. Bot state (Dispatcher, Bot, Database) is created in the
``lifespan`` context manager and shared via the FastAPI ``app.state``.

Required environment variables:
  - ``BOT_TOKEN``: Telegram bot token (from @BotFather).
  - ``WEBHOOK_URL`` (or auto-derived from ``FLY_APP_NAME``): The public HTTPS
    URL the bot is reachable at. The bot will POST updates to
    ``<WEBHOOK_URL>/webhook``.

Optional environment variables:
  - ``WEBHOOK_SECRET``: Secret token used to authenticate Telegram callbacks
    (https://core.telegram.org/bots/api#setwebhook). If unset, a random one
    is generated on each startup (acceptable because Telegram will be told
    about it during setWebhook).
  - ``DB_PATH``: Path to the SQLite database file (default ``reputation.db``).
  - ``OWNER_ID``: Telegram user ID with super-owner rights across all chats.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from .config import Config
from .database import Database
from .handlers import make_router

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"


def _resolve_webhook_url() -> str:
    """Determine the public HTTPS URL to register with Telegram.

    Order of resolution:
    1. ``WEBHOOK_URL`` env var (explicit override).
    2. ``RENDER_EXTERNAL_URL`` (Render.com auto-injects this).
    3. ``RENDER_EXTERNAL_HOSTNAME`` (also Render.com).
    4. ``FLY_APP_NAME`` (Fly.io).
    """
    for var in ("WEBHOOK_URL", "RENDER_EXTERNAL_URL"):
        url = os.environ.get(var, "").strip()
        if url:
            return url.rstrip("/")

    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        return f"https://{render_host}"

    fly_app = os.environ.get("FLY_APP_NAME", "").strip()
    if fly_app:
        return f"https://{fly_app}.fly.dev"

    raise RuntimeError(
        "Cannot determine webhook URL. Set WEBHOOK_URL, or run on Render (which sets "
        "RENDER_EXTERNAL_URL automatically), or on Fly.io (which sets FLY_APP_NAME)."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = Config.from_env()
    db = Database(config.db_path)
    await db.connect()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(make_router(db, config))

    webhook_url = _resolve_webhook_url()
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "").strip() or secrets.token_urlsafe(32)

    me = await bot.get_me()
    logger.info("Bot @%s (id=%s) starting in webhook mode", me.username, me.id)

    await bot.set_webhook(
        url=f"{webhook_url}{WEBHOOK_PATH}",
        secret_token=webhook_secret,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info("Webhook registered: %s%s", webhook_url, WEBHOOK_PATH)

    app.state.bot = bot
    app.state.dp = dp
    app.state.db = db
    app.state.webhook_secret = webhook_secret
    app.state.bot_username = me.username

    try:
        yield
    finally:
        try:
            await bot.delete_webhook()
        except Exception:
            logger.exception("Failed to delete webhook during shutdown")
        await bot.session.close()
        await db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def healthz() -> dict[str, str]:
    """Healthcheck endpoint."""
    bot_username = getattr(app.state, "bot_username", None)
    return {"status": "ok", "bot": f"@{bot_username}" if bot_username else "unknown"}


@app.get("/healthz")
async def healthz_alias() -> dict[str, str]:
    return await healthz()


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """Receive an update from Telegram and feed it into aiogram."""
    expected_secret: str = request.app.state.webhook_secret
    if x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    data = await request.json()
    bot: Bot = request.app.state.bot
    dp: Dispatcher = request.app.state.dp
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
