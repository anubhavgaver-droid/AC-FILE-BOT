"""Force-subscribe management.

/addfsub [direct|request]  forward a post from the channel (or send its ID)
/delfsub <channel_id>      remove a channel
/fsublist                  list channels

Public channel  -> normal join button ("direct").
Private channel -> join-REQUEST link; a pending request counts as joined ("request").
The bot must be an admin (with "Invite users via link") in each channel.
"""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from fsbot import fsub, settings
from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.utils import h

log = logging.getLogger(__name__)
WAIT = 0
MODES = {"auto", "direct", "request"}


async def addfsub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    mode = context.args[0].lower() if context.args else "auto"
    if mode not in MODES:
        await msg.reply_html("Usage: <code>/addfsub [direct|request]</code>")
        return ConversationHandler.END
    if len(await get_db().list_fsub()) >= fsub.MAX_CHANNELS:
        await msg.reply_text(f"At most {fsub.MAX_CHANNELS} force-subscribe channels. Remove one with /delfsub.")
        return ConversationHandler.END
    context.user_data["fsub_mode"] = mode
    await msg.reply_html(
        "📢 <b>Add force-subscribe channel</b>\n\n"
        "Forward <b>any post</b> from the channel (the bot must be admin there), or send the channel ID.\n\n"
        "• Public channel → normal join button\n"
        "• Private channel → join-request link (a request counts as joined)\n"
        "Force a mode with <code>/addfsub direct</code> or <code>/addfsub request</code>.\n\n"
        "Send /cancel to stop."
    )
    return WAIT


async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    chat_id: Optional[int] = None
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "type", None) == "channel":
        chat_id = origin.chat.id
    elif (msg.text or "").strip().lstrip("-").isdigit():
        chat_id = int(msg.text.strip())
    if chat_id is None:
        await msg.reply_text("❌ Forward a post from the channel (not from a user), or send its numeric ID.")
        return WAIT
    try:
        chat = await context.bot.get_chat(chat_id)
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as exc:
        await msg.reply_text(f"❌ Cannot access that channel: {exc}\nAdd the bot as admin and try again, or /cancel.")
        return WAIT
    if me.status not in {"administrator", "creator"}:
        await msg.reply_text("❌ Make the bot an administrator of that channel first, then forward a post again.")
        return WAIT

    mode = context.user_data.pop("fsub_mode", "auto")
    if mode == "auto":
        mode = "direct" if chat.username else "request"
    try:
        link = await fsub.build_invite_link(context.bot, chat, mode)
    except TelegramError as exc:
        await msg.reply_text(
            f"❌ Could not create an invite link: {exc}\nGive the bot the “Invite users via link” admin right and retry."
        )
        return ConversationHandler.END
    title = chat.title or str(chat.id)
    await get_db().add_fsub(chat.id, title, mode, link)
    kind = "join-request link (a request is enough)" if mode == "request" else "direct join button"
    await msg.reply_html(f"✅ <b>{h(title)}</b> added.\nMode: <b>{kind}</b>")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("fsub_mode", None)
    await update.effective_message.reply_text("Cancelled.")
    return ConversationHandler.END


async def delfsub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_html("Usage: <code>/delfsub &lt;channel_id&gt;</code> (see /fsublist)")
        return
    removed = await get_db().remove_fsub(chat_id)
    await update.effective_message.reply_text("🗑 Channel removed." if removed else "Channel not found.")


async def fsublist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = await get_db().list_fsub()
    if not rows:
        await update.effective_message.reply_text("No force-subscribe channels. Add one with /addfsub.")
        return
    lines = ["📢 <b>Force-subscribe channels</b>", ""]
    for ch in rows:
        kind = "🔐 request" if ch["mode"] == "request" else "📢 direct"
        lines.append(f"• <b>{h(ch['title'])}</b> — {kind}\n   <code>{ch['chat_id']}</code>")
    await update.effective_message.reply_html("\n".join(lines))


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remember join requests of force-sub channels (and approve them if enabled)."""
    request = update.chat_join_request
    if request.chat.id not in {ch["chat_id"] for ch in await get_db().list_fsub()}:
        return
    await get_db().add_join_request(request.chat.id, request.from_user.id)
    if settings.get("fsub_auto_approve"):
        try:
            await request.approve()
        except TelegramError as exc:
            log.warning("Could not approve join request: %s", exc)


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("addfsub", addfsub, filters=admin)],
            states={WAIT: [MessageHandler(admin & ~filters.COMMAND, receive_channel)]},
            fallbacks=[CommandHandler("cancel", cancel, filters=admin)],
        )
    )
    app.add_handler(CommandHandler("delfsub", delfsub, filters=admin))
    app.add_handler(CommandHandler("fsublist", fsublist, filters=admin))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
