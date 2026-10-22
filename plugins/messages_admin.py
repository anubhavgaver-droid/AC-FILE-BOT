"""Customise bot messages with text and a poster photo.

/setmsg <welcome|fsub|verify|wait>   reply to a photo (caption = text) or to a text message
/delphoto <name>                     remove the poster photo
/resetmsg <name>                     back to the default
/previewmsg <name>                   see how it looks
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

from fsbot import messages
from fsbot.admins import admin_filter


def _name(context: ContextTypes.DEFAULT_TYPE):
    name = context.args[0].lower() if context.args else ""
    return name if name in messages.NAMES else None


def _usage() -> str:
    names = " | ".join(messages.NAMES)
    placeholders = "\n".join(f"• <b>{n}</b>: <code>{p}</code>" for n, p in messages.PLACEHOLDERS.items())
    return (
        f"Usage: <code>/setmsg &lt;{names}&gt;</code> as a <b>reply</b> to a photo (its caption becomes the text) "
        f"or to a text message. HTML formatting is kept.\n\nPlaceholders you can use:\n{placeholders}"
    )


async def _preview(update: Update, name: str) -> None:
    await messages.send(update.effective_chat, name, **messages.PREVIEW_VARS)


async def setmsg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, name = update.effective_message, _name(context)
    source = msg.reply_to_message
    if name is None or source is None:
        await msg.reply_html(_usage())
        return
    photo = text = None
    if source.photo:
        if name not in messages.PHOTO_NAMES:
            await msg.reply_text(f"The '{name}' message is edited in place, so it supports text only.")
            return
        photo = source.photo[-1].file_id
        text = source.caption_html if source.caption else None
    elif source.text:
        text = source.text_html
    else:
        await msg.reply_html(_usage())
        return
    effective_text = text or messages.get_msg(name)["text"]
    if (photo or messages.get_msg(name)["photo"]) and len(effective_text) > messages.CAPTION_LIMIT:
        await msg.reply_text(
            f"❌ With a photo the text is a caption and can have at most {messages.CAPTION_LIMIT} characters "
            f"(yours has {len(effective_text)})."
        )
        return
    await messages.set_msg(name, photo=photo, text=text)
    await msg.reply_text("✅ Saved. Preview:")
    await _preview(update, name)


async def delphoto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = _name(context)
    if name is None:
        await update.effective_message.reply_html("Usage: <code>/delphoto &lt;welcome|fsub|verify&gt;</code>")
        return
    await messages.set_msg(name, clear_photo=True)
    await update.effective_message.reply_text("🗑 Photo removed.")


async def resetmsg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = _name(context)
    if name is None:
        await update.effective_message.reply_html("Usage: <code>/resetmsg &lt;welcome|fsub|verify|wait&gt;</code>")
        return
    await messages.reset_msg(name)
    await update.effective_message.reply_text("✅ Reset to the default message.")


async def previewmsg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = _name(context)
    if name is None:
        await update.effective_message.reply_html("Usage: <code>/previewmsg &lt;welcome|fsub|verify|wait&gt;</code>")
        return
    await _preview(update, name)


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    for name, fn in (("setmsg", setmsg), ("delphoto", delphoto), ("resetmsg", resetmsg), ("previewmsg", previewmsg)):
        app.add_handler(CommandHandler(name, fn, filters=admin))
