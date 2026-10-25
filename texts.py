"""Standart matnlar (HTML) va ularni owner paneldan almashtirish tizimi.

Matnlar bazada `texts` jadvalida saqlanadi. Owner yuborgan xabarning HTML ko'rinishi
(premium emojilar `<tg-emoji>` sifatida) shu yerga yoziladi.
"""
from __future__ import annotations

from typing import Any

from .db import Database

LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}

REGIONS = [
    "Toshkent shahri", "Toshkent viloyati", "Andijon", "Buxoro", "Farg'ona",
    "Jizzax", "Xorazm", "Namangan", "Navoiy", "Qashqadaryo",
    "Qoraqalpog'iston", "Samarqand", "Sirdaryo", "Surxondaryo",
]

# mavzu kodi -> (nomi, natija sarlavhasi emojisi, like emojisi)
THEMES = {
    "default": ("Standart", "🎧", "❤️"),
    "angel": ("👼 Angel", "👼", "🤍"),
    "autumn": ("🎨 Warm Autumn", "🍂", "🧡"),
    "night": ("🌙 Night", "🌙", "💜"),
    "fire": ("🔥 Fire", "🔥", "❤️‍🔥"),
}

# Owner paneldagi tahrir ro'yxati: kalit -> (tavsif, o'zgaruvchilar)
EDITABLE: dict[str, tuple[str, str]] = {
    "start": ("/start xabari", "{name}"),
    "help": ("Yordam xabari", ""),
    "caption_video": ("Video ostidagi yozuv", "{bot}"),
    "caption_audio": ("Audio ostidagi yozuv", "{bot}"),
    "sub_required": ("Majburiy obuna xabari", ""),
    "sub_fail": ("Obuna bo'lmaganda ogohlantirish", ""),
    "searching": ("Qidirilmoqda xabari", ""),
    "shazam_wait": ("Shazam aniqlanmoqda xabari", ""),
    "shazam_fail": ("Shazam topolmadi xabari", ""),
    "downloading": ("Yuklanmoqda xabari", ""),
    "not_found": ("Topilmadi xabari", ""),
    "error": ("Xatolik xabari", ""),
    "too_big": ("Fayl juda katta xabari", "{mb}"),
    "busy": ("Band xabari", ""),
    "settings_title": ("Sozlamalar sarlavhasi", ""),
    "region_set": ("Viloyat tanlandi xabari", "{region}"),
    "playlist_empty": ("Audio playlist bo'sh", ""),
    "vplaylist_head": ("Video playlist xabari", ""),
    "btn_video": ("«Video» tugmasi", ""),
    "btn_audio": ("«Audio» tugmasi", ""),
    "btn_add_group": ("«Guruhga qo'shish» tugmasi", ""),
    "btn_save": ("«Saqlash» tugmasi", ""),
    "btn_extract": ("«Qo'shiqni yuklab olish» tugmasi", ""),
    "btn_subscribe": ("«Obuna bo'lish» tugmasi", ""),
    "btn_confirm": ("«Tasdiqlash» tugmasi", ""),
    "btn_open_playlist": ("«Playlistni ochish» tugmasi", ""),
}

DEFAULTS: dict[str, dict[str, str]] = {
    "uz": {
        "start": (
            "🔥 Assalomu alaykum, <b>{name}</b>! Xush kelibsiz.\n"
            "Bot orqali quyidagilarni yuklab olishingiz mumkin:\n\n"
            "• <b>Instagram</b> - post, reels va IGTV + audio bilan;\n"
            "• <b>TikTok</b> - suv belgisiz video + audio bilan;\n"
            "• <b>YouTube</b> - videolar va shorts + audio bilan;\n"
            "• <b>Snapchat</b> - suv belgisiz video + audio bilan;\n"
            "• <b>Likee</b> - suv belgisiz video + audio bilan;\n"
            "• <b>Pinterest</b> - suv belgisiz video va rasmlar;\n"
            "• <b>Threads</b> - video va rasmlar + audio bilan;\n\n"
            "<b>Shazam funksiya:</b>\n"
            "• Qo‘shiq nomi yoki ijrochi ismi\n"
            "• Qo‘shiq matni\n"
            "• Ovozli xabar\n"
            "• Video\n"
            "• Audio\n"
            "• Video xabar\n\n"
            "🚀 Yuklab olmoqchi bo'lgan videoga havolani yuboring!\n"
            "😎 Bot guruhlarda ham ishlay oladi!"
        ),
        "help": (
            "ℹ️ <b>Qanday ishlatiladi?</b>\n\n"
            "• Video havolasini yuboring — video yuklab beraman\n"
            "• Qo‘shiq nomi yoki matnini yozing — topib beraman\n"
            "• Ovozli xabar, audio yoki video yuboring — qo‘shiqni aniqlayman\n\n"
            "/my — audio playlist\n/playlist — video playlist\n"
            "/top — mashhur qo‘shiqlar\n/new — yangi qo‘shiqlar\n/settings — sozlamalar"
        ),
        "caption_video": "❤️@{bot} orqali yuklab olindi🚀📥",
        "caption_audio": "❤️@{bot} orqali istagan musiqangizni tez va oson toping!🚀",
        "sub_required": "Iltimos, quyidagi kanallarimizga obuna bo‘ling,\nkeyin botni ishlatishingiz mumkin.",
        "sub_fail": "❌ Siz hali barcha kanallarga obuna bo‘lmadingiz.",
        "searching": "🔎 Qidirilmoqda...",
        "shazam_wait": "🎧 Qo‘shiq aniqlanmoqda...",
        "shazam_fail": "😔 Qo‘shiq aniqlanmadi. Boshqa parcha yoki aniqroq yozuv yuboring.",
        "downloading": "⏳ Yuklanmoqda...",
        "not_found": "😔 Hech narsa topilmadi. Boshqacha yozib ko‘ring.",
        "error": "⚠️ Yuklab bo‘lmadi. Havola to‘g‘riligini tekshiring yoki keyinroq urinib ko‘ring.",
        "too_big": "⚠️ Fayl juda katta (limit {mb} MB). Past sifatda ham sig‘madi.",
        "busy": "⏳ Oldingi so‘rovingiz hali tugamadi, biroz kuting...",
        "settings_title": "⚙️ <b>Sozlamalar</b>\n\nNimani o'zgartirishni xohlaysiz?",
        "region_set": "✅ Viloyat tanlandi: <b>{region}</b>\n\n🙏 So'rovnomada qatnashganingiz uchun rahmat!",
        "playlist_empty": "Playlistingiz hozircha bo‘sh. Qo‘shiqlarni ❤️ bosib saqlang.",
        "vplaylist_head": "🎬 <b>Playlist — videolaringiz bir joyda</b>\n\n• Videoni pastdagi SAQLASH tugmasi bilan qo‘shib boring.",
        "btn_video": "🎞 Video",
        "btn_audio": "🎧 Audio",
        "btn_add_group": "👉 Guruhga qo'shish ⤴️",
        "btn_save": "💾 Saqlash",
        "btn_extract": "📥 Qo'shiqni yuklab olish",
        "btn_subscribe": "➕ Obuna bo‘lish",
        "btn_confirm": "✅ Tasdiqlash",
        "btn_open_playlist": "🎥 Playlistni ochish",
    },
    "ru": {
        "start": (
            "🔥 Здравствуйте, <b>{name}</b>! Добро пожаловать.\n"
            "С помощью бота можно скачать:\n\n"
            "• <b>Instagram</b> — посты, reels, IGTV со звуком;\n"
            "• <b>TikTok</b> — видео без водяного знака;\n"
            "• <b>YouTube</b> — видео и shorts;\n"
            "• <b>Snapchat, Likee, Pinterest, Threads</b>.\n\n"
            "<b>Shazam:</b> название, текст песни, голосовое, аудио, видео, кружок.\n\n"
            "🚀 Отправьте ссылку на видео!\n😎 Бот работает и в группах!"
        ),
        "help": "ℹ️ Отправьте ссылку — скачаю видео. Напишите название песни — найду. Отправьте голосовое/аудио/видео — определю песню.\n\n/my /playlist /top /new /settings",
        "caption_video": "❤️Скачано через @{bot}🚀📥",
        "caption_audio": "❤️Любая музыка быстро и легко через @{bot}!🚀",
        "sub_required": "Пожалуйста, подпишитесь на каналы ниже, затем можно пользоваться ботом.",
        "sub_fail": "❌ Вы ещё не подписались на все каналы.",
        "searching": "🔎 Поиск...",
        "shazam_wait": "🎧 Определяю песню...",
        "shazam_fail": "😔 Песня не определена. Отправьте другой фрагмент.",
        "downloading": "⏳ Загрузка...",
        "not_found": "😔 Ничего не найдено.",
        "error": "⚠️ Не удалось скачать. Проверьте ссылку или попробуйте позже.",
        "too_big": "⚠️ Файл слишком большой (лимит {mb} МБ).",
        "busy": "⏳ Предыдущий запрос ещё выполняется...",
        "settings_title": "⚙️ <b>Настройки</b>\n\nЧто изменить?",
        "region_set": "✅ Регион выбран: <b>{region}</b>\n\n🙏 Спасибо за участие в опросе!",
        "playlist_empty": "Плейлист пока пуст. Нажимайте ❤️ чтобы сохранять песни.",
        "vplaylist_head": "🎬 <b>Плейлист — ваши видео в одном месте</b>\n\n• Добавляйте видео кнопкой СОХРАНИТЬ.",
        "btn_video": "🎞 Видео",
        "btn_audio": "🎧 Аудио",
        "btn_add_group": "👉 Добавить в группу ⤴️",
        "btn_save": "💾 Сохранить",
        "btn_extract": "📥 Скачать песню",
        "btn_subscribe": "➕ Подписаться",
        "btn_confirm": "✅ Подтвердить",
        "btn_open_playlist": "🎥 Открыть плейлист",
    },
    "en": {
        "start": (
            "🔥 Hello, <b>{name}</b>! Welcome.\n"
            "Download with this bot:\n\n"
            "• <b>Instagram</b> — posts, reels, IGTV with audio;\n"
            "• <b>TikTok</b> — no watermark;\n"
            "• <b>YouTube</b> — videos and shorts;\n"
            "• <b>Snapchat, Likee, Pinterest, Threads</b>.\n\n"
            "<b>Shazam:</b> song name, lyrics, voice, audio, video, video note.\n\n"
            "🚀 Send a video link!\n😎 Works in groups too!"
        ),
        "help": "ℹ️ Send a link to download. Type a song name to search. Send voice/audio/video to recognize a song.\n\n/my /playlist /top /new /settings",
        "caption_video": "❤️Downloaded via @{bot}🚀📥",
        "caption_audio": "❤️Find any music fast and easy with @{bot}!🚀",
        "sub_required": "Please subscribe to the channels below, then you can use the bot.",
        "sub_fail": "❌ You have not subscribed to all channels yet.",
        "searching": "🔎 Searching...",
        "shazam_wait": "🎧 Recognizing the song...",
        "shazam_fail": "😔 Could not recognize the song. Send another clip.",
        "downloading": "⏳ Downloading...",
        "not_found": "😔 Nothing found.",
        "error": "⚠️ Could not download. Check the link or try later.",
        "too_big": "⚠️ File is too large (limit {mb} MB).",
        "busy": "⏳ Your previous request is still running...",
        "settings_title": "⚙️ <b>Settings</b>\n\nWhat do you want to change?",
        "region_set": "✅ Region selected: <b>{region}</b>\n\n🙏 Thanks for taking part in the poll!",
        "playlist_empty": "Your playlist is empty. Tap ❤️ to save songs.",
        "vplaylist_head": "🎬 <b>Playlist — your videos in one place</b>\n\n• Add videos with the SAVE button.",
        "btn_video": "🎞 Video",
        "btn_audio": "🎧 Audio",
        "btn_add_group": "👉 Add to group ⤴️",
        "btn_save": "💾 Save",
        "btn_extract": "📥 Download the song",
        "btn_subscribe": "➕ Subscribe",
        "btn_confirm": "✅ Confirm",
        "btn_open_playlist": "🎥 Open playlist",
    },
}


class _Safe(dict):
    def __missing__(self, key: str) -> str:  # noqa: D401
        return "{" + key + "}"


class Texts:
    """Matn beruvchi: avval bazadagi (owner o'zgartirgan), keyin standart."""

    def __init__(self, db: Database):
        self.db = db
        self._over: dict[tuple[str, str], str] = {}

    async def load(self) -> None:
        self._over = await self.db.all_texts()

    def raw(self, key: str, lang: str) -> str:
        if (key, lang) in self._over:
            return self._over[(key, lang)]
        if key in DEFAULTS.get(lang, {}):
            return DEFAULTS[lang][key]
        if (key, "uz") in self._over:
            return self._over[(key, "uz")]
        return DEFAULTS["uz"].get(key, key)

    def get(self, key: str, lang: str = "uz", **fmt: Any) -> str:
        text = self.raw(key, lang)
        try:
            return text.format_map(_Safe(fmt))
        except (ValueError, IndexError):
            return text

    async def set(self, key: str, lang: str, value: str) -> None:
        await self.db.set_text(key, lang, value)
        self._over[(key, lang)] = value

    async def reset(self, key: str, lang: str) -> None:
        await self.db.reset_text(key, lang)
        self._over.pop((key, lang), None)

    def is_custom(self, key: str, lang: str) -> bool:
        return (key, lang) in self._over
