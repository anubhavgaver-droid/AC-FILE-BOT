"""Verification link shortener (GPLinks / Shrinkme style APIs). One API per verification step."""
from __future__ import annotations

import logging

import httpx

from fsbot import settings

log = logging.getLogger(__name__)


async def shorten(url: str, step: int = 1) -> str:
    api_url, api_key = settings.get_api(step)
    if not (api_url and api_key):
        return url  # no API configured: the raw bot link is used
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(api_url, params={"api": api_key, "url": url, "format": "text"})
        body = resp.text.strip()
        if body.startswith("http"):
            return body
        data = resp.json()
        for key in ("shortenedUrl", "short_url", "shorturl", "link"):
            if isinstance(data, dict) and str(data.get(key, "")).startswith("http"):
                return data[key]
        log.warning("Shortener (step %s) returned an unexpected response: %s", step, body[:200])
    except Exception:  # noqa: BLE001 - a broken API must not block users
        log.exception("Shortener request failed (step %s)", step)
    return url
