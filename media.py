"""Yuklash xizmati: yt-dlp (asosiy), cobalt (zaxira), qidiruv, ffmpeg yordamchilari."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urlparse

import aiohttp
import yt_dlp

from ..config import Config
from ..db import Database

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"(^|\.)(instagram\.com|instagr\.am)$")),
    ("tiktok", re.compile(r"(^|\.)(tiktok\.com)$")),
    ("youtube", re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$")),
    ("snapchat", re.compile(r"(^|\.)(snapchat\.com)$")),
    ("likee", re.compile(r"(^|\.)(likee\.video|likee\.com|l\.likee\.video)$")),
    ("pinterest", re.compile(r"(^|\.)(pinterest\.[a-z.]+|pin\.it)$")),
    ("threads", re.compile(r"(^|\.)(threads\.net|threads\.com)$")),
    ("facebook", re.compile(r"(^|\.)(facebook\.com|fb\.watch|fb\.com)$")),
    ("twitter", re.compile(r"(^|\.)(twitter\.com|x\.com)$")),
]
COOKIE_PLATFORMS = ("youtube", "instagram", "tiktok", "facebook", "twitter", "threads")

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VID_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUD_EXT = {".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wav"}

VIDEO_TIERS = [
    "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
    "bv*[height<=720]+ba/b[height<=720]/b",
    "bv*[height<=480]+ba/b[height<=480]/b",
    "bv*[height<=360]+ba/b[height<=360]/w",
]

AUDIO_EFFECTS: dict[str, tuple[str, str]] = {
    "bass": ("🔊 Bass boost", "bass=g=10,acompressor=threshold=0.3:ratio=3"),
    "fast": ("⚡ Tezlashtirilgan", "atempo=1.25"),
    "slow": ("🌊 Slowed + reverb", "asetrate=44100*0.85,aresample=44100,aecho=0.8:0.88:60|1000:0.3|0.2"),
    "8d": ("🎧 8D", "apulsator=hz=0.12"),
}


class MediaError(Exception):
    """kind: login | private | unsupported | toobig | toolong | failed"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass
class MediaFile:
    path: Path
    kind: str                      # video | photo | audio
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumb: Path | None = None


@dataclass
class MediaResult:
    files: list[MediaFile]
    workdir: Path
    platform: str
    key: str
    title: str = ""
    performer: str = ""
    duration: int = 0
    source: str = "yt-dlp"

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


@dataclass
class SearchItem:
    id: str
    title: str
    duration: int
    channel: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "duration": self.duration, "channel": self.channel}


# ---------------------------------------------------------------- yordamchilar
def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;)") for u in URL_RE.findall(text or "")]


def detect_platform(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for name, rx in PLATFORM_PATTERNS:
        if rx.search(host):
            return name
    return None


def youtube_id(url: str) -> str | None:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.endswith("youtu.be"):
        return p.path.strip("/").split("/")[0] or None
    if "youtube" in host:
        if p.path == "/watch":
            return (parse_qs(p.query).get("v") or [None])[0]
        m = re.match(r"^/(shorts|embed|live|v)/([\w-]{6,})", p.path)
        if m:
            return m.group(2)
    return None


def canonical(url: str) -> str:
    yid = youtube_id(url)
    if yid:
        return f"youtube:{yid}"
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    return f"{host}{p.path.rstrip('/')}"


_JUNK = re.compile(
    r"\s*[\(\[](official|lyrics?|lyric video|video|audio|music video|hd|4k|clip|klip|"
    r"yangi|premyera|premiere|visuali[sz]er|live|remastered)[^\)\]]*[\)\]]",
    re.I,
)


def split_title(title: str, uploader: str = "") -> tuple[str, str]:
    """(ijrochi, nom). Ijrochi topilmasa kanal nomi ishlatiladi."""
    t = _JUNK.sub("", title or "").strip()
    uploader = re.sub(r"\s*-\s*Topic$", "", uploader or "").strip()
    for sep in (" - ", " — ", " – ", " | "):
        if sep in t:
            a, b = t.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip()[:64], b.strip()[:128]
    return uploader[:64] or "Unknown", t[:128] or "Audio"


def fmt_duration(sec: int | float | None) -> str:
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _classify(err: str) -> str:
    e = err.lower()
    if any(x in e for x in ("login", "sign in", "log in", "cookies", "confirm you", "not a bot", "rate-limit", "rate limit")):
        return "login"
    if any(x in e for x in ("private", "not available", "unavailable", "removed", "deleted")):
        return "private"
    if "unsupported url" in e:
        return "unsupported"
    if "does not pass filter" in e or "too long" in e:
        return "toolong"
    return "failed"


# ---------------------------------------------------------------- ffmpeg
async def _ffmpeg(*args: str, timeout: int = 300) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    if proc.returncode != 0:
        log.warning("ffmpeg xato: %s", (err or b"").decode(errors="ignore")[:300])
        return False
    return True


async def make_thumb(src: Path, dst: Path) -> Path | None:
    ok = await _ffmpeg(
        "-i", str(src), "-frames:v", "1",
        "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
        "-q:v", "6", str(dst), timeout=60,
    )
    return dst if ok and dst.exists() and dst.stat().st_size < 200_000 else None


async def extract_audio_file(src: Path, dst: Path) -> bool:
    return await _ffmpeg("-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(dst))


async def apply_effect(src: Path, dst: Path, effect: str) -> bool:
    flt = AUDIO_EFFECTS[effect][1]
    return await _ffmpeg("-i", str(src), "-vn", "-af", flt, "-c:a", "libmp3lame", "-b:a", "192k", str(dst))


# ---------------------------------------------------------------- servis
class MediaService:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self.sem = asyncio.Semaphore(cfg.max_parallel)

    # ----- cookies -----
    def cookie_path(self, platform: str) -> Path:
        return self.cfg.cookies_dir / f"{platform}.txt"

    def cookie_for(self, platform: str | None) -> str | None:
        if not platform:
            return None
        p = self.cookie_path(platform)
        if p.exists() and p.stat().st_size > 20:
            return str(p)
        # Threads cookies Instagram bilan umumiy
        if platform == "threads" and self.cookie_path("instagram").exists():
            return str(self.cookie_path("instagram"))
        return None

    def cookie_status(self) -> dict[str, bool]:
        return {p: self.cookie_for(p) is not None for p in COOKIE_PLATFORMS}

    # ----- ish papkasi -----
    @asynccontextmanager
    async def workspace(self) -> AsyncIterator[Path]:
        d = self.cfg.tmp_dir / uuid.uuid4().hex[:12]
        d.mkdir(parents=True, exist_ok=True)
        try:
            yield d
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def new_workdir(self) -> Path:
        d = self.cfg.tmp_dir / uuid.uuid4().hex[:12]
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ----- yt-dlp opsiyalari -----
    def _base_opts(self, platform: str | None, workdir: Path) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": str(workdir / "%(id).60B.%(ext)s"),
            "restrictfilenames": True,
            "merge_output_format": "mp4",
            "socket_timeout": 25,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "noplaylist": True,
            "js_runtimes": {"node": {}, "deno": {}},
        }
        ck = self.cookie_for(platform)
        if ck:
            opts["cookiefile"] = ck
        return opts

    # ----- qidiruv -----
    def _search_sync(self, query: str, n: int) -> list[SearchItem]:
        opts = self._base_opts("youtube", self.cfg.tmp_dir)
        opts.update({"extract_flat": True, "skip_download": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
        out: list[SearchItem] = []
        seen: set[str] = set()
        for e in (info or {}).get("entries") or []:
            if not e or not e.get("id") or e["id"] in seen:
                continue
            dur = int(e.get("duration") or 0)
            if dur and (dur > 3 * 3600):
                continue
            seen.add(e["id"])
            out.append(SearchItem(
                id=e["id"], title=e.get("title") or "", duration=dur,
                channel=e.get("channel") or e.get("uploader") or "",
            ))
        return out

    async def search(self, query: str, n: int = 15) -> list[SearchItem]:
        async with self.sem:
            try:
                return await asyncio.to_thread(self._search_sync, query, n)
            except Exception as e:  # noqa: BLE001
                log.warning("qidiruv xatosi: %s", e)
                raise MediaError(_classify(str(e)), str(e)[:300]) from e

    # ----- video / rasm yuklash -----
    def _collect(self, info: dict, ydl: yt_dlp.YoutubeDL) -> list[MediaFile]:
        entries = info.get("entries") or [info]
        files: list[MediaFile] = []
        for e in entries:
            if not e:
                continue
            paths: list[tuple[Path, dict]] = []
            rds = e.get("requested_downloads") or []
            for rd in rds:
                fp = rd.get("filepath") or rd.get("_filename")
                if fp:
                    paths.append((Path(fp), e))
            if not paths:
                try:
                    paths.append((Path(ydl.prepare_filename(e)), e))
                except Exception:  # noqa: BLE001
                    continue
            for p, meta in paths:
                if not p.exists():
                    mp4 = p.with_suffix(".mp4")
                    if mp4.exists():
                        p = mp4
                    else:
                        continue
                ext = p.suffix.lower()
                kind = "photo" if ext in IMG_EXT else "audio" if ext in AUD_EXT else "video"
                files.append(MediaFile(
                    path=p, kind=kind, width=meta.get("width"), height=meta.get("height"),
                    duration=int(meta.get("duration") or 0) or None,
                ))
        return files

    def _download_sync(self, url: str, platform: str | None, workdir: Path,
                       tier: int, limit_mb: int, max_items: int) -> tuple[dict, list[MediaFile]]:
        opts = self._base_opts(platform, workdir)
        opts["format"] = VIDEO_TIERS[tier]
        opts["max_filesize"] = limit_mb * 1024 * 1024
        if platform in ("instagram", "threads", "pinterest", "twitter", "facebook"):
            opts["noplaylist"] = False
            opts["playlistend"] = max_items
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise MediaError("failed", "yt-dlp bo'sh javob qaytardi")
            files = self._collect(info, ydl)
        return info, files

    async def fetch_video(self, url: str) -> MediaResult:
        """Havola bo'yicha video/rasm(lar)ni yuklaydi. Natija `cleanup()` bilan tozalanadi."""
        platform = detect_platform(url) or "other"
        key = f"v:{canonical(url)}"
        max_items = int(await self.db.get_setting("max_playlist_items", "10") or 10)
        limit = self.cfg.upload_limit_mb
        start = 0 if self.cfg.local_api else (1 if platform == "youtube" else 0)
        workdir = self.new_workdir()
        last_err: Exception | None = None

        async with self.sem:
            for tier in range(start, len(VIDEO_TIERS)):
                try:
                    info, files = await asyncio.to_thread(
                        self._download_sync, url, platform, workdir, tier, limit, max_items
                    )
                except MediaError:
                    shutil.rmtree(workdir, ignore_errors=True)
                    raise
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    kind = _classify(str(e))
                    if "larger than max-filesize" in str(e) or "File is larger" in str(e):
                        continue
                    if kind in ("login", "private", "unsupported"):
                        break
                    log.info("yt-dlp urinish %s muvaffaqiyatsiz: %s", tier, str(e)[:200])
                    break
                files = [f for f in files if f.path.exists()]
                if not files:
                    continue
                oversize = [f for f in files if f.path.stat().st_size > limit * 1024 * 1024]
                if oversize:
                    for f in oversize:
                        f.path.unlink(missing_ok=True)
                    continue
                title = info.get("title") or ""
                performer, track = split_title(title, info.get("uploader") or "")
                return MediaResult(
                    files=files, workdir=workdir, platform=platform, key=key,
                    title=track, performer=performer,
                    duration=int(info.get("duration") or 0),
                )

            # yt-dlp ishlamadi -> zaxira usullar
            res = await self._fallbacks(url, platform, workdir, key)
            if res:
                return res

        shutil.rmtree(workdir, ignore_errors=True)
        if last_err is None:
            raise MediaError("toobig", "barcha sifatlar limitdan katta")
        raise MediaError(_classify(str(last_err)), str(last_err)[:400])

    # ----- zaxira usullar -----
    async def _fallbacks(self, url: str, platform: str, workdir: Path, key: str) -> MediaResult | None:
        cobalt = (await self.db.get_setting("cobalt_url", "")).strip()
        if cobalt:
            try:
                files = await self._cobalt(cobalt, url, workdir)
                if files:
                    return MediaResult(files=files, workdir=workdir, platform=platform,
                                       key=key, source="cobalt")
            except Exception as e:  # noqa: BLE001
                log.info("cobalt xatosi: %s", e)
        if platform == "pinterest":
            try:
                files = await self._og_image(url, workdir)
                if files:
                    return MediaResult(files=files, workdir=workdir, platform=platform,
                                       key=key, source="og")
            except Exception as e:  # noqa: BLE001
                log.info("og:image xatosi: %s", e)
        return None

    async def _download_file(self, session: aiohttp.ClientSession, url: str, dst: Path) -> None:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as r:
            r.raise_for_status()
            with dst.open("wb") as f:
                async for chunk in r.content.iter_chunked(1 << 16):
                    f.write(chunk)

    async def _cobalt(self, base: str, url: str, workdir: Path) -> list[MediaFile]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(base, json={"url": url, "videoQuality": "1080"},
                              timeout=aiohttp.ClientTimeout(total=60)) as r:
                data = await r.json(content_type=None)
            status = data.get("status")
            items: list[tuple[str, str]] = []
            if status in ("tunnel", "redirect", "stream"):
                items.append((data["url"], data.get("filename") or "file.mp4"))
            elif status == "picker":
                for i, it in enumerate(data.get("picker", [])[:10]):
                    ext = "jpg" if it.get("type") == "photo" else "mp4"
                    items.append((it["url"], f"item{i}.{ext}"))
            else:
                raise MediaError("failed", f"cobalt: {data}")
            files: list[MediaFile] = []
            limit = self.cfg.upload_limit_mb * 1024 * 1024
            for i, (u, name) in enumerate(items):
                dst = workdir / f"{i}_{re.sub(r'[^\w.\-]', '_', name)[:60]}"
                await self._download_file(s, u, dst)
                if dst.stat().st_size > limit:
                    dst.unlink(missing_ok=True)
                    continue
                ext = dst.suffix.lower()
                kind = "photo" if ext in IMG_EXT else "audio" if ext in AUD_EXT else "video"
                files.append(MediaFile(path=dst, kind=kind))
            return files

    async def _og_image(self, url: str, workdir: Path) -> list[MediaFile]:
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
        async with aiohttp.ClientSession(headers=ua) as s:
            async with s.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)) as r:
                html = await r.text(errors="ignore")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
            if not m:
                return []
            img = m.group(1).replace("&amp;", "&")
            if "pinimg" in img:
                img = re.sub(r"/\d+x(?:\d+)?/", "/originals/", img, count=1)
            dst = workdir / "pin.jpg"
            await self._download_file(s, img, dst)
            return [MediaFile(path=dst, kind="photo")]

    # ----- audio yuklash -----
    def _audio_sync(self, url: str, platform: str | None, workdir: Path) -> tuple[dict, Path | None, Path | None]:
        opts = self._base_opts(platform, workdir)
        opts.update({
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "writethumbnail": True,
            "match_filter": yt_dlp.utils.match_filter_func("duration <? 5400"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            ],
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        mp3 = next(iter(sorted(workdir.glob("*.mp3"))), None)
        thumb = next((p for p in workdir.iterdir() if p.suffix.lower() in IMG_EXT), None)
        return info or {}, mp3, thumb

    async def fetch_audio(self, url: str, key: str | None = None) -> MediaResult:
        platform = detect_platform(url) or "other"
        key = key or f"a:{canonical(url)}"
        workdir = self.new_workdir()
        async with self.sem:
            try:
                info, mp3, thumb = await asyncio.to_thread(self._audio_sync, url, platform, workdir)
            except Exception as e:  # noqa: BLE001
                shutil.rmtree(workdir, ignore_errors=True)
                raise MediaError(_classify(str(e)), str(e)[:400]) from e
            if not mp3 or not mp3.exists():
                shutil.rmtree(workdir, ignore_errors=True)
                raise MediaError("toolong" if info else "failed", "audio chiqmadi")
            if mp3.stat().st_size > self.cfg.upload_limit_mb * 1024 * 1024:
                shutil.rmtree(workdir, ignore_errors=True)
                raise MediaError("toobig", "audio katta")
            small = await make_thumb(thumb, workdir / "thumb_small.jpg") if thumb else None
            title = info.get("track") or info.get("title") or ""
            artist = info.get("artist") or info.get("creator") or ""
            if artist and info.get("track"):
                performer, track = artist.split(",")[0][:64], title[:128]
            else:
                performer, track = split_title(title, info.get("uploader") or "")
            dur = int(info.get("duration") or 0)
            return MediaResult(
                files=[MediaFile(path=mp3, kind="audio", duration=dur or None, thumb=small)],
                workdir=workdir, platform=platform, key=key,
                title=track, performer=performer, duration=dur,
            )

    async def fetch_youtube_audio(self, video_id: str) -> MediaResult:
        return await self.fetch_audio(f"https://www.youtube.com/watch?v={video_id}", key=f"a:youtube:{video_id}")
