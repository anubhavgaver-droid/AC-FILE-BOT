"""Builds the 'link created' reply used by /single, /batch and /custombatch."""
from __future__ import annotations

from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from fsbot.encode import deep_link


def result(username: str, kind: str, key: str, headline: str):
    url = deep_link(username, kind, key)
    text = f"{headline}\n\n🔗 <code>{url}</code>"
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={quote(url, safe='')}")]]
    )
    return text, markup
