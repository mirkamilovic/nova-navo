from __future__ import annotations

if not __package__:
    # `python main.py` tekis (bot/ papkasiz) tuzilmada ishga tushirilsa — katalogni "bot" paketi qilib ulaymiz
    import pathlib
    import sys
    import types

    _pkg = types.ModuleType("bot")
    _pkg.__path__ = [str(pathlib.Path(__file__).resolve().parent)]
    sys.modules["bot"] = _pkg
    from bot.main import run as _run  # noqa: E402

    _run()
    raise SystemExit(0)

import asyncio
import logging
import shutil
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .app import App
from .commands import set_admin_commands, set_descriptions, set_user_commands
from .config import Config, load_config
from .db import Database
from .handlers import owner, user
from .middleware import UserMiddleware
from .services.media import MediaService
from .services.shazam import ShazamService
from .services.subs import SubService
from .texts import Texts

log = logging.getLogger("navobot")


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
    mw = UserMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(owner.router)   # owner birinchi: FSM holatlari qidiruvga tushib ketmasin
    dp.include_router(user.router)
    return dp


async def setup_bot(bot: Bot, app: App) -> None:
    await set_user_commands(bot)
    await set_descriptions(bot)
    for uid in app.all_admins():
        await set_admin_commands(bot, uid)


def clean_tmp(cfg: Config, older_than: float = 0) -> None:
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
