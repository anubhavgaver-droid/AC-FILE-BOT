"""/single — save ONE file (forwarded or not) and get a Base64 link.

The bot copies it into your private DB channel, stores the record in MongoDB and replies with the link.
"""
from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from config import get_config
from fsbot import links
from fsbot.admins import admin_filter
from fsbot.db import get_db

WAIT = 0


async def single_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_html(
        "📄 <b>Single link</b>\n\nSend me the file you want to save — forwarded or not, anything works.\n"
        "Send /cancel to stop."
    )
    return WAIT


async def single_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg, user = update.effective_message, update.effective_user
    db_channel = get_config().db_channel_id
    try:
        stored = await context.bot.copy_message(chat_id=db_channel, from_chat_id=msg.chat_id, message_id=msg.message_id)
    except TelegramError as exc:
        await msg.reply_html(
            f"❌ Could not store the file in the DB channel: <code>{exc}</code>\n"
            "Make sure the bot is an <b>admin</b> of that channel (DB_CHANNEL_ID)."
        )
        return ConversationHandler.END
    key = await get_db().create_link("s", [[db_channel, stored.message_id, stored.message_id]], user.id)
    text, markup = links.result(context.bot_data["username"], "s", key, "✅ <b>File saved</b>")
    await msg.reply_html(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Cancelled.")
    return ConversationHandler.END


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("single", single_start, filters=admin)],
            states={WAIT: [MessageHandler(admin & ~filters.COMMAND, single_receive)]},
            fallbacks=[CommandHandler("cancel", cancel, filters=admin)],
        )
    )
