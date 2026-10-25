"""Owner / admin paneli — barcha sozlamalar bot ichidan."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LinkPreviewOptions, CallbackQuery, Message
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..app import App
from ..services.media import COOKIE_PLATFORMS
from ..texts import EDITABLE, LANGS, _Safe

log = logging.getLogger(__name__)
router = Router(name="owner")


class AdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, app: App) -> bool:
        return bool(event.from_user and app.is_admin(event.from_user.id))


router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class S(StatesGroup):
    channel = State()
    channel_link = State()
    cookie = State()
    text = State()
    image = State()
    broadcast = State()
    value = State()
    admin = State()


# ---------------------------------------------------------------- yordamchilar
def kb_back(target: str = "ad:main") -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(Btn(text="⬅️ Ortga", callback_data=target))
    return b


async def edit(c: CallbackQuery, text: str, kb: InlineKeyboardBuilder | None = None) -> None:
    try:
        await c.message.edit_text(text, reply_markup=kb.as_markup() if kb else None,
                                  link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


def main_kb(app: App, uid: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(Btn(text="📊 Statistika", callback_data="ad:stats"),
          Btn(text="📢 Majburiy obuna", callback_data="ad:subs"))
    b.row(Btn(text="🍪 Cookies", callback_data="ad:ck"),
          Btn(text="✏️ Matnlar", callback_data="ad:tx"))
    b.row(Btn(text="🖼 Rasmlar", callback_data="ad:img"),
          Btn(text="📨 Xabar yuborish", callback_data="ad:bc"))
    b.row(Btn(text="⚙️ Sozlamalar", callback_data="ad:set"))
    if app.is_owner(uid):
        b.row(Btn(text="👑 Adminlar", callback_data="ad:adm"))
    b.row(Btn(text="🔄 yt-dlp yangilash", callback_data="ad:upd"))
    b.row(Btn(text="❌ Yopish", callback_data="ad:close"))
    return b


PANEL_TEXT = "🛠 <b>Owner paneli</b>\n\nKerakli bo'limni tanlang:"


@router.message(Command("admin", "panel"))
async def cmd_admin(m: Message, app: App, state: FSMContext) -> None:
    await state.clear()
    await m.answer(PANEL_TEXT, reply_markup=main_kb(app, m.from_user.id).as_markup())


@router.callback_query(F.data == "ad:main")
async def cb_main(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await edit(c, PANEL_TEXT, main_kb(app, c.from_user.id))
    await c.answer()


@router.callback_query(F.data == "ad:close")
async def cb_close(c: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await c.message.delete()
    except TelegramBadRequest:
        pass
    await c.answer()


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer("Bekor qilindi. /admin")


# ---------------------------------------------------------------- statistika
@router.callback_query(F.data == "ad:stats")
async def cb_stats(c: CallbackQuery, app: App) -> None:
    s = await app.db.stats_summary()
    plat = "\n".join(f"  • {p}: <b>{n}</b>" for p, n in s["platforms"]) or "  —"
    reg = "\n".join(f"  • {r}: <b>{n}</b>" for r, n in s["regions"]) or "  —"
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami: <b>{s['total']}</b> (faol: <b>{s['active']}</b>)\n"
        f"🆕 Bugun: <b>{s['new_day']}</b> · 7 kun: <b>{s['new_week']}</b>\n"
        f"🟢 24 soatda faol: <b>{s['online_day']}</b>\n\n"
        f"📥 Yuklashlar: bugun <b>{s['dl_day']}</b> · jami <b>{s['dl_total']}</b>\n"
        f"⚠️ Bugungi xatolar: <b>{s['fail_day']}</b>\n\n"
        f"🌐 Platformalar (7 kun):\n{plat}\n\n🏙 Viloyatlar (top 5):\n{reg}"
    )
    b = InlineKeyboardBuilder()
    b.row(Btn(text="🔃 Yangilash", callback_data="ad:stats"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, text, b)
    await c.answer()


# ---------------------------------------------------------------- majburiy obuna
async def subs_view(c: CallbackQuery | Message, app: App) -> None:
    chans = await app.db.channels()
    on = await app.subs.enabled()
    lines = [f"📢 <b>Majburiy obuna</b>: {'✅ yoqilgan' if on else '⛔️ o‘chirilgan'}\n"]
    b = InlineKeyboardBuilder()
    for ch in chans:
        warn = " ⚠️" if ch["chat_id"] in app.subs.broken else ""
        lines.append(f"• {html.escape(ch['title'])}{warn}\n  <code>{ch['chat_id']}</code>")
        b.row(Btn(text=f"🗑 {ch['title'][:30]}", callback_data=f"ad:sd:{ch['id']}"))
    if not chans:
        lines.append("Hozircha kanal qo'shilmagan.")
    if app.subs.broken:
        lines.append("\n⚠️ — bot kanalda admin emas yoki kanal topilmadi (obuna tekshirilmaydi).")
    b.row(Btn(text="➕ Kanal qo'shish", callback_data="ad:sa"))
    b.row(Btn(text="⛔️ O‘chirish" if on else "✅ Yoqish", callback_data="ad:sf"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    text = "\n".join(lines)
    if isinstance(c, CallbackQuery):
        await edit(c, text, b)
    else:
        await c.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "ad:subs")
async def cb_subs(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await subs_view(c, app)
    await c.answer()


@router.callback_query(F.data == "ad:sf")
async def cb_sub_toggle(c: CallbackQuery, app: App) -> None:
    await app.db.set_setting("force_sub", "0" if await app.subs.enabled() else "1")
    await subs_view(c, app)
    await c.answer("OK")


@router.callback_query(F.data.startswith("ad:sd:"))
async def cb_sub_del(c: CallbackQuery, app: App) -> None:
    await app.db.del_channel(int(c.data.split(":")[2]))
    await subs_view(c, app)
    await c.answer("🗑 O‘chirildi")


@router.callback_query(F.data == "ad:sa")
async def cb_sub_add(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(S.channel)
    b = kb_back("ad:subs")
    await edit(
        c,
        "➕ <b>Kanal qo'shish</b>\n\n1) Botni kanalga <b>admin</b> qiling.\n"
        "2) Kanaldan istalgan xabarni shu yerga <b>forward</b> qiling, yoki "
        "<code>@username</code> / <code>-100...</code> ID yuboring.\n\n/cancel — bekor qilish",
        b,
    )
    await c.answer()


@router.message(S.channel)
async def st_channel(m: Message, app: App, bot: Bot, state: FSMContext) -> None:
    chat = None
    try:
        origin = getattr(m, "forward_origin", None)
        if origin is not None and getattr(origin, "chat", None) is not None:
            chat = await bot.get_chat(origin.chat.id)
        elif m.text:
            raw = m.text.strip()
            ref = raw if raw.startswith("@") or raw.lstrip("-").isdigit() else "@" + raw.split("/")[-1]
            chat = await bot.get_chat(int(ref) if ref.lstrip("-").isdigit() else ref)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ Kanal topilmadi: <code>{html.escape(str(e)[:150])}</code>")
        return
    if chat is None:
        await m.answer("❌ Forward qiling yoki @username / ID yuboring.")
        return

    admin_ok = False
    try:
        me = await bot.get_chat_member(chat.id, (await bot.me()).id)
        admin_ok = me.status in ("administrator", "creator")
    except Exception:  # noqa: BLE001
        pass

    url = f"https://t.me/{chat.username}" if chat.username else ""
    if not url:
        try:
            url = chat.invite_link or (await bot.create_chat_invite_link(chat.id)).invite_link
        except Exception:  # noqa: BLE001
            url = ""
    if not url:
        await state.set_state(S.channel_link)
        await state.update_data(chat_id=chat.id, title=chat.title or str(chat.id))
        await m.answer("🔗 Kanal yopiq. Taklif havolasini (<code>https://t.me/+...</code>) yuboring.")
        return
    await app.db.add_channel(chat.id, chat.title or str(chat.id), url)
    await state.clear()
    warn = "" if admin_ok else "\n\n⚠️ Bot bu kanalda admin emas — obuna tekshirilmaydi. Botni admin qiling."
    await m.answer(f"✅ Qo'shildi: <b>{html.escape(chat.title or '')}</b>{warn}\n\n/admin")


@router.message(S.channel_link)
async def st_channel_link(m: Message, app: App, state: FSMContext) -> None:
    link = (m.text or "").strip()
    if not link.startswith("https://t.me/"):
        await m.answer("❌ Havola <code>https://t.me/</code> bilan boshlanishi kerak.")
        return
    d = await state.get_data()
    await app.db.add_channel(d["chat_id"], d["title"], link)
    await state.clear()
    await m.answer("✅ Kanal qo'shildi. /admin")


# ---------------------------------------------------------------- cookies
async def cookies_view(c: CallbackQuery, app: App) -> None:
    st = app.media.cookie_status()
    b = InlineKeyboardBuilder()
    lines = ["🍪 <b>Cookies</b>\n"]
    for p in COOKIE_PLATFORMS:
        ok = st.get(p)
        lines.append(f"{'✅' if ok else '❌'} {p}")
        row = [Btn(text=f"📤 {p}", callback_data=f"ad:cp:{p}")]
        if ok:
            row.append(Btn(text="🗑", callback_data=f"ad:cd:{p}"))
        b.row(*row)
    lines.append(
        "\nℹ️ Brauzerda akkauntga kiring va <b>cookies.txt</b> (Netscape format) eksport qiling "
        "(masalan «Get cookies.txt LOCALLY» kengaytmasi). Instagram uchun <b>asosiy emas, alohida "
        "akkaunt</b> ishlating. Fayl yoki matnni tugma bosgandan so'ng yuboring."
    )
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, "\n".join(lines), b)


@router.callback_query(F.data == "ad:ck")
async def cb_cookies(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await cookies_view(c, app)
    await c.answer()


@router.callback_query(F.data.startswith("ad:cd:"))
async def cb_cookie_del(c: CallbackQuery, app: App) -> None:
    p = c.data.split(":")[2]
    if p in COOKIE_PLATFORMS:
        app.media.cookie_path(p).unlink(missing_ok=True)
    await cookies_view(c, app)
    await c.answer("🗑")


@router.callback_query(F.data.startswith("ad:cp:"))
async def cb_cookie_ask(c: CallbackQuery, state: FSMContext) -> None:
    p = c.data.split(":")[2]
    if p not in COOKIE_PLATFORMS:
        await c.answer()
        return
    await state.set_state(S.cookie)
    await state.update_data(platform=p)
    await edit(c, f"📤 <b>{p}</b> uchun <b>cookies.txt</b> faylini yuboring (yoki matnini yopishtiring).\n\n/cancel",
               kb_back("ad:ck"))
    await c.answer()


def _valid_cookies(raw: str) -> bool:
    good = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if len(line.split("\t")) >= 7:
            good += 1
    return good >= 1


@router.message(S.cookie)
async def st_cookie(m: Message, app: App, bot: Bot, state: FSMContext) -> None:
    d = await state.get_data()
    platform = d.get("platform")
    raw = ""
    if m.document:
        if (m.document.file_size or 0) > 5 * 1024 * 1024:
            await m.answer("❌ Fayl juda katta.")
            return
        tmp = app.cfg.tmp_dir / f"ck_{m.from_user.id}.txt"
        await bot.download(m.document, destination=tmp)
        raw = tmp.read_text(encoding="utf-8", errors="ignore")
        tmp.unlink(missing_ok=True)
    elif m.text:
        raw = m.text
    if not _valid_cookies(raw):
        await m.answer("❌ Bu Netscape formatidagi cookies.txt ga o'xshamaydi (tab bilan ajratilgan 7 ustun kerak).")
        return
    if "# Netscape" not in raw[:200]:
        raw = "# Netscape HTTP Cookie File\n" + raw
    path: Path = app.media.cookie_path(platform)
    path.write_text(raw.replace("\r\n", "\n"), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    await state.clear()
    try:  # xavfsizlik uchun cookies yuborilgan xabarni o'chiramiz
        await m.delete()
    except TelegramBadRequest:
        pass
    await m.answer(f"✅ <b>{platform}</b> cookies saqlandi. /admin")


# ---------------------------------------------------------------- matnlar
@router.callback_query(F.data == "ad:tx")
async def cb_texts(c: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    b = InlineKeyboardBuilder()
    for code, name in LANGS.items():
        b.row(Btn(text=name, callback_data=f"ad:tl:{code}"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, "✏️ <b>Matnlar</b>\n\nQaysi til matnlarini tahrirlaysiz?", b)
    await c.answer()


@router.callback_query(F.data.startswith("ad:tl:"))
async def cb_text_list(c: CallbackQuery, app: App) -> None:
    lang = c.data.split(":")[2]
    b = InlineKeyboardBuilder()
    for key, (desc, _v) in EDITABLE.items():
        mark = "✏️ " if app.texts.is_custom(key, lang) else ""
        b.row(Btn(text=f"{mark}{desc}", callback_data=f"ad:te:{lang}:{key}"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:tx"))
    await edit(c, f"✏️ <b>Matnlar — {LANGS[lang]}</b>\n\n✏️ belgisi — o'zgartirilgan matn.", b)
    await c.answer()


async def _show_text(c: CallbackQuery, app: App, lang: str, key: str) -> None:
    desc, variables = EDITABLE[key]
    raw = app.texts.raw(key, lang)
    b = InlineKeyboardBuilder()
    b.row(Btn(text="✏️ O‘zgartirish", callback_data=f"ad:tw:{lang}:{key}"))
    if app.texts.is_custom(key, lang):
        b.row(Btn(text="♻️ Standartga qaytarish", callback_data=f"ad:tr:{lang}:{key}"))
    b.row(Btn(text="⬅️ Ortga", callback_data=f"ad:tl:{lang}"))
    var = f"\nO'zgaruvchilar: <code>{html.escape(variables)}</code>" if variables else ""
    await edit(c, f"<b>{desc}</b> ({lang}){var}\n\n<pre>{html.escape(raw)}</pre>", b)


@router.callback_query(F.data.startswith("ad:te:"))
async def cb_text_show(c: CallbackQuery, app: App) -> None:
    _a, _t, lang, key = c.data.split(":")
    await _show_text(c, app, lang, key)
    await c.answer()


@router.callback_query(F.data.startswith("ad:tr:"))
async def cb_text_reset(c: CallbackQuery, app: App) -> None:
    _a, _t, lang, key = c.data.split(":")
    await app.texts.reset(key, lang)
    await _show_text(c, app, lang, key)
    await c.answer("♻️ Standartga qaytarildi")


@router.callback_query(F.data.startswith("ad:tw:"))
async def cb_text_write(c: CallbackQuery, state: FSMContext) -> None:
    _a, _t, lang, key = c.data.split(":")
    await state.set_state(S.text)
    await state.update_data(lang=lang, key=key)
    desc, variables = EDITABLE[key]
    extra = (
        "\n\n💎 <b>Premium emojilar</b>: matnni premium emojilar bilan yozib shu yerga yuboring — "
        "ular avtomatik saqlanadi."
        if not key.startswith("btn_") else "\n\nTugma matni oddiy matn bo'lishi kerak."
    )
    await edit(c, f"✏️ <b>{desc}</b> ({lang}) uchun yangi matnni yuboring.\n"
                  f"O'zgaruvchilar: <code>{html.escape(variables or '—')}</code>{extra}\n\n/cancel",
               kb_back(f"ad:te:{lang}:{key}"))
    await c.answer()


@router.message(S.text, F.text)
async def st_text(m: Message, app: App, state: FSMContext) -> None:
    d = await state.get_data()
    key, lang = d["key"], d["lang"]
    value = m.text if key.startswith("btn_") else m.html_text
    sample = {"name": "Ism", "bot": app.bot_username, "mb": app.cfg.upload_limit_mb, "region": "Farg'ona"}
    try:  # saqlashdan oldin ko'rib chiqamiz (noto'g'ri HTML bo'lsa saqlanmaydi)
        if key.startswith("btn_"):
            await m.answer("👁 " + html.escape(value))
        else:
            try:
                preview = value.format_map(_Safe(sample))
            except (ValueError, IndexError):
                preview = value
            await m.answer("👁 <b>Ko'rinishi:</b>\n\n" + preview)
    except TelegramBadRequest as e:
        await m.answer(f"❌ Matn Telegramga yaramadi: <code>{html.escape(str(e)[:150])}</code>\nQayta yuboring.")
        return
    await app.texts.set(key, lang, value)
    await state.clear()
    await m.answer("✅ Saqlandi. /admin")


# ---------------------------------------------------------------- rasmlar
IMAGES = {"start": ("img_start", "/start xabari rasmi")}


@router.callback_query(F.data == "ad:img")
async def cb_images(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    b = InlineKeyboardBuilder()
    lines = ["🖼 <b>Rasmlar</b>\n"]
    for code, (skey, desc) in IMAGES.items():
        has = bool(await app.db.get_setting(skey, ""))
        lines.append(f"{'✅' if has else '❌'} {desc}")
        row = [Btn(text=f"📤 {desc}", callback_data=f"ad:iw:{code}")]
        if has:
            row.append(Btn(text="🗑", callback_data=f"ad:id:{code}"))
        b.row(*row)
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, "\n".join(lines), b)
    await c.answer()


@router.callback_query(F.data.startswith("ad:id:"))
async def cb_image_del(c: CallbackQuery, app: App, state: FSMContext) -> None:
    code = c.data.split(":")[2]
    if code in IMAGES:
        await app.db.del_setting(IMAGES[code][0])
    await cb_images(c, app, state)


@router.callback_query(F.data.startswith("ad:iw:"))
async def cb_image_ask(c: CallbackQuery, state: FSMContext) -> None:
    code = c.data.split(":")[2]
    await state.set_state(S.image)
    await state.update_data(code=code)
    await edit(c, "📤 Rasmni yuboring (fayl emas, oddiy rasm sifatida).\n\n/cancel", kb_back("ad:img"))
    await c.answer()


@router.message(S.image, F.photo)
async def st_image(m: Message, app: App, state: FSMContext) -> None:
    d = await state.get_data()
    await app.db.set_setting(IMAGES[d["code"]][0], m.photo[-1].file_id)
    await state.clear()
    await m.answer("✅ Rasm saqlandi. /admin")


# ---------------------------------------------------------------- ommaviy xabar
@router.callback_query(F.data == "ad:bc")
async def cb_bc(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(S.broadcast)
    await edit(c, "📨 Hammaga yuboriladigan xabarni yuboring (matn, rasm, video — premium emoji ham bo'ladi).\n\n/cancel",
               kb_back())
    await c.answer()


@router.message(S.broadcast)
async def st_bc(m: Message, app: App, state: FSMContext) -> None:
    n = len(await app.db.user_ids())
    await state.update_data(chat_id=m.chat.id, msg_id=m.message_id)
    b = InlineKeyboardBuilder()
    b.row(Btn(text=f"✅ {n} ta foydalanuvchiga yuborish", callback_data="ad:bs"))
    b.row(Btn(text="❌ Bekor qilish", callback_data="ad:main"))
    await m.reply("Yuqoridagi xabar yuboriladi. Tasdiqlaysizmi?", reply_markup=b.as_markup())


@router.callback_query(F.data == "ad:bs")
async def cb_bc_send(c: CallbackQuery, app: App, bot: Bot, state: FSMContext) -> None:
    d = await state.get_data()
    await state.clear()
    if "msg_id" not in d:
        await c.answer("Xabar topilmadi", show_alert=True)
        return
    await c.answer("🚀 Boshlandi")
    await edit(c, "🚀 Yuborish boshlandi...")
    asyncio.create_task(_broadcast(bot, app, c.message, d["chat_id"], d["msg_id"]))


async def _broadcast(bot: Bot, app: App, status: Message, from_chat: int, msg_id: int) -> None:
    ids = await app.db.user_ids()
    ok = fail = 0
    for i, uid in enumerate(ids, 1):
        for _attempt in range(3):
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                await app.db.set_user_field(uid, "active", 0)
                fail += 1
                break
            except Exception:  # noqa: BLE001
                fail += 1
                break
        await asyncio.sleep(0.04)   # ~25 xabar/soniya
        if i % 300 == 0:
            try:
                await status.edit_text(f"🚀 Yuborilmoqda... {i}/{len(ids)}")
            except Exception:  # noqa: BLE001
                pass
    try:
        await status.edit_text(f"✅ <b>Yuborish tugadi</b>\n\nYetkazildi: <b>{ok}</b>\nYetkazilmadi: <b>{fail}</b>")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- umumiy sozlamalar
async def settings_view(c: CallbackQuery, app: App) -> None:
    g = app.db.get_setting
    force = await g("force_sub", "1") == "1"
    cap = await g("caption_on", "1") == "1"
    cobalt = await g("cobalt_url", "")
    items = await g("max_playlist_items", "10")
    b = InlineKeyboardBuilder()
    b.row(Btn(text=f"Majburiy obuna: {'✅' if force else '⛔️'}", callback_data="ad:tg:force_sub"))
    b.row(Btn(text=f"Caption reklamasi: {'✅' if cap else '⛔️'}", callback_data="ad:tg:caption_on"))
    b.row(Btn(text=f"Albom (post) limiti: {items}", callback_data="ad:sv:max_playlist_items"))
    b.row(Btn(text=f"Zaxira yuklovchi (cobalt): {'✅' if cobalt else '—'}", callback_data="ad:sv:cobalt_url"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    text = (
        "⚙️ <b>Sozlamalar</b>\n\n"
        "• <b>Caption reklamasi</b> — video/audio ostidagi @bot yozuvi.\n"
        "• <b>Albom limiti</b> — bitta postdan eng ko'pi bilan nechta rasm/video.\n"
        "• <b>Cobalt</b> — yt-dlp ishlamasa zaxira (o'z cobalt serveringiz API manzili)."
    )
    await edit(c, text, b)


@router.callback_query(F.data == "ad:set")
async def cb_settings(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await settings_view(c, app)
    await c.answer()


@router.callback_query(F.data.startswith("ad:tg:"))
async def cb_toggle(c: CallbackQuery, app: App) -> None:
    key = c.data.split(":")[2]
    if key in ("force_sub", "caption_on"):
        cur = await app.db.get_setting(key, "1")
        await app.db.set_setting(key, "0" if cur == "1" else "1")
    await settings_view(c, app)
    await c.answer("OK")


@router.callback_query(F.data.startswith("ad:sv:"))
async def cb_setval(c: CallbackQuery, state: FSMContext) -> None:
    key = c.data.split(":")[2]
    await state.set_state(S.value)
    await state.update_data(key=key)
    hint = {
        "max_playlist_items": "Son yuboring (1–10).",
        "cobalt_url": "Cobalt API manzilini yuboring (masalan <code>https://cobalt.example.com/</code>) yoki <code>-</code> (o'chirish).",
    }.get(key, "Qiymatni yuboring.")
    await edit(c, f"✏️ {hint}\n\n/cancel", kb_back("ad:set"))
    await c.answer()


@router.message(S.value, F.text)
async def st_value(m: Message, app: App, state: FSMContext) -> None:
    d = await state.get_data()
    key, val = d["key"], m.text.strip()
    if key == "max_playlist_items":
        if not val.isdigit() or not 1 <= int(val) <= 10:
            await m.answer("❌ 1 dan 10 gacha son yuboring.")
            return
    elif key == "cobalt_url":
        if val == "-":
            val = ""
        elif not val.startswith("http"):
            await m.answer("❌ Manzil http(s) bilan boshlanishi kerak.")
            return
    await app.db.set_setting(key, val)
    await state.clear()
    await m.answer("✅ Saqlandi. /admin")


# ---------------------------------------------------------------- adminlar (faqat owner)
@router.callback_query(F.data == "ad:adm")
async def cb_admins(c: CallbackQuery, app: App, state: FSMContext) -> None:
    if not app.is_owner(c.from_user.id):
        await c.answer("Faqat owner uchun", show_alert=True)
        return
    await state.clear()
    b = InlineKeyboardBuilder()
    lines = ["👑 <b>Adminlar</b>\n"]
    for uid in app.cfg.owner_ids:
        lines.append(f"• <code>{uid}</code> (owner)")
    for uid in sorted(app._admins):
        lines.append(f"• <code>{uid}</code>")
        b.row(Btn(text=f"🗑 {uid}", callback_data=f"ad:ar:{uid}"))
    b.row(Btn(text="➕ Admin qo'shish", callback_data="ad:aa"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, "\n".join(lines), b)
    await c.answer()


@router.callback_query(F.data.startswith("ad:ar:"))
async def cb_admin_del(c: CallbackQuery, app: App, state: FSMContext) -> None:
    if app.is_owner(c.from_user.id):
        await app.del_admin(int(c.data.split(":")[2]))
    await cb_admins(c, app, state)


@router.callback_query(F.data == "ad:aa")
async def cb_admin_ask(c: CallbackQuery, app: App, state: FSMContext) -> None:
    if not app.is_owner(c.from_user.id):
        await c.answer("Faqat owner uchun", show_alert=True)
        return
    await state.set_state(S.admin)
    await edit(c, "Yangi admin Telegram ID sini yuboring (u botga /id yozsa bilib oladi).\n\n/cancel", kb_back("ad:adm"))
    await c.answer()


@router.message(S.admin, F.text)
async def st_admin(m: Message, app: App, state: FSMContext) -> None:
    if not app.is_owner(m.from_user.id) or not m.text.strip().isdigit():
        await m.answer("❌ Faqat raqamli ID yuboring.")
        return
    new_id = int(m.text.strip())
    await app.add_admin(new_id)
    from ..commands import set_admin_commands
    await set_admin_commands(m.bot, new_id)
    await state.clear()
    await m.answer("✅ Admin qo'shildi. /admin")


# ---------------------------------------------------------------- yt-dlp yangilash
@router.callback_query(F.data == "ad:upd")
async def cb_update(c: CallbackQuery) -> None:
    await c.answer("⏳ Yangilanmoqda...")
    await edit(c, "🔄 yt-dlp yangilanmoqda, kuting...")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-U", "--quiet", "yt-dlp[default]",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    tail = html.escape((out or b"").decode(errors="ignore")[-600:]) or "OK"
    b = InlineKeyboardBuilder()
    b.row(Btn(text="🔁 Botni qayta ishga tushirish", callback_data="ad:rs"))
    b.row(Btn(text="⬅️ Ortga", callback_data="ad:main"))
    await edit(c, f"{'✅' if proc.returncode == 0 else '⚠️'} Yangilash tugadi (kod {proc.returncode}).\n\n"
                  f"<pre>{tail}</pre>\nYangi versiya ishlashi uchun botni qayta ishga tushiring.", b)


@router.callback_query(F.data == "ad:rs")
async def cb_restart(c: CallbackQuery) -> None:
    await c.answer("🔁 Qayta ishga tushmoqda...")
    await edit(c, "🔁 Bot qayta ishga tushmoqda, bir necha soniya...")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable, *sys.argv])
