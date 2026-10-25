from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .app import App
from .keyboards import sub_kb

log = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """Foydalanuvchini yozib boradi, til/mavzuni beradi, majburiy obunani tekshiradi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        app: App = data["app"]
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if not user or user.is_bot:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and (event.message is None or not hasattr(event.message, "chat")
                                                 or type(event.message).__name__ == "InaccessibleMessage"):
            await event.answer("⌛ Xabar eskirgan, qaytadan yuboring", show_alert=True)
            return None

        private = bool(chat and chat.type == "private")
        if private:
            await app.db.touch_user(user.id, user.username, user.first_name)
        row = await app.db.get_user(user.id)
        data["lang"] = row["lang"] if row else "uz"
        data["theme"] = row["theme"] if row else "default"
        data["region"] = row["region"] if row else None
        data["is_admin"] = app.is_admin(user.id)

        if private and not app.is_admin(user.id) and await self._gate(app, event, data):
            return None
        return await handler(event, data)

    async def _gate(self, app: App, event: TelegramObject, data: dict[str, Any]) -> bool:
        """True qaytarsa — handler bajarilmaydi (obuna talab qilindi)."""
        if isinstance(event, Message):
            txt = (event.text or "").strip()
            if txt.startswith("/start") or txt.startswith("/id"):
                return False
        elif isinstance(event, CallbackQuery):
            if (event.data or "").startswith("sub:"):
                return False
        else:
            return False

        bot = data["bot"]
        user = data["event_from_user"]
        missing = await app.subs.missing(bot, user.id)
        if not missing:
            return False
        lang = data["lang"]
        text = app.texts.get("sub_required", lang)
        kb = sub_kb(app, lang, missing)
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
        else:
            await event.answer()
            if event.message:
                await event.message.answer(text, reply_markup=kb)
        return True
