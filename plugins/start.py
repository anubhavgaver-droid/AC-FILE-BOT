"""/start, Base64 deep links, force-subscribe + verification gates, menus."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from fsbot import fsub, messages, verify
from fsbot.db import get_db
from fsbot.delivery import send_items
from fsbot.encode import decode
from fsbot.utils import h

HELP_TEXT = (
    "ℹ️ <b>Help</b>\n\n"
    "/start — Start the bot\n"
    "/help — This message\n\n"
    "<b>Getting a file</b>\n"
    "Open a file link. If asked, join the channel(s) and complete the quick verification — "
    "your file arrives automatically."
)


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📊 My Status", callback_data="menu:status"),
          InlineKeyboardButton("ℹ️ Help", callback_data="menu:help")]]
    )


async def _serve(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str, key: str) -> None:
    """Gate order: valid link -> force-subscribe -> token verification -> delivery."""
    user, chat = update.effective_user, update.effective_chat
    link = await get_db().get_link(key)
    if not link:
        await chat.send_message("❌ This link is invalid or has been removed.")
        return

    username = context.bot_data["username"]
    missing = await fsub.missing(context.bot, user.id)
    if missing:
        await messages.send(
            chat, "fsub", reply_markup=fsub.markup(missing, payload),
            name=h(user.first_name), request_note=fsub.request_note(missing),
        )
        return

    gate = await verify.evaluate(user.id)
    if gate.allowed:
        await send_items(context.bot, chat.id, link["ranges"], payload, username)
        return

    url, error = await verify.create_link(user.id, payload, username, gate.step)
    if error:
        await chat.send_message(error, parse_mode="HTML")
        return
    await messages.send(
        chat, "verify",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify Now", url=url)]]),
        name=h(user.first_name), step=gate.step, total=gate.total_steps,
        flow=verify.describe_flow(gate.step, gate.total_steps),
    )


async def _redeem(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    user, chat = update.effective_user, update.effective_chat
    ok, message, payload = await verify.redeem(user.id, token)
    await chat.send_message(message, parse_mode="HTML")
    if not (ok and payload):
        return
    decoded = decode(payload)
    link = await get_db().get_link(decoded[1]) if decoded and decoded[0] in {"s", "b", "c"} else None
    if link:
        await send_items(context.bot, chat.id, link["ranges"], payload, context.bot_data["username"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, chat = update.effective_user, update.effective_chat
    db = get_db()
    await db.upsert_user(user.id, user.first_name or "", user.username)
    if await db.is_banned(user.id):
        return

    if not context.args:
        await messages.send(chat, "welcome", reply_markup=_menu(), name=h(user.first_name or "there"))
        return
    payload = context.args[0]
    decoded = decode(payload)
    if decoded is None:
        await chat.send_message("❌ Unknown link.")
    elif decoded[0] == "v":
        await _redeem(update, context, decoded[1])
    else:
        await _serve(update, context, payload, decoded[1])


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(HELP_TEXT, parse_mode="HTML")


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user, chat = query.from_user, update.effective_chat
    if await get_db().is_banned(user.id):
        return
    action = query.data.partition(":")[2]
    if action == "status":
        await chat.send_message(await verify.status_text(user.id), parse_mode="HTML")
    elif action == "help":
        await chat.send_message(HELP_TEXT, parse_mode="HTML")


async def fsub_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """'I've joined — Continue' button."""
    query = update.callback_query
    user = query.from_user
    if await get_db().is_banned(user.id):
        await query.answer()
        return
    payload = query.data.partition(":")[2]
    decoded = decode(payload)
    if decoded is None or decoded[0] == "v":
        await query.answer()
        return
    if await fsub.missing(context.bot, user.id):
        await query.answer("❌ You haven't joined every channel yet. Join, then tap again.", show_alert=True)
        return
    await query.answer("✅ Thanks for joining!")
    try:
        await query.message.delete()
    except TelegramError:
        pass
    await _serve(update, context, payload, decoded[1])


def register(app) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", start, filters=private))
    app.add_handler(CommandHandler("help", help_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(menu_button, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(fsub_retry, pattern=r"^fsub:"))
