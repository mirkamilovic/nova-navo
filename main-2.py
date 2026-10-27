from __future__ import annotations

if not __package__:
    # `python main.py` tekis (papkasiz) tuzilmada ishga tushirilsa, katalogni
    # "bot", "bot.services" va "bot.handlers" paketlari qilib ulaymiz
    import pathlib
    import sys
    import types

    _root = str(pathlib.Path(__file__).resolve().parent)
    for _name in ("bot", "bot.services", "bot.handlers"):
        _m = types.ModuleType(_name)
        _m.__path__ = [_root]
        sys.modules[_name] = _m
    from bot.main import run as _run  # noqa: E402

    _run()
    raise SystemExit(0)

import asyncio
import html
import logging
import shutil
import time
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, Message
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import commands as _cmds
from .app import App
from .commands import set_admin_commands, set_descriptions, set_user_commands
from .config import Config, load_config
from .db import Database
from .handlers import owner, user
from .handlers.owner import AdminFilter, _broadcast
from .middleware import UserMiddleware
from .services.media import MediaService
from .services.shazam import ShazamService
from .services.subs import SubService
from .texts import Texts

log = logging.getLogger("navobot")

# =====================================================================
#  «/» MENYUSI  (commands.py dagi ro'yxat o'rniga shu ishlatiladi)
# =====================================================================
USER_MENU = [
    BotCommand(command="start", description="🏠 Bosh menyu"),
    BotCommand(command="premium", description="💎 Premium"),
    BotCommand(command="help", description="📥 Qanday yuklash"),
    BotCommand(command="ref", description="🎁 Do'st taklif qilish"),
    BotCommand(command="promo", description="🎟 Promokod"),
    BotCommand(command="rate", description="⭐ Botni baholash"),
    BotCommand(command="contact", description="✉️ Adminga yozish"),
    BotCommand(command="paysupport", description="💳 To'lov yordami"),
]
ADMIN_MENU = [
    BotCommand(command="admin", description="🛠 Admin panel"),
    BotCommand(command="stats", description="📊 Statistika"),
    BotCommand(command="broadcast", description="📣 Reklama"),
    BotCommand(command="channels", description="📡 Kanallar"),
    BotCommand(command="user", description="🔎 User kartochkasi"),
    BotCommand(command="income", description="💰 Daromad (owner)"),
    BotCommand(command="adminhelp", description="📖 Barcha buyruqlar"),
    BotCommand(command="cancel", description="❌ Amalni bekor qilish"),
]
# owner.py (admin qo'shganda) commands.py dagi ro'yxatlarni o'qiydi — joyida almashtiramiz
_cmds.USER_COMMANDS[:] = USER_MENU
_cmds.ADMIN_EXTRA[:] = ADMIN_MENU

FREE_COMMANDS = {"/start", "/id", "/help", "/contact", "/paysupport", "/premium"}


class Gate(UserMiddleware):
    """Majburiy obuna: yordam/aloqa buyruqlari obunasiz ham ishlaydi."""

    async def _gate(self, app: App, event: Any, data: dict[str, Any]) -> bool:
        if isinstance(event, Message) and event.text:
            cmd = event.text.split(maxsplit=1)[0].split("@")[0].lower()
            if cmd in FREE_COMMANDS:
                return False
        if isinstance(event, CallbackQuery) and (event.data or "").startswith(("rt:", "sub:")):
            return False
        return await super()._gate(app, event, data)


# =====================================================================
#  QO'SHIMCHA BUYRUQLAR
# =====================================================================
extras = Router(name="extras")
_tasks: set[asyncio.Task] = set()
_promo_lock = asyncio.Lock()

DEFAULT_HELP = (
    "📥 <b>Qanday yuklash?</b>\n\n"
    "Havolani yuboring — bot video/audioni yuklab beradi:\n"
    "• Instagram, TikTok, YouTube, Snapchat, Pinterest, Threads, Facebook, X\n\n"
    "🎧 <b>Musiqa topish:</b> qo'shiq nomi, matni, ovozli xabar, video yoki video xabar yuboring.\n\n"
    "📌 /top — mashhur qo'shiqlar · /new — yangilari\n"
    "📌 /premium · /ref · /promo · /rate · /contact"
)
DEFAULT_PREMIUM = (
    "💎 <b>Premium</b>\n\nReklamasiz, limitsiz va tezkor yuklash.\n"
    "Sotib olish uchun adminga yozing: /contact"
)
DEFAULT_PAY = (
    "💳 <b>To'lov yordami</b>\n\nTo'lov bilan muammo bo'lsa, quyidagicha yozing:\n"
    "<code>/paysupport muammo tavsifi</code>\nAdmin tez orada javob beradi."
)


async def _get(app: App, key: str, default: str = "") -> str:
    v = await app.db.get_setting(key, default)
    return v if v is not None else default


async def _num(app: App, key: str) -> float:
    try:
        return float(await _get(app, key, "0") or 0)
    except ValueError:
        return 0.0


async def _to_admins(bot: Bot, app: App, text: str) -> int:
    n = 0
    for uid in app.all_admins():
        try:
            await bot.send_message(uid, text)
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def _who(m: Message) -> str:
    u = m.from_user
    uname = f" @{u.username}" if u.username else ""
    return f"{html.escape(u.full_name)}{uname} (<code>{u.id}</code>)"


# ---------------------------------------------------------------- foydalanuvchi
@extras.message(Command("id"))
async def cmd_id(m: Message) -> None:
    await m.answer(f"🆔 Sizning ID: <code>{m.from_user.id}</code>")


@extras.message(Command("help"))
async def cmd_help(m: Message, app: App) -> None:
    await m.answer(await _get(app, "help_text", DEFAULT_HELP))


@extras.message(Command("premium"))
async def cmd_premium(m: Message, app: App) -> None:
    text = await _get(app, "premium_text", DEFAULT_PREMIUM)
    until = await _num(app, f"premium:{m.from_user.id}")
    if until > time.time():
        left = int((until - time.time()) // 86400) + 1
        text = f"✅ <b>Sizda Premium faol</b> — yana ~{left} kun.\n\n" + text
    await m.answer(text)


@extras.message(Command("ref"))
async def cmd_ref(m: Message, app: App) -> None:
    link = f"https://t.me/{app.bot_username}?start=ref_{m.from_user.id}"
    await m.answer(
        "🎁 <b>Do'st taklif qilish</b>\n\nSizning shaxsiy havolangiz:\n"
        f"<code>{link}</code>\n\nDo'stlaringizga yuboring — ular shu havola orqali botga kirsin."
    )


@extras.message(Command("promo"))
async def cmd_promo(m: Message, app: App, command: CommandObject) -> None:
    code = (command.args or "").strip().upper()
    if not code:
        await m.answer("🎟 Promokodni shunday yuboring:\n<code>/promo KOD</code>")
        return
    uid = m.from_user.id
    async with _promo_lock:
        raw = await _get(app, f"promo:{code}")
        if not raw:
            await m.answer("❌ Bunday promokod yo'q.")
            return
        if await _get(app, f"promo_used:{uid}:{code}"):
            await m.answer("⚠️ Bu promokodni allaqachon ishlatgansiz.")
            return
        try:
            days_s, left_s = raw.split("|")
            days, left = int(days_s), int(left_s)
        except ValueError:
            await m.answer("❌ Promokod buzilgan, adminga xabar bering.")
            return
        if left <= 0:
            await m.answer("❌ Bu promokod tugagan.")
            return
        base = max(await _num(app, f"premium:{uid}"), time.time())
        await app.db.set_setting(f"premium:{uid}", str(base + days * 86400))
        await app.db.set_setting(f"promo:{code}", f"{days}|{left - 1}")
        await app.db.set_setting(f"promo_used:{uid}:{code}", "1")
    await m.answer(f"✅ Promokod qabul qilindi! 💎 Premium: +{days} kun.")


@extras.message(Command("rate"))
async def cmd_rate(m: Message) -> None:
    b = InlineKeyboardBuilder()
    b.row(*[Btn(text="⭐" * i, callback_data=f"rt:{i}") for i in (1, 2, 3)])
    b.row(*[Btn(text="⭐" * i, callback_data=f"rt:{i}") for i in (4, 5)])
    await m.answer("⭐ Botimizni baholang:", reply_markup=b.as_markup())


@extras.callback_query(F.data.regexp(r"^rt:[1-5]$"))
async def cb_rate(c: CallbackQuery, app: App, bot: Bot) -> None:
    n = int(c.data.split(":")[1])
    await app.db.set_setting(f"rate:{c.from_user.id}", str(n))
    await c.answer("Rahmat! ❤️")
    try:
        await c.message.edit_text(f"Rahmat! Bahoyingiz: {'⭐' * n}")
    except Exception:  # noqa: BLE001
        pass
    await app.notify_admins(bot, f"rate:{c.from_user.id}",
                            f"⭐ Yangi baho: <b>{n}/5</b> — {html.escape(c.from_user.full_name)} "
                            f"(<code>{c.from_user.id}</code>)", every=1)


async def _support(m: Message, app: App, bot: Bot, command: CommandObject, tag: str, empty: str) -> None:
    text = (command.args or "").strip()
    if not text:
        await m.answer(empty)
        return
    sent = await _to_admins(bot, app, f"{tag} {_who(m)}\n\n{html.escape(text[:3000])}\n\n"
                                      f"↩️ Javob: <code>/reply {m.from_user.id} matn</code>")
    await m.answer("✅ Xabaringiz adminga yuborildi." if sent else "⚠️ Hozir adminlarga yetkazib bo'lmadi, keyinroq urinib ko'ring.")


@extras.message(Command("contact"))
async def cmd_contact(m: Message, app: App, bot: Bot, command: CommandObject) -> None:
    uname = await _get(app, "contact_username")
    empty = "✉️ <b>Adminga yozish</b>\n\n<code>/contact xabaringiz</code>"
    if uname:
        empty += f"\n\nYoki to'g'ridan-to'g'ri: {html.escape(uname)}"
    await _support(m, app, bot, command, "✉️", empty)


@extras.message(Command("paysupport"))
async def cmd_paysupport(m: Message, app: App, bot: Bot, command: CommandObject) -> None:
    await _support(m, app, bot, command, "💳 <b>To'lov</b>", await _get(app, "pay_text", DEFAULT_PAY))


# ---------------------------------------------------------------- admin
@extras.message(Command("adminhelp"), AdminFilter())
async def cmd_adminhelp(m: Message, app: App) -> None:
    text = (
        "📖 <b>Admin buyruqlari</b>\n\n"
        "/admin — panel\n/stats — statistika\n"
        "/broadcast — xabarga <b>reply</b> qilib yozing, hammaga yuboriladi\n"
        "/channels — majburiy obuna kanallari\n/user <code>ID</code> — foydalanuvchi kartochkasi\n"
        "/reply <code>ID matn</code> — foydalanuvchiga javob\n"
        "/addpromo <code>KOD KUN SONI</code> — promokod yaratish\n/cancel — bekor qilish"
    )
    if app.is_owner(m.from_user.id):
        text += (
            "\n\n👑 <b>Owner</b>\n/income — daromad · <code>/income add SUMMA</code>\n"
            "/set <code>kalit qiymat</code> — kalitlar: <code>help_text premium_text pay_text contact_username</code>"
        )
    await m.answer(text)


@extras.message(Command("stats"), AdminFilter())
async def cmd_stats(m: Message, app: App) -> None:
    s = await app.db.stats_summary()
    plat = "\n".join(f"  • {p}: <b>{n}</b>" for p, n in s["platforms"]) or "  —"
    await m.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami: <b>{s['total']}</b> (faol: <b>{s['active']}</b>)\n"
        f"🆕 Bugun: <b>{s['new_day']}</b> · 7 kun: <b>{s['new_week']}</b>\n"
        f"🟢 24 soatda faol: <b>{s['online_day']}</b>\n\n"
        f"📥 Yuklashlar: bugun <b>{s['dl_day']}</b> · jami <b>{s['dl_total']}</b>\n"
        f"⚠️ Bugungi xatolar: <b>{s['fail_day']}</b>\n\n🌐 Platformalar (7 kun):\n{plat}"
    )


@extras.message(Command("channels"), AdminFilter())
async def cmd_channels(m: Message, app: App) -> None:
    chans = await app.db.channels()
    on = await app.subs.enabled()
    lines = [f"📡 <b>Kanallar</b> — majburiy obuna: {'✅' if on else '⛔️'}\n"]
    for ch in chans:
        warn = " ⚠️ bot admin emas" if ch["chat_id"] in app.subs.broken else ""
        lines.append(f"• {html.escape(ch['title'])}{warn}\n  <code>{ch['chat_id']}</code>")
    if not chans:
        lines.append("Hozircha kanal yo'q. Qo'shish: /admin → 📢 Majburiy obuna")
    await m.answer("\n".join(lines))


@extras.message(Command("user"), AdminFilter())
async def cmd_user(m: Message, app: App, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await m.answer("🔎 Foydalanish: <code>/user 123456789</code>")
        return
    uid = int(arg)
    row = await app.db.get_user(uid)
    if not row:
        await m.answer("❌ Bunday foydalanuvchi bazada yo'q.")
        return
    try:
        data = dict(row)
    except Exception:  # noqa: BLE001
        data = {"info": str(row)}
    lines = [f"🔎 <b>Foydalanuvchi</b> <code>{uid}</code>\n"]
    for k, v in data.items():
        lines.append(f"• {html.escape(str(k))}: <code>{html.escape(str(v)[:100])}</code>")
    until = await _num(app, f"premium:{uid}")
    lines.append(f"• premium: {'✅ ' + time.strftime('%Y-%m-%d', time.localtime(until)) if until > time.time() else '—'}")
    await m.answer("\n".join(lines))


@extras.message(Command("reply"), AdminFilter())
async def cmd_reply(m: Message, bot: Bot, command: CommandObject) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await m.answer("Foydalanish: <code>/reply ID matn</code>")
        return
    try:
        await bot.send_message(int(parts[0]), f"📩 <b>Admin javobi:</b>\n\n{html.escape(parts[1])}")
        await m.answer("✅ Yuborildi.")
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ Yuborilmadi: <code>{html.escape(str(e)[:150])}</code>")


@extras.message(Command("addpromo"), AdminFilter())
async def cmd_addpromo(m: Message, app: App, command: CommandObject) -> None:
    p = (command.args or "").split()
    if len(p) != 3 or not p[1].isdigit() or not p[2].isdigit():
        await m.answer("Foydalanish: <code>/addpromo KOD KUN SONI</code>\nMasalan: <code>/addpromo NAVO30 30 100</code>")
        return
    code = p[0].upper()
    await app.db.set_setting(f"promo:{code}", f"{int(p[1])}|{int(p[2])}")
    await m.answer(f"✅ Promokod <code>{html.escape(code)}</code>: {p[1]} kun Premium, {p[2]} ta foydalanuvchi.")


@extras.message(Command("broadcast"), AdminFilter())
async def cmd_broadcast(m: Message, app: App) -> None:
    src = m.reply_to_message
    if not src:
        await m.answer("📣 Yuboriladigan xabarga <b>reply</b> qilib <code>/broadcast</code> yozing.")
        return
    n = len(await app.db.user_ids())
    b = InlineKeyboardBuilder()
    b.row(Btn(text=f"✅ {n} ta foydalanuvchiga yuborish", callback_data=f"bx:{src.chat.id}:{src.message_id}"))
    b.row(Btn(text="❌ Bekor qilish", callback_data="bx:no"))
    await src.reply("Shu xabar hammaga yuboriladi. Tasdiqlaysizmi?", reply_markup=b.as_markup())


@extras.callback_query(F.data == "bx:no", AdminFilter())
async def cb_bx_no(c: CallbackQuery) -> None:
    await c.answer("Bekor qilindi")
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass


@extras.callback_query(F.data.regexp(r"^bx:-?\d+:\d+$"), AdminFilter())
async def cb_bx(c: CallbackQuery, app: App, bot: Bot) -> None:
    _p, chat, mid = c.data.split(":")
    await c.answer("🚀 Boshlandi")
    await c.message.edit_text("🚀 Yuborish boshlandi...")
    t = asyncio.create_task(_broadcast(bot, app, c.message, int(chat), int(mid)))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@extras.message(Command("income"), AdminFilter())
async def cmd_income(m: Message, app: App, command: CommandObject) -> None:
    if not app.is_owner(m.from_user.id):
        await m.answer("👑 Bu buyruq faqat owner uchun.")
        return
    p = (command.args or "").split()
    if len(p) == 2 and p[0].lower() == "add" and p[1].lstrip("-").isdigit():
        total = await _num(app, "income_total") + int(p[1])
        await app.db.set_setting("income_total", str(int(total)))
    total = int(await _num(app, "income_total"))
    await m.answer(f"💰 <b>Daromad</b>: <b>{total:,}</b> so'm\n\nQo'shish: <code>/income add 50000</code>".replace(",", " "))


@extras.message(Command("set"), AdminFilter())
async def cmd_set(m: Message, app: App, command: CommandObject) -> None:
    if not app.is_owner(m.from_user.id):
        await m.answer("👑 Bu buyruq faqat owner uchun.")
        return
    parts = (command.args or "").split(maxsplit=1)
    allowed = {"help_text", "premium_text", "pay_text", "contact_username"}
    if len(parts) < 2 or parts[0] not in allowed:
        await m.answer("Foydalanish: <code>/set kalit qiymat</code>\nKalitlar: " + ", ".join(f"<code>{k}</code>" for k in sorted(allowed)))
        return
    value = m.html_text.split(None, 2)[2] if len(m.html_text.split(None, 2)) > 2 else parts[1]
    await app.db.set_setting(parts[0], value)
    await m.answer("✅ Saqlandi.")


# =====================================================================
#  ASOSIY
# =====================================================================
def make_bot(cfg: Config) -> Bot:
    if cfg.local_api:
        session = AiohttpSession(api=TelegramAPIServer.from_base(cfg.bot_api_url, is_local=True), timeout=900)
    else:
        session = AiohttpSession(timeout=300)
    return Bot(cfg.token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def build_app(cfg: Config, bot: Bot) -> App:
    """Baza, matnlar va xizmatlarni yig'adi."""
    db = Database(cfg.db_path)
    await db.connect()
    texts = Texts(db)
    await texts.load()
    media = MediaService(cfg, db)
    app = App(cfg=cfg, db=db, texts=texts, media=media, shazam=ShazamService(media), subs=SubService(db))
    await app.load_admins()
    me = await bot.get_me()
    app.bot_username = me.username or ""
    return app


def build_dispatcher(app: App) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), app=app)
    mw = Gate()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(owner.router)   # owner birinchi: FSM holatlari qidiruvga tushib ketmasin
    dp.include_router(extras)         # buyruqlar user.py dagi umumiy matn qidiruvidan OLDIN
    dp.include_router(user.router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        log.error("Handler xatosi: %s", event.exception, exc_info=event.exception)
        try:
            upd = event.update
            if upd.message:
                await upd.message.answer("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.")
            elif upd.callback_query:
                await upd.callback_query.answer("⚠️ Xatolik yuz berdi", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return True

    return dp


async def setup_bot(bot: Bot, app: App) -> None:
    for step in (set_user_commands(bot), set_descriptions(bot)):
        try:
            await step
        except Exception:  # noqa: BLE001
            log.exception("bot sozlamasini o'rnatib bo'lmadi")
    for uid in app.all_admins():
        await set_admin_commands(bot, uid)


def clean_tmp(cfg: Config, older_than: float = 0) -> None:
    cfg.tmp_dir.mkdir(parents=True, exist_ok=True)
    for d in cfg.tmp_dir.iterdir():
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime >= older_than:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


async def housekeeping(app: App) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await app.db.cleanup()
            clean_tmp(app.cfg, older_than=6 * 3600)
        except Exception:  # noqa: BLE001
            log.exception("housekeeping xatosi")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    if not cfg.owner_ids:
        log.warning("OWNER_IDS bo'sh! Owner paneli ishlamaydi. Botga /id yozib ID ni bilib oling.")
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg topilmadi — audio/video ishlamaydi!")
    if not (shutil.which("node") or shutil.which("deno")):
        log.warning("node/deno topilmadi — YouTube yuklash ishlamasligi mumkin")
    clean_tmp(cfg)

    bot = make_bot(cfg)
    app: App | None = None
    task: asyncio.Task | None = None
    try:
        app = await build_app(cfg, bot)
        log.info("Bot ishga tushdi: @%s", app.bot_username)
        dp = build_dispatcher(app)
        await setup_bot(bot, app)
        task = asyncio.create_task(housekeeping(app))
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if task:
            task.cancel()
        if app:
            await app.db.close()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
