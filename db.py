from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    lang TEXT NOT NULL DEFAULT 'uz',
    region TEXT,
    theme TEXT NOT NULL DEFAULT 'default',
    joined INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS texts (
    key TEXT NOT NULL, lang TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY (key, lang)
);
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    file_id TEXT NOT NULL,
    title TEXT, performer TEXT, duration INTEGER,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY, query TEXT, items TEXT NOT NULL, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, url TEXT NOT NULL, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
    user_id INTEGER NOT NULL, key TEXT NOT NULL,
    title TEXT, performer TEXT, duration INTEGER, file_id TEXT,
    created INTEGER NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS vplaylist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, file_id TEXT NOT NULL,
    title TEXT, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, platform TEXT, kind TEXT, ok INTEGER NOT NULL DEFAULT 1,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stats_ts ON stats(ts);
CREATE INDEX IF NOT EXISTS idx_vpl_user ON vplaylist(user_id);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "force_sub": "1",          # majburiy obuna yoqilgan
    "caption_on": "1",         # captionga bot reklamasini qo'shish
    "cobalt_url": "",          # zaxira yuklovchi (ixtiyoriy)
    "max_playlist_items": "10",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            await self.conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
            )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- umumiy ----------
    async def _one(self, sql: str, args: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(args)) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, args: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(args)) as cur:
            return list(await cur.fetchall())

    async def _run(self, sql: str, args: Iterable[Any] = ()) -> None:
        await self.conn.execute(sql, tuple(args))
        await self.conn.commit()

    # ---------- foydalanuvchilar ----------
    async def touch_user(self, uid: int, username: str | None, first_name: str | None) -> bool:
        """Foydalanuvchini yangilaydi. Yangi bo'lsa True qaytaradi."""
        now = int(time.time())
        row = await self._one("SELECT id FROM users WHERE id=?", (uid,))
        if row:
            await self._run(
                "UPDATE users SET username=?, first_name=?, last_seen=?, active=1 WHERE id=?",
                (username, first_name, now, uid),
            )
            return False
        await self._run(
            "INSERT INTO users(id,username,first_name,joined,last_seen) VALUES(?,?,?,?,?)",
            (uid, username, first_name, now, now),
        )
        return True

    async def get_user(self, uid: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM users WHERE id=?", (uid,))

    async def set_user_field(self, uid: int, field: str, value: Any) -> None:
        if field not in {"lang", "region", "theme", "active"}:
            raise ValueError(field)
        await self._run(f"UPDATE users SET {field}=? WHERE id=?", (value, uid))

    async def user_ids(self, only_active: bool = True) -> list[int]:
        sql = "SELECT id FROM users" + (" WHERE active=1" if only_active else "")
        return [r["id"] for r in await self._all(sql)]

    # ---------- adminlar ----------
    async def admin_ids(self) -> list[int]:
        return [r["id"] for r in await self._all("SELECT id FROM admins")]

    async def add_admin(self, uid: int) -> None:
        await self._run("INSERT OR IGNORE INTO admins(id) VALUES(?)", (uid,))

    async def del_admin(self, uid: int) -> None:
        await self._run("DELETE FROM admins WHERE id=?", (uid,))

    # ---------- sozlamalar ----------
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._run(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def del_setting(self, key: str) -> None:
        await self._run("DELETE FROM settings WHERE key=?", (key,))

    # ---------- matnlar ----------
    async def get_text(self, key: str, lang: str) -> str | None:
        row = await self._one("SELECT value FROM texts WHERE key=? AND lang=?", (key, lang))
        return row["value"] if row else None

    async def set_text(self, key: str, lang: str, value: str) -> None:
        await self._run(
            "INSERT INTO texts(key,lang,value) VALUES(?,?,?) "
            "ON CONFLICT(key,lang) DO UPDATE SET value=excluded.value",
            (key, lang, value),
        )

    async def reset_text(self, key: str, lang: str) -> None:
        await self._run("DELETE FROM texts WHERE key=? AND lang=?", (key, lang))

    async def all_texts(self) -> dict[tuple[str, str], str]:
        return {(r["key"], r["lang"]): r["value"] for r in await self._all("SELECT * FROM texts")}

    # ---------- kanallar ----------
    async def channels(self) -> list[aiosqlite.Row]:
        return await self._all("SELECT * FROM channels ORDER BY id")

    async def add_channel(self, chat_id: int, title: str, url: str) -> None:
        await self._run(
            "INSERT INTO channels(chat_id,title,url) VALUES(?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, url=excluded.url",
            (chat_id, title, url),
        )

    async def del_channel(self, cid: int) -> None:
        await self._run("DELETE FROM channels WHERE id=?", (cid,))

    # ---------- kesh ----------
    async def cache_get(self, key: str) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM cache WHERE key=?", (key,))

    async def cache_put(self, key: str, kind: str, file_id: str,
                        title: str | None = None, performer: str | None = None,
                        duration: int | None = None) -> None:
        await self._run(
            "INSERT INTO cache(key,kind,file_id,title,performer,duration,created) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "file_id=excluded.file_id, title=excluded.title, "
            "performer=excluded.performer, duration=excluded.duration",
            (key, kind, file_id, title, performer, duration, int(time.time())),
        )

    async def cache_drop(self, key: str) -> None:
        await self._run("DELETE FROM cache WHERE key=?", (key,))

    # ---------- qidiruv natijalari va ishlar ----------
    async def search_save(self, query: str, items: list[dict]) -> str:
        sid = secrets.token_urlsafe(6)
        await self._run(
            "INSERT INTO searches(id,query,items,created) VALUES(?,?,?,?)",
            (sid, query, json.dumps(items, ensure_ascii=False), int(time.time())),
        )
        return sid

    async def search_get(self, sid: str) -> tuple[str, list[dict]] | None:
        row = await self._one("SELECT query, items FROM searches WHERE id=?", (sid,))
        if not row:
            return None
        return row["query"], json.loads(row["items"])

    async def job_save(self, url: str) -> str:
        jid = secrets.token_urlsafe(6)
        await self._run(
            "INSERT INTO jobs(id,url,created) VALUES(?,?,?)", (jid, url, int(time.time()))
        )
        return jid

    async def job_get(self, jid: str) -> str | None:
        row = await self._one("SELECT url FROM jobs WHERE id=?", (jid,))
        return row["url"] if row else None

    async def cleanup(self) -> None:
        now = int(time.time())
        await self._run("DELETE FROM searches WHERE created<?", (now - 7 * 86400,))
        await self._run("DELETE FROM jobs WHERE created<?", (now - 30 * 86400,))

    # ---------- playlist ----------
    async def like_toggle(self, uid: int, key: str, title: str, performer: str,
                          duration: int, file_id: str) -> bool:
        """True = qo'shildi, False = olib tashlandi."""
        row = await self._one("SELECT 1 FROM likes WHERE user_id=? AND key=?", (uid, key))
        if row:
            await self._run("DELETE FROM likes WHERE user_id=? AND key=?", (uid, key))
            return False
        await self._run(
            "INSERT INTO likes(user_id,key,title,performer,duration,file_id,created) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid, key, title, performer, duration, file_id, int(time.time())),
        )
        return True

    async def likes(self, uid: int) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT rowid AS rid, * FROM likes WHERE user_id=? ORDER BY created DESC", (uid,)
        )

    async def like_get(self, uid: int, rid: int) -> aiosqlite.Row | None:
        return await self._one(
            "SELECT rowid AS rid, * FROM likes WHERE user_id=? AND rowid=?", (uid, rid)
        )

    async def vp_add(self, uid: int, file_id: str, title: str) -> None:
        await self._run(
            "INSERT INTO vplaylist(user_id,file_id,title,created) VALUES(?,?,?,?)",
            (uid, file_id, title, int(time.time())),
        )

    async def vp_list(self, uid: int) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT * FROM vplaylist WHERE user_id=? ORDER BY id DESC", (uid,)
        )

    async def vp_get(self, pid: int, uid: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM vplaylist WHERE id=? AND user_id=?", (pid, uid))

    async def vp_del(self, pid: int, uid: int) -> None:
        await self._run("DELETE FROM vplaylist WHERE id=? AND user_id=?", (pid, uid))

    # ---------- statistika ----------
    async def stat_add(self, uid: int, platform: str, kind: str, ok: bool = True) -> None:
        await self._run(
            "INSERT INTO stats(user_id,platform,kind,ok,ts) VALUES(?,?,?,?,?)",
            (uid, platform, kind, 1 if ok else 0, int(time.time())),
        )

    async def stats_summary(self) -> dict[str, Any]:
        now = int(time.time())
        day, week = now - 86400, now - 7 * 86400
        one = lambda r: r[0] if r else 0  # noqa: E731
        total = one(await self._one("SELECT COUNT(*) FROM users"))
        active = one(await self._one("SELECT COUNT(*) FROM users WHERE active=1"))
        new_day = one(await self._one("SELECT COUNT(*) FROM users WHERE joined>?", (day,)))
        new_week = one(await self._one("SELECT COUNT(*) FROM users WHERE joined>?", (week,)))
        online_day = one(await self._one("SELECT COUNT(*) FROM users WHERE last_seen>?", (day,)))
        dl_day = one(await self._one("SELECT COUNT(*) FROM stats WHERE ts>? AND ok=1", (day,)))
        dl_total = one(await self._one("SELECT COUNT(*) FROM stats WHERE ok=1"))
        fail_day = one(await self._one("SELECT COUNT(*) FROM stats WHERE ts>? AND ok=0", (day,)))
        platforms = await self._all(
            "SELECT platform, COUNT(*) c FROM stats WHERE ok=1 AND ts>? "
            "GROUP BY platform ORDER BY c DESC LIMIT 8", (week,)
        )
        regions = await self._all(
            "SELECT region, COUNT(*) c FROM users WHERE region IS NOT NULL "
            "GROUP BY region ORDER BY c DESC LIMIT 5"
        )
        return {
            "total": total, "active": active, "new_day": new_day, "new_week": new_week,
            "online_day": online_day, "dl_day": dl_day, "dl_total": dl_total,
            "fail_day": fail_day,
            "platforms": [(r["platform"], r["c"]) for r in platforms],
            "regions": [(r["region"], r["c"]) for r in regions],
        }
