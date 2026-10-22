"""Token verification (1 or 2 steps, each with its own API).

Two-step flow:
    step 1/2  asked immediately -> `verify_gap_hours` of access
    step 2/2  asked after that  -> `verify_free_hours` (e.g. 24 h) of free access
    then the cycle restarts at step 1/2.
One-step flow: verify -> `verify_free_hours` of free access.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Optional

from fsbot import settings
from fsbot.db import get_db
from fsbot.encode import deep_link
from fsbot.shortener import shorten
from fsbot.utils import human_duration


@dataclass
class Gate:
    allowed: bool
    step: int = 1
    total_steps: int = 1


def _hours(key: str) -> float:
    return float(settings.get(key)) * 3600


def describe_flow(step: int, total: int) -> str:
    gap, free = human_duration(_hours("verify_gap_hours")), human_duration(_hours("verify_free_hours"))
    if total == 2:
        if step == 1:
            return f"• After step 1/2 → <b>{gap}</b> of access\n• After step 2/2 → <b>{free}</b> of free access"
        return f"• After step 2/2 → <b>{free}</b> of free access"
    return f"• After verification → <b>{free}</b> of free access"


async def evaluate(user_id: int) -> Gate:
    if not settings.get("verify_enabled"):
        return Gate(True)
    total = int(settings.get("verify_steps"))
    stage, until = await get_db().get_verify(user_id)
    if time.time() < until:
        return Gate(True)
    return Gate(False, stage if total == 2 and stage in (1, 2) else 1, total)


async def status_text(user_id: int) -> str:
    if not settings.get("verify_enabled"):
        return "✅ Verification is switched off — everything is open."
    total = int(settings.get("verify_steps"))
    stage, until = await get_db().get_verify(user_id)
    left = int(until - time.time())
    if left > 0:
        text = f"✅ <b>Verified</b> — access left: <b>{human_duration(left)}</b>"
        if total == 2 and stage == 2:
            text += "\nNext: verification <b>step 2/2</b> when this runs out."
        else:
            text += "\nAfter that you will need to verify again."
        return text
    step = f" (step {stage if total == 2 and stage in (1, 2) else 1}/{total})" if total == 2 else ""
    return f"🔐 <b>Verification needed</b>{step} — open any file link to start."


async def create_link(user_id: int, payload: str, bot_username: str, step: int) -> tuple[Optional[str], Optional[str]]:
    """(url, None) on success, (None, error_html) when the user hit the link limit."""
    db = get_db()
    await db.purge_old()
    limit = int(settings.get("link_limit"))
    window = int(_hours("link_window_hours"))
    since = int(time.time()) - window
    if await db.link_count(user_id, since) >= limit:
        wait = await db.oldest_link(user_id, since) + window - int(time.time())
        return None, (
            f"🚫 You have reached the limit of <b>{limit}</b> verification links per <b>{human_duration(window)}</b>.\n"
            f"⏳ Please try again in <b>{human_duration(wait)}</b>."
        )
    token = secrets.token_urlsafe(9)
    await db.add_token(token, user_id, step, payload)
    await db.log_link(user_id)
    return await shorten(deep_link(bot_username, "v", token), step), None


async def redeem(user_id: int, token: str) -> tuple[bool, str, Optional[str]]:
    """Validate a verification token. Returns (ok, message_html, original_payload)."""
    db = get_db()
    row = await db.get_token(token)
    if not row or row["user_id"] != user_id:
        return False, "❌ This verification link is invalid. Please request a new one.", None
    if row["used"]:
        return False, "⚠️ This link has already been used. Please request a new one.", None
    age = int(time.time()) - int(row["created_at"])
    if age > int(settings.get("token_expiry_minutes")) * 60:
        return False, "⌛ This verification link has expired. Please request a new one.", None
    if age < int(settings.get("verify_min_seconds")):
        return False, "❌ Verification failed. Please open the link and complete all of its steps, then try again.", None

    await db.use_token(token)
    total = int(settings.get("verify_steps"))
    if total == 2 and row["step"] == 1:
        duration = _hours("verify_gap_hours")
        await db.set_verify(user_id, 2, int(time.time() + duration))
        message = (
            "✅ <b>Step 1/2 verified!</b>\n\n"
            f"You have access for <b>{human_duration(duration)}</b>. After that, step 2/2 unlocks "
            f"<b>{human_duration(_hours('verify_free_hours'))}</b> of free access."
        )
    else:
        duration = _hours("verify_free_hours")
        await db.set_verify(user_id, 1, int(time.time() + duration))
        message = (
            "🎉 <b>Verification complete!</b>\n\n"
            f"Enjoy <b>{human_duration(duration)}</b> of free access — no more verification until then."
        )
    return True, message, row["payload"]
