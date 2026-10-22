"""/custombatch — collect any files one by one into ONE link.

While it runs, a status message with an inline ⏹ Stop button stays at the bottom of the chat.
Files are copied into the private DB channel; Stop creates the Base64 link.
"""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_config
from fsbot import links
from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.utils import spawn

COLLECT = 0
MAX_FILES = 500
_refresh: dict[int, asyncio.Task] = {}


def _markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏹ Stop & Create Link", callback_data="cb:stop")],
         [InlineKeyboardButton("❌ Cancel", callback_data="cb:cancel")]]
    )


def _status_text(count: int) -> str:
    return (
        f"📥 <b>Custom batch</b> — <b>{count}</b> file{'s' if count != 1 else ''} collected.\n\n"
        "Keep sending files (forwarded or not). Tap <b>⏹ Stop</b> when you are done."
    )


async def _post_status(bot, chat_id: int, user_data: dict, delay: float = 0.0) -> None:
    """Move the status message to the bottom of the chat (debounced while files stream in)."""
    if delay:
        await asyncio.sleep(delay)
    old = user_data.pop("cb_status", None)
    if old:
        try:
            await bot.delete_message(chat_id, old)
        except TelegramError:
            pass
    msg = await bot.send_message(
        chat_id, _status_text(len(user_data.get("cb_ranges", []))), parse_mode="HTML", reply_markup=_markup()
    )
    user_data["cb_status"] = msg.message_id


def _cancel_refresh(chat_id: int) -> None:
    task = _refresh.pop(chat_id, None)
    if task:
        task.cancel()


async def custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    _cancel_refresh(chat_id)
    context.user_data["cb_ranges"] = []
    context.user_data.pop("cb_status", None)
    await _post_status(context.bot, chat_id, context.user_data)
    return COLLECT


async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg, chat_id = update.effective_message, update.effective_chat.id
    ranges: list = context.user_data.setdefault("cb_ranges", [])
    if len(ranges) >= MAX_FILES:
        await msg.reply_text(f"Limit of {MAX_FILES} files reached. Tap ⏹ Stop to create the link.")
        return COLLECT
    db_channel = get_config().db_channel_id
    try:
        stored = await context.bot.copy_message(chat_id=db_channel, from_chat_id=chat_id, message_id=msg.message_id)
    except TelegramError as exc:
        await msg.reply_html(f"❌ Could not store this file: <code>{exc}</code>\nIs the bot an admin of the DB channel?")
        return COLLECT
    ranges.append([db_channel, stored.message_id, stored.message_id])
    _cancel_refresh(chat_id)
    _refresh[chat_id] = spawn(_post_status(context.bot, chat_id, context.user_data, delay=1.0))
    return COLLECT


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE, create: bool) -> int:
    chat_id = update.effective_chat.id
    _cancel_refresh(chat_id)
    ranges = context.user_data.get("cb_ranges", [])
    status = context.user_data.pop("cb_status", None)
    context.user_data.pop("cb_ranges", None)
    if status:
        try:
            await context.bot.delete_message(chat_id, status)
        except TelegramError:
            pass
    if not create:
        await context.bot.send_message(chat_id, "Cancelled. Nothing was saved as a link.")
        return ConversationHandler.END
    if not ranges:
        await context.bot.send_message(chat_id, "No files were collected, so no link was created.")
        return ConversationHandler.END

    key = await get_db().create_link("c", ranges, update.effective_user.id)
    text, markup = links.result(
        context.bot_data["username"], "c", key, f"✅ <b>Custom batch created</b> — {len(ranges)} file(s)"
    )
    await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    return ConversationHandler.END


async def stop_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _finish(update, context, create=query.data == "cb:stop")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _finish(update, context, create=True)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _finish(update, context, create=False)


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("custombatch", custom_start, filters=admin)],
            states={
                COLLECT: [
                    MessageHandler(admin & ~filters.COMMAND, collect),
                    CallbackQueryHandler(stop_button, pattern=r"^cb:(stop|cancel)$"),
                ]
            },
            fallbacks=[
                CommandHandler("stop", stop_command, filters=admin),
                CommandHandler("cancel", cancel_command, filters=admin),
            ],
        )
    )
