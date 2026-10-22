"""Configurable bot messages: text + optional poster photo.

Messages: welcome, fsub (join prompt), verify (verification prompt), wait (please-wait).
Admins change them with /setmsg; a photo turns the message into a poster with the text as caption.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from telegram.error import TelegramError

from fsbot import settings

log = logging.getLogger(__name__)
NAMES = ("welcome", "fsub", "verify", "wait")
PHOTO_NAMES = ("welcome", "fsub", "verify")  # "wait" is edited in place, so text only
CAPTION_LIMIT = 1024

DEFAULTS = {
    "welcome": (
        "👋 <b>Welcome, {name}!</b>\n\n"
        "📂 I deliver files straight from our channels. Open a link and I'll send the file right here.\n\n"
        "✨ <b>How it works</b>\n"
        "1️⃣ Open a file link\n"
        "2️⃣ Join the required channel(s)\n"
        "3️⃣ Complete the quick verification\n"
        "4️⃣ Get your file instantly"
    ),
    "fsub": (
        "📢 <b>Join to continue</b>\n\n"
        "Please join the channel(s) below to unlock your file, then tap <b>I've joined — Continue</b>.{request_note}"
    ),
    "verify": (
        "🔐 <b>Verification required</b> (step {step}/{total})\n\n"
        "Complete a quick verification to unlock your file — it is delivered automatically afterwards.\n\n"
        "{flow}"
    ),
    "wait": "⏳ <b>Please wait…</b>\nSending {count} file(s). Don't close this chat.",
}

PLACEHOLDERS = {
    "welcome": "{name}",
    "fsub": "{name} {request_note}",
    "verify": "{name} {step} {total} {flow}",
    "wait": "{count}",
}

PREVIEW_VARS = {
    "name": "Friend", "request_note": "", "step": 1, "total": 2,
    "flow": "• After step 1/2 → <b>6h</b> of access\n• After step 2/2 → <b>1d</b> of free access", "count": 5,
}


def get_msg(name: str) -> dict[str, Optional[str]]:
    stored = settings.raw(f"msg_{name}") or {}
    return {"photo": stored.get("photo"), "text": stored.get("text") or DEFAULTS[name]}


async def set_msg(name: str, *, photo: Optional[str] = None, text: Optional[str] = None, clear_photo: bool = False) -> None:
    current = settings.raw(f"msg_{name}") or {}
    data = {"photo": current.get("photo"), "text": current.get("text")}
    if photo:
        data["photo"] = photo
    if clear_photo:
        data["photo"] = None
    if text:
        data["text"] = text
    await settings.put_raw(f"msg_{name}", data)


async def reset_msg(name: str) -> None:
    await settings.del_raw(f"msg_{name}")


def fill(text: str, variables: dict[str, Any]) -> str:
    for key, value in variables.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def render(message: str, **variables: Any) -> tuple[Optional[str], str]:
    """`message` is the message key (welcome/fsub/...); `variables` fill the {placeholders}."""
    msg = get_msg(message)
    return msg["photo"], fill(msg["text"], variables)


async def send(chat, message: str, reply_markup=None, **variables: Any):
    """Send a configured message to `chat` (photo + caption when a photo is set)."""
    photo, text = render(message, **variables)
    if photo and len(text) <= CAPTION_LIMIT:
        try:
            return await chat.send_photo(photo=photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        except TelegramError as exc:
            log.warning("Poster photo for '%s' failed (%s); sending text only", message, exc)
    return await chat.send_message(text, parse_mode="HTML", reply_markup=reply_markup)
