"""Small shared helpers."""
from __future__ import annotations

import asyncio
import html
import time
from typing import Iterator, Sequence, TypeVar

T = TypeVar("T")
_tasks: set[asyncio.Task] = set()


def now() -> int:
    return int(time.time())


def h(text: object) -> str:
    """HTML-escape any value for Telegram's HTML parse mode."""
    return html.escape(str(text if text is not None else ""))


def chunked(seq: Sequence[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def human_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def spawn(coro) -> asyncio.Task:
    """Run a coroutine in the background and keep a strong reference to it."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
