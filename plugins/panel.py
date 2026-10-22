"""/admin — inline admin panel with one-tap toggles."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from fsbot import admins, settings
from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.utils import human_duration

DELETE_PRESETS = [0, 300, 600, 1800, 3600]


def _on(value: bool) -> str:
    return "✅ ON" if value else "❌ OFF"


def _markup() -> InlineKeyboardMarkup:
    delay = int(settings.get("auto_delete_seconds"))
    delay_label = human_duration(delay) if delay else "off"
    button = InlineKeyboardButton
    return InlineKeyboardMarkup(
        [
            [button(f"🔐 Verification: {_on(settings.get('verify_enabled'))}", callback_data="adm:verify_enabled"),
             button(f"🔢 Steps: {settings.get('verify_steps')}", callback_data="adm:steps")],
            [button(f"🛡 Protect: {_on(settings.get('protect_content'))}", callback_data="adm:protect_content"),
             button(f"🗑 Auto-delete: {delay_label}", callback_data="adm:autodel")],
            [button(f"📢 Auto-approve: {_on(settings.get('fsub_auto_approve'))}", callback_data="adm:fsub_auto_approve")],
            [button("📋 All settings", callback_data="adm:settings"), button("📊 Stats", callback_data="adm:stats")],
        ]
    )


PANEL_TEXT = "🛠 <b>Admin panel</b>\n\nTap a button to change a setting instantly. /adminhelp lists every command."


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(PANEL_TEXT, reply_markup=_markup())


async def panel_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not admins.is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    action = query.data.partition(":")[2]
    if action in {"verify_enabled", "protect_content", "fsub_auto_approve"}:
        await settings.set_value(action, "0" if settings.get(action) else "1")
    elif action == "steps":
        await settings.set_value("verify_steps", "1" if settings.get("verify_steps") == 2 else "2")
    elif action == "autodel":
        current = int(settings.get("auto_delete_seconds"))
        nxt = DELETE_PRESETS[(DELETE_PRESETS.index(current) + 1) % len(DELETE_PRESETS)] if current in DELETE_PRESETS else 0
        await settings.set_value("auto_delete_seconds", str(nxt))
    elif action == "stats":
        from plugins.admin import stats_text  # local import keeps plugins independent at load time

        await query.answer()
        await update.effective_chat.send_message(await stats_text(), parse_mode="HTML")
        return
    elif action == "settings":
        from plugins.admin import settings_text

        await query.answer()
        await update.effective_chat.send_message(settings_text(), parse_mode="HTML")
        return
    await query.answer("Updated")
    try:
        await query.edit_message_reply_markup(_markup())
    except TelegramError:
        pass


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("admin", panel, filters=admin))
    app.add_handler(CallbackQueryHandler(panel_button, pattern=r"^adm:"))
