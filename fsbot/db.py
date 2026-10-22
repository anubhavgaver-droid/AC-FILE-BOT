"""MongoDB layer (PyMongo's native async client)."""
from __future__ import annotations

import secrets
from typing import Optional

from config import get_config
from fsbot.utils import now


class Database:
    def __init__(self, uri: str, name: str) -> None:
        from pymongo import AsyncMongoClient

        self.client = AsyncMongoClient(uri)
        self.db = self.client[name]

    async def init(self) -> None:
        d = self.db
        await d.users.create_index([("banned", 1), ("active", 1)])
        await d.link_log.create_index([("user_id", 1), ("created_at", 1)])
        await d.deletions.create_index("delete_at")

    async def close(self) -> None:
        await self.client.close()

    # ---------------------------------------------------------- settings
    async def all_settings(self) -> dict:
        return {d["_id"]: d["value"] async for d in self.db.settings.find({})}

    async def set_setting(self, key: str, value) -> None:
        await self.db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

    async def del_setting(self, key: str) -> None:
        await self.db.settings.delete_one({"_id": key})

    # -------------------------------------------------------------- users
    async def upsert_user(self, user_id: int, first_name: str, username: Optional[str]) -> None:
        await self.db.users.update_one(
            {"_id": user_id},
            {
                "$set": {"user_id": user_id, "first_name": first_name, "username": username, "active": 1},
                "$setOnInsert": {"joined_at": now(), "banned": 0},
            },
            upsert=True,
        )

    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self.db.users.update_one(
            {"_id": user_id},
            {"$set": {"user_id": user_id, "banned": int(banned)}, "$setOnInsert": {"joined_at": now(), "active": 1}},
            upsert=True,
        )

    async def is_banned(self, user_id: int) -> bool:
        doc = await self.db.users.find_one({"_id": user_id})
        return bool(doc and doc.get("banned"))

    async def mark_inactive(self, user_id: int) -> None:
        await self.db.users.update_one({"_id": user_id}, {"$set": {"active": 0}})

    async def user_ids(self) -> list[int]:
        return [d["_id"] async for d in self.db.users.find({"banned": 0, "active": 1})]

    # ------------------------------------------------------------- admins
    async def add_admin(self, user_id: int) -> None:
        await self.db.admins.update_one({"_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)

    async def remove_admin(self, user_id: int) -> bool:
        return (await self.db.admins.delete_one({"_id": user_id})).deleted_count > 0

    async def list_admins(self) -> list[int]:
        return [d["_id"] async for d in self.db.admins.find({})]

    # -------------------------------------------------------------- links
    async def create_link(self, kind: str, ranges: list, created_by: int, title: Optional[str] = None) -> str:
        """Store a link. `ranges` = [[source_chat_id, first_msg_id, last_msg_id], ...]."""
        key = secrets.token_urlsafe(6)
        while await self.db.links.find_one({"_id": key}):
            key = secrets.token_urlsafe(6)
        await self.db.links.insert_one(
            {"_id": key, "kind": kind, "ranges": ranges, "created_by": created_by,
             "created_at": now(), "title": title}
        )
        return key

    async def get_link(self, key: str):
        return await self.db.links.find_one({"_id": key})

    async def delete_link(self, key: str) -> bool:
        return (await self.db.links.delete_one({"_id": key})).deleted_count > 0

    # ------------------------------------------------- force-subscribe
    async def add_fsub(self, chat_id: int, title: str, mode: str, link: str) -> None:
        import time

        await self.db.fsub.update_one(
            {"_id": chat_id},
            {"$set": {"chat_id": chat_id, "title": title, "mode": mode, "link": link},
             "$setOnInsert": {"created_at": time.time_ns()}},  # ns keeps insertion order
            upsert=True,
        )

    async def remove_fsub(self, chat_id: int) -> bool:
        return (await self.db.fsub.delete_one({"_id": chat_id})).deleted_count > 0

    async def list_fsub(self):
        return [d async for d in self.db.fsub.find({}).sort("created_at", 1)]

    async def add_join_request(self, chat_id: int, user_id: int) -> None:
        await self.db.join_requests.update_one(
            {"_id": f"{chat_id}:{user_id}"},
            {"$set": {"chat_id": chat_id, "user_id": user_id, "created_at": now()}},
            upsert=True,
        )

    async def has_join_request(self, chat_id: int, user_id: int) -> bool:
        return await self.db.join_requests.find_one({"_id": f"{chat_id}:{user_id}"}) is not None

    # ------------------------------------------------------- verification
    async def get_verify(self, user_id: int) -> tuple[int, int]:
        doc = await self.db.verification.find_one({"_id": user_id})
        return (int(doc["stage"]), int(doc["access_until"])) if doc else (1, 0)

    async def set_verify(self, user_id: int, stage: int, access_until: int) -> None:
        await self.db.verification.update_one(
            {"_id": user_id}, {"$set": {"stage": stage, "access_until": access_until}}, upsert=True
        )

    async def add_token(self, token: str, user_id: int, step: int, payload: Optional[str]) -> None:
        await self.db.tokens.insert_one(
            {"_id": token, "user_id": user_id, "step": step, "payload": payload, "created_at": now(), "used": 0}
        )

    async def get_token(self, token: str):
        return await self.db.tokens.find_one({"_id": token})

    async def use_token(self, token: str) -> None:
        await self.db.tokens.update_one({"_id": token}, {"$set": {"used": 1}})

    async def log_link(self, user_id: int) -> None:
        await self.db.link_log.insert_one({"user_id": user_id, "created_at": now()})

    async def link_count(self, user_id: int, since: int) -> int:
        return await self.db.link_log.count_documents({"user_id": user_id, "created_at": {"$gte": since}})

    async def oldest_link(self, user_id: int, since: int) -> int:
        cursor = self.db.link_log.find({"user_id": user_id, "created_at": {"$gte": since}}).sort("created_at", 1).limit(1)
        docs = await cursor.to_list(1)
        return int(docs[0]["created_at"]) if docs else now()

    async def purge_old(self) -> None:
        cutoff = now() - 7 * 86400
        await self.db.tokens.delete_many({"created_at": {"$lt": cutoff}})
        await self.db.link_log.delete_many({"created_at": {"$lt": cutoff}})

    # ----------------------------------------- scheduled file deletion
    async def add_deletion(self, chat_id: int, message_ids: list[int], delete_at: int,
                           note_id: Optional[int], payload: Optional[str]) -> None:
        await self.db.deletions.insert_one(
            {"_id": secrets.token_hex(6), "chat_id": chat_id, "message_ids": message_ids,
             "delete_at": delete_at, "note_id": note_id, "payload": payload}
        )

    async def due_deletions(self, limit: int = 50):
        cursor = self.db.deletions.find({"delete_at": {"$lte": now()}}).sort("delete_at", 1).limit(limit)
        return [d async for d in cursor]

    async def remove_deletion(self, deletion_id: str) -> None:
        await self.db.deletions.delete_one({"_id": deletion_id})

    # -------------------------------------------------------------- stats
    async def stats(self) -> dict[str, int]:
        d = self.db
        return {
            "users": await d.users.count_documents({}),
            "active": await d.users.count_documents({"active": 1, "banned": 0}),
            "banned": await d.users.count_documents({"banned": 1}),
            "single": await d.links.count_documents({"kind": "s"}),
            "batch": await d.links.count_documents({"kind": "b"}),
            "custom": await d.links.count_documents({"kind": "c"}),
            "fsub": await d.fsub.count_documents({}),
            "scheduled": await d.deletions.count_documents({}),
        }


_instance: Optional[Database] = None


async def init_db() -> Database:
    global _instance
    if _instance is None:
        cfg = get_config()
        _instance = Database(cfg.mongo_uri, cfg.mongo_db_name)
        await _instance.init()
    return _instance


def get_db() -> Database:
    if _instance is None:
        raise RuntimeError("Database is not initialised; call `await init_db()` first.")
    return _instance
