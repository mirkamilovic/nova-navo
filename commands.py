"""«/» menyusidagi buyruqlar: oddiy foydalanuvchi va admin uchun alohida."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

log = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand(command="my", description="List your playlist"),
    BotCommand(command="playlist", description="List your video playlist"),
    BotCommand(command="top", description="TOP Popular Songs"),
    BotCommand(command="new", description="NEW Popular Songs"),
    BotCommand(command="settings", description="Settings"),
]

ADMIN_EXTRA = [
    BotCommand(command="admin", description="🛠 Owner paneli"),
    BotCommand(command="cancel", description="Amalni bekor qilish"),
]

DESCRIPTION = (
    "Assalomu Aleykum!\n\n"
    "Men siz izlagan musiqangizni topishga yordam beraman 🎧\n\n"
    "Siz izlayotgan qo'shiqni topishim uchun quyidagilardan birini yuboring:\n"
    "• Qo'shiq nomi yoki ijrochi ismi\n• Video\n• Qo'shiq matni\n• Ovozli xabar\n"
    "• Video xabar\n• Tik Tokdagi video xavolasi\n• Instagramdagi video xavolasi"
)
SHORT_DESCRIPTION = "Instagram, TikTok, YouTube'dan video + istalgan musiqani tez va oson yuklab beruvchi bot!"


async def set_user_commands(bot: Bot) -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(USER_COMMANDS)


async def set_admin_commands(bot: Bot, uid: int) -> None:
    try:
        await bot.set_my_commands(USER_COMMANDS + ADMIN_EXTRA, scope=BotCommandScopeChat(chat_id=uid))
    except Exception as e:  # noqa: BLE001  (admin botni hali boshlamagan bo'lishi mumkin)
        log.info("admin (%s) buyruqlarini o'rnatib bo'lmadi: %s", uid, e)


async def set_descriptions(bot: Bot) -> None:
    try:
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
    except Exception as e:  # noqa: BLE001
        log.info("tavsifni o'rnatib bo'lmadi: %s", e)
