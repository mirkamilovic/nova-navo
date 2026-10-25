"""Soxta Telegram: aiogram 3 ning bot ishlatadigan qismini taqlid qiladi (faqat testlar uchun).

Haqiqiy tarmoq ham, aiogram/aiohttp/yt-dlp/shazamio ham kerak emas. `install()` ularning o'rniga
sys.modules ga soxta modullarni qo'yadi, shundan keyin `bot.*` kodi o'zgarishsiz import qilinadi.
"""
from __future__ import annotations

import asyncio
import inspect
import itertools
import os
import re
import sqlite3
import sys
import time
import traceback
import types
from pathlib import Path
from typing import Any

_ids = itertools.count(1)
UNHANDLED = object()


# ============================================================ istisnolar
class TelegramBadRequest(Exception):
    def __init__(self, message: str = "bad request"):
        super().__init__(message)


class TelegramForbiddenError(Exception):
    pass


class TelegramRetryAfter(Exception):
    def __init__(self, retry_after: int = 0):
        super().__init__(f"retry after {retry_after}")
        self.retry_after = retry_after


# ============================================================ tiplar
class TelegramObject:
    pass


class FSInputFile:
    def __init__(self, path, filename=None):
        self.path = str(path)
        self.filename = filename


class InlineKeyboardButton:
    def __init__(self, text: str, callback_data: str | None = None, url: str | None = None, **kw):
        assert isinstance(text, str) and text, "tugma matni bo'sh bo'lmasin"
        if callback_data is not None:
            assert len(callback_data.encode()) <= 64, f"callback_data 64 baytdan oshdi: {callback_data}"
        assert (callback_data is None) != (url is None), "tugmada callback_data yoki url bo'lishi shart"
        self.text, self.callback_data, self.url = text, callback_data, url


class InlineKeyboardMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard

    def flat(self):
        return [b for row in self.inline_keyboard for b in row]


class InlineKeyboardBuilder:
    def __init__(self):
        self.rows: list[list[InlineKeyboardButton]] = []

    def row(self, *buttons):
        assert buttons, "bo'sh qator"
        assert len(buttons) <= 8, "qatorda 8 tadan ko'p tugma"
        self.rows.append(list(buttons))
        return self

    def button(self, text, callback_data=None, url=None, **kw):
        self.rows.append([InlineKeyboardButton(text, callback_data=callback_data, url=url)])
        return self

    def as_markup(self):
        return InlineKeyboardMarkup(self.rows)


class InputMediaPhoto:
    def __init__(self, media, caption=None, **kw):
        self.media, self.caption = media, caption


class InputMediaVideo:
    def __init__(self, media, caption=None, **kw):
        self.media, self.caption = media, caption


class ReplyParameters:
    def __init__(self, message_id, allow_sending_without_reply=None, **kw):
        self.message_id = message_id


class BotCommand:
    def __init__(self, command, description):
        assert re.fullmatch(r"[a-z0-9_]{1,32}", command), command
        assert 3 <= len(description) <= 256
        self.command, self.description = command, description


class BotCommandScopeAllPrivateChats:
    pass


class BotCommandScopeChat:
    def __init__(self, chat_id):
        self.chat_id = chat_id


class User:
    def __init__(self, id, first_name="User", username=None, is_bot=False):
        self.id, self.first_name, self.username, self.is_bot = id, first_name, username, is_bot


class Chat:
    def __init__(self, id, type="private", title=None, username=None, invite_link=None):
        self.id, self.type, self.title, self.username, self.invite_link = id, type, title, username, invite_link


class Media:
    def __init__(self, **kw):
        self.file_id = kw.pop("file_id", f"FID{next(_ids)}")
        self.file_unique_id = kw.pop("file_unique_id", "U" + self.file_id)
        self.file_size = kw.pop("file_size", 1000)
        self.__dict__.update(kw)


class Message(TelegramObject):
    def __init__(self, bot, chat, from_user, text=None, **kw):
        self.bot = bot
        self.message_id = next(_ids)
        self.chat, self.from_user, self.text = chat, from_user, text
        self.caption = kw.pop("caption", None)
        self.reply_markup = kw.pop("reply_markup", None)
        self.voice = self.audio = self.video = self.video_note = self.document = self.photo = None
        self.forward_origin = None
        self.deleted = False
        self.__dict__.update(kw)

    @property
    def html_text(self):
        return self.text

    async def answer(self, text, reply_markup=None, **kw):
        return await self.bot.send_message(self.chat.id, text, reply_markup=reply_markup, **kw)

    reply = answer

    async def answer_photo(self, photo, caption=None, reply_markup=None, **kw):
        return await self.bot.send_photo(self.chat.id, photo, caption=caption, reply_markup=reply_markup, **kw)

    async def edit_text(self, text, reply_markup=None, **kw):
        if self.deleted:
            raise TelegramBadRequest("message to edit not found")
        if text == self.text and _markup_sig(reply_markup) == _markup_sig(self.reply_markup):
            raise TelegramBadRequest("message is not modified")
        self.text, self.reply_markup = text, reply_markup
        return self

    async def edit_reply_markup(self, reply_markup=None, **kw):
        if self.deleted:
            raise TelegramBadRequest("message to edit not found")
        if _markup_sig(reply_markup) == _markup_sig(self.reply_markup):
            raise TelegramBadRequest("message is not modified")
        self.reply_markup = reply_markup
        return self

    async def delete(self):
        if self.deleted:
            raise TelegramBadRequest("message to delete not found")
        self.deleted = True
        return True


def _markup_sig(m):
    if m is None:
        return None
    return tuple(tuple((b.text, b.callback_data, b.url) for b in row) for row in m.inline_keyboard)


class CallbackQuery(TelegramObject):
    def __init__(self, bot, from_user, message, data):
        self.bot, self.from_user, self.message, self.data = bot, from_user, message, data
        self.id = str(next(_ids))
        self.answers: list[tuple[Any, bool]] = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append((text, show_alert))
        self.bot.callback_answers.append((self.from_user.id, text, show_alert))
        return True


class ChatMemberUpdated(TelegramObject):
    def __init__(self, bot, chat, from_user, status):
        self.bot, self.chat, self.from_user = bot, chat, from_user
        self.new_chat_member = types.SimpleNamespace(status=status)


class InaccessibleMessage(TelegramObject):
    def __init__(self, chat):
        self.chat, self.message_id, self.date = chat, 1, 0


# ============================================================ bot
class FakeSession:
    async def close(self):
        pass


class Bot:
    def __init__(self, token=None, session=None, default=None, **kw):
        self.token, self.session, self.default = token, session or FakeSession(), default
        self.id = 999
        self.username = "navotestbot"
        self.outbox: list[Message] = []
        self.deleted: list[Message] = []
        self.callback_answers: list[tuple] = []
        self.files: dict[str, str] = {}              # file_id -> tur
        self.members: dict[tuple[int, int], str] = {}
        self.broken_chats: set[int] = set()
        self.known_chats: dict[Any, Chat] = {}
        self.blocked: set[int] = set()
        self.retry_after_once: set[int] = set()
        self.commands: dict[Any, list[BotCommand]] = {}
        self.description = self.short_description = None
        self.webhook_deleted = False
        self.download_bytes = b"FAKE-MEDIA"
        self.download_limit = 20 * 1024 * 1024

    # ---- yordamchilar
    def _new(self, chat_id, text=None, **kw) -> Message:
        if chat_id in self.blocked:
            raise TelegramForbiddenError("bot was blocked by the user")
        m = Message(self, Chat(chat_id, "private" if chat_id > 0 else "supergroup"),
                    User(self.id, "bot", self.username, True), text=text, **kw)
        self.outbox.append(m)
        return m

    @staticmethod
    def _check_len(text, limit, what):
        if text is not None and len(text) > limit:
            raise TelegramBadRequest(f"{what} too long ({len(text)}>{limit})")

    def _check_file(self, f, kind):
        if isinstance(f, FSInputFile):
            if not os.path.exists(f.path):
                raise AssertionError(f"yuborilayotgan fayl mavjud emas (erta o'chirilgan?): {f.path}")
            if os.path.getsize(f.path) == 0:
                raise TelegramBadRequest("file must be non-empty")
            fid = f"{kind[:3].upper()}-{next(_ids)}"
            self.files[fid] = kind
            return fid
        if f not in self.files:
            raise TelegramBadRequest("wrong file identifier/HTTP URL specified")
        return f

    # ---- API
    async def me(self):
        return await self.get_me()

    async def get_me(self):
        return User(self.id, "Navo", self.username, True)

    me = get_me

    async def delete_webhook(self, **kw):
        self.webhook_deleted = True

    async def set_my_commands(self, commands, scope=None, **kw):
        key = scope.chat_id if isinstance(scope, BotCommandScopeChat) else type(scope).__name__
        self.commands[key] = commands

    async def set_my_description(self, d=None, **kw):
        self._check_len(d, 512, "description")
        self.description = d

    async def set_my_short_description(self, d=None, **kw):
        self._check_len(d, 120, "short description")
        self.short_description = d

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        assert isinstance(text, str) and text.strip(), "bo'sh matn yuborib bo'lmaydi"
        self._check_len(text, 4096, "message")
        return self._new(chat_id, text, reply_markup=reply_markup)

    async def send_chat_action(self, chat_id, action, **kw):
        return True

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, **kw):
        self._check_len(caption, 1024, "caption")
        if kw.get("thumbnail") is not None:
            self._check_file(kw["thumbnail"], "thumb")
        fid = self._check_file(audio, "audio")
        m = self._new(chat_id, None, caption=caption, reply_markup=reply_markup)
        m.audio = Media(file_id=fid, file_unique_id="u" + fid, title=kw.get("title"),
                        performer=kw.get("performer"), duration=kw.get("duration"),
                        file_size=os.path.getsize(audio.path) if isinstance(audio, FSInputFile) else 1000)
        return m

    async def send_video(self, chat_id, video, caption=None, reply_markup=None, **kw):
        self._check_len(caption, 1024, "caption")
        fid = self._check_file(video, "video")
        m = self._new(chat_id, None, caption=caption, reply_markup=reply_markup)
        m.video = Media(file_id=fid, file_name=None, duration=kw.get("duration"))
        return m

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        self._check_len(caption, 1024, "caption")
        if isinstance(photo, FSInputFile) and os.path.getsize(photo.path) > 10 * 1024 * 1024:
            raise TelegramBadRequest("PHOTO_INVALID_DIMENSIONS / file too big for photo")
        fid = self._check_file(photo, "photo")
        m = self._new(chat_id, None, caption=caption, reply_markup=reply_markup)
        m.photo = [Media(file_id=fid)]
        return m

    async def send_document(self, chat_id, document, caption=None, reply_markup=None, **kw):
        fid = self._check_file(document, "document")
        m = self._new(chat_id, None, caption=caption, reply_markup=reply_markup)
        m.document = Media(file_id=fid)
        return m

    async def send_media_group(self, chat_id, media, **kw):
        assert 2 <= len(media) <= 10, f"albom 2..10 ta bo'lishi kerak, {len(media)}"
        out = []
        for it in media:
            kind = "photo" if isinstance(it, InputMediaPhoto) else "video"
            self._check_len(it.caption, 1024, "caption")
            fid = self._check_file(it.media, kind)
            m = self._new(chat_id, None, caption=it.caption)
            if kind == "photo":
                m.photo = [Media(file_id=fid)]
            else:
                m.video = Media(file_id=fid)
            out.append(m)
        return out

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        if chat_id in self.retry_after_once:
            self.retry_after_once.discard(chat_id)
            raise TelegramRetryAfter(0)
        return self._new(chat_id, f"copy:{from_chat_id}:{message_id}")

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.broken_chats:
            raise TelegramBadRequest("Bad Request: chat not found")
        return types.SimpleNamespace(status=self.members.get((chat_id, user_id), "left"), is_member=False)

    async def get_chat(self, ref):
        if ref not in self.known_chats:
            raise TelegramBadRequest("Bad Request: chat not found")
        return self.known_chats[ref]

    async def create_chat_invite_link(self, chat_id, **kw):
        return types.SimpleNamespace(invite_link=f"https://t.me/+invite{abs(chat_id)}")

    async def download(self, obj, destination=None, **kw):
        size = getattr(obj, "file_size", 0) or 0
        if size > self.download_limit:
            raise TelegramBadRequest("file is too big")
        Path(destination).write_bytes(self.download_bytes)


# ============================================================ filtrlar
class MF:
    """magic-filter (F) taqlidi."""

    def __init__(self, fn=lambda o: o):
        self.fn = fn

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        fn = self.fn

        def get(o):
            v = fn(o)
            return getattr(v, name, None) if v is not None else None
        return MF(get)

    def __eq__(self, other):
        fn = self.fn
        return MF(lambda o: fn(o) == other)

    __hash__ = None

    def startswith(self, p):
        fn = self.fn
        return MF(lambda o: isinstance(fn(o), str) and fn(o).startswith(p))

    def regexp(self, pat):
        c, fn = re.compile(pat), self.fn
        return MF(lambda o: isinstance(fn(o), str) and c.match(fn(o)) is not None)

    def __or__(self, other):
        fn = self.fn
        return MF(lambda o: bool(fn(o)) or bool(other.fn(o)))

    def __and__(self, other):
        fn = self.fn
        return MF(lambda o: bool(fn(o)) and bool(other.fn(o)))

    def __invert__(self):
        fn = self.fn
        return MF(lambda o: not fn(o))

    def check(self, o):
        return bool(self.fn(o))


F = MF()


class BaseFilter:
    pass


class Command:
    def __init__(self, *commands, **kw):
        self.commands = [c.lstrip("/").lower() for c in commands]

    def matches(self, event, bot_username="navotestbot"):
        text = getattr(event, "text", None)
        if not text or not text.startswith("/"):
            return False
        cmd = text.split()[0][1:].split("@")[0].lower()
        return cmd in self.commands


def CommandStart(**kw):
    return Command("start")


class BaseMiddleware:
    pass


# ============================================================ FSM
class State:
    def __init__(self):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = f"{owner.__name__}:{name}"


class StatesGroup:
    pass


class MemoryStorage:
    def __init__(self):
        self.states: dict[tuple, str | None] = {}
        self.data: dict[tuple, dict] = {}


class FSMContext:
    def __init__(self, storage, key):
        self.storage, self.key = storage, key

    async def set_state(self, state):
        self.storage.states[self.key] = state.name if isinstance(state, State) else state

    async def get_state(self):
        return self.storage.states.get(self.key)

    async def update_data(self, **kw):
        self.storage.data.setdefault(self.key, {}).update(kw)

    async def get_data(self):
        return dict(self.storage.data.get(self.key, {}))

    async def clear(self):
        self.storage.states.pop(self.key, None)
        self.storage.data.pop(self.key, None)


# ============================================================ router / dispatcher
class Observer:
    def __init__(self, name):
        self.name, self.handlers, self.filters, self.outer = name, [], [], []

    def __call__(self, *filters):
        def deco(fn):
            self.handlers.append((filters, fn))
            return fn
        return deco

    def filter(self, *f):
        self.filters.extend(f)

    def outer_middleware(self, mw):
        self.outer.append(mw)


class Router:
    def __init__(self, name=None):
        self.name = name
        self.message = Observer("message")
        self.callback_query = Observer("callback_query")
        self.my_chat_member = Observer("my_chat_member")
        self.routers: list[Router] = []

    def include_router(self, r):
        self.routers.append(r)

    def walk(self):
        yield self
        for r in self.routers:
            yield from r.walk()


async def _inject(fn, event, data, first=True):
    """aiogram kabi: birinchi argument — event, qolganlari nomi bo'yicha data dan."""
    target = fn.__call__ if not inspect.isfunction(fn) and not inspect.ismethod(fn) else fn
    sig = inspect.signature(target)
    params = list(sig.parameters.values())
    args, kwargs = [], {}
    has_kw = any(p.kind == p.VAR_KEYWORD for p in params)
    for i, p in enumerate(params):
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if i == 0 and first:
            args.append(event)
        elif p.name in data:
            kwargs[p.name] = data[p.name]
        elif p.default is p.empty:
            raise TypeError(f"{getattr(fn, '__qualname__', fn)}: '{p.name}' argumenti uchun qiymat yo'q "
                            f"(mavjud: {sorted(data)})")
    if has_kw:
        for k, v in data.items():
            kwargs.setdefault(k, v)
    res = target(*args, **kwargs)
    return await res if inspect.isawaitable(res) else res


class Dispatcher(Router):
    def __init__(self, storage=None, **workflow):
        super().__init__("dp")
        self.storage = storage or MemoryStorage()
        self.workflow = workflow
        self.errors: list[str] = []
        self.polling_started = False
        self.handled = 0

    def resolve_used_update_types(self):
        return ["message", "callback_query", "my_chat_member"]

    async def start_polling(self, bot, **kw):
        self.polling_started = True
        self.polling_kw = kw

    async def _match(self, flt, event, data):
        if isinstance(flt, MF):
            return flt.check(event)
        if isinstance(flt, Command):
            return flt.matches(event)
        if isinstance(flt, State):
            return await data["state"].get_state() == flt.name
        if isinstance(flt, BaseFilter):
            return bool(await _inject(flt, event, data))
        raise TypeError(f"noma'lum filtr: {flt!r}")

    async def _propagate(self, kind, event, data):
        for router in self.walk():
            obs = getattr(router, kind)
            for filters, fn in obs.handlers:
                ok = True
                for f in list(obs.filters) + list(filters):
                    if not await self._match(f, event, data):
                        ok = False
                        break
                if ok:
                    await _inject(fn, event, data)
                    return None
        return UNHANDLED

    async def _chain(self, mws, kind, event, data):
        if not mws:
            return await self._propagate(kind, event, data)

        async def nxt(e, d):
            return await self._chain(mws[1:], kind, e, d)
        return await mws[0](nxt, event, data)

    async def feed(self, event):
        if isinstance(event, Message):
            kind, chat, user = "message", event.chat, event.from_user
        elif isinstance(event, CallbackQuery):
            kind, chat, user = "callback_query", event.message.chat, event.from_user
        else:
            kind, chat, user = "my_chat_member", event.chat, event.from_user
        data = dict(self.workflow)
        data.update(bot=event.bot, event_from_user=user, event_chat=chat,
                    state=FSMContext(self.storage, (chat.id, user.id)))
        mws = list(getattr(self, kind).outer)
        self.handled += 1
        try:
            return await self._chain(mws, kind, event, data)
        except Exception:  # noqa: BLE001  (aiogram ham xatoni log qilib davom etadi)
            self.errors.append(traceback.format_exc())
            return None


# ============================================================ aiohttp / yt-dlp / shazamio / aiosqlite
class ClientTimeout:
    def __init__(self, total=None):
        self.total = total


class FakeResp:
    def __init__(self, payload=None, body=b"BINARY", status=200):
        self.payload, self.body, self.status = payload, body, status
        outer = self

        class Content:
            async def iter_chunked(self, n):
                for i in range(0, len(outer.body), n):
                    yield outer.body[i:i + n]
        self.content = Content()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self, content_type=None):
        return self.payload

    async def text(self, errors=None):
        return self.payload if isinstance(self.payload, str) else ""


class ClientSession:
    """aiohttp.ClientSession taqlidi. Sinfning `routes` lug'ati orqali javoblar beriladi."""
    routes: dict[tuple[str, str], FakeResp] = {}
    requests: list[tuple[str, str]] = []

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _resp(self, method, url):
        ClientSession.requests.append((method, url))
        for (m, prefix), r in ClientSession.routes.items():
            if m == method and url.startswith(prefix):
                return r
        return FakeResp(status=404)

    def post(self, url, **kw):
        return self._resp("POST", url)

    def get(self, url, **kw):
        return self._resp("GET", url)


class AiosqliteShim:
    pass


def _make_aiosqlite():
    mod = types.ModuleType("aiosqlite")
    mod.Row = sqlite3.Row

    class Cur:
        def __init__(self, c):
            self.c = c

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def fetchone(self):
            return self.c.fetchone()

        async def fetchall(self):
            return self.c.fetchall()

    class Conn:
        def __init__(self, path):
            object.__setattr__(self, "c", sqlite3.connect(path, check_same_thread=False))

        def __setattr__(self, k, v):
            object.__setattr__(self, k, v)
            if k == "row_factory":
                self.c.row_factory = v

        async def executescript(self, x):
            self.c.executescript(x)

        def execute(self, sql, args=()):
            cur = self.c.execute(sql, args)

            class W:
                def __await__(w):
                    async def f():
                        return cur
                    return f().__await__()

                async def __aenter__(w):
                    return Cur(cur)

                async def __aexit__(w, *a):
                    return False
            return W()

        async def commit(self):
            self.c.commit()

        async def close(self):
            self.c.close()

    async def connect(path):
        return Conn(path)
    mod.connect = connect
    return mod


class FakeShazam:
    recognize_result: dict | None = {"track": {"title": "Onam chiroyli", "subtitle": "Gulsanam Mamazoitova", "key": "1"}}
    fail = False
    calls = 0

    async def recognize(self, path):
        FakeShazam.calls += 1
        if FakeShazam.fail:
            raise RuntimeError("shazam down")
        return FakeShazam.recognize_result or {}

    async def top_country_tracks(self, cc, limit=200, start_from=0):
        if FakeShazam.fail:
            raise RuntimeError("shazam down")
        return {"tracks": [{"title": f"Song{i}", "subtitle": f"Artist{i}"} for i in range(limit)]}


def install():
    """Soxta modullarni sys.modules ga o'rnatadi (aiogram, aiohttp, yt_dlp, shazamio, aiosqlite)."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class Enum(str):
        pass

    class ChatMemberStatus:
        MEMBER, ADMINISTRATOR, CREATOR, RESTRICTED, LEFT, KICKED = (
            "member", "administrator", "creator", "restricted", "left", "kicked")

    class ParseMode:
        HTML = "HTML"

    class DefaultBotProperties:
        def __init__(self, **kw):
            self.kw = kw

    class AiohttpSession:
        def __init__(self, api=None, timeout=60.0, **kw):
            self.api, self.timeout = api, timeout

        async def close(self):
            pass

    class TelegramAPIServer:
        def __init__(self, base, is_local=False):
            self.base, self.is_local = base, is_local

        @classmethod
        def from_base(cls, base, is_local=False):
            return cls(base, is_local)

    mod("aiogram", Bot=Bot, Dispatcher=Dispatcher, F=F, Router=Router, BaseMiddleware=BaseMiddleware)
    mod("aiogram.client")
    mod("aiogram.client.default", DefaultBotProperties=DefaultBotProperties)
    mod("aiogram.client.session")
    mod("aiogram.client.session.aiohttp", AiohttpSession=AiohttpSession)
    mod("aiogram.client.telegram", TelegramAPIServer=TelegramAPIServer)
    mod("aiogram.enums", ParseMode=ParseMode, ChatMemberStatus=ChatMemberStatus)
    mod("aiogram.exceptions", TelegramBadRequest=TelegramBadRequest,
        TelegramForbiddenError=TelegramForbiddenError, TelegramRetryAfter=TelegramRetryAfter)
    mod("aiogram.filters", BaseFilter=BaseFilter, Command=Command, CommandStart=CommandStart)
    mod("aiogram.fsm")
    mod("aiogram.fsm.context", FSMContext=FSMContext)
    mod("aiogram.fsm.state", State=State, StatesGroup=StatesGroup)
    mod("aiogram.fsm.storage")
    mod("aiogram.fsm.storage.memory", MemoryStorage=MemoryStorage)
    mod("aiogram.types", CallbackQuery=CallbackQuery, ChatMemberUpdated=ChatMemberUpdated, FSInputFile=FSInputFile,
        InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
        InputMediaPhoto=InputMediaPhoto, InputMediaVideo=InputMediaVideo, Message=Message,
        ReplyParameters=ReplyParameters, BotCommand=BotCommand, TelegramObject=TelegramObject,
        BotCommandScopeAllPrivateChats=BotCommandScopeAllPrivateChats, BotCommandScopeChat=BotCommandScopeChat,
        InaccessibleMessage=InaccessibleMessage, LinkPreviewOptions=lambda **kw: types.SimpleNamespace(**kw))
    mod("aiogram.utils")
    mod("aiogram.utils.keyboard", InlineKeyboardBuilder=InlineKeyboardBuilder)
    mod("aiohttp", ClientSession=ClientSession, ClientTimeout=ClientTimeout)
    mod("shazamio", Shazam=FakeShazam)
    sys.modules["aiosqlite"] = _make_aiosqlite()
    from . import fake_ytdlp  # noqa: WPS433
    fake_ytdlp.install()
