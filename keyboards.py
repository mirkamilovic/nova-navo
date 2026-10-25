from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .app import App
from .services.media import SearchItem, fmt_duration, split_title
from .services.shazam import COUNTRIES
from .texts import LANGS, REGIONS, THEMES

PAGE = 5


def add_group_btn(app: App, lang: str) -> Btn:
    return Btn(
        text=app.texts.get("btn_add_group", lang),
        url=f"https://t.me/{app.bot_username}?startgroup=true",
    )


def audio_kb(app: App, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(Btn(text="❤️/💔", callback_data="lk"), Btn(text="🎛", callback_data="fx"))
    b.row(add_group_btn(app, lang))
    return b.as_markup()


def video_kb(app: App, lang: str, job_id: str | None, extract: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(Btn(text=app.texts.get("btn_save", lang), callback_data="sv"))
    if extract and job_id:
        b.row(Btn(text=app.texts.get("btn_extract", lang), callback_data=f"ea:{job_id}"))
    b.row(add_group_btn(app, lang))
    return b.as_markup()


def fx_kb(effects: dict[str, tuple[str, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, (label, _f) in effects.items():
        b.row(Btn(text=label, callback_data=f"fe:{code}"))
    b.row(Btn(text="⬅️ Ortga", callback_data="fb"))
    return b.as_markup()


# ---------------------------------------------------------------- qidiruv natijasi
def search_view(app: App, lang: str, theme: str, sid: str, items: list[SearchItem],
                page: int, mode: str) -> tuple[str, InlineKeyboardMarkup]:
    import html

    head_emoji = app.theme(theme)[1]
    first_perf, first_track = split_title(items[0].title, items[0].channel)
    lines = [f"{head_emoji} <b>{html.escape(first_perf)} — {html.escape(first_track)}</b>\n"]
    start = page * PAGE
    chunk = items[start:start + PAGE]
    for i, it in enumerate(chunk, start + 1):
        lines.append(f"{i}. {html.escape(it.title[:90])} <b>{fmt_duration(it.duration)}</b>")
    text = "\n".join(lines)

    b = InlineKeyboardBuilder()
    other = "v" if mode == "a" else "a"
    toggle = app.texts.get("btn_video", lang) if mode == "a" else app.texts.get("btn_audio", lang)
    b.row(Btn(text=toggle, callback_data=f"sm:{sid}:{page}:{other}"))
    b.row(*[Btn(text=str(i), callback_data=f"sd:{sid}:{i - 1}:{mode}")
            for i in range(start + 1, start + len(chunk) + 1)])
    pages = (len(items) + PAGE - 1) // PAGE
    nav = []
    if page > 0:
        nav.append(Btn(text="⬅️", callback_data=f"sp:{sid}:{page - 1}:{mode}"))
    if page + 1 < pages:
        nav.append(Btn(text="➡️", callback_data=f"sp:{sid}:{page + 1}:{mode}"))
    if nav:
        b.row(*nav)
    b.row(Btn(text="↩️ TOP Popular Songs", callback_data="ch:t:UZ:0"))
    return text, b.as_markup()


# ---------------------------------------------------------------- reyting
CHART_PAGE = 10


def chart_view(kind: str, cc: str, items: list[dict], page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    row = []
    for code, flag, _w in COUNTRIES:
        row.append(Btn(text=flag + (" ✅" if code == cc else ""), callback_data=f"ch:{kind}:{code}:0"))
    b.row(*row)
    start = page * CHART_PAGE
    for i, it in enumerate(items[start:start + CHART_PAGE], start):
        b.row(Btn(text=it["label"][:60], callback_data=f"cs:{kind}:{cc}:{i}"))
    pages = (len(items) + CHART_PAGE - 1) // CHART_PAGE
    nav = []
    if page > 0:
        nav.append(Btn(text="⬅️", callback_data=f"ch:{kind}:{cc}:{page - 1}"))
    if page + 1 < pages:
        nav.append(Btn(text="➡️", callback_data=f"ch:{kind}:{cc}:{page + 1}"))
    if nav:
        b.row(*nav)
    return b.as_markup()


# ---------------------------------------------------------------- sozlamalar
def settings_kb(app: App, lang: str, region: str | None, theme: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(Btn(text="🌐 Til", callback_data="st:lang"))
    b.row(Btn(text=f"🏙 Viloyat: {region or '—'}", callback_data="st:region"))
    b.row(Btn(text=f"🎨 Mavzu: {THEMES.get(theme, THEMES['default'])[0]}", callback_data="st:theme"))
    b.row(Btn(text="❌ Yopish", callback_data="st:close"))
    return b.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, name in LANGS.items():
        b.row(Btn(text=name, callback_data=f"sl:{code}"))
    b.row(Btn(text="⬅️ Ortga", callback_data="st:back"))
    return b.as_markup()


def region_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(0, len(REGIONS), 2):
        b.row(*[Btn(text=REGIONS[j], callback_data=f"sr:{j}") for j in range(i, min(i + 2, len(REGIONS)))])
    b.row(Btn(text="⬅️ Ortga", callback_data="st:back"))
    return b.as_markup()


def theme_kb(current: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, (name, _h, _l) in THEMES.items():
        b.row(Btn(text=name + (" ✅" if code == current else ""), callback_data=f"sth:{code}"))
    b.row(Btn(text="⬅️ Ortga", callback_data="st:back"))
    return b.as_markup()


# ---------------------------------------------------------------- playlist
LIST_PAGE = 10


def list_kb(prefix: str, ids: list[int], page: int, total: int, delete_prefix: str | None = None) -> InlineKeyboardMarkup:
    """prefix: 'mp' (audio) yoki 'vp' (video). ids — joriy sahifadagi yozuv id lari."""
    b = InlineKeyboardBuilder()
    nums = [Btn(text=str(page * LIST_PAGE + i + 1), callback_data=f"{prefix}:{rid}") for i, rid in enumerate(ids)]
    for i in range(0, len(nums), 5):
        b.row(*nums[i:i + 5])
    pages = (total + LIST_PAGE - 1) // LIST_PAGE
    nav = []
    kind = "ml" if prefix == "mp" else "vl"
    if page > 0:
        nav.append(Btn(text="⬅️", callback_data=f"{kind}:{page - 1}"))
    if page + 1 < pages:
        nav.append(Btn(text="➡️", callback_data=f"{kind}:{page + 1}"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def sub_kb(app: App, lang: str, channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(Btn(text=f"{app.texts.get('btn_subscribe', lang)} · {ch['title'][:30]}", url=ch["url"]))
    b.row(Btn(text=app.texts.get("btn_confirm", lang), callback_data="sub:ok"))
    return b.as_markup()
