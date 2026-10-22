"""Dynamic settings: cached in memory, stored in MongoDB, changed live by admins."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config import get_config
from fsbot.db import get_db


@dataclass(frozen=True)
class Spec:
    default: str
    kind: str  # "bool" | "int" | "float"
    low: float = 0
    high: float = 1_000_000
    desc: str = ""


SPEC: dict[str, Spec] = {
    "verify_enabled": Spec("1", "bool", desc="Token verification on/off (1/0)"),
    "verify_steps": Spec("2", "int", 1, 2, "Verification steps: 1 or 2"),
    "verify_gap_hours": Spec("6", "float", 0, 720, "2-step: hours of access after step 1, then step 2 is asked"),
    "verify_free_hours": Spec("24", "float", 0, 720, "Free hours after the final verification step"),
    "link_limit": Spec("7", "int", 1, 1000, "Max verification links a user can generate per window"),
    "link_window_hours": Spec("24", "float", 0.1, 720, "Window (hours) used by link_limit"),
    "token_expiry_minutes": Spec("15", "int", 1, 1440, "Minutes before an unused verification link expires"),
    "verify_min_seconds": Spec("8", "int", 0, 600, "Minimum seconds to finish a link (anti-bypass)"),
    "auto_delete_seconds": Spec("600", "int", 0, 86400, "Delete delivered files after N seconds (0 = keep)"),
    "protect_content": Spec("0", "bool", desc="Block forwarding / saving of delivered files (1/0)"),
    "fsub_auto_approve": Spec("0", "bool", desc="Auto-approve join requests of force-sub channels (1/0)"),
}

_cache: dict[str, Any] = {}


async def load() -> None:
    _cache.clear()
    _cache.update(await get_db().all_settings())


def raw(key: str, default: Any = None) -> Any:
    return _cache.get(key, default)


async def put_raw(key: str, value: Any) -> None:
    await get_db().set_setting(key, value)
    _cache[key] = value


async def del_raw(key: str) -> None:
    await get_db().del_setting(key)
    _cache.pop(key, None)


def _cast(spec: Spec, value: Any):
    if spec.kind == "bool":
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if spec.kind == "int":
        return int(float(value))
    return float(value)


def get(key: str):
    spec = SPEC[key]
    return _cast(spec, _cache.get(key, spec.default))


async def set_value(key: str, value_raw: str) -> str:
    """Validate and store a setting; returns the canonical stored value."""
    if key not in SPEC:
        raise ValueError(f"Unknown setting: {key}")
    spec = SPEC[key]
    if spec.kind == "bool":
        lowered = value_raw.strip().lower()
        if lowered not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ValueError("Use 1/0 (or on/off).")
        value = "1" if lowered in {"1", "true", "yes", "on"} else "0"
    else:
        try:
            number = _cast(spec, value_raw)
        except ValueError:
            raise ValueError("A number is required.") from None
        if not spec.low <= number <= spec.high:
            raise ValueError(f"Value must be between {spec.low:g} and {spec.high:g}.")
        value = str(number)
    await put_raw(key, value)
    return value


# ------------------------------------------------------- verification APIs
def get_api(step: int) -> tuple[str, str]:
    """(api_url, api_key) for a verification step. Step 2 falls back to step 1."""
    cfg = get_config()
    url, key = raw(f"api{step}_url", ""), raw(f"api{step}_key", "")
    if not url and step == 1:
        url, key = cfg.shortener_url, cfg.shortener_key
    if not url and step == 2:
        return get_api(1)
    return url, key


async def set_api(step: int, url: str, key: str) -> None:
    await put_raw(f"api{step}_url", url)
    await put_raw(f"api{step}_key", key)


async def delete_api(step: int) -> None:
    await del_raw(f"api{step}_url")
    await del_raw(f"api{step}_key")
