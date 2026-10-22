"""/broadcast — reply to a message to copy it to every active user."""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import CommandHandler, ContextTypes, filters

from fsbot.admins import admin_filter
from fsbot.db import get_db
from fsbot.utils import spawn


async def _run(bot, user_ids: list[int], source, status) -> None:
    sent = blocked = failed = 0
    for index, uid in enumerate(user_ids, 1):
        for _ in range(2):
            try:
                await bot.copy_message(uid, source.chat_id, source.message_id)
                sent += 1
            except RetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after) + 1)
                continue
            except Forbidden:
                blocked += 1
                await get_db().mark_inactive(uid)
            except TelegramError:
                failed += 1
            break
        await asyncio.sleep(0.05)  # ~20 messages/second
        if index % 100 == 0:
            try:
                await status.edit_text(f"📣 Broadcasting… {index}/{len(user_ids)}")
            except TelegramError:
                pass
    await status.edit_text(
        f"✅ <b>Broadcast finished</b>\n\nDelivered: <b>{sent}</b>\nBlocked: <b>{blocked}</b>\nFailed: <b>{failed}</b>",
        parse_mode="HTML",
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_html("Reply to the message you want to send with <code>/broadcast</code>.")
        return
    user_ids = await get_db().user_ids()
    status = await msg.reply_text(f"📣 Broadcasting to {len(user_ids)} users…")
    spawn(_run(context.bot, user_ids, msg.reply_to_message, status))


def register(app) -> None:
    app.add_handler(CommandHandler("broadcast", broadcast, filters=admin_filter() & filters.ChatType.PRIVATE))
