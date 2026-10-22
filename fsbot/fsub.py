"""Force-subscribe.

Each channel has a mode chosen by the admin:
  direct   public channel (or a normal invite link): the user must be a member.
  request  private channel with a join-REQUEST link: a member OR a pending join request passes.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from fsbot.db import get_db

log = logging.getLogger(__name__)
MEMBER_STATUSES = {"member", "administrator", "creator"}
MAX_CHANNELS = 5


async def is_joined(bot, channel, user_id: int) -> bool:
    chat_id = channel["chat_id"]
    member = None
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramError as exc:
        text = str(exc).lower()
        if "user not found" not in text and "participant" not in text:
            log.warning("Force-sub check failed for %s: %s", chat_id, exc)
            return True  # broken setup (bot lost admin rights...) must never lock users out
    if member is not None:
        if member.status in MEMBER_STATUSES:
            return True
        if member.status == "restricted" and getattr(member, "is_member", False):
            return True
    if channel["mode"] == "request" and await get_db().has_join_request(chat_id, user_id):
        return True
    return False


async def missing(bot, user_id: int) -> list:
    """Channels the user still has to join (empty list = all good)."""
    channels = await get_db().list_fsub()
    if not channels:
        return []
    results = await asyncio.gather(*(is_joined(bot, ch, user_id) for ch in channels))
    return [ch for ch, ok in zip(channels, results) if not ok]


def markup(channels: list, retry_payload: str) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        icon = "🔐 Request to Join" if ch["mode"] == "request" else "📢 Join"
        rows.append([InlineKeyboardButton(f"{icon} {ch['title']}", url=ch["link"])])
    rows.append([InlineKeyboardButton("✅ I've joined — Continue", callback_data=f"fsub:{retry_payload}")])
    return InlineKeyboardMarkup(rows)


def request_note(channels: list) -> str:
    if any(ch["mode"] == "request" for ch in channels):
        return "\n\n🔐 For private channels just send a <b>join request</b> — that is enough."
    return ""


async def build_invite_link(bot, chat, mode: str) -> str:
    if mode == "direct" and chat.username:
        return f"https://t.me/{chat.username}"
    invite = await bot.create_chat_invite_link(chat.id, name="FileStore", creates_join_request=(mode == "request"))
    return invite.invite_link
