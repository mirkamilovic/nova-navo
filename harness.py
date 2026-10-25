"""Test muhiti: soxta Telegram + haqiqiy bot kodi."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import fakegram as fg  # noqa: E402

fg.install()

from bot import main as bot_main  # noqa: E402
from bot.config import Config, load_config  # noqa: E402

_REAL_MP3: bytes | None = None


def real_mp3() -> bytes | None:
    """ffmpeg bilan haqiqiy 2 soniyali mp3 (effekt va Shazam konvertatsiyasi uchun)."""
    global _REAL_MP3
    if _REAL_MP3 is None and shutil.which("ffmpeg"):
        p = Path(tempfile.mkdtemp()) / "t.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                            str(p)], capture_output=True)
        if r.returncode == 0:
            _REAL_MP3 = p.read_bytes()
    return _REAL_MP3


class Client:
    """Bitta soxta foydalanuvchi."""

    def __init__(self, env: "Env", uid: int, name: str = "User", username: str | None = None):
        self.env, self.uid = env, uid
        self.user = fg.User(uid, name, username or f"user{uid}")
        self.chat = fg.Chat(uid, "private")

    # ---- yordamchilar
    def msgs(self):
        return [m for m in self.env.bot.outbox if m.chat.id == self.chat.id and not m.deleted]

    def last(self):
        return self.msgs()[-1]

    def texts(self):
        return [m.text or m.caption or "" for m in self.msgs()]

    async def _feed(self, ev):
        before = len(self.env.bot.outbox)
        await self.env.dp.feed(ev)
        return [m for m in self.env.bot.outbox[before:] if m.chat.id == self.chat.id]

    # ---- harakatlar
    async def say(self, text: str, chat=None, **kw):
        m = fg.Message(self.env.bot, chat or self.chat, self.user, text=text, **kw)
        return await self._feed(m)

    async def send_media(self, kind: str, size: int = 5000, **kw):
        media = fg.Media(file_size=size, **kw)
        m = fg.Message(self.env.bot, self.chat, self.user, **{kind: media})
        return await self._feed(m)

    async def send_photo(self):
        m = fg.Message(self.env.bot, self.chat, self.user, photo=[fg.Media(), fg.Media()])
        self.env.bot.files[m.photo[-1].file_id] = "photo"
        return await self._feed(m)

    async def send_doc(self, name="cookies.txt", size=1000):
        m = fg.Message(self.env.bot, self.chat, self.user, document=fg.Media(file_size=size, file_name=name))
        return await self._feed(m)

    async def send_forward_from_channel(self, chat: fg.Chat):
        m = fg.Message(self.env.bot, self.chat, self.user, text="forwarded")
        m.forward_origin = type("Origin", (), {"chat": chat})()
        return await self._feed(m)

    def find(self, msg, label=None, data=None):
        for b in (msg.reply_markup.flat() if msg.reply_markup else []):
            if (label is not None and label in b.text) or (data is not None and b.callback_data == data):
                return b
        return None

    async def press(self, msg, label=None, data=None):
        b = self.find(msg, label, data)
        assert b is not None and b.callback_data, f"tugma topilmadi: label={label!r} data={data!r}; " \
            f"mavjud: {[(x.text, x.callback_data) for x in (msg.reply_markup.flat() if msg.reply_markup else [])]}"
        cq = fg.CallbackQuery(self.env.bot, self.user, msg, b.callback_data)
        new = await self._feed(cq)
        return new, cq

    async def press_data(self, msg, data):
        cq = fg.CallbackQuery(self.env.bot, self.user, msg, data)
        new = await self._feed(cq)
        return new, cq


class Env:
    def __init__(self):
        self.tmp: Path
        self.bot: fg.Bot
        self.dp: fg.Dispatcher
        self.app = None
        self._clients: dict[int, Client] = {}
        self._patched = None

    @classmethod
    async def create(cls, limit_mb: int = 1, owners=(1000,), parallel: int = 4, local_api: bool = False):
        self = cls()
        self.tmp = Path(tempfile.mkdtemp(prefix="navotest_"))
        os.environ.update(BOT_TOKEN="123:TEST", OWNER_IDS=",".join(map(str, owners)), DATA_DIR=str(self.tmp),
                          MAX_PARALLEL=str(parallel), BOT_API_URL="http://localhost:8081" if local_api else "")
        self._patched = Config.upload_limit_mb
        Config.upload_limit_mb = property(lambda s: limit_mb)
        self.cfg = load_config()
        self.bot = bot_main.make_bot(cfg=self.cfg)
        self.app = await bot_main.build_app(self.cfg, self.bot)
        self.dp = bot_main.build_dispatcher(self.app)
        await bot_main.setup_bot(self.bot, self.app)
        fg.ClientSession.routes = {}
        fg.ClientSession.requests = []
        fg.FakeShazam.fail = False
        fg.FakeShazam.calls = 0
        from tests.fake_ytdlp import FakeYoutubeDL
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.delay = 0.0
        FakeYoutubeDL.max_active = 0
        FakeYoutubeDL.active = 0
        return self

    async def close(self):
        await self.app.db.close()
        Config.upload_limit_mb = self._patched
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, uid: int, name="User") -> Client:
        if uid not in self._clients:
            self._clients[uid] = Client(self, uid, name)
        return self._clients[uid]

    @property
    def owner(self) -> Client:
        return self.client(self.cfg.owner_ids[0], "Owner")

    def tmp_dirs(self):
        return [d for d in self.cfg.tmp_dir.iterdir()]

    def ytdlp_calls(self, audio=None):
        from tests.fake_ytdlp import FakeYoutubeDL
        return [c for c in FakeYoutubeDL.calls if not c["url"].startswith("ytsearch") and
                (audio is None or c["audio"] == audio)]


async def run_main_once() -> dict:
    """bot.main.main() ni to'liq ishga tushiradi (polling soxta)."""
    tmp = Path(tempfile.mkdtemp(prefix="navomain_"))
    os.environ.update(BOT_TOKEN="123:TEST", OWNER_IDS="1000", DATA_DIR=str(tmp), BOT_API_URL="")
    seen = {}
    orig_make, orig_dp = bot_main.make_bot, bot_main.build_dispatcher

    def mk(cfg):
        seen["bot"] = orig_make(cfg)
        return seen["bot"]

    def bd(app):
        seen["dp"] = orig_dp(app)
        return seen["dp"]

    bot_main.make_bot, bot_main.build_dispatcher = mk, bd
    try:
        await bot_main.main()
    finally:
        bot_main.make_bot, bot_main.build_dispatcher = orig_make, orig_dp
        shutil.rmtree(tmp, ignore_errors=True)
    bot = seen["bot"]
    return {"polling": seen["dp"].polling_started, "webhook_deleted": bot.webhook_deleted,
            "commands": bool(bot.commands)}
