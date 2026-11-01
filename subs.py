"""Majburiy obuna (kanallarga a'zolikni tekshirish)."""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("navobot.subs")

_OK_TTL = 60  # soniya: a'zo deb tasdiqlangan holat shuncha vaqt eslab qolinadi


class SubService:
    def __init__(self, db: Any):
        self.db = db
        self.broken: set[int] = set()  # bot admin bo'lmagan / topilmagan kanallar
        self._ok: dict[tuple[int, int], float] = {}

    async def enabled(self) -> bool:
        return (await self.db.get_setting("subs_enabled", "0")) == "1"

    async def set_enabled(self, on: bool) -> None:
        await self.db.set_setting("subs_enabled", "1" if on else "0")

    async def missing(self, bot: Any, uid: int, fresh: bool = False) -> list[dict[str, Any]]:
        """Foydalanuvchi a'zo bo'lmagan kanallar ro'yxati."""
        out: list[dict[str, Any]] = []
        now = time.time()
        if len(self._ok) > 20000:
            self._ok.clear()
        for ch in await self.db.channels():
            chat_id = int(ch["chat_id"])
            if not fresh and self._ok.get((uid, chat_id), 0) > now:
                continue
            try:
                member = await bot.get_chat_member(chat_id, uid)
            except Exception as e:  # noqa: BLE001
                # bot kanalda admin emas yoki kanal o'chgan — foydalanuvchini bloklamaymiz
                if chat_id not in self.broken:
                    log.warning("Kanal %s tekshirilmadi: %s", chat_id, e)
                self.broken.add(chat_id)
                continue
            self.broken.discard(chat_id)
            status = str(getattr(member.status, "value", member.status))
            joined = status in ("creator", "administrator", "member") or (
                status == "restricted" and getattr(member, "is_member", True)
            )
            if joined:
                self._ok[(uid, chat_id)] = now + _OK_TTL
            else:
                out.append({"chat_id": chat_id, "title": ch["title"], "link": ch["link"]})
        return out
