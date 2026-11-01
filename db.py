"""SQLite (standart kutubxona). Barcha chaqiruvlar thread'da bajariladi, bot bloklanmaydi."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    joined INTEGER,
    last_seen INTEGER,
    banned INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    ref_by INTEGER,
    downloads INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS channels(chat_id INTEGER PRIMARY KEY, title TEXT, link TEXT);
CREATE TABLE IF NOT EXISTS downloads(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, platform TEXT, ts INTEGER, ok INTEGER, via TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_dl_ts ON downloads(ts);
CREATE INDEX IF NOT EXISTS ix_dl_user ON downloads(user_id, ts);
CREATE TABLE IF NOT EXISTS tracks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, artist TEXT, ts INTEGER, hits INTEGER DEFAULT 1,
    UNIQUE(title, artist)
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ yadro
    async def connect(self) -> None:
        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_open)

    async def close(self) -> None:
        if self._conn:
            conn, self._conn = self._conn, None
            await asyncio.to_thread(conn.close)

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        assert self._conn is not None, "Database.connect() chaqirilmagan"
        async with self._lock:
            def _call() -> Any:
                try:
                    res = fn(self._conn)
                    self._conn.commit()
                    return res
                except Exception:
                    self._conn.rollback()
                    raise

            return await asyncio.to_thread(_call)

    async def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return await self._run(lambda c: c.execute(sql, args).fetchall())

    async def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        return await self._run(lambda c: c.execute(sql, args).fetchone())

    async def _exec(self, sql: str, args: tuple = ()) -> int:
        return await self._run(lambda c: c.execute(sql, args).rowcount)

    async def cleanup(self) -> None:
        cut = int(time.time()) - 90 * 86400
        await self._exec("DELETE FROM downloads WHERE ts < ?", (cut,))

    # ------------------------------------------------------------------ sozlamalar
    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    async def del_setting(self, key: str) -> None:
        await self._exec("DELETE FROM settings WHERE key=?", (key,))

    async def settings_like(self, prefix: str) -> dict[str, str]:
        rows = await self._all("SELECT key,value FROM settings WHERE key LIKE ?", (prefix + "%",))
        return {r["key"]: r["value"] for r in rows}

    # ------------------------------------------------------------------ foydalanuvchilar
    async def touch_user(self, user: Any) -> bool:
        """Foydalanuvchini yozadi/yangilaydi. Yangi bo'lsa True qaytaradi."""
        now = int(time.time())
        username = getattr(user, "username", None) or ""
        full = getattr(user, "full_name", None) or ""

        def _do(c: sqlite3.Connection) -> bool:
            cur = c.execute(
                "INSERT OR IGNORE INTO users(id,username,full_name,joined,last_seen) VALUES(?,?,?,?,?)",
                (user.id, username, full, now, now),
            )
            if cur.rowcount == 1:
                return True
            c.execute(
                "UPDATE users SET username=?, full_name=?, last_seen=?, active=1 WHERE id=?",
                (username, full, now, user.id),
            )
            return False

        return await self._run(_do)

    async def get_user(self, uid: int) -> sqlite3.Row | None:
        return await self._one("SELECT * FROM users WHERE id=?", (uid,))

    async def is_banned(self, uid: int) -> bool:
        row = await self._one("SELECT banned FROM users WHERE id=?", (uid,))
        return bool(row and row["banned"])

    async def set_banned(self, uid: int, banned: bool) -> bool:
        return (await self._exec("UPDATE users SET banned=? WHERE id=?", (1 if banned else 0, uid))) > 0

    async def set_active(self, uid: int, active: bool) -> None:
        await self._exec("UPDATE users SET active=? WHERE id=?", (1 if active else 0, uid))

    async def set_ref(self, uid: int, ref_by: int) -> None:
        await self._exec("UPDATE users SET ref_by=? WHERE id=? AND ref_by IS NULL", (ref_by, uid))

    async def ref_count(self, uid: int) -> int:
        row = await self._one("SELECT COUNT(*) AS n FROM users WHERE ref_by=?", (uid,))
        return int(row["n"]) if row else 0

    async def user_ids(self) -> list[int]:
        rows = await self._all("SELECT id FROM users WHERE active=1 AND banned=0")
        return [int(r["id"]) for r in rows]

    # ------------------------------------------------------------------ adminlar / kanallar
    async def admin_ids(self) -> list[int]:
        return [int(r["id"]) for r in await self._all("SELECT id FROM admins")]

    async def add_admin(self, uid: int) -> None:
        await self._exec("INSERT OR IGNORE INTO admins(id) VALUES(?)", (uid,))

    async def del_admin(self, uid: int) -> None:
        await self._exec("DELETE FROM admins WHERE id=?", (uid,))

    async def channels(self) -> list[sqlite3.Row]:
        return await self._all("SELECT chat_id,title,link FROM channels ORDER BY rowid")

    async def add_channel(self, chat_id: int, title: str, link: str) -> None:
        await self._exec(
            "INSERT INTO channels(chat_id,title,link) VALUES(?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, link=excluded.link",
            (chat_id, title, link),
        )

    async def del_channel(self, chat_id: int) -> None:
        await self._exec("DELETE FROM channels WHERE chat_id=?", (chat_id,))

    # ------------------------------------------------------------------ yuklashlar
    async def log_download(self, uid: int, platform: str, ok: bool, via: str = "", error: str = "") -> None:
        now = int(time.time())

        def _do(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO downloads(user_id,platform,ts,ok,via,error) VALUES(?,?,?,?,?,?)",
                (uid, platform, now, 1 if ok else 0, via, error[:500]),
            )
            if ok:
                c.execute("UPDATE users SET downloads=downloads+1 WHERE id=?", (uid,))

        await self._run(_do)

    async def downloads_today(self, uid: int) -> int:
        cut = int(time.time()) - 86400
        row = await self._one("SELECT COUNT(*) AS n FROM downloads WHERE user_id=? AND ok=1 AND ts>=?", (uid, cut))
        return int(row["n"]) if row else 0

    async def stats_summary(self) -> dict[str, Any]:
        now = int(time.time())
        day, week = now - 86400, now - 7 * 86400

        def _do(c: sqlite3.Connection) -> dict[str, Any]:
            def n(sql: str, *a: Any) -> int:
                return int(c.execute(sql, a).fetchone()[0])

            plats = c.execute(
                "SELECT platform, COUNT(*) AS n FROM downloads WHERE ok=1 AND ts>=? "
                "GROUP BY platform ORDER BY n DESC LIMIT 10",
                (week,),
            ).fetchall()
            return {
                "total": n("SELECT COUNT(*) FROM users"),
                "active": n("SELECT COUNT(*) FROM users WHERE active=1 AND banned=0"),
                "new_day": n("SELECT COUNT(*) FROM users WHERE joined>=?", day),
                "new_week": n("SELECT COUNT(*) FROM users WHERE joined>=?", week),
                "online_day": n("SELECT COUNT(*) FROM users WHERE last_seen>=?", day),
                "dl_day": n("SELECT COUNT(*) FROM downloads WHERE ok=1 AND ts>=?", day),
                "dl_total": n("SELECT COUNT(*) FROM downloads WHERE ok=1"),
                "fail_day": n("SELECT COUNT(*) FROM downloads WHERE ok=0 AND ts>=?", day),
                "platforms": [(r["platform"] or "?", int(r["n"])) for r in plats],
            }

        return await self._run(_do)

    # ------------------------------------------------------------------ qo'shiqlar
    async def add_track(self, title: str, artist: str) -> None:
        now = int(time.time())
        await self._exec(
            "INSERT INTO tracks(title,artist,ts) VALUES(?,?,?) "
            "ON CONFLICT(title,artist) DO UPDATE SET hits=hits+1, ts=excluded.ts",
            (title, artist, now),
        )

    async def top_tracks(self, limit: int = 10) -> list[sqlite3.Row]:
        return await self._all("SELECT title,artist,hits FROM tracks ORDER BY hits DESC, ts DESC LIMIT ?", (limit,))

    async def new_tracks(self, limit: int = 10) -> list[sqlite3.Row]:
        return await self._all("SELECT title,artist,hits FROM tracks ORDER BY ts DESC LIMIT ?", (limit,))
