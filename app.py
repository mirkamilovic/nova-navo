"""Umumiy ilova konteksti: barcha xizmatlar bir joyda."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from aiogram import Bot

from .config import Config
from .db import Database
from .services.media import MediaService
from .services.shazam import ShazamService
from .services.subs import SubService
from .texts import Texts, THEMES

log = logging.getLogger(__name__)


@dataclass
class App:
    cfg: Config
    db: Database
    texts: Texts
    media: MediaService
    shazam: ShazamService
    subs: SubService
    bot_username: str = ""
    inflight: set[str] = field(default_factory=set)
    _admins: set[int] = field(default_factory=set)
    _notified: dict[str, float] = field(default_factory=dict)

    # ----- owner / admin -----
    async def load_admins(self) -> None:
        self._admins = set(await self.db.admin_ids())

    def is_owner(self, uid: int) -> bool:
        return uid in self.cfg.owner_ids

    def is_admin(self, uid: int) -> bool:
        return uid in self.cfg.owner_ids or uid in self._admins

    def all_admins(self) -> list[int]:
        return sorted(set(self.cfg.owner_ids) | self._admins)

    async def add_admin(self, uid: int) -> None:
        await self.db.add_admin(uid)
        self._admins.add(uid)

    async def del_admin(self, uid: int) -> None:
        await self.db.del_admin(uid)
        self._admins.discard(uid)

    async def notify_admins(self, bot: Bot, key: str, text: str, every: int = 1800) -> None:
        """Adminlarga muhim ogohlantirish (bir xil kalit uchun `every` soniyada bir marta)."""
        now = time.time()
        if now - self._notified.get(key, 0) < every:
            return
        self._notified[key] = now
        for uid in self.all_admins():
            try:
                await bot.send_message(uid, text)
            except Exception:  # noqa: BLE001
                pass

    # ----- foydalanuvchi sozlamalari -----
    def theme(self, code: str | None) -> tuple[str, str, str]:
        return THEMES.get(code or "default", THEMES["default"])

    def caption(self, key: str, lang: str) -> str:
        return self.texts.get(key, lang, bot=self.bot_username)
