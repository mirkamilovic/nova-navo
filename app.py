"""Umumiy kontekst: handlerlar `app: App` argumenti orqali oladi."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("navobot")


@dataclass
class App:
    cfg: Any
    db: Any
    texts: Any
    media: Any
    shazam: Any
    subs: Any
    bot_username: str = ""
    admins: set[int] = field(default_factory=set)
    _notify_counts: dict[str, int] = field(default_factory=dict)

    async def load_admins(self) -> None:
        self.admins = set(self.cfg.owner_ids) | set(await self.db.admin_ids())

    def all_admins(self) -> list[int]:
        return sorted(self.admins)

    def is_owner(self, uid: int) -> bool:
        return uid in self.cfg.owner_ids

    def is_admin(self, uid: int) -> bool:
        return uid in self.admins

    async def add_admin(self, uid: int) -> None:
        await self.db.add_admin(uid)
        self.admins.add(uid)

    async def remove_admin(self, uid: int) -> None:
        if uid in self.cfg.owner_ids:
            return
        await self.db.del_admin(uid)
        self.admins.discard(uid)

    async def notify_admins(self, bot: Any, key: str, text: str, every: int = 1) -> None:
        """Adminlarga xabar. every=N bo'lsa shu kalitdagi har N-hodisadan faqat bittasi yuboriladi."""
        if len(self._notify_counts) > 5000:
            self._notify_counts.clear()
        n = self._notify_counts.get(key, 0) + 1
        self._notify_counts[key] = n
        if every > 1 and (n - 1) % every:
            return
        for uid in self.all_admins():
            try:
                await bot.send_message(uid, text)
            except Exception:  # noqa: BLE001
                pass
