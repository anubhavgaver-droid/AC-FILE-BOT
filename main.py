"""Entry point: python main.py"""
from __future__ import annotations

import asyncio
import logging

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from config import get_config
from fsbot import admins, settings, web
from fsbot.db import get_db, init_db
from fsbot.delivery import deletion_loop
from fsbot.utils import spawn
from plugins import load_plugins

logging.basicConfig(format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("filestore")

PUBLIC_COMMANDS = [BotCommand("start", "Start the bot"), BotCommand("help", "Help")]
ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand("settings", "Settings panel (all buttons)"),
    BotCommand("single", "Save one file → link"),
    BotCommand("batch", "Channel range → link"),
    BotCommand("custombatch", "Many files → one link"),
    BotCommand("adminhelp", "All admin commands"),
]


async def post_init(app: Application) -> None:
    cfg = get_config()
    me = await app.bot.get_me()
    app.bot_data["username"] = me.username
    web.set_info(bot=me.username)

    await app.bot.set_my_commands(PUBLIC_COMMANDS)
    for owner in cfg.owner_ids:
        try:
            await app.bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(owner))
        except TelegramError:
            pass

    if cfg.port:  # Render (or any host that provides $PORT) needs an open HTTP port
        await web.start_server(cfg.port)
        if cfg.public_url:
            spawn(web.keepalive_loop(cfg.public_url))
    spawn(deletion_loop(app.bot, me.username))
    log.info("Bot started as @%s", me.username)


async def post_stop(app: Application) -> None:
    await web.stop_server()
    try:
        await get_db().close()
    except Exception:  # noqa: BLE001
        pass


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error", exc_info=context.error)


def main() -> None:
    cfg = get_config()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())  # MongoDB + indexes
    loop.run_until_complete(settings.load())
    loop.run_until_complete(admins.load())

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    load_plugins(app)
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
