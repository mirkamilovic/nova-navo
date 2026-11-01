"""Foydalanuvchiga ko'rsatiladigan matnlar. Admin `text:<kalit>` sozlamasi bilan o'zgartira oladi."""
from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, str] = {
    "start": (
        "👋 Salom, <b>{name}</b>!\n\n"
        "Men video va musiqa yuklovchi botman.\n\n"
        "📥 <b>Video yuklash:</b> Instagram, TikTok, YouTube, Pinterest, Facebook, X, Threads havolasini yuboring.\n"
        "🎧 <b>Musiqa topish:</b> qo'shiq nomi yoki matnini yozing, ovozli xabar / video yuboring.\n\n"
        "ℹ️ Yordam: /help"
    ),
    "downloading": "⏳ Yuklanmoqda...",
    "searching": "🔎 Qidirilmoqda...",
    "recognizing": "🎧 Aniqlanmoqda...",
    "caption": "📥 {bot}",
    "busy": "⏳ Oldingi so'rovingiz hali tugamadi, biroz kuting.",
    "unsupported_link": "❌ Bu havola qo'llab-quvvatlanmaydi.\nInstagram, TikTok, YouTube, Pinterest, Facebook, X yoki Threads havolasini yuboring.",
    "sub_required": "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng «✅ Tekshirish» tugmasini bosing:",
    "err_private": "🔒 Bu post yopiq (private) yoki yosh cheklovi bor, uni yuklab bo'lmaydi.",
    "err_not_found": "❌ Post topilmadi yoki o'chirilgan. Havolani tekshiring.",
    "err_too_large": "📦 Fayl juda katta — Telegram orqali yuborib bo'lmaydi.",
    "err_blocked": (
        "⚠️ Platforma hozir serverimizga yuklashga ruxsat bermayapti.\n"
        "Admin xabardor qilindi, birozdan keyin qayta urinib ko'ring."
    ),
    "err_unsupported": "❌ Bu havoladan media topilmadi.",
    "err_generic": "⚠️ Yuklab bo'lmadi. Havolani tekshiring yoki keyinroq urinib ko'ring.",
    "no_results": "😕 Hech narsa topilmadi. Boshqacha yozib ko'ring.",
    "pick_track": "🎧 <b>Topilgan qo'shiqlar</b> — yuklash uchun raqamni bosing:",
    "recognized": "🎵 <b>{title}</b>\n👤 {artist}",
    "not_recognized": "😕 Qo'shiq aniqlanmadi. Aniqroq / uzunroq (10–20 soniya) parcha yuboring.",
    "file_too_big_tg": "📦 Fayl 20 MB dan katta — Telegram bot uni yuklab ola olmaydi. Qisqaroq parcha yuboring.",
    "limit_reached": "🚫 Bugungi bepul limit ({limit} ta) tugadi.\n💎 Cheksiz foydalanish uchun /premium",
    "top_empty": "Hozircha ro'yxat bo'sh. Qo'shiq aniqlatib ko'ring!",
    "banned": "🚫 Siz botdan foydalana olmaysiz.",
}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Texts:
    def __init__(self, db: Any):
        self.db = db
        self._over: dict[str, str] = {}

    async def load(self) -> None:
        rows = await self.db.settings_like("text:")
        self._over = {k[5:]: v for k, v in rows.items()}

    def t(self, key: str, **kw: Any) -> str:
        raw = self._over.get(key) or DEFAULTS.get(key, key)
        try:
            return raw.format_map(_Safe(kw))
        except (ValueError, IndexError):
            return raw
