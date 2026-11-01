"""Foydalanuvchini ro'yxatga olish, ban va majburiy obuna tekshiruvi."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        app = data.get("app")
        user = data.get("event_from_user")
        if app is None or user is None or user.is_bot:
            return await handler(event, data)

        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message is not None:
            chat = event.message.chat
        if chat is not None and chat.type != "private":
            return await handler(event, data)

        data["is_new_user"] = await app.db.touch_user(user)

        if app.is_admin(user.id):
            return await handler(event, data)

        if await app.db.is_banned(user.id):
            await self._say(event, app.texts.t("banned"))
            return None

        if await self._gate(app, event, data):
            return None
        return await handler(event, data)

    async def _gate(self, app: Any, event: Any, data: dict[str, Any]) -> bool:
        """True qaytarsa — hodisa to'xtatiladi (obuna talab qilinadi)."""
        if not await app.subs.enabled():
            return False
        if not await app.db.channels():
            return False
        bot = data["bot"]
        user = data["event_from_user"]
        missing = await app.subs.missing(bot, user.id)
        if not missing:
            return False

        kb = InlineKeyboardBuilder()
        for ch in missing:
            if ch["link"]:
                kb.row(Btn(text=f"📢 {ch['title']}", url=ch["link"]))
        kb.row(Btn(text="✅ Tekshirish", callback_data="sub:check"))
        text = app.texts.t("sub_required")
        if isinstance(event, CallbackQuery):
            await event.answer("📢 Avval kanallarga obuna bo'ling", show_alert=True)
            if event.message is not None:
                try:
                    await event.message.answer(text, reply_markup=kb.as_markup())
                except Exception:  # noqa: BLE001
                    pass
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=kb.as_markup())
        return True

    @staticmethod
    async def _say(event: Any, text: str) -> None:
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except Exception:  # noqa: BLE001
            pass
