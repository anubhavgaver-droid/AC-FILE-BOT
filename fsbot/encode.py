"""Base64 deep-link payloads.

Every link the bot generates looks like  t.me/<bot>?start=<base64url("kind-key")>

kind:  s = single file   b = batch (range of a channel)   c = custom batch   v = verification token
key :  random token that points to a record in MongoDB (so links cannot be enumerated).

Note: Base64 is an *encoding* — it hides the structure from casual eyes, it is not
cryptography. Security comes from the random keys and from the checks done on open.
"""
from __future__ import annotations

import base64
import binascii
from typing import Optional

KINDS = {"s", "b", "c", "v"}


def encode(kind: str, key: str) -> str:
    raw = f"{kind}-{key}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(payload: str) -> Optional[tuple[str, str]]:
    """Return (kind, key) or None when the payload is not one of ours."""
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    kind, _, key = raw.partition("-")
    if kind not in KINDS or not key:
        return None
    return kind, key


def deep_link(username: str, kind: str, key: str) -> str:
    return f"https://t.me/{username}?start={encode(kind, key)}"
