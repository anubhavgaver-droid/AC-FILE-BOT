"""Copies one message to many users with flood-limit handling."""
from __future__ import annotations

import asyncio

from telegram.error import Forbidden, RetryAfter, TelegramError

from fsbot.db import get_db


async def run(bot, user_ids: list[int], from_chat_id: int, message_id: int, status) -> None:
    sent = blocked = failed = 0
    for index, uid in enumerate(user_ids, 1):
        for _ in range(2):
            try:
                await bot.copy_message(uid, from_chat_id, message_id)
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
    try:
        await status.edit_text(
            f"✅ <b>Broadcast finished</b>\n\nDelivered: <b>{sent}</b>\nBlocked: <b>{blocked}</b>\nFailed: <b>{failed}</b>",
            parse_mode="HTML",
        )
    except TelegramError:
        pass
