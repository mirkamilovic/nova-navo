"""«/» menyusi. main.py bu ro'yxatlarni joyida almashtiradi (USER_COMMANDS[:] = ...)."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

USER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="🏠 Bosh menyu"),
    BotCommand(command="help", description="📥 Qanday yuklash"),
]
ADMIN_EXTRA: list[BotCommand] = [
    BotCommand(command="admin", description="🛠 Admin panel"),
]

DESCRIPTION = (
    "📥 Instagram, TikTok, YouTube, Pinterest, Facebook, X dan video va musiqa yuklovchi bot.\n"
    "🎧 Qo'shiq nomi, ovozli xabar yoki video yuboring — musiqani topib beraman."
)
SHORT_DESCRIPTION = "📥 Video va musiqa yuklovchi · 🎧 Shazam"


async def set_user_commands(bot: Bot) -> None:
    await bot.set_my_commands(list(USER_COMMANDS), scope=BotCommandScopeDefault())


async def set_descriptions(bot: Bot) -> None:
    await bot.set_my_description(DESCRIPTION)
    await bot.set_my_short_description(SHORT_DESCRIPTION)


async def set_admin_commands(bot: Bot, uid: int) -> None:
    try:
        await bot.set_my_commands(
            list(USER_COMMANDS) + list(ADMIN_EXTRA), scope=BotCommandScopeChat(chat_id=uid)
        )
    except Exception:  # noqa: BLE001  (admin botni hali /start qilmagan bo'lishi mumkin)
        pass
