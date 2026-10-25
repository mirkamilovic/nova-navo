"""Majburiy obuna tekshiruvi."""
from __future__ import annotations

import logging
import time

import aiosqlite
from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from ..db import Database

log = logging.getLogger(__name__)

OK_STATUSES = {
    ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR,
}
CACHE_TTL = 90


class SubService:
    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[tuple[int, int], tuple[float, bool]] = {}
        self.broken: dict[int, str] = {}   # chat_id -> xato matni (owner ko'radi)

    async def enabled(self) -> bool:
        return (await self.db.get_setting("force_sub", "1")) == "1"

    async def _is_member(self, bot: Bot, chat_id: int, uid: int, fresh: bool) -> bool:
        ck = (chat_id, uid)
        hit = self._cache.get(ck)
        if hit and not fresh and time.time() - hit[0] < CACHE_TTL and hit[1]:
            return True
        try:
            m = await bot.get_chat_member(chat_id, uid)
            ok = m.status in OK_STATUSES or (
                m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False)
            )
            self.broken.pop(chat_id, None)
        except Exception as e:  # noqa: BLE001
            # Bot kanalda admin emas yoki kanal topilmadi: foydalanuvchini to'smaymiz
            self.broken[chat_id] = str(e)[:120]
            log.warning("obuna tekshiruvi %s: %s", chat_id, e)
            ok = True
        self._cache[ck] = (time.time(), ok)
        return ok

    async def missing(self, bot: Bot, uid: int, fresh: bool = False) -> list[aiosqlite.Row]:
        if not await self.enabled():
            return []
        out = []
        for ch in await self.db.channels():
            if not await self._is_member(bot, ch["chat_id"], uid, fresh):
                out.append(ch)
        return out
