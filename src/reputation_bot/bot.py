"""Bot bootstrap: build the Bot/Dispatcher and run polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Config
from .database import Database
from .handlers import make_router

logger = logging.getLogger(__name__)


async def run(config: Config) -> None:
    db = Database(config.db_path)
    await db.connect()
    try:
        bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher()
        dp.include_router(make_router(db, config))

        me = await bot.get_me()
        logger.info("Starting bot @%s (id=%s)", me.username, me.id)

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = Config.from_env()
    asyncio.run(run(config))
