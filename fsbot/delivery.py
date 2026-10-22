"""Sends stored files to users: 'please wait' message, progress, auto-delete timer, protect content.

Auto-delete is stored in MongoDB and executed by a background sweeper, so timers
survive restarts and redeploys.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterator

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter, TelegramError

from fsbot import messages, settings
from fsbot.db import get_db
from fsbot.utils import chunked, human_duration, now

log = logging.getLogger(__name__)
MAX_ITEMS = 1000
_active: set[int] = set()


def expand(ranges: list, limit: int = MAX_ITEMS) -> list[tuple[int, int]]:
    """[[chat, first, last], ...] -> [(chat, message_id), ...] (capped)."""
    out: list[tuple[int, int]] = []
    for chat_id, first, last in ranges:
        for message_id in range(int(first), int(last) + 1):
            out.append((int(chat_id), message_id))
            if len(out) >= limit:
                return out
    return out


async def _copy(bot, chat_id: int, source_chat: int, message_id: int, protect: bool):
    for _ in range(3):
        try:
            return await bot.copy_message(
                chat_id=chat_id, from_chat_id=source_chat, message_id=message_id, protect_content=protect
            )
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 1)
    return None


async def send_items(bot, chat_id: int, ranges: list, payload: str, username: str) -> None:
    if chat_id in _active:
        await bot.send_message(chat_id, "⏳ Your previous request is still being processed. Please wait a moment.")
        return
    items = expand(ranges)
    if not items:
        await bot.send_message(chat_id, "❌ This link has no files.")
        return
    _active.add(chat_id)
    try:
        await _deliver(bot, chat_id, items, payload)
    finally:
        _active.discard(chat_id)


async def _deliver(bot, chat_id: int, items: list[tuple[int, int]], payload: str) -> None:
    protect = bool(settings.get("protect_content"))
    delay = int(settings.get("auto_delete_seconds"))
    wait_text = messages.fill(messages.get_msg("wait")["text"], {"count": len(items)})

    wait = None
    try:
        await bot.send_chat_action(chat_id, "upload_document")
        wait = await bot.send_message(chat_id, wait_text, parse_mode="HTML")
    except Forbidden:
        return  # the user blocked the bot
    except TelegramError:
        pass

    sent: list[int] = []
    for index, (source_chat, message_id) in enumerate(items, 1):
        try:
            result = await _copy(bot, chat_id, source_chat, message_id, protect)
        except Forbidden:
            break
        except TelegramError as exc:  # deleted message, bot removed from the channel...
            log.info("Skipping %s/%s: %s", source_chat, message_id, exc)
            continue
        if result:
            sent.append(result.message_id)
        if wait and len(items) >= 10 and index % 10 == 0:
            try:
                await bot.edit_message_text(
                    f"{wait_text}\n\n📤 Sent <b>{index}/{len(items)}</b>", chat_id, wait.message_id, parse_mode="HTML"
                )
            except TelegramError:
                pass
        await asyncio.sleep(0.35)  # stay below Telegram's flood limits

    if wait:
        try:
            await bot.delete_message(chat_id, wait.message_id)
        except TelegramError:
            pass
    if not sent:
        await bot.send_message(chat_id, "❌ File not found. It may have been removed.")
        return

    if delay > 0:
        note = await bot.send_message(
            chat_id,
            f"⚠️ <b>These files will be deleted in {human_duration(delay)}.</b>\n"
            "Forward them to Saved Messages to keep a copy.",
            parse_mode="HTML",
        )
        await get_db().add_deletion(chat_id, sent, now() + delay, note.message_id, payload)


async def sweep(bot, username: str) -> int:
    """Delete every file whose timer has run out. Returns how many deliveries were cleaned."""
    db = get_db()
    cleaned = 0
    for item in await db.due_deletions(50):
        for part in chunked(item["message_ids"], 100):
            try:
                await bot.delete_messages(item["chat_id"], part)
            except TelegramError:
                for message_id in part:
                    try:
                        await bot.delete_message(item["chat_id"], message_id)
                    except TelegramError:
                        pass
        if item.get("note_id"):
            button = []
            if item.get("payload"):
                button = [[InlineKeyboardButton("📥 Get Again", url=f"https://t.me/{username}?start={item['payload']}")]]
            try:
                await bot.edit_message_text(
                    "🗑 <b>Your files were deleted</b> as scheduled.\nTap below if you need them again.",
                    item["chat_id"], item["note_id"], parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(button) if button else None,
                )
            except TelegramError:
                pass
        await db.remove_deletion(item["_id"])
        cleaned += 1
    return cleaned


async def deletion_loop(bot, username: str) -> None:
    while True:
        try:
            await sweep(bot, username)
        except Exception:  # noqa: BLE001 - the loop must never die
            log.exception("Deletion sweeper error")
        await asyncio.sleep(20)
