"""Configuration from environment variables / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _ids(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.replace(" ", "").split(",") if p)


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_ids: tuple[int, ...]
    db_channel_id: int  # private channel that stores /single and /custombatch files
    mongo_uri: str
    mongo_db_name: str
    shortener_url: str  # first-run seed for verification API 1
    shortener_key: str
    port: int  # 0 = no web server
    public_url: str  # used for keep-alive pings


@lru_cache(maxsize=1)
def get_config() -> Config:
    required = ("BOT_TOKEN", "OWNER_IDS", "DB_CHANNEL_ID", "MONGO_URI")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return Config(
        bot_token=os.environ["BOT_TOKEN"].strip(),
        owner_ids=_ids(os.environ["OWNER_IDS"]),
        db_channel_id=int(os.environ["DB_CHANNEL_ID"]),
        mongo_uri=os.environ["MONGO_URI"].strip(),
        mongo_db_name=os.getenv("MONGO_DB_NAME", "filestoreeeexx").strip() or "filestore",
        shortener_url=os.getenv("SHORTENER_API_URL", "").strip(),
        shortener_key=os.getenv("SHORTENER_API_KEY", "").strip(),
        port=int(os.getenv("PORT", "0") or 0),
        public_url=(os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/"),
    )
