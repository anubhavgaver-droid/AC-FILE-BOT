"""/batch — one link for a range of posts in a channel.

Rule: the bot must be an ADMIN of the channel the files come from (first and last post must be in the
same channel). Any channel where the bot is admin works — it is not limited to one fixed channel.
"""
from __future__ import annotations

import re
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from fsbot import links
from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.delivery import MAX_ITEMS
from fsbot.utils import h

FIRST, LAST = range(2)
LINK_RE = re.compile(r"t\.me/(?:c/(\d+)|([A-Za-z0-9_]{4,}))/(\d+)")
ADMIN_STATUSES = {"administrator", "creator"}


async def resolve_source(context: ContextTypes.DEFAULT_TYPE, msg) -> tuple[Optional[tuple[int, int, str]], Optional[str]]:
    """Return ((chat_id, message_id, title), None) or (None, error_text)."""
    chat_id = message_id = None
    title = None
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "type", None) == "channel":
        chat_id, message_id, title = origin.chat.id, origin.message_id, origin.chat.title
    else:
        match = LINK_RE.search(msg.text or "")
        if match:
            message_id = int(match.group(3))
            try:
                if match.group(1):
                    chat_id = int(f"-100{match.group(1)}")
                else:
                    chat = await context.bot.get_chat(f"@{match.group(2)}")
                    chat_id, title = chat.id, chat.title
            except TelegramError as exc:
                return None, f"❌ I can't open that channel ({exc}). Add me as an admin there first."
    if chat_id is None or message_id is None:
        return None, "❌ Forward a post from the channel (not from a user), or send the post link."

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as exc:
        return None, f"❌ I can't access that channel ({exc}). Add me as an <b>admin</b> there first."
    if me.status not in ADMIN_STATUSES:
        return None, "❌ I must be an <b>admin</b> of the channel the files come from. Add me as admin there, then try again."
    if title is None:
        try:
            title = (await context.bot.get_chat(chat_id)).title
        except TelegramError:
            title = str(chat_id)
    return (chat_id, message_id, title), None


async def batch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("batch_first", None)
    await update.effective_message.reply_html(
        "📦 <b>Batch link</b>\n\nForward the <b>FIRST</b> post from the channel (or send its post link).\n"
        "The bot must be an admin of that channel.\n\nSend /cancel to stop."
    )
    return FIRST


async def batch_first(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    found, error = await resolve_source(context, msg)
    if error:
        await msg.reply_html(error)
        return FIRST
    context.user_data["batch_first"] = found
    await msg.reply_html(f"✅ First post saved from <b>{h(found[2])}</b>.\nNow forward the <b>LAST</b> post (or send its link).")
    return LAST


async def batch_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    found, error = await resolve_source(context, msg)
    if error:
        await msg.reply_html(error)
        return LAST
    first = context.user_data.pop("batch_first", None)
    if first is None or first[0] != found[0]:
        await msg.reply_text("❌ The last post must come from the same channel as the first. Start again with /batch.")
        return ConversationHandler.END
    if found[1] < first[1]:
        await msg.reply_text("❌ The last post must come after the first. Start again with /batch.")
        return ConversationHandler.END
    count = found[1] - first[1] + 1
    if count > MAX_ITEMS:
        await msg.reply_text(f"❌ A batch can cover at most {MAX_ITEMS} posts. Pick a smaller range.")
        return ConversationHandler.END

    key = await get_db().create_link("b", [[found[0], first[1], found[1]]], update.effective_user.id, title=found[2])
    text, markup = links.result(
        context.bot_data["username"], "b", key,
        f"✅ <b>Batch created</b>\n📡 {h(found[2])} · posts {first[1]}–{found[1]} (up to {count} files)",
    )
    await msg.reply_html(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("batch_first", None)
    await update.effective_message.reply_text("Cancelled.")
    return ConversationHandler.END


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    content = admin & ~filters.COMMAND
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("batch", batch_start, filters=admin)],
            states={FIRST: [MessageHandler(content, batch_first)], LAST: [MessageHandler(content, batch_last)]},
            fallbacks=[CommandHandler("cancel", cancel, filters=admin)],
        )
    )
