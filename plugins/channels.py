"""DMs the owners the channel ID whenever the bot is made admin of (or removed from) a channel."""
from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ChatMemberHandler, ContextTypes

from config import get_config
from fsbot.utils import h


async def on_my_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event = update.my_chat_member
    chat = event.chat
    if chat.type != "channel":
        return
    status = event.new_chat_member.status
    if status == "administrator":
        text = f"✅ Bot is now an admin in <b>{h(chat.title)}</b>\nChannel ID: <code>{chat.id}</code>"
    elif status in {"left", "kicked"}:
        text = f"⚠️ Bot was removed from <b>{h(chat.title)}</b> (<code>{chat.id}</code>)."
    else:
        return
    for owner in get_config().owner_ids:
        try:
            await context.bot.send_message(owner, text, parse_mode="HTML")
        except TelegramError:
            pass


def register(app) -> None:
    app.add_handler(ChatMemberHandler(on_my_status, ChatMemberHandler.MY_CHAT_MEMBER))
