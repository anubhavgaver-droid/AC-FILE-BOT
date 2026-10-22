"""Admin registry: owners (from .env) + admins added at runtime with /addadmin."""
from __future__ import annotations

from typing import Optional

from telegram.ext import filters

from config import get_config
from fsbot.db import get_db

_extra: set[int] = set()
_filter: Optional[filters.User] = None


def admin_filter():
    """A live PTB filter: admins added later are picked up without a restart."""
    global _filter
    if _filter is None:
        _filter = filters.User(user_id=list(get_config().owner_ids))
    return _filter


def is_owner(user_id: int) -> bool:
    return user_id in get_config().owner_ids


def is_admin(user_id: int) -> bool:
    return is_owner(user_id) or user_id in _extra


async def load() -> None:
    for user_id in await get_db().list_admins():
        _extra.add(user_id)
        admin_filter().add_user_ids(user_id)


async def add(user_id: int) -> None:
    await get_db().add_admin(user_id)
    _extra.add(user_id)
    admin_filter().add_user_ids(user_id)


async def remove(user_id: int) -> bool:
    if is_owner(user_id):
        return False
    removed = await get_db().remove_admin(user_id)
    _extra.discard(user_id)
    admin_filter().remove_user_ids(user_id)
    return removed


def all_admins() -> list[int]:
    return sorted(set(get_config().owner_ids) | _extra)
