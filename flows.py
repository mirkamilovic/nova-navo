"""Yuborish oqimlari: video/rasm/audio yuklab foydalanuvchiga jo'natish."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile, InputMediaPhoto, InputMediaVideo, Message, ReplyParameters,
)

from .app import App
from .keyboards import audio_kb, video_kb
from .services.media import MediaError, MediaResult, canonical, detect_platform

log = logging.getLogger(__name__)

UPLOAD_TIMEOUT = 900


def _reply(reply_to: int | None) -> ReplyParameters | None:
    return ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None


async def _caption(app: App, key: str, lang: str) -> str:
    if (await app.db.get_setting("caption_on", "1")) != "1":
        return ""
    return app.caption(key, lang)


async def report_error(bot: Bot, app: App, chat_id: int, lang: str, err: MediaError,
                       platform: str | None, uid: int) -> None:
    await app.db.stat_add(uid, platform or "other", "error", ok=False)
    if err.kind == "toobig":
        text = app.texts.get("too_big", lang, mb=app.cfg.upload_limit_mb)
    else:
        text = app.texts.get("error", lang)
    await bot.send_message(chat_id, text)
    if err.kind == "login" or (platform in ("instagram", "youtube") and err.kind == "failed"):
        await app.notify_admins(
            bot, f"cookie:{platform}",
            f"⚠️ <b>{platform}</b> yuklashda xatolik. Cookies eskirgan yoki yo'q bo'lishi mumkin.\n"
            f"Owner panel → 🍪 Cookies orqali yangilang.\n\n<code>{err.detail[:300]}</code>"
            .replace("<code></code>", ""),
        )


# ---------------------------------------------------------------- AUDIO
async def send_audio_result(bot: Bot, app: App, chat_id: int, res: MediaResult, lang: str,
                            reply_to: int | None = None) -> Message:
    f = res.files[0]
    msg = await bot.send_audio(
        chat_id,
        audio=FSInputFile(f.path, filename=f"{res.performer} - {res.title}.mp3"[:100]),
        caption=await _caption(app, "caption_audio", lang),
        duration=res.duration or f.duration,
        performer=res.performer or None,
        title=res.title or None,
        thumbnail=FSInputFile(f.thumb) if f.thumb else None,
        reply_markup=audio_kb(app, lang),
        reply_parameters=_reply(reply_to),
        request_timeout=UPLOAD_TIMEOUT,
    )
    if msg.audio:
        await app.db.cache_put(res.key, "audio", msg.audio.file_id, res.title, res.performer,
                               res.duration or 0)
    return msg


async def _send_cached_audio(bot: Bot, app: App, chat_id: int, key: str, lang: str,
                             reply_to: int | None) -> bool:
    row = await app.db.cache_get(key)
    if not row or row["kind"] != "audio":
        return False
    try:
        await bot.send_audio(
            chat_id, audio=row["file_id"],
            caption=await _caption(app, "caption_audio", lang),
            reply_markup=audio_kb(app, lang), reply_parameters=_reply(reply_to),
        )
        return True
    except TelegramBadRequest:
        await app.db.cache_drop(key)
        return False


async def send_youtube_audio(bot: Bot, app: App, chat_id: int, uid: int, video_id: str,
                             lang: str, reply_to: int | None = None) -> bool:
    key = f"a:youtube:{video_id}"
    if await _send_cached_audio(bot, app, chat_id, key, lang, reply_to):
        await app.db.stat_add(uid, "youtube", "audio")
        return True
    if key in app.inflight:
        await bot.send_message(chat_id, app.texts.get("busy", lang))
        return False
    app.inflight.add(key)
    status = await bot.send_message(chat_id, app.texts.get("downloading", lang))
    res: MediaResult | None = None
    try:
        await bot.send_chat_action(chat_id, "upload_voice")
        res = await app.media.fetch_youtube_audio(video_id)
        await send_audio_result(bot, app, chat_id, res, lang, reply_to)
        await app.db.stat_add(uid, "youtube", "audio")
        return True
    except MediaError as e:
        await report_error(bot, app, chat_id, lang, e, "youtube", uid)
    except Exception:  # noqa: BLE001
        log.exception("audio yuborishda xato")
        await bot.send_message(chat_id, app.texts.get("error", lang))
    finally:
        app.inflight.discard(key)
        if res:
            res.cleanup()
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass
    return False


async def send_audio_from_url(bot: Bot, app: App, chat_id: int, uid: int, url: str, lang: str,
                              reply_to: int | None = None) -> bool:
    """Videodan (havola orqali) audio ajratib yuboradi."""
    platform = detect_platform(url) or "other"
    key = f"a:{canonical(url)}"
    if await _send_cached_audio(bot, app, chat_id, key, lang, reply_to):
        return True
    if key in app.inflight:
        await bot.send_message(chat_id, app.texts.get("busy", lang))
        return False
    app.inflight.add(key)
    status = await bot.send_message(chat_id, app.texts.get("downloading", lang))
    res: MediaResult | None = None
    try:
        await bot.send_chat_action(chat_id, "upload_voice")
        res = await app.media.fetch_audio(url, key=key)
        await send_audio_result(bot, app, chat_id, res, lang, reply_to)
        await app.db.stat_add(uid, platform, "audio")
        return True
    except MediaError as e:
        await report_error(bot, app, chat_id, lang, e, platform, uid)
    except Exception:  # noqa: BLE001
        log.exception("audio (url) yuborishda xato")
        await bot.send_message(chat_id, app.texts.get("error", lang))
    finally:
        app.inflight.discard(key)
        if res:
            res.cleanup()
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass
    return False


# ---------------------------------------------------------------- VIDEO / RASM
async def _send_single(bot: Bot, app: App, chat_id: int, kind: str, media, lang: str,
                       reply_to: int | None, kb, caption: str, meta: dict | None = None) -> Message:
    meta = meta or {}
    common = dict(caption=caption, reply_markup=kb, reply_parameters=_reply(reply_to),
                  request_timeout=UPLOAD_TIMEOUT)
    if kind == "photo":
        try:
            return await bot.send_photo(chat_id, photo=media, **common)
        except TelegramBadRequest:
            if isinstance(media, str):
                raise
            return await bot.send_document(chat_id, document=media, **common)
    return await bot.send_video(
        chat_id, video=media, supports_streaming=True,
        width=meta.get("width"), height=meta.get("height"), duration=meta.get("duration"),
        **common,
    )


async def send_video_from_url(bot: Bot, app: App, chat_id: int, uid: int, url: str, lang: str,
                              reply_to: int | None = None) -> bool:
    platform = detect_platform(url) or "other"
    key = f"v:{canonical(url)}"
    caption = await _caption(app, "caption_video", lang)

    # 1) keshdan
    row = await app.db.cache_get(key)
    if row and row["kind"] in ("video", "photo"):
        try:
            jid = await app.db.job_save(url)
            await _send_single(bot, app, chat_id, row["kind"], row["file_id"], lang, reply_to,
                               video_kb(app, lang, jid, extract=row["kind"] == "video"), caption)
            await app.db.stat_add(uid, platform, "video")
            return True
        except TelegramBadRequest:
            await app.db.cache_drop(key)

    # 2) yangi yuklash
    if key in app.inflight:
        await bot.send_message(chat_id, app.texts.get("busy", lang))
        return False
    app.inflight.add(key)
    status = await bot.send_message(chat_id, app.texts.get("downloading", lang))
    res: MediaResult | None = None
    try:
        await bot.send_chat_action(chat_id, "upload_video")
        res = await app.media.fetch_video(url)
        files = res.files
        if len(files) == 1:
            f = files[0]
            jid = await app.db.job_save(url)
            msg = await _send_single(
                bot, app, chat_id, f.kind, FSInputFile(f.path), lang, reply_to,
                video_kb(app, lang, jid, extract=f.kind == "video"), caption,
                {"width": f.width, "height": f.height, "duration": f.duration},
            )
            fid = (msg.video.file_id if msg.video else
                   msg.photo[-1].file_id if msg.photo else
                   msg.document.file_id if msg.document else None)
            if fid:
                await app.db.cache_put(key, "photo" if f.kind == "photo" else "video", fid,
                                       res.title, res.performer, res.duration)
        else:
            for i in range(0, len(files), 10):
                group = []
                for j, f in enumerate(files[i:i + 10]):
                    cap = caption if (i == 0 and j == 0) else None
                    inp = FSInputFile(f.path)
                    if f.kind == "photo":
                        group.append(InputMediaPhoto(media=inp, caption=cap))
                    else:
                        group.append(InputMediaVideo(media=inp, caption=cap, supports_streaming=True,
                                                     width=f.width, height=f.height, duration=f.duration))
                await bot.send_media_group(chat_id, media=group, reply_parameters=_reply(reply_to),
                                           request_timeout=UPLOAD_TIMEOUT)
        await app.db.stat_add(uid, platform, "video")
        return True
    except MediaError as e:
        await report_error(bot, app, chat_id, lang, e, platform, uid)
    except TelegramBadRequest as e:
        log.warning("yuborishda Telegram xatosi: %s", e)
        await report_error(bot, app, chat_id, lang, MediaError("failed", str(e)), platform, uid)
    except Exception:  # noqa: BLE001
        log.exception("video yuborishda xato")
        await bot.send_message(chat_id, app.texts.get("error", lang))
    finally:
        app.inflight.discard(key)
        if res:
            res.cleanup()
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass
    return False
