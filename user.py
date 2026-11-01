"""Foydalanuvchi tomoni: havola → video, matn → musiqa qidiruv, ovoz/video → Shazam."""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import re
import shutil
import time
import uuid
from collections import OrderedDict
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Message
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..app import App
from ..services.media import DownloadFailed, Hit, MediaFile, MediaResult, detect_platform, extract_url

log = logging.getLogger("navobot.user")
router = Router(name="user")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # oddiy Bot API: bot yuklab oladigan fayl chegarasi


# ====================================================================== yordamchilar
class _Store:
    """Callback_data 64 baytdan oshmasligi uchun havola/natijalar xotirada saqlanadi."""

    def __init__(self, cap: int = 1000):
        self._d: OrderedDict[str, Any] = OrderedDict()
        self._cap = cap

    def put(self, value: Any) -> str:
        tok = uuid.uuid4().hex[:10]
        self._d[tok] = value
        while len(self._d) > self._cap:
            self._d.popitem(last=False)
        return tok

    def get(self, tok: str) -> Any:
        return self._d.get(tok)


tokens = _Store()
_busy: set[int] = set()


def _lock(uid: int) -> bool:
    if uid in _busy:
        return False
    _busy.add(uid)
    return True


def _unlock(uid: int) -> None:
    _busy.discard(uid)


@contextlib.asynccontextmanager
async def _action(bot: Bot, chat_id: int, action: ChatAction):
    """Yuklash davomida «yuklanmoqda...» holatini yangilab turadi."""
    async def loop() -> None:
        while True:
            try:
                await bot.send_chat_action(chat_id, action)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(4)

    t = asyncio.create_task(loop())
    try:
        yield
    finally:
        t.cancel()


async def _safe_edit(msg: Message | None, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    if msg is None:
        return
    try:
        await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        pass


async def _safe_delete(msg: Message | None) -> None:
    if msg is None:
        return
    with contextlib.suppress(Exception):
        await msg.delete()


async def _over_limit(app: App, uid: int) -> int | None:
    if app.is_admin(uid):
        return None
    raw = await app.db.get_setting("daily_limit", "0") or "0"
    limit = int(raw) if raw.isdigit() else 0
    if limit <= 0:
        return None
    try:
        until = float(await app.db.get_setting(f"premium:{uid}", "0") or 0)
    except ValueError:
        until = 0.0
    if until > time.time():
        return None
    return limit if await app.db.downloads_today(uid) >= limit else None


def _safe_name(s: str, fallback: str = "audio") -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s).strip(" .")
    return (s[:80] or fallback)


async def _send_file(target: Message, f: MediaFile, caption: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Bitta faylni turiga qarab yuboradi; Telegram rad etsa hujjat sifatida yuboradi."""
    try:
        if f.kind == "video":
            await target.answer_video(
                FSInputFile(f.path), caption=caption, duration=f.duration or None, width=f.width or None,
                height=f.height or None, supports_streaming=True, reply_markup=kb)
        elif f.kind == "photo":
            await target.answer_photo(FSInputFile(f.path), caption=caption, reply_markup=kb)
        else:
            name = _safe_name(f"{f.performer} - {f.title}" if f.performer and f.title else (f.title or "audio"))
            await target.answer_audio(
                FSInputFile(f.path, filename=f"{name}{f.path.suffix}"), caption=caption,
                title=(f.title or None), performer=(f.performer or None), duration=f.duration or None)
    except TelegramBadRequest as e:
        log.warning("Telegram %s ni qabul qilmadi (%s), hujjat sifatida yuboriladi", f.kind, e)
        await target.answer_document(FSInputFile(f.path), caption=caption)


async def _send_result(target: Message, app: App, res: MediaResult, mp3_url: str | None = None) -> None:
    caption = app.texts.t("caption", bot=f"@{app.bot_username}") if app.bot_username else ""
    files = res.files
    if len(files) == 1:
        f = files[0]
        kb = None
        if f.kind == "video" and mp3_url:
            kb = InlineKeyboardBuilder().row(Btn(text="🎵 MP3", callback_data=f"mp3:{tokens.put(mp3_url)}")).as_markup()
        await _send_file(target, f, caption, kb)
        return
    visual = [f for f in files if f.kind in ("photo", "video")]
    for i in range(0, len(visual), 10):
        chunk = visual[i:i + 10]
        if len(chunk) == 1:
            await _send_file(target, chunk[0], caption)
            continue
        media = []
        for j, f in enumerate(chunk):
            cap = caption if (i == 0 and j == 0) else None
            if f.kind == "photo":
                media.append(InputMediaPhoto(media=FSInputFile(f.path), caption=cap))
            else:
                media.append(InputMediaVideo(media=FSInputFile(f.path), caption=cap, duration=f.duration or None,
                                             width=f.width or None, height=f.height or None, supports_streaming=True))
        try:
            await target.answer_media_group(media)
        except TelegramBadRequest:
            for f in chunk:
                await _send_file(target, f, caption)
    for f in files:
        if f.kind == "audio":
            await _send_file(target, f, caption)


async def _report_failure(app: App, bot: Bot, uid: int, platform: str, url: str, err: DownloadFailed) -> str:
    """Xatoni bazaga yozadi, kerak bo'lsa adminga xabar beradi. Foydalanuvchi matnini qaytaradi."""
    reason = err.reason
    await app.db.log_download(uid, platform, False, "", err.summary())
    if reason in ("blocked", "other", "unsupported"):
        await app.notify_admins(
            bot, f"dlfail:{platform}",
            f"⚠️ <b>Yuklash xatosi</b> — {html.escape(platform)}\n\n{html.escape(err.summary())}\n\n"
            f"🔗 {html.escape(url)}\n🧪 Sinash: <code>/test {html.escape(url)}</code>",
            every=5,
        )
    key = {"private": "err_private", "not_found": "err_not_found", "too_large": "err_too_large",
           "blocked": "err_blocked", "unsupported": "err_unsupported"}.get(reason, "err_generic")
    return app.texts.t(key)


# ====================================================================== /start, obuna, /top, /new
@router.message(CommandStart())
async def cmd_start(m: Message, app: App, bot: Bot, command: CommandObject, is_new_user: bool = False) -> None:
    args = (command.args or "").strip()
    if is_new_user and args.startswith("ref_") and args[4:].isdigit():
        ref = int(args[4:])
        if ref != m.from_user.id and await app.db.get_user(ref):
            await app.db.set_ref(m.from_user.id, ref)
            with contextlib.suppress(Exception):
                await bot.send_message(ref, "🎉 Sizning havolangiz orqali yangi foydalanuvchi qo'shildi!")
    await m.answer(app.texts.t("start", name=html.escape(m.from_user.first_name or "do'st")))


@router.callback_query(F.data == "sub:check")
async def cb_sub_check(c: CallbackQuery, app: App, bot: Bot) -> None:
    if await app.subs.missing(bot, c.from_user.id, fresh=True):
        await c.answer("❌ Hali hamma kanalga obuna bo'lmadingiz", show_alert=True)
        return
    await c.answer("✅ Rahmat!")
    await _safe_delete(c.message)
    if c.message:
        await c.message.answer(app.texts.t("start", name=html.escape(c.from_user.first_name or "do'st")))


async def _tracks_list(m: Message, app: App, title: str, rows: list[Any]) -> None:
    if not rows:
        await m.answer(app.texts.t("top_empty"))
        return
    lines = [f"<b>{title}</b>\n"]
    kb = InlineKeyboardBuilder()
    btns = []
    for i, r in enumerate(rows, 1):
        name = f"{r['artist']} — {r['title']}" if r["artist"] else r["title"]
        lines.append(f"{i}. {html.escape(name)}")
        btns.append(Btn(text=str(i), callback_data=f"dq:{tokens.put(name)}"))
    for i in range(0, len(btns), 5):
        kb.row(*btns[i:i + 5])
    await m.answer("\n".join(lines) + "\n\n⬇️ Yuklash uchun raqamni bosing", reply_markup=kb.as_markup())


@router.message(Command("top"))
async def cmd_top(m: Message, app: App) -> None:
    await _tracks_list(m, app, "🔥 Mashhur qo'shiqlar", await app.db.top_tracks(10))


@router.message(Command("new"))
async def cmd_new(m: Message, app: App) -> None:
    await _tracks_list(m, app, "🆕 Yangi aniqlanganlar", await app.db.new_tracks(10))


# ====================================================================== havola → video
@router.message(F.text, F.text.contains("://"), ~F.text.startswith("/"))
async def on_link(m: Message, app: App, bot: Bot) -> None:
    url = extract_url(m.text)
    platform = detect_platform(url) if url else None
    if not url or not platform:
        await m.answer(app.texts.t("unsupported_link"))
        return
    uid = m.from_user.id
    lim = await _over_limit(app, uid)
    if lim:
        await m.answer(app.texts.t("limit_reached", limit=lim))
        return
    if not _lock(uid):
        await m.answer(app.texts.t("busy"))
        return
    status = await m.answer(app.texts.t("downloading"))
    audio = platform == "soundcloud"
    try:
        async with _action(bot, m.chat.id, ChatAction.UPLOAD_VIDEO):
            try:
                res = await app.media.download(url, platform=platform, audio=audio)
            except DownloadFailed as e:
                await _safe_edit(status, await _report_failure(app, bot, uid, platform, url, e))
                return
            try:
                await _send_result(m, app, res, mp3_url=None if audio else url)
                await app.db.log_download(uid, platform, True, res.via)
            finally:
                res.cleanup()
        await _safe_delete(status)
    except Exception as e:  # noqa: BLE001
        log.exception("on_link xatosi")
        await app.db.log_download(uid, platform, False, "", f"{type(e).__name__}: {e}")
        await _safe_edit(status, app.texts.t("err_generic"))
    finally:
        _unlock(uid)


@router.callback_query(F.data.startswith("mp3:"))
async def cb_mp3(c: CallbackQuery, app: App, bot: Bot) -> None:
    url = tokens.get(c.data[4:])
    if not url:
        await c.answer("Havola eskirgan — qayta yuboring", show_alert=True)
        return
    uid = c.from_user.id
    if not _lock(uid):
        await c.answer(app.texts.t("busy"), show_alert=True)
        return
    await c.answer("⏳ MP3 tayyorlanmoqda...")
    status = await c.message.answer("⏳ MP3 tayyorlanmoqda...")
    platform = detect_platform(url) or "other"
    try:
        async with _action(bot, c.message.chat.id, ChatAction.UPLOAD_VOICE):
            try:
                res = await app.media.download(url, platform=platform, audio=True)
            except DownloadFailed as e:
                await _safe_edit(status, await _report_failure(app, bot, uid, platform, url, e))
                return
            try:
                await _send_result(c.message, app, res)
                await app.db.log_download(uid, platform, True, res.via)
            finally:
                res.cleanup()
        await _safe_delete(status)
    except Exception:  # noqa: BLE001
        log.exception("cb_mp3 xatosi")
        await _safe_edit(status, app.texts.t("err_generic"))
    finally:
        _unlock(uid)


# ====================================================================== matn → musiqa qidiruv
@router.message(F.text, ~F.text.startswith("/"))
async def on_text(m: Message, app: App) -> None:
    q = (m.text or "").strip()[:200]
    if len(q) < 2:
        return
    if not _lock(m.from_user.id):
        await m.answer(app.texts.t("busy"))
        return
    status = await m.answer(app.texts.t("searching"))
    try:
        hits = await app.media.search(q, 5)
    except Exception:  # noqa: BLE001
        log.exception("qidiruv xatosi")
        hits = []
    finally:
        _unlock(m.from_user.id)
    if not hits:
        await _safe_edit(status, app.texts.t("no_results"))
        return
    tok = tokens.put(hits)
    lines = [app.texts.t("pick_track"), ""] + [f"{i}. {h.label}" for i, h in enumerate(hits, 1)]
    kb = InlineKeyboardBuilder()
    kb.row(*[Btn(text=str(i), callback_data=f"ys:{tok}:{i - 1}") for i in range(1, len(hits) + 1)])
    await _safe_edit(status, "\n".join(lines), kb.as_markup())


async def _deliver_hit(c: CallbackQuery, app: App, bot: Bot, hit: Hit) -> None:
    uid = c.from_user.id
    lim = await _over_limit(app, uid)
    if lim:
        await c.answer(app.texts.t("limit_reached", limit=lim), show_alert=True)
        return
    if not _lock(uid):
        await c.answer(app.texts.t("busy"), show_alert=True)
        return
    await c.answer("⏳ Yuklanmoqda...")
    status = await c.message.answer(f"⏳ {html.escape(hit.title[:70])}")
    try:
        async with _action(bot, c.message.chat.id, ChatAction.UPLOAD_VOICE):
            try:
                res = await app.media.download_hit(hit)
            except DownloadFailed as e:
                await _safe_edit(status, await _report_failure(app, bot, uid, hit.source, hit.url, e))
                return
            try:
                await _send_result(c.message, app, res)
                await app.db.log_download(uid, hit.source, True, res.via)
            finally:
                res.cleanup()
        await _safe_delete(status)
    except Exception:  # noqa: BLE001
        log.exception("_deliver_hit xatosi")
        await _safe_edit(status, app.texts.t("err_generic"))
    finally:
        _unlock(uid)


@router.callback_query(F.data.regexp(r"^ys:[0-9a-f]{10}:\d$"))
async def cb_pick(c: CallbackQuery, app: App, bot: Bot) -> None:
    _p, tok, idx = c.data.split(":")
    hits = tokens.get(tok)
    if not hits or int(idx) >= len(hits):
        await c.answer("Ro'yxat eskirgan — qayta qidiring", show_alert=True)
        return
    await _deliver_hit(c, app, bot, hits[int(idx)])


@router.callback_query(F.data.regexp(r"^dq:[0-9a-f]{10}$"))
async def cb_dq(c: CallbackQuery, app: App, bot: Bot) -> None:
    q = tokens.get(c.data[3:])
    if not q:
        await c.answer("Ro'yxat eskirgan — qayta urinib ko'ring", show_alert=True)
        return
    await c.answer("🔎 Qidirilmoqda...")
    try:
        hits = await app.media.search(q, 3)
    except Exception:  # noqa: BLE001
        hits = []
    if not hits:
        await c.message.answer(app.texts.t("no_results"))
        return
    await _deliver_hit(c, app, bot, hits[0])


# ====================================================================== ovoz / video → Shazam
@router.message(F.voice | F.audio | F.video | F.video_note)
async def on_media(m: Message, app: App, bot: Bot) -> None:
    obj = m.voice or m.audio or m.video or m.video_note
    if obj is None:
        return
    if (getattr(obj, "file_size", 0) or 0) > TG_DOWNLOAD_LIMIT and not app.cfg.local_api:
        await m.answer(app.texts.t("file_too_big_tg"))
        return
    uid = m.from_user.id
    if not _lock(uid):
        await m.answer(app.texts.t("busy"))
        return
    status = await m.answer(app.texts.t("recognizing"))
    workdir = app.media.new_workdir()
    track = None
    failed = False
    try:
        async with _action(bot, m.chat.id, ChatAction.TYPING):
            src = workdir / f"in_{obj.file_unique_id}"
            await bot.download(obj, destination=src)
            track = await app.shazam.recognize(src)
    except Exception as e:  # noqa: BLE001
        failed = True
        log.exception("Shazam xatosi")
        await app.notify_admins(bot, "shazam_err", f"⚠️ Shazam xatosi: <code>{html.escape(str(e)[:300])}</code>", every=10)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        _unlock(uid)
    if failed:
        await _safe_edit(status, app.texts.t("err_generic"))
        return
    if not track or not track.title:
        await _safe_edit(status, app.texts.t("not_recognized"))
        return
    await app.db.add_track(track.title, track.artist)
    kb = InlineKeyboardBuilder()
    kb.row(Btn(text="⬇️ Yuklab olish", callback_data=f"dq:{tokens.put(track.query)}"))
    if track.url.startswith("http"):
        kb.row(Btn(text="🔗 Shazam", url=track.url))
    text = app.texts.t("recognized", title=html.escape(track.title), artist=html.escape(track.artist or "—"))
    sent = False
    if track.cover.startswith("http"):
        try:
            await m.answer_photo(track.cover, caption=text, reply_markup=kb.as_markup())
            sent = True
        except Exception:  # noqa: BLE001
            sent = False
    if not sent:
        await m.answer(text, reply_markup=kb.as_markup())
    await _safe_delete(status)
