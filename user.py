"""Oddiy foydalanuvchi handlerlari."""
from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import flows
from ..app import App
from ..keyboards import (
    LIST_PAGE, add_group_btn, audio_kb, chart_view, fx_kb, lang_kb, list_kb, region_kb,
    search_view, settings_kb, sub_kb, theme_kb,
)
from ..services.media import (
    AUDIO_EFFECTS, MediaError, SearchItem, apply_effect, detect_platform, extract_urls,
    fmt_duration, split_title,
)
from ..texts import LANGS, REGIONS, THEMES

log = logging.getLogger(__name__)
router = Router(name="user")

PRIVATE = F.chat.type == "private"
TG_DL_LIMIT = 20 * 1024 * 1024


async def _safe_edit(msg: Message, text: str | None = None, kb=None) -> None:
    try:
        if text is not None:
            await msg.edit_text(text, reply_markup=kb)
        else:
            await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


# ================================================================ /start, /help, /id
@router.message(CommandStart())
async def cmd_start(m: Message, app: App, lang: str) -> None:
    if m.chat.type != "private":
        await m.answer(app.texts.get("help", lang))
        return
    text = app.texts.get("start", lang, name=html.escape(m.from_user.first_name or ""))
    kb = InlineKeyboardBuilder()
    kb.row(add_group_btn(app, lang))
    img = await app.db.get_setting("img_start", "")
    if img and len(text) <= 1000:
        try:
            await m.answer_photo(img, caption=text, reply_markup=kb.as_markup())
            return
        except TelegramBadRequest:
            log.warning("start rasmi yaroqsiz, matn bilan yuboriladi")
    elif img:
        try:
            await m.answer_photo(img)
        except TelegramBadRequest:
            pass
    await m.answer(text, reply_markup=kb.as_markup())


@router.message(Command("help"))
async def cmd_help(m: Message, app: App, lang: str) -> None:
    await m.answer(app.texts.get("help", lang))


@router.message(Command("id"))
async def cmd_id(m: Message) -> None:
    await m.answer(f"🆔 <code>{m.from_user.id}</code>")


@router.my_chat_member(PRIVATE)
async def on_block(ev: ChatMemberUpdated, app: App) -> None:
    if ev.new_chat_member.status in ("kicked", "left"):
        await app.db.set_user_field(ev.from_user.id, "active", 0)
    elif ev.new_chat_member.status == "member":
        await app.db.set_user_field(ev.from_user.id, "active", 1)


# ================================================================ Obuna tasdiqlash
@router.callback_query(F.data == "sub:ok")
async def cb_sub_ok(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    missing = await app.subs.missing(bot, c.from_user.id, fresh=True)
    if missing:
        await c.answer(app.texts.get("sub_fail", lang), show_alert=True)
        await _safe_edit(c.message, kb=sub_kb(app, lang, missing))
        return
    await c.answer("✅")
    try:
        await c.message.delete()
    except TelegramBadRequest:
        pass
    await bot.send_message(c.from_user.id, app.texts.get("help", lang))


# ================================================================ Havola -> video
@router.message(F.text.regexp(r"(?s).*https?://"))
async def on_link(m: Message, app: App, bot: Bot, lang: str) -> None:
    urls = extract_urls(m.text)
    private = m.chat.type == "private"
    todo = [u for u in urls if (private or detect_platform(u))]
    if not todo:
        return
    for url in todo[:5]:
        await flows.send_video_from_url(
            bot, app, m.chat.id, m.from_user.id, url, lang,
            reply_to=m.message_id if not private else None,
        )


# ================================================================ Qidiruv
async def run_search(m: Message, app: App, lang: str, theme: str, query: str) -> None:
    status = await m.answer(app.texts.get("searching", lang))
    try:
        items = await app.media.search(query, 15)
    except MediaError as e:
        await status.delete()
        await flows.report_error(m.bot, app, m.chat.id, lang, e, "youtube", m.from_user.id)
        return
    if not items:
        await status.edit_text(app.texts.get("not_found", lang))
        return
    sid = await app.db.search_save(query, [i.to_dict() for i in items])
    text, kb = search_view(app, lang, theme, sid, items, 0, "a")
    await status.edit_text(text, reply_markup=kb)


async def _load_items(app: App, sid: str) -> tuple[str, list[SearchItem]] | None:
    got = await app.db.search_get(sid)
    if not got:
        return None
    q, raw = got
    return q, [SearchItem(**d) for d in raw]


@router.callback_query(F.data.regexp(r"^(sm|sp):"))
async def cb_search_nav(c: CallbackQuery, app: App, lang: str, theme: str) -> None:
    _kind, sid, page, mode = c.data.split(":")
    got = await _load_items(app, sid)
    if not got:
        await c.answer("⌛ Qidiruv eskirdi, qayta yozing", show_alert=True)
        return
    _q, items = got
    text, kb = search_view(app, lang, theme, sid, items, int(page), mode)
    await _safe_edit(c.message, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("sd:"))
async def cb_search_pick(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    _k, sid, idx, mode = c.data.split(":")
    got = await _load_items(app, sid)
    if not got or int(idx) >= len(got[1]):
        await c.answer("⌛ Qidiruv eskirdi, qayta yozing", show_alert=True)
        return
    item = got[1][int(idx)]
    await c.answer()
    chat_id = c.message.chat.id
    if mode == "v":
        await flows.send_video_from_url(
            bot, app, chat_id, c.from_user.id,
            f"https://www.youtube.com/watch?v={item.id}", lang,
        )
    else:
        await flows.send_youtube_audio(bot, app, chat_id, c.from_user.id, item.id, lang)


@router.message(PRIVATE, F.text, ~F.text.startswith("/"))
async def on_text(m: Message, app: App, lang: str, theme: str) -> None:
    query = m.text.strip()
    if len(query) < 2:
        return
    await run_search(m, app, lang, theme, query[:200])


# ================================================================ Shazam
@router.message(PRIVATE, F.voice | F.audio | F.video | F.video_note)
async def on_media(m: Message, app: App, bot: Bot, lang: str, theme: str) -> None:
    obj = m.voice or m.audio or m.video or m.video_note
    if obj.file_size and obj.file_size > TG_DL_LIMIT and not app.cfg.local_api:
        await m.answer(app.texts.get("too_big", lang, mb=20))
        return
    status = await m.answer(app.texts.get("shazam_wait", lang))
    workdir = app.media.new_workdir()
    try:
        src = workdir / "input"
        await bot.download(obj, destination=src)
        async with app.media.sem:
            found = await app.shazam.recognize_file(src, workdir)
    except Exception:  # noqa: BLE001
        log.exception("shazam yuklashda xato")
        found = None
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
    if not found:
        await status.edit_text(app.texts.get("shazam_fail", lang))
        return
    await status.delete()
    await app.db.stat_add(m.from_user.id, "shazam", "recognize")
    await run_search(m, app, lang, theme, f"{found['artist']} {found['title']}".strip())


# ================================================================ Audio ostidagi tugmalar
@router.callback_query(F.data == "lk")
async def cb_like(c: CallbackQuery, app: App) -> None:
    a = c.message.audio
    if not a:
        await c.answer()
        return
    added = await app.db.like_toggle(
        c.from_user.id, "a:" + a.file_unique_id, a.title or "", a.performer or "",
        a.duration or 0, a.file_id,
    )
    await c.answer("❤️ Playlistga qo‘shildi" if added else "💔 Playlistdan olib tashlandi")


@router.callback_query(F.data == "fx")
async def cb_fx(c: CallbackQuery) -> None:
    await _safe_edit(c.message, kb=fx_kb(AUDIO_EFFECTS))
    await c.answer()


@router.callback_query(F.data == "fb")
async def cb_fx_back(c: CallbackQuery, app: App, lang: str) -> None:
    await _safe_edit(c.message, kb=audio_kb(app, lang))
    await c.answer()


@router.callback_query(F.data.startswith("fe:"))
async def cb_fx_apply(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    code = c.data.split(":", 1)[1]
    a = c.message.audio
    if code not in AUDIO_EFFECTS or not a:
        await c.answer()
        return
    if a.file_size and a.file_size > TG_DL_LIMIT and not app.cfg.local_api:
        await c.answer("Fayl juda katta", show_alert=True)
        return
    await c.answer("⏳")
    await _safe_edit(c.message, kb=audio_kb(app, lang))
    status = await bot.send_message(c.message.chat.id, app.texts.get("downloading", lang))
    workdir = app.media.new_workdir()
    try:
        src, dst = workdir / "src", workdir / "out.mp3"
        await bot.download(a, destination=src)
        async with app.media.sem:
            ok = await apply_effect(src, dst, code)
        if not ok or not dst.exists():
            raise RuntimeError("ffmpeg ishlamadi")
        label = AUDIO_EFFECTS[code][0]
        await bot.send_audio(
            c.message.chat.id, FSInputFile(dst, filename=f"{a.title or 'audio'} ({code}).mp3"),
            title=f"{a.title or 'Audio'} · {label}"[:128], performer=a.performer,
            duration=a.duration, caption=app.caption("caption_audio", lang),
            reply_markup=audio_kb(app, lang), request_timeout=flows.UPLOAD_TIMEOUT,
        )
    except Exception:  # noqa: BLE001
        log.exception("audio effekt xatosi")
        await bot.send_message(c.message.chat.id, app.texts.get("error", lang))
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            await status.delete()
        except TelegramBadRequest:
            pass


# ================================================================ Video ostidagi tugmalar
@router.callback_query(F.data == "sv")
async def cb_video_save(c: CallbackQuery, app: App) -> None:
    v = c.message.video
    if not v:
        await c.answer("Faqat videoni saqlash mumkin", show_alert=True)
        return
    existing = await app.db.vp_list(c.from_user.id)
    if any(r["file_id"] == v.file_id for r in existing):
        await c.answer("Bu video allaqachon saqlangan")
        return
    title = (c.message.caption or v.file_name or "Video")[:80]
    await app.db.vp_add(c.from_user.id, v.file_id, title)
    await c.answer("✅ Saqlandi")


@router.callback_query(F.data.startswith("ea:"))
async def cb_extract_audio(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    url = await app.db.job_get(c.data.split(":", 1)[1])
    if not url:
        await c.answer("⌛ Havola eskirgan, qayta yuboring", show_alert=True)
        return
    await c.answer("🎧")
    await flows.send_audio_from_url(bot, app, c.message.chat.id, c.from_user.id, url, lang)


# ================================================================ Playlist
async def show_likes(target: Message, app: App, uid: int, lang: str, page: int, edit: bool) -> None:
    rows = await app.db.likes(uid)
    if not rows:
        text, kb = app.texts.get("playlist_empty", lang), None
    else:
        pages = (len(rows) + LIST_PAGE - 1) // LIST_PAGE
        page = max(0, min(page, pages - 1))
        chunk = rows[page * LIST_PAGE:(page + 1) * LIST_PAGE]
        lines = [f"🎧 <b>Playlist</b> ({len(rows)})\n"]
        for i, r in enumerate(chunk, page * LIST_PAGE + 1):
            lines.append(f"{i}. {html.escape((r['performer'] or '')[:40])} — "
                         f"{html.escape((r['title'] or '')[:50])} <b>{fmt_duration(r['duration'])}</b>")
        text = "\n".join(lines)
        kb = list_kb("mp", [r["rid"] for r in chunk], page, len(rows))
    if edit:
        await _safe_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(Command("my"))
async def cmd_my(m: Message, app: App, lang: str) -> None:
    await show_likes(m, app, m.from_user.id, lang, 0, False)


@router.callback_query(F.data.startswith("ml:"))
async def cb_my_page(c: CallbackQuery, app: App, lang: str) -> None:
    await show_likes(c.message, app, c.from_user.id, lang, int(c.data.split(":")[1]), True)
    await c.answer()


@router.callback_query(F.data.startswith("mp:"))
async def cb_my_play(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    row = await app.db.like_get(c.from_user.id, int(c.data.split(":")[1]))
    if not row or not row["file_id"]:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    await bot.send_audio(c.message.chat.id, row["file_id"], caption=app.caption("caption_audio", lang),
                         reply_markup=audio_kb(app, lang))


async def show_vplaylist(target: Message, app: App, uid: int, lang: str, page: int, edit: bool) -> None:
    rows = await app.db.vp_list(uid)
    head = app.texts.get("vplaylist_head", lang)
    kb = None
    text = head
    if rows:
        pages = (len(rows) + LIST_PAGE - 1) // LIST_PAGE
        page = max(0, min(page, pages - 1))
        chunk = rows[page * LIST_PAGE:(page + 1) * LIST_PAGE]
        lines = [head, ""]
        for i, r in enumerate(chunk, page * LIST_PAGE + 1):
            lines.append(f"{i}. {html.escape((r['title'] or 'Video')[:60])}")
        text = "\n".join(lines)
        kb = list_kb("vp", [r["id"] for r in chunk], page, len(rows))
    if edit:
        await _safe_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(Command("playlist"))
async def cmd_playlist(m: Message, app: App, lang: str) -> None:
    await show_vplaylist(m, app, m.from_user.id, lang, 0, False)


@router.callback_query(F.data.startswith("vl:"))
async def cb_vp_page(c: CallbackQuery, app: App, lang: str) -> None:
    await show_vplaylist(c.message, app, c.from_user.id, lang, int(c.data.split(":")[1]), True)
    await c.answer()


@router.callback_query(F.data.startswith("vp:"))
async def cb_vp_play(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    pid = int(c.data.split(":")[1])
    row = await app.db.vp_get(pid, c.from_user.id)
    if not row:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 O‘chirish", callback_data=f"vd:{pid}")
    kb.row(add_group_btn(app, lang))
    try:
        await bot.send_video(c.message.chat.id, row["file_id"],
                             caption=app.caption("caption_video", lang), reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await app.db.vp_del(pid, c.from_user.id)
        await bot.send_message(c.message.chat.id, app.texts.get("error", lang))


@router.callback_query(F.data.startswith("vd:"))
async def cb_vp_del(c: CallbackQuery, app: App) -> None:
    await app.db.vp_del(int(c.data.split(":")[1]), c.from_user.id)
    await c.answer("🗑 Playlistdan o‘chirildi")
    try:
        await c.message.delete()
    except TelegramBadRequest:
        pass


# ================================================================ TOP / NEW
CHART_TITLES = {"t": "TOP Popular Songs", "n": "NEW Popular Songs"}


async def _chart_items(app: App, kind: str, cc: str) -> list[dict]:
    return await (app.shazam.top(cc) if kind == "t" else app.shazam.new(cc))


async def show_chart(target: Message, app: App, lang: str, kind: str, cc: str, page: int, edit: bool) -> None:
    items = await _chart_items(app, kind, cc)
    if not items:
        text = app.texts.get("not_found", lang)
        if edit:
            await _safe_edit(target, text)
        else:
            await target.answer(text)
        return
    kb = chart_view(kind, cc, items, page)
    text = CHART_TITLES[kind]
    if edit:
        await _safe_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


def _default_cc(region: str | None) -> str:
    return "UZ"


@router.message(Command("top"))
async def cmd_top(m: Message, app: App, lang: str, region: str | None) -> None:
    await show_chart(m, app, lang, "t", _default_cc(region), 0, False)


@router.message(Command("new"))
async def cmd_new(m: Message, app: App, lang: str, region: str | None) -> None:
    await show_chart(m, app, lang, "n", _default_cc(region), 0, False)


@router.callback_query(F.data.startswith("ch:"))
async def cb_chart(c: CallbackQuery, app: App, lang: str) -> None:
    _k, kind, cc, page = c.data.split(":")
    await show_chart(c.message, app, lang, kind, cc, int(page), True)
    await c.answer()


@router.callback_query(F.data.startswith("cs:"))
async def cb_chart_pick(c: CallbackQuery, app: App, bot: Bot, lang: str) -> None:
    _k, kind, cc, idx = c.data.split(":")
    items = await _chart_items(app, kind, cc)
    if int(idx) >= len(items):
        await c.answer("⌛ Ro‘yxat yangilandi", show_alert=True)
        return
    item = items[int(idx)]
    await c.answer()
    vid = item.get("vid")
    if not vid:
        try:
            found = await app.media.search(item["query"], 3)
        except MediaError as e:
            await flows.report_error(bot, app, c.message.chat.id, lang, e, "youtube", c.from_user.id)
            return
        if not found:
            await bot.send_message(c.message.chat.id, app.texts.get("not_found", lang))
            return
        vid = found[0].id
    await flows.send_youtube_audio(bot, app, c.message.chat.id, c.from_user.id, vid, lang)


# ================================================================ Sozlamalar
async def _settings_text_kb(app: App, uid: int, lang: str):
    row = await app.db.get_user(uid)
    return (
        app.texts.get("settings_title", lang),
        settings_kb(app, lang, row["region"], row["theme"]),
    )


@router.message(Command("settings"))
async def cmd_settings(m: Message, app: App, lang: str) -> None:
    text, kb = await _settings_text_kb(app, m.from_user.id, lang)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("st:"))
async def cb_settings(c: CallbackQuery, app: App, lang: str, theme: str) -> None:
    action = c.data.split(":")[1]
    if action == "lang":
        await _safe_edit(c.message, "🌐", lang_kb())
    elif action == "region":
        await _safe_edit(c.message, "🏙 Viloyatni tanlang:", region_kb())
    elif action == "theme":
        await _safe_edit(c.message, "🎨 Mavzuni tanlang:", theme_kb(theme))
    elif action == "back":
        text, kb = await _settings_text_kb(app, c.from_user.id, lang)
        await _safe_edit(c.message, text, kb)
    elif action == "close":
        try:
            await c.message.delete()
        except TelegramBadRequest:
            pass
    await c.answer()


@router.callback_query(F.data.startswith("sl:"))
async def cb_set_lang(c: CallbackQuery, app: App) -> None:
    code = c.data.split(":")[1]
    if code in LANGS:
        await app.db.set_user_field(c.from_user.id, "lang", code)
    text, kb = await _settings_text_kb(app, c.from_user.id, code if code in LANGS else "uz")
    await _safe_edit(c.message, text, kb)
    await c.answer("✅")


@router.callback_query(F.data.startswith("sr:"))
async def cb_set_region(c: CallbackQuery, app: App, lang: str) -> None:
    idx = int(c.data.split(":")[1])
    if 0 <= idx < len(REGIONS):
        await app.db.set_user_field(c.from_user.id, "region", REGIONS[idx])
        await _safe_edit(c.message, app.texts.get("region_set", lang, region=html.escape(REGIONS[idx])))
    await c.answer("✅")


@router.callback_query(F.data.startswith("sth:"))
async def cb_set_theme(c: CallbackQuery, app: App, lang: str) -> None:
    code = c.data.split(":")[1]
    if code in THEMES:
        await app.db.set_user_field(c.from_user.id, "theme", code)
    text, kb = await _settings_text_kb(app, c.from_user.id, lang)
    await _safe_edit(c.message, text, kb)
    await c.answer("✅")
