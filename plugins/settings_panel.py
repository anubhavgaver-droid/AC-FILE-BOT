"""/settings (and /admin) — the full inline control panel. Every setting is a button.

Two kinds of callbacks:
  * navigation / toggles / presets  -> `route`
  * "type something" prompts        -> a small conversation (custom time, API domain + key, welcome text/photo, ...)
"""
from __future__ import annotations

import logging

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

from fsbot import admins, fsub, messages, settings, ui
from fsbot.admins import admin_filter
from fsbot.broadcast import run as run_broadcast
from fsbot.db import get_db
from fsbot.shortener import shorten
from fsbot.utils import spawn

log = logging.getLogger(__name__)
INPUT = 0
NAV = r"^(m|n|np|t|f|fm|fl|fd|fdy|a|at|ad|g|gp|gr|gx|x|bc):"
CANCEL = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="ic:cancel")]])
TEST_URL = "https://t.me/telegram"


# ------------------------------------------------------------------ helpers
async def _edit(query, text: str, markup) -> None:
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramError as exc:
        if "not modified" not in str(exc).lower():
            log.warning("Panel edit failed: %s", exc)


async def _try_delete(bot, chat_id: int, message_id) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


async def _toggle(key: str) -> str:
    if key not in ui.TOGGLE_BACK:
        return "❌ Unknown setting."
    if key == "verify_steps":
        await settings.set_value(key, "1" if settings.get(key) == 2 else "2")
    else:
        await settings.set_value(key, "0" if settings.get(key) else "1")
    return "✅ Updated."


async def _set_preset(key: str, value: str) -> str:
    if key not in ui.NUMERIC:
        return "❌ Unknown setting."
    try:
        await settings.set_value(key, ui.normalize(key, float(value)))
    except ValueError as exc:
        return f"❌ {exc}"
    return "✅ Saved."


async def _set_mode(bot, chat_id: str, force_mode=None) -> str:
    channel = await ui._find_channel(chat_id)
    if channel is None:
        return "❌ Channel not found."
    mode = force_mode or ("direct" if channel["mode"] == "request" else "request")
    ok, error = await fsub.set_mode(bot, channel, mode)
    if not ok:
        return f"❌ {error}\nGive the bot the “Invite users via link” right."
    if force_mode:
        return "✅ New invite link created."
    return f"✅ Switched to {'🔐 request' if mode == 'request' else '📢 direct'} mode."


async def _test_api(step: int) -> str:
    if not settings.get_api(step)[0]:
        return "⚠️ No API is set for this step."
    result = await shorten(TEST_URL, step)
    return "✅ The API works." if result != TEST_URL else "❌ The API did not return a short link — check the domain and key."


# ------------------------------------------------------------- open the panel
async def open_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await ui.render("main")
    await update.effective_message.reply_html(text, reply_markup=markup)


# --------------------------------------------------------------- navigation
async def route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not admins.is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    kind, _, rest = query.data.partition(":")
    chat_id = update.effective_chat.id
    note, view = "", ("main", None)

    if kind == "x":
        await query.answer()
        await _try_delete(context.bot, chat_id, query.message.message_id)
        return
    if kind == "bc":
        await _broadcast_confirm(update, context, rest)
        return
    if kind == "gp":
        await query.answer("Preview sent")
        await messages.send(update.effective_chat, rest, **messages.PREVIEW_VARS)
        return

    if kind == "m":
        view = (rest, None)
    elif kind == "n":
        view = ("numeric", rest)
    elif kind == "np":
        key, _, value = rest.partition(":")
        note, view = await _set_preset(key, value), ("numeric", key)
    elif kind == "t":
        note, view = await _toggle(rest), (ui.TOGGLE_BACK.get(rest, "main"), None)
    elif kind == "f":
        view = ("channel", rest)
    elif kind == "fm":
        note, view = await _set_mode(context.bot, rest), ("channel", rest)
    elif kind == "fl":
        ch = await ui._find_channel(rest)
        note, view = await _set_mode(context.bot, rest, force_mode=ch["mode"] if ch else None), ("channel", rest)
    elif kind == "fd":
        view = ("confirm_remove", rest)
    elif kind == "fdy":
        removed = await get_db().remove_fsub(int(rest))
        note, view = ("🗑 Channel removed." if removed else "Channel not found."), ("fsub", None)
    elif kind == "a":
        view = ("api", rest)
    elif kind == "at":
        note, view = await _test_api(int(rest)), ("api", rest)
    elif kind == "ad":
        await settings.delete_api(int(rest))
        note, view = "🗑 API removed.", ("api", rest)
    elif kind == "g":
        view = ("message", rest)
    elif kind == "gr":
        await messages.reset_msg(rest)
        note, view = "🔄 Reset to the default.", ("message", rest)
    elif kind == "gx":
        await messages.set_msg(rest, clear_photo=True)
        note, view = "🗑 Photo removed.", ("message", rest)

    text, markup = await ui.render(view[0], view[1], note=note)
    await query.answer()
    await _edit(query, text, markup)


async def _broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    source = context.user_data.pop("bc", None)
    if action == "no" or source is None:
        await query.answer("Cancelled" if action == "no" else "Nothing to send.")
        await _try_delete(context.bot, chat_id, query.message.message_id)
        return
    user_ids = await get_db().user_ids()
    await query.answer("Broadcast started")
    await query.edit_message_text(f"📣 Broadcasting to {len(user_ids)} users…")
    spawn(run_broadcast(context.bot, user_ids, source[0], source[1], query.message))


# ------------------------------------------------------- typed input handlers
async def _in_num(update, context, inp, msg):
    key = inp["arg"]
    value = ui.parse_amount(msg.text or "", ui.NUMERIC[key]["unit"])
    if value is None:
        return "again", "❌ I couldn't read that.\n" + ui.input_hint(key)
    try:
        await settings.set_value(key, ui.normalize(key, value))
    except ValueError as exc:
        return "again", f"❌ {exc}"
    return "done", "✅ Saved.", ("numeric", key)


async def _in_api(update, context, inp, msg):
    step, text = int(inp["arg"]), (msg.text or "").strip()
    if inp["step"] == 1:
        url = ui.parse_domain(text)
        if url is None:
            return "again", "❌ That doesn't look like a domain. Send it <b>without http</b>, e.g. <code>gplinks.com</code>."
        inp["tmp"]["url"] = url
        inp["step"] = 2
        return "next", ui.api_key_prompt(step, url)
    if not text or " " in text:
        return "again", "❌ Send only the API key — no spaces."
    await settings.set_api(step, inp["tmp"]["url"], text)
    works = await shorten(TEST_URL, step) != TEST_URL
    note = "✅ API saved and working." if works else "⚠️ API saved, but the test failed — check the domain and key."
    return "done", note, ("api", str(step))


async def _in_msgtext(update, context, inp, msg):
    name, text = inp["arg"], msg.text_html if msg.text else None
    if not text:
        return "again", "❌ Send the new text as a normal text message."
    if messages.get_msg(name)["photo"] and len(text) > messages.CAPTION_LIMIT:
        return "again", f"❌ With a poster photo the text is a caption (max {messages.CAPTION_LIMIT} characters, yours has {len(text)})."
    await messages.set_msg(name, text=text)
    return "done", "✅ Text saved.", ("message", name)


async def _in_msgphoto(update, context, inp, msg):
    name = inp["arg"]
    if not msg.photo:
        return "again", "❌ Send a <b>photo</b> (not a file)."
    caption = msg.caption_html if msg.caption else None
    effective = caption or messages.get_msg(name)["text"]
    if len(effective) > messages.CAPTION_LIMIT:
        return "again", f"❌ The text would be too long for a photo caption (max {messages.CAPTION_LIMIT})."
    await messages.set_msg(name, photo=msg.photo[-1].file_id, text=caption)
    return "done", "✅ Poster photo saved.", ("message", name)


async def _in_fsubadd(update, context, inp, msg):
    chat_id = None
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "type", None) == "channel":
        chat_id = origin.chat.id
    elif (msg.text or "").strip().lstrip("-").isdigit():
        chat_id = int(msg.text.strip())
    if chat_id is None:
        return "again", "❌ Forward a post from the channel (not from a user), or send its numeric ID."
    channel, error = await fsub.register_channel(context.bot, chat_id)
    if error:
        return "again", f"❌ {error}"
    return "done", "✅ Channel added.", ("channel", str(channel["chat_id"]))


def _user_id(msg):
    text = (msg.text or "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


async def _in_ban(update, context, inp, msg):
    user_id = _user_id(msg)
    if user_id is None:
        return "again", "❌ Send the numeric user ID."
    if admins.is_admin(user_id):
        return "again", "❌ You cannot ban an admin."
    await get_db().set_banned(user_id, inp["action"] == "ban")
    return "done", ("🚫 User banned." if inp["action"] == "ban" else "✅ User unbanned."), ("users", None)


async def _in_admin(update, context, inp, msg):
    user_id = _user_id(msg)
    if user_id is None:
        return "again", "❌ Send the numeric user ID."
    if inp["action"] == "addadmin":
        await admins.add(user_id)
        return "done", "✅ Admin added.", ("admins", None)
    removed = await admins.remove(user_id)
    return "done", ("🗑 Admin removed." if removed else "Not found (owners cannot be removed)."), ("admins", None)


async def _in_broadcast(update, context, inp, msg):
    context.user_data["bc"] = (msg.chat_id, msg.message_id)
    count = len(await get_db().user_ids())
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"✅ Send to {count} users", callback_data="bc:go"),
          InlineKeyboardButton("❌ Cancel", callback_data="bc:no")]]
    )
    await context.bot.send_message(msg.chat_id, f"📣 Send the message above to <b>{count}</b> users?",
                                   parse_mode="HTML", reply_markup=markup)
    return ("end",)


HANDLERS = {
    "num": _in_num, "api": _in_api, "msgtext": _in_msgtext, "msgphoto": _in_msgphoto, "fsubadd": _in_fsubadd,
    "ban": _in_ban, "unban": _in_ban, "addadmin": _in_admin, "deladmin": _in_admin, "broadcast": _in_broadcast,
}


# ------------------------------------------------------------- the prompt flow
async def input_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    _, _, rest = query.data.partition(":")
    action, _, arg = rest.partition(":")
    if not admins.is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return ConversationHandler.END
    if action not in ui.INPUT_ACTIONS:
        await query.answer()
        return ConversationHandler.END
    if action in {"addadmin", "deladmin"} and not admins.is_owner(query.from_user.id):
        await query.answer("Only owners can manage admins.", show_alert=True)
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    old = context.user_data.pop("inp", None)
    if old:
        await _try_delete(context.bot, chat_id, old["prompt_msg"])
    prompt_text = ui.input_prompt(action, arg)
    await query.answer()
    prompt = await context.bot.send_message(chat_id, prompt_text, parse_mode="HTML", reply_markup=CANCEL)
    context.user_data["inp"] = {
        "action": action, "arg": arg, "step": 1, "tmp": {}, "prompt_text": prompt_text,
        "menu_msg": query.message.message_id, "prompt_msg": prompt.message_id,
    }
    return INPUT


async def _set_prompt(context, chat_id: int, inp: dict, text: str) -> None:
    """Show an error / the next question inside the prompt message itself (no clutter)."""
    inp["prompt_text"] = text if inp.get("_keep") else inp["prompt_text"]
    try:
        await context.bot.edit_message_text(text, chat_id, inp["prompt_msg"], parse_mode="HTML", reply_markup=CANCEL)
    except TelegramError:
        pass


async def input_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    inp = context.user_data.get("inp")
    if not inp:
        return ConversationHandler.END
    msg, chat_id = update.effective_message, update.effective_chat.id
    result = await HANDLERS[inp["action"]](update, context, inp, msg)
    if inp["action"] != "broadcast":  # keep the broadcast source message; delete everything else (may hold secrets)
        await _try_delete(context.bot, chat_id, msg.message_id)

    kind = result[0]
    if kind == "again":
        await _set_prompt(context, chat_id, inp, f"{inp['prompt_text']}\n\n{result[1]}")
        return INPUT
    if kind == "next":
        inp["prompt_text"] = result[1]
        await _set_prompt(context, chat_id, inp, result[1])
        return INPUT

    await _try_delete(context.bot, chat_id, inp["prompt_msg"])
    context.user_data.pop("inp", None)
    if kind == "done":
        _, note, view = result
        text, markup = await ui.render(view[0], view[1], note=note)
        try:
            await context.bot.edit_message_text(text, chat_id, inp["menu_msg"], parse_mode="HTML", reply_markup=markup)
        except TelegramError:
            await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    return ConversationHandler.END


async def input_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    inp = context.user_data.pop("inp", None)
    if update.callback_query:
        await update.callback_query.answer("Cancelled")
    if inp:
        await _try_delete(context.bot, update.effective_chat.id, inp["prompt_msg"])
    return ConversationHandler.END


async def nav_in_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """A menu button pressed while the bot was waiting for typed input: drop the prompt, then navigate."""
    inp = context.user_data.pop("inp", None)
    if inp:
        await _try_delete(context.bot, update.effective_chat.id, inp["prompt_msg"])
    await route(update, context)
    return ConversationHandler.END


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["settings", "admin"], open_settings, filters=admin))
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(input_start, pattern=r"^in:")],
            states={
                INPUT: [
                    MessageHandler(admin & ~filters.COMMAND, input_receive),
                    CallbackQueryHandler(input_cancel, pattern=r"^ic:cancel$"),
                    CallbackQueryHandler(nav_in_input, pattern=NAV),
                ]
            },
            fallbacks=[CommandHandler("cancel", input_cancel, filters=admin)],
            allow_reentry=True,
        )
    )
    app.add_handler(CallbackQueryHandler(route, pattern=NAV))
