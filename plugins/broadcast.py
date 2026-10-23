"""/broadcast — reply to a message to copy it to every active user."""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

from fsbot.admins import admin_filter
from fsbot.broadcast import run
from fsbot.db import get_db
from fsbot.utils import spawn


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    source = msg.reply_to_message
    if not source:
        await msg.reply_html("Reply to the message you want to send with <code>/broadcast</code> "
                             "(or use /settings → Users → Broadcast).")
        return
    user_ids = await get_db().user_ids()
    status = await msg.reply_text(f"📣 Broadcasting to {len(user_ids)} users…")
    spawn(run(context.bot, user_ids, source.chat_id, source.message_id, status))


def register(app) -> None:
    app.add_handler(CommandHandler("broadcast", broadcast, filters=admin_filter() & filters.ChatType.PRIVATE))
