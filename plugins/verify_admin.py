"""Verification APIs, one per step (admin only).

/apis                      show the configured APIs (keys masked)
/setapi <1|2> <url> <key>  set the shortener API for a verification step
/delapi <1|2>              remove it (step 2 then falls back to step 1)
/testapi <1|2>             shorten a test URL to check the API works
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, filters

from fsbot import settings
from fsbot.admins import admin_filter
from fsbot.shortener import shorten
from fsbot.utils import h


def _mask(key: str) -> str:
    return "—" if not key else (key[:4] + "…" + key[-3:] if len(key) > 8 else "••••")


async def apis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["🔑 <b>Verification APIs</b>", ""]
    for step in (1, 2):
        url, key = settings.get_api(step)
        own = bool(settings.raw(f"api{step}_url")) or (step == 1 and bool(url))
        note = "" if own else " <i>(uses API 1)</i>"
        lines.append(f"<b>Step {step}</b>{note}\nURL: <code>{h(url or '—')}</code>\nKey: <code>{h(_mask(key))}</code>\n")
    lines.append("Set with <code>/setapi &lt;1|2&gt; &lt;url&gt; &lt;key&gt;</code>")
    if not settings.get_api(1)[0]:
        lines.append("⚠️ No API configured — verification links are not shortened, so users can skip them.")
    await update.effective_message.reply_html("\n".join(lines))


async def setapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, args = update.effective_message, context.args
    if len(args) != 3 or args[0] not in {"1", "2"} or not args[1].startswith("http"):
        await msg.reply_html("Usage: <code>/setapi &lt;1|2&gt; &lt;https://api-url&gt; &lt;api_key&gt;</code>")
        return
    await settings.set_api(int(args[0]), args[1], args[2])
    await msg.reply_html(f"✅ API for step {args[0]} saved. Check it with <code>/testapi {args[0]}</code>.")
    try:  # the message contains a secret key
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass


async def delapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0] not in {"1", "2"}:
        await update.effective_message.reply_html("Usage: <code>/delapi &lt;1|2&gt;</code>")
        return
    await settings.delete_api(int(context.args[0]))
    await update.effective_message.reply_text("🗑 API removed.")


async def testapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0] not in {"1", "2"}:
        await update.effective_message.reply_html("Usage: <code>/testapi &lt;1|2&gt;</code>")
        return
    step = int(context.args[0])
    if not settings.get_api(step)[0]:
        await update.effective_message.reply_text("No API configured for that step.")
        return
    test = "https://t.me/telegram"
    result = await shorten(test, step)
    if result == test:
        await update.effective_message.reply_text("❌ The API did not return a short link. Check the URL and key.")
    else:
        await update.effective_message.reply_html(f"✅ Works: <code>{h(result)}</code>")


def register(app) -> None:
    admin = admin_filter() & filters.ChatType.PRIVATE
    for name, fn in (("apis", apis), ("setapi", setapi), ("delapi", delapi), ("testapi", testapi)):
        app.add_handler(CommandHandler(name, fn, filters=admin))
