"""Admin / owner paneli: cookies, yuklash manbalari, majburiy obuna, adminlar, reklama."""
from __future__ import annotations

import asyncio
import html
import io
import logging
import time
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..app import App
from ..commands import set_admin_commands
from ..services.media import COOKIE_PLATFORMS, detect_platform, extract_url

log = logging.getLogger("navobot.owner")
router = Router(name="owner")

PLATFORM_TITLES = {
    "instagram": "📸 Instagram", "youtube": "▶️ YouTube", "tiktok": "🎵 TikTok",
    "facebook": "📘 Facebook", "twitter": "🐦 X / Twitter",
}


class AdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, app: App) -> bool:
        u = getattr(event, "from_user", None)
        return bool(u and app.is_admin(u.id))


class OwnerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, app: App) -> bool:
        u = getattr(event, "from_user", None)
        return bool(u and app.is_owner(u.id))


class St(StatesGroup):
    cookies = State()
    add_channel = State()
    add_admin = State()


# ====================================================================== yordamchilar
async def _edit(c: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            await c.message.answer(text, reply_markup=kb)


def _kb(*rows: list[Btn]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rows:
        b.row(*r)
    return b.as_markup()


BACK_HOME = [Btn(text="⬅️ Ortga", callback_data="adm:home")]


def panel_kb(is_owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [Btn(text="📊 Statistika", callback_data="adm:stats"), Btn(text="🍪 Cookies", callback_data="adm:ck")],
        [Btn(text="🔌 Yuklash manbalari", callback_data="adm:src"), Btn(text="📢 Majburiy obuna", callback_data="adm:subs")],
        [Btn(text="📣 Reklama (broadcast)", callback_data="adm:bc")],
    ]
    if is_owner:
        rows.append([Btn(text="👮 Adminlar", callback_data="adm:adm")])
    return _kb(*rows)


async def stats_text(app: App) -> str:
    s = await app.db.stats_summary()
    plat = "\n".join(f"  • {p}: <b>{n}</b>" for p, n in s["platforms"]) or "  —"
    return (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami: <b>{s['total']}</b> (faol: <b>{s['active']}</b>)\n"
        f"🆕 Bugun: <b>{s['new_day']}</b> · 7 kun: <b>{s['new_week']}</b>\n"
        f"🟢 24 soatda faol: <b>{s['online_day']}</b>\n\n"
        f"📥 Yuklashlar: bugun <b>{s['dl_day']}</b> · jami <b>{s['dl_total']}</b>\n"
        f"⚠️ Bugungi xatolar: <b>{s['fail_day']}</b>\n\n🌐 Platformalar (7 kun):\n{plat}"
    )


async def sources_text(app: App) -> str:
    cfg, media = app.cfg, app.media
    ck = ", ".join(f"{p} {'✅' if media.has_cookies(p) else '—'}" for p in COOKIE_PLATFORMS)
    st = "\n".join(
        f"  • {m}: ✅ {a} · ❌ {b}" for m, (a, b) in sorted(media.stats.items())
    ) or "  — (hali yuklash bo'lmagan)"
    errs = "\n".join(f"  • {html.escape(k)}: <code>{html.escape(v[:110])}</code>" for k, v in list(media.last_errors.items())[-6:]) or "  —"
    return (
        "🔌 <b>Yuklash manbalari</b>\n\n"
        f"• Cobalt: {'✅ ' + html.escape(cfg.cobalt_url) if cfg.cobalt_url else '⛔️ sozlanmagan (COBALT_API_URL)'}\n"
        f"• yt-dlp: <code>{html.escape(media.ytdlp_version())}</code>\n"
        f"• Proxy: {'✅ sozlangan' if cfg.proxy else '⛔️ yo`q (PROXY_URL)'}\n"
        f"• Pullik API (FastSaver): {'✅' if cfg.fastsaver_key else '⛔️ yo`q (FASTSAVER_API_KEY)'}\n"
        f"• Cookies: {ck}\n"
        f"• Tartib: <code>{' → '.join(cfg.source_order)}</code>\n"
        f"• Limit: {cfg.max_upload_mb} MB · parallel: {cfg.max_parallel}\n\n"
        f"📈 Natijalar (ishga tushgandan beri):\n{st}\n\n"
        f"🕓 Oxirgi xatolar:\n{errs}\n\n"
        "🧪 Aniq tekshirish: <code>/test HAVOLA</code>"
    )


# ====================================================================== panel
@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    await state.clear()
    await m.answer("Bekor qilindi. /admin" if cur else "Bekor qilinadigan amal yo'q.")


@router.message(Command("admin"), AdminFilter())
async def cmd_admin(m: Message, app: App, state: FSMContext) -> None:
    await state.clear()
    await m.answer("🛠 <b>Admin panel</b>", reply_markup=panel_kb(app.is_owner(m.from_user.id)))


@router.callback_query(F.data == "adm:home", AdminFilter())
async def cb_home(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await c.answer()
    await _edit(c, "🛠 <b>Admin panel</b>", panel_kb(app.is_owner(c.from_user.id)))


@router.callback_query(F.data == "adm:stats", AdminFilter())
async def cb_stats(c: CallbackQuery, app: App) -> None:
    await c.answer()
    await _edit(c, await stats_text(app), _kb(BACK_HOME))


@router.callback_query(F.data == "adm:bc", AdminFilter())
async def cb_bc(c: CallbackQuery) -> None:
    await c.answer()
    await _edit(c, "📣 <b>Reklama</b>\n\nYubormoqchi bo'lgan xabarni (matn, rasm, video — istalgani) botga yuboring, "
                   "so'ng shu xabarga <b>reply</b> qilib <code>/broadcast</code> deb yozing.", _kb(BACK_HOME))


# ====================================================================== cookies
def _ck_menu(app: App) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for p in COOKIE_PLATFORMS:
        mark = "✅" if app.media.has_cookies(p) else "➕"
        rows.append([Btn(text=f"{mark} {PLATFORM_TITLES[p]}", callback_data=f"adm:ck:{p}")])
    rows.append(BACK_HOME)
    text = (
        "🍪 <b>Cookies</b>\n\n"
        "Platforma tanlang va <code>cookies.txt</code> yuboring.\n"
        "⚠️ <b>Muhim:</b> asosiy akkauntingizni ishlatmang — Instagram yuklovchi akkauntlarni cheklashi mumkin. "
        "Alohida (ikkinchi) akkaunt oching.\n\n"
        "Cookies muddati o'tsa, yuklash yana xato beradi — shunda qaytadan yuboring."
    )
    return text, _kb(*rows)


@router.callback_query(F.data == "adm:ck", AdminFilter())
async def cb_ck(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await c.answer()
    text, kb = _ck_menu(app)
    await _edit(c, text, kb)


@router.callback_query(F.data.regexp(r"^adm:ck:[a-z]+$"), AdminFilter())
async def cb_ck_pick(c: CallbackQuery, app: App, state: FSMContext) -> None:
    platform = c.data.split(":")[2]
    if platform not in COOKIE_PLATFORMS:
        await c.answer("Noma'lum platforma", show_alert=True)
        return
    await c.answer()
    await state.set_state(St.cookies)
    await state.update_data(platform=platform)
    rows = [[Btn(text="⬅️ Ortga", callback_data="adm:ck")]]
    if app.media.has_cookies(platform):
        rows.insert(0, [Btn(text="🗑 Mavjud cookies'ni o'chirish", callback_data=f"adm:ckdel:{platform}")])
    await _edit(
        c,
        f"📥 <b>{platform}</b> uchun cookies.txt faylini yuboring (yoki matnini yopishtiring).\n\n"
        "Formatlar: Netscape <code>cookies.txt</code>, JSON (EditThisCookie) yoki <code>a=b; c=d</code>.\n"
        "Bekor qilish: /cancel",
        _kb(*rows),
    )


@router.callback_query(F.data.regexp(r"^adm:ckdel:[a-z]+$"), AdminFilter())
async def cb_ck_del(c: CallbackQuery, app: App, state: FSMContext) -> None:
    platform = c.data.split(":")[2]
    if platform in COOKIE_PLATFORMS:
        app.media.delete_cookies(platform)
    await state.clear()
    await c.answer("🗑 O'chirildi")
    text, kb = _ck_menu(app)
    await _edit(c, text, kb)


async def _store_cookies(m: Message, app: App, state: FSMContext, raw: str) -> None:
    platform = (await state.get_data()).get("platform", "instagram")
    try:
        n = app.media.save_cookies(platform, raw)
    except ValueError as e:
        await m.answer(f"❌ {html.escape(str(e))}\n\nQayta yuboring yoki /cancel")
        return
    await state.clear()
    try:
        await m.delete()  # cookies maxfiy — chatdan olib tashlaymiz
    except Exception:  # noqa: BLE001
        pass
    await m.answer(f"✅ {platform} cookies saqlandi ({n} ta yozuv). /admin\n\nSinash: <code>/test HAVOLA</code>")


@router.message(St.cookies, AdminFilter(), F.document)
async def got_cookie_file(m: Message, app: App, state: FSMContext, bot: Bot) -> None:
    doc = m.document
    if doc.file_size and doc.file_size > 2 * 1024 * 1024:
        await m.answer("❌ Fayl juda katta (2 MB dan kichik bo'lishi kerak).")
        return
    buf = io.BytesIO()
    await bot.download(doc, destination=buf)
    await _store_cookies(m, app, state, buf.getvalue().decode("utf-8", "ignore"))


@router.message(St.cookies, AdminFilter(), F.text, ~F.text.startswith("/"))
async def got_cookie_text(m: Message, app: App, state: FSMContext) -> None:
    await _store_cookies(m, app, state, m.text)


# ====================================================================== manbalar / diagnostika
@router.callback_query(F.data == "adm:src", AdminFilter())
async def cb_src(c: CallbackQuery, app: App) -> None:
    await c.answer()
    await _edit(c, await sources_text(app), _kb([Btn(text="🔄 yt-dlp ni yangilash", callback_data="adm:upd")], BACK_HOME))


@router.callback_query(F.data == "adm:upd", AdminFilter())
async def cb_upd(c: CallbackQuery, app: App) -> None:
    await c.answer("⏳ Yangilanmoqda...")
    res = await app.media.update_ytdlp()
    await c.message.answer(res)


@router.message(Command("diag"), AdminFilter())
async def cmd_diag(m: Message, app: App) -> None:
    await m.answer(await sources_text(app))


@router.message(Command("update"), AdminFilter())
async def cmd_update(m: Message, app: App) -> None:
    note = await m.answer("⏳ yt-dlp yangilanmoqda...")
    await note.edit_text(await app.media.update_ytdlp())


@router.message(Command("test"), AdminFilter())
async def cmd_test(m: Message, app: App, command: CommandObject) -> None:
    url = extract_url(command.args or "")
    if not url:
        await m.answer("🧪 Foydalanish: <code>/test https://www.instagram.com/reel/...</code>\n"
                       "Har bir usul alohida sinaladi va aniq sababi ko'rsatiladi.")
        return
    note = await m.answer(f"🧪 Sinalmoqda ({html.escape(detect_platform(url) or 'noma`lum')})... bu 1–3 daqiqa olishi mumkin.")
    rows = await app.media.diagnose(url)
    lines = ["🧪 <b>Natija</b>\n"]
    for name, ok, detail in rows:
        lines.append(f"{'✅' if ok else '❌'} <b>{name}</b> — {html.escape(detail)}")
    ok_any = any(ok for _n, ok, _d in rows)
    lines.append("\n" + ("✅ Kamida bitta usul ishlayapti — bot shu yo'l bilan yuklaydi." if ok_any else
                         "⛔️ Hech bir usul ishlamadi. Yechim: Cobalt'ni ulang (COBALT_API_URL), proxy (PROXY_URL) "
                         "yoki pullik API (FASTSAVER_API_KEY) qo'shing; /update ham sinab ko'ring."))
    await note.edit_text("\n".join(lines))


# ====================================================================== majburiy obuna
async def _subs_view(app: App) -> tuple[str, InlineKeyboardMarkup]:
    on = await app.subs.enabled()
    chans = await app.db.channels()
    lines = [f"📢 <b>Majburiy obuna</b>: {'✅ yoqilgan' if on else '⛔️ o`chiq'}\n"]
    rows: list[list[Btn]] = []
    for ch in chans:
        warn = " ⚠️ bot admin emas" if ch["chat_id"] in app.subs.broken else ""
        lines.append(f"• {html.escape(ch['title'])}{warn}\n  <code>{ch['chat_id']}</code>")
        rows.append([Btn(text=f"🗑 {ch['title'][:28]}", callback_data=f"adm:chdel:{ch['chat_id']}")])
    if not chans:
        lines.append("Kanal yo'q. «➕ Kanal qo'shish» ni bosing.")
    lines.append("\nℹ️ Bot kanalda <b>admin</b> bo'lishi shart.")
    rows.append([Btn(text="⛔️ O'chirish" if on else "✅ Yoqish", callback_data="adm:subtoggle"),
                 Btn(text="➕ Kanal qo'shish", callback_data="adm:chadd")])
    rows.append(BACK_HOME)
    return "\n".join(lines), _kb(*rows)


@router.callback_query(F.data == "adm:subs", AdminFilter())
async def cb_subs(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await c.answer()
    text, kb = await _subs_view(app)
    await _edit(c, text, kb)


@router.callback_query(F.data == "adm:subtoggle", AdminFilter())
async def cb_subtoggle(c: CallbackQuery, app: App) -> None:
    await app.subs.set_enabled(not await app.subs.enabled())
    await c.answer("Saqlandi")
    text, kb = await _subs_view(app)
    await _edit(c, text, kb)


@router.callback_query(F.data.regexp(r"^adm:chdel:-?\d+$"), AdminFilter())
async def cb_chdel(c: CallbackQuery, app: App) -> None:
    await app.db.del_channel(int(c.data.split(":")[2]))
    await c.answer("🗑 O'chirildi")
    text, kb = await _subs_view(app)
    await _edit(c, text, kb)


@router.callback_query(F.data == "adm:chadd", AdminFilter())
async def cb_chadd(c: CallbackQuery, state: FSMContext) -> None:
    await c.answer()
    await state.set_state(St.add_channel)
    await _edit(c, "➕ Kanal <code>@username</code> yoki ID sini yuboring, yoki kanaldan biror xabarni <b>forward</b> qiling.\n"
                   "Avval botni kanalga <b>admin</b> qilib qo'shing.\n\nBekor qilish: /cancel",
                _kb([Btn(text="⬅️ Ortga", callback_data="adm:subs")]))


@router.message(St.add_channel, AdminFilter(), ~F.text.startswith("/"))
async def got_channel(m: Message, app: App, bot: Bot, state: FSMContext) -> None:
    ref: Any = None
    origin = getattr(m, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None) is not None:
        ref = origin.chat.id
    elif m.text:
        t = m.text.strip().replace("https://t.me/", "@").replace("http://t.me/", "@").replace("t.me/", "@")
        ref = int(t) if t.lstrip("-").isdigit() else (t if t.startswith("@") else "@" + t)
    if ref is None:
        await m.answer("❌ Kanalni aniqlab bo'lmadi. @username, ID yuboring yoki xabar forward qiling.")
        return
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ Kanal topilmadi yoki bot unda yo'q: <code>{html.escape(str(e)[:150])}</code>")
        return
    status = str(getattr(me.status, "value", me.status))
    if status not in ("administrator", "creator"):
        await m.answer("❌ Bot bu kanalda admin emas. Avval botni admin qiling, so'ng qayta yuboring.")
        return
    link = f"https://t.me/{chat.username}" if chat.username else (getattr(chat, "invite_link", None) or "")
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:  # noqa: BLE001
            link = ""
    await app.db.add_channel(chat.id, chat.title or str(chat.id), link)
    app.subs.broken.discard(chat.id)
    await state.clear()
    await m.answer(f"✅ Qo'shildi: <b>{html.escape(chat.title or str(chat.id))}</b>\n/admin → 📢 Majburiy obuna")


# ====================================================================== adminlar (faqat owner)
async def _adm_view(app: App) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["👮 <b>Adminlar</b>\n"]
    rows: list[list[Btn]] = []
    for uid in app.all_admins():
        owner = app.is_owner(uid)
        lines.append(f"• <code>{uid}</code>{' 👑' if owner else ''}")
        if not owner:
            rows.append([Btn(text=f"🗑 {uid}", callback_data=f"adm:adel:{uid}")])
    rows.append([Btn(text="➕ Admin qo'shish", callback_data="adm:aadd")])
    rows.append(BACK_HOME)
    return "\n".join(lines), _kb(*rows)


@router.callback_query(F.data == "adm:adm", OwnerFilter())
async def cb_adm(c: CallbackQuery, app: App, state: FSMContext) -> None:
    await state.clear()
    await c.answer()
    text, kb = await _adm_view(app)
    await _edit(c, text, kb)


@router.callback_query(F.data.regexp(r"^adm:adel:\d+$"), OwnerFilter())
async def cb_adel(c: CallbackQuery, app: App, bot: Bot) -> None:
    uid = int(c.data.split(":")[2])
    await app.remove_admin(uid)
    try:
        from aiogram.types import BotCommandScopeChat

        from .. import commands as _c

        await bot.set_my_commands(list(_c.USER_COMMANDS), scope=BotCommandScopeChat(chat_id=uid))
    except Exception:  # noqa: BLE001
        pass
    await c.answer("🗑 O'chirildi")
    text, kb = await _adm_view(app)
    await _edit(c, text, kb)


@router.callback_query(F.data == "adm:aadd", OwnerFilter())
async def cb_aadd(c: CallbackQuery, state: FSMContext) -> None:
    await c.answer()
    await state.set_state(St.add_admin)
    await _edit(c, "➕ Yangi adminning Telegram ID sini yuboring (u botga /id yozib bilib oladi).\nBekor qilish: /cancel",
                _kb([Btn(text="⬅️ Ortga", callback_data="adm:adm")]))


@router.message(St.add_admin, OwnerFilter(), F.text, ~F.text.startswith("/"))
async def got_admin(m: Message, app: App, bot: Bot, state: FSMContext) -> None:
    t = m.text.strip()
    if not t.isdigit():
        await m.answer("❌ Faqat raqamli ID yuboring yoki /cancel")
        return
    uid = int(t)
    await app.add_admin(uid)
    await set_admin_commands(bot, uid)
    await state.clear()
    await m.answer(f"✅ <code>{uid}</code> admin qilindi. /admin")


# ====================================================================== ban / limit
@router.message(Command("ban"), AdminFilter())
async def cmd_ban(m: Message, app: App, command: CommandObject) -> None:
    a = (command.args or "").strip()
    if not a.isdigit():
        await m.answer("Foydalanish: <code>/ban ID</code>")
        return
    if app.is_admin(int(a)):
        await m.answer("❌ Adminni ban qilib bo'lmaydi.")
        return
    ok = await app.db.set_banned(int(a), True)
    await m.answer("🚫 Ban qilindi." if ok else "❌ Bunday foydalanuvchi yo'q.")


@router.message(Command("unban"), AdminFilter())
async def cmd_unban(m: Message, app: App, command: CommandObject) -> None:
    a = (command.args or "").strip()
    if not a.isdigit():
        await m.answer("Foydalanish: <code>/unban ID</code>")
        return
    ok = await app.db.set_banned(int(a), False)
    await m.answer("✅ Ban olib tashlandi." if ok else "❌ Bunday foydalanuvchi yo'q.")


@router.message(Command("limit"), OwnerFilter())
async def cmd_limit(m: Message, app: App, command: CommandObject) -> None:
    a = (command.args or "").strip()
    if a.isdigit():
        await app.db.set_setting("daily_limit", a)
    cur = await app.db.get_setting("daily_limit", "0")
    await m.answer(f"📉 Bepul kunlik limit: <b>{'cheksiz' if cur in ('0', '') else cur}</b> ta yuklash\n"
                   "O'zgartirish: <code>/limit 20</code> (0 = cheksiz). Premium foydalanuvchilarga limit qo'llanmaydi.")


# ====================================================================== reklama
async def _broadcast(bot: Bot, app: App, status: Message, from_chat: int, msg_id: int) -> None:
    ids = await app.db.user_ids()
    total, ok, fail, started = len(ids), 0, 0, time.time()

    async def _progress(final: bool = False) -> None:
        head = "✅ <b>Yuborish tugadi</b>" if final else "🚀 <b>Yuborilmoqda...</b>"
        try:
            await status.edit_text(
                f"{head}\n\n📨 Yuborildi: <b>{ok}</b>\n⚠️ Yetmadi: <b>{fail}</b>\n👥 Jami: <b>{total}</b>"
                f"\n⏱ {int(time.time() - started)} soniya"
            )
        except Exception:  # noqa: BLE001
            pass

    for i, uid in enumerate(ids, 1):
        for attempt in (1, 2):
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                ok += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                if attempt == 1:
                    continue
                fail += 1
            except TelegramForbiddenError:
                fail += 1
                await app.db.set_active(uid, False)
            except Exception:  # noqa: BLE001
                fail += 1
            break
        await asyncio.sleep(0.04)  # ~25 xabar/soniya
        if i % 100 == 0:
            await _progress()
    await _progress(final=True)
