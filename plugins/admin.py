"""Admin tools: /adminhelp, /set, /stats, /ban, /unban, /addadmin, /deladmin, /admins, /revoke."""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

from fsbot import admins, settings
from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.ui import stats_text
from fsbot.encode import decode
from fsbot.utils import h

ADMIN_HELP = """🛠 <b>Admin commands</b>

<b>Create links</b>
/single — save one file → link
/batch — range of posts from a channel (bot must be admin there) → link
/custombatch — send many files one by one, tap ⏹ Stop → link
/revoke &lt;link&gt; — delete a link

<b>Force-subscribe</b>
/addfsub [direct|request] · /delfsub &lt;id&gt; · /fsublist

<b>Verification</b>
/apis · /setapi &lt;1|2&gt; &lt;url&gt; &lt;key&gt; · /delapi &lt;1|2&gt; · /testapi &lt;1|2&gt;
/set &lt;key&gt; &lt;value&gt; (power users; the panel does the same with buttons)

<b>Messages (poster photo + text)</b>
/setmsg &lt;welcome|fsub|verify|wait&gt; (reply) · /delphoto · /resetmsg · /previewmsg

<b>People</b>
/broadcast (reply) · /ban · /unban
/addadmin &lt;id&gt; · /deladmin &lt;id&gt; · /admins (owners only)

/settings (or /admin) — the full button panel · /stats"""


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(ADMIN_HELP)


async def set_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.effective_message.reply_html("Usage: <code>/set &lt;key&gt; &lt;value&gt;</code>  (see /settings)")
        return
    try:
        value = await settings.set_value(context.args[0], context.args[1])
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    await update.effective_message.reply_html(f"✅ <code>{h(context.args[0])}</code> = <b>{h(value)}</b>")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(await stats_text())


async def _ban(update: Update, context: ContextTypes.DEFAULT_TYPE, banned: bool) -> None:
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text(f"Usage: /{'ban' if banned else 'unban'} <user_id>")
        return
    if admins.is_admin(user_id):
        await update.effective_message.reply_text("You cannot ban an admin.")
        return
    await get_db().set_banned(user_id, banned)
    await update.effective_message.reply_text("🚫 User banned." if banned else "✅ User unbanned.")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ban(update, context, True)


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ban(update, context, False)


async def _owner_only(update: Update) -> bool:
    if admins.is_owner(update.effective_user.id):
        return True
    await update.effective_message.reply_text("Only owners can manage admins.")
    return False


async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_html("Usage: <code>/addadmin &lt;user_id&gt;</code>")
        return
    await admins.add(user_id)
    await update.effective_message.reply_html(f"✅ <code>{user_id}</code> is now an admin.")


async def deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_only(update):
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_html("Usage: <code>/deladmin &lt;user_id&gt;</code>")
        return
    removed = await admins.remove(user_id)
    await update.effective_message.reply_text("🗑 Admin removed." if removed else "Not found (owners cannot be removed).")


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["👑 <b>Admins</b>", ""]
    lines += [f"• <code>{uid}</code>{' (owner)' if admins.is_owner(uid) else ''}" for uid in admins.all_admins()]
    await update.effective_message.reply_html("\n".join(lines))


async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/revoke <link or payload> — delete a stored link."""
    if not context.args:
        await update.effective_message.reply_html("Usage: <code>/revoke &lt;link&gt;</code>")
        return
    payload = context.args[0].rsplit("start=", 1)[-1]
    decoded = decode(payload)
    if decoded is None or decoded[0] == "v":
        await update.effective_message.reply_text("That is not one of my file links.")
        return
    removed = await get_db().delete_link(decoded[1])
    await update.effective_message.reply_text("🗑 Link deleted. It no longer works." if removed else "Link not found.")


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    for name, fn in (
        ("adminhelp", adminhelp), ("set", set_setting), ("stats", stats),
        ("ban", ban), ("unban", unban), ("addadmin", addadmin), ("deladmin", deladmin),
        ("admins", list_admins), ("revoke", revoke),
    ):
        app.add_handler(CommandHandler(name, fn, filters=admin))
