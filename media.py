"""
Yuklash xizmati. Bitta usulga bog'lanib qolmaydi — zanjir bo'yicha sinaydi:

    cobalt  →  yt-dlp (cookies / proxy bilan)  →  instagram-embed  →  pullik API (FastSaver)

Qaysi usul ishlamasa, keyingisiga o'tadi. Hammasi muvaffaqiyatsiz bo'lsa DownloadFailed
ko'tariladi va unda har bir usulning aniq sababi bo'ladi (admin /test bilan ko'radi).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("navobot.media")

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
    "twitter": ("twitter.com", "x.com", "t.co"),
    "pinterest": ("pinterest.com", "pin.it"),
    "snapchat": ("snapchat.com",),
    "threads": ("threads.net", "threads.com"),
    "soundcloud": ("soundcloud.com",),
}
COOKIE_PLATFORMS = ("instagram", "youtube", "tiktok", "facebook", "twitter")
COOKIE_DOMAINS = {
    "instagram": [".instagram.com"],
    "youtube": [".youtube.com", ".google.com"],
    "tiktok": [".tiktok.com"],
    "facebook": [".facebook.com"],
    "twitter": [".x.com", ".twitter.com"],
}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".3gp"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ====================================================================== URL yordamchilari
def extract_url(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(").,;!?»>") if m else None


def detect_platform(url: str) -> str | None:
    host = (urlparse(url).netloc or "").lower().split("@")[-1].split(":")[0]
    for plat, hosts in PLATFORM_HOSTS.items():
        for h in hosts:
            if host == h or host.endswith("." + h):
                return plat
    return None


def normalize_url(url: str, platform: str | None) -> str:
    """Kuzatuv parametrlari (utm_source, igsh, si ...) ko'pincha xatoga sabab bo'ladi — tozalaymiz."""
    p = urlparse(url)
    path = p.path or "/"
    if platform == "instagram":
        m = re.match(r"^/(?:[A-Za-z0-9_.]+/)?(reels?|p|tv)/([A-Za-z0-9_-]+)", path)
        if m:
            kind = "reel" if m.group(1).startswith("reel") else m.group(1)
            return f"https://www.instagram.com/{kind}/{m.group(2)}/"
        return f"https://www.instagram.com{path}"
    if platform == "youtube":
        host = p.netloc.lower()
        if host.endswith("youtu.be"):
            vid = path.strip("/").split("/")[0]
            return f"https://www.youtube.com/watch?v={vid}" if vid else url
        m = re.match(r"^/(shorts|live|embed)/([A-Za-z0-9_-]{6,})", path)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(2)}" if m.group(1) != "shorts" else f"https://www.youtube.com/shorts/{m.group(2)}"
        v = parse_qs(p.query).get("v", [""])[0]
        if v:
            return f"https://www.youtube.com/watch?v={v}"
        return url
    if platform == "facebook":
        v = parse_qs(p.query).get("v", [""])[0]
        return f"https://www.facebook.com{path}?v={v}" if v else f"{p.scheme}://{p.netloc}{path}"
    if platform in ("tiktok", "twitter", "threads", "pinterest"):
        return f"{p.scheme}://{p.netloc}{path}"
    return url


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in AUDIO_EXT:
        return "audio"
    return "video"


# ====================================================================== ma'lumot turlari
class MethodError(Exception):
    """Bitta usul muvaffaqiyatsiz. reason: private|not_found|too_large|blocked|unsupported|network|config|other"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class DownloadFailed(Exception):
    def __init__(self, attempts: list[tuple[str, str, str]]):
        super().__init__("; ".join(f"{m}={r}" for m, r, _ in attempts) or "usul yo'q")
        self.attempts = attempts

    @property
    def reason(self) -> str:
        # embed — eng ishonchsiz usul: uning noaniq natijalari umumiy sababni buzmasin
        rs = [r for m, r, _d in self.attempts if not (m == "embed" and r in ("blocked", "network", "other"))]
        for key in ("private", "too_large"):
            if key in rs:
                return key
        real = [r for r in rs if r != "config"]
        if real and all(r == "not_found" for r in real):
            return "not_found"
        if "blocked" in rs or "network" in rs:
            return "blocked"
        if real and all(r == "unsupported" for r in real):
            return "unsupported"
        return "other"

    def summary(self) -> str:
        return "\n".join(f"• {m}: {r} — {d[:160]}" for m, r, d in self.attempts) or "—"


@dataclass
class MediaFile:
    path: Path
    kind: str  # video | audio | photo
    title: str = ""
    performer: str = ""
    duration: int = 0
    width: int = 0
    height: int = 0


@dataclass
class MediaResult:
    files: list[MediaFile]
    via: str
    platform: str
    workdir: Path
    attempts: list[tuple[str, str, str]] = field(default_factory=list)

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


@dataclass
class Hit:
    id: str
    title: str
    uploader: str
    duration: int
    url: str
    source: str  # youtube | soundcloud | api

    @property
    def label(self) -> str:
        m, s = divmod(int(self.duration or 0), 60)
        t = f" ({m}:{s:02d})" if self.duration else ""
        who = f" — {self.uploader}" if self.uploader else ""
        return f"{html.escape(self.title)}{html.escape(who)}{t}"


# ====================================================================== xato tasnifi
def classify_text(msg: str) -> str:
    m = (msg or "").lower()
    if any(k in m for k in ("private video", "video is private", "account is private", "this account is private",
                            "protected tweet", "members-only", "members only", "age-restricted", "age restricted",
                            "confirm your age", "error.api.content.video.private", "error.api.content.video.age")):
        return "private"
    if any(k in m for k in ("sign in to confirm", "not a bot", "login required", "log in", "rate-limit", "rate limit",
                            "too many requests", "429", "403", "forbidden", "requested content is not available",
                            "cookies", "checkpoint", "challenge", "error.api.youtube.login", "error.api.fetch.rate",
                            "error.api.rate_exceeded", "error.api.fetch.fail", "error.api.fetch.critical",
                            "decipher", "captcha", "blocked")):
        return "blocked"
    if any(k in m for k in ("unsupported url", "unsupported_url", "service.unsupported", "link.unsupported",
                            "link.invalid", "is not a valid url", "no video in this post", "there is no video")):
        return "unsupported"
    if any(k in m for k in ("too_long", "too large", "larger than", "file is larger")):
        return "too_large"
    if any(k in m for k in ("not found", "404", "unavailable", "not available", "does not exist", "removed", "deleted", "no longer available",
                            "post.unavailable", "video.unavailable", "fetch.empty")):
        return "not_found"
    if any(k in m for k in ("timed out", "timeout", "connection", "network", "name or service", "temporary failure")):
        return "network"
    if "ffmpeg" in m and ("not found" in m or "not installed" in m):
        return "config"
    return "other"


# ====================================================================== asosiy xizmat
class MediaService:
    def __init__(self, cfg: Any, db: Any):
        self.cfg = cfg
        self.db = db
        self._sem = asyncio.Semaphore(cfg.max_parallel)
        self.stats: dict[str, list[int]] = {}  # usul -> [muvaffaqiyat, xato]
        self.last_errors: dict[str, str] = {}

    # ---------------------------------------------------------------- umumiy
    @property
    def limit_bytes(self) -> int:
        return int(self.cfg.max_upload_mb) * 1024 * 1024

    def new_workdir(self) -> Path:
        d = self.cfg.tmp_dir / uuid.uuid4().hex[:12]
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    async def run(*cmd: str, timeout: float = 300) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, "", "timeout"
        except FileNotFoundError:
            return 127, "", f"{cmd[0]} topilmadi"
        return proc.returncode or 0, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")

    def _count(self, method: str, ok: bool) -> None:
        self.stats.setdefault(method, [0, 0])[0 if ok else 1] += 1

    # ---------------------------------------------------------------- cookies
    def cookie_path(self, platform: str) -> Path:
        return self.cfg.cookies_dir / f"{platform}.txt"

    def has_cookies(self, platform: str) -> bool:
        p = self.cookie_path(platform)
        return p.is_file() and p.stat().st_size > 20

    def delete_cookies(self, platform: str) -> None:
        self.cookie_path(platform).unlink(missing_ok=True)

    def save_cookies(self, platform: str, raw: str) -> int:
        """Netscape matn, JSON (EditThisCookie) yoki 'a=b; c=d' qatorini qabul qiladi. Yozuvlar sonini qaytaradi."""
        if platform not in COOKIE_PLATFORMS:
            raise ValueError("Noma'lum platforma")
        raw = (raw or "").lstrip("﻿").strip()
        if not raw:
            raise ValueError("Bo'sh matn")
        lines: list[str] = []
        if raw[0] in "[{":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON o'qilmadi: {e}") from e
            if isinstance(data, dict):
                data = data.get("cookies") or []
            for c in data:
                dom = str(c.get("domain", "")).strip()
                if not dom or not c.get("name"):
                    continue
                exp = int(float(c.get("expirationDate") or c.get("expires") or 0)) if c.get("expirationDate") or c.get("expires") else 0
                lines.append("\t".join([
                    dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path", "/") or "/",
                    "TRUE" if c.get("secure") else "FALSE", str(max(exp, 0)), str(c["name"]), str(c.get("value", "")),
                ]))
        elif "\t" in raw:
            for ln in raw.splitlines():
                s = ln.rstrip("\r")
                if not s.strip():
                    continue
                if s.startswith("#") and not s.startswith("#HttpOnly_"):
                    continue
                if len(s.split("\t")) >= 7:
                    lines.append(s)
        elif re.search(r"^\S+\s+(?:TRUE|FALSE)\s+/", raw, re.M | re.I):
            # Tab o'rniga bo'shliq bilan nusxalangan Netscape matni
            for ln in raw.splitlines():
                s2 = ln.strip()
                if not s2 or (s2.startswith("#") and not s2.startswith("#HttpOnly_")):
                    continue
                parts = re.split(r"\s+", s2, maxsplit=6)
                if len(parts) == 7:
                    lines.append("\t".join(parts))
        elif "=" in raw:
            # «Cookie:» sarlavhasi ko'rinishi: a=b; c=d
            far = int(time.time()) + 365 * 86400
            for part in raw.replace("Cookie:", "").replace("cookie:", "").split(";"):
                if "=" not in part:
                    continue
                k, v = part.strip().split("=", 1)
                for dom in COOKIE_DOMAINS[platform]:
                    lines.append("\t".join([dom, "TRUE", "/", "TRUE", str(far), k.strip(), v.strip()]))
        if not lines:
            raise ValueError(
                "Cookies o'qilmadi. Netscape formatidagi cookies.txt (brauzer kengaytmasi «Get cookies.txt LOCALLY») yuboring."
            )
        body = "# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n"
        self.cookie_path(platform).write_text(body, encoding="utf-8")
        return len(lines)

    def _cookie_copy(self, platform: str, workdir: Path) -> str | None:
        """yt-dlp cookie faylini qayta yozadi, shuning uchun nusxasi beriladi."""
        if not self.has_cookies(platform):
            return None
        dst = workdir / f"cookies_{platform}.txt"
        shutil.copyfile(self.cookie_path(platform), dst)
        return str(dst)

    # ---------------------------------------------------------------- zanjir
    def _order(self, platform: str, audio: bool) -> list[str]:
        order = [m for m in self.cfg.source_order if m in ("cobalt", "ytdlp", "embed", "api")]
        for m in ("cobalt", "ytdlp", "embed", "api"):
            if m not in order:
                order.append(m)
        # Cookies yoki proxy sozlangan bo'lsa yt-dlp ishonchliroq — birinchi o'ringa
        if "ytdlp" in order and (self.has_cookies(platform) or self.cfg.proxy):
            order.remove("ytdlp")
            order.insert(0, "ytdlp")
        return [m for m in order if self._usable(m, platform, audio)]

    def _usable(self, method: str, platform: str, audio: bool) -> bool:
        if method == "cobalt":
            return bool(self.cfg.cobalt_url)
        if method == "embed":
            return platform == "instagram" and not audio
        if method == "api":
            return bool(self.cfg.fastsaver_key)
        return True

    async def download(self, url: str, *, audio: bool = False, platform: str | None = None) -> MediaResult:
        platform = platform or detect_platform(url) or "other"
        url = normalize_url(url, platform)
        workdir = self.new_workdir()
        attempts: list[tuple[str, str, str]] = []
        async with self._sem:
            for name in self._order(platform, audio):
                t0 = time.time()
                try:
                    fn = getattr(self, f"_m_{name}")
                    files = await asyncio.wait_for(fn(url, platform, audio, workdir), self.cfg.method_timeout)
                    if not files:
                        raise MethodError("other", "bo'sh natija")
                    files = await self._finalize(files, audio)
                    self._count(name, True)
                    log.info("%s OK via %s (%.1fs): %s", platform, name, time.time() - t0, url)
                    return MediaResult(files, via=name, platform=platform, workdir=workdir, attempts=attempts)
                except MethodError as e:
                    attempts.append((name, e.reason, e.detail))
                except asyncio.TimeoutError:
                    attempts.append((name, "network", f"{self.cfg.method_timeout}s ichida tugamadi"))
                except Exception as e:  # noqa: BLE001
                    log.exception("%s usuli kutilmagan xato", name)
                    attempts.append((name, classify_text(str(e)), f"{type(e).__name__}: {e}"))
                self._count(name, False)
                self.last_errors[f"{platform}/{name}"] = f"{attempts[-1][1]}: {attempts[-1][2][:200]}"
                self._purge(workdir)
        shutil.rmtree(workdir, ignore_errors=True)
        log.warning("%s yuklanmadi: %s | %s", platform, url, attempts)
        raise DownloadFailed(attempts)

    @staticmethod
    def _purge(workdir: Path) -> None:
        for f in workdir.iterdir():
            try:
                shutil.rmtree(f) if f.is_dir() else f.unlink()
            except OSError:
                pass

    # ---------------------------------------------------------------- yakuniy ishlov (hajm, format)
    async def probe(self, path: Path) -> dict[str, Any]:
        rc, out, _e = await self.run("ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                     "-show_format", str(path), timeout=60)
        if rc != 0:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {}

    async def _finalize(self, files: list[MediaFile], audio: bool) -> list[MediaFile]:
        done: list[MediaFile] = []
        for f in files:
            if not f.path.exists() or f.path.stat().st_size == 0:
                raise MethodError("other", f"{f.path.name} bo'sh yoki yo'q")
            f.kind = kind_of(f.path)
            if audio and f.kind != "audio":
                f = await self._to_mp3(f)
            elif f.kind == "video":
                f = await self._ensure_h264(f)
            if f.path.stat().st_size > self.limit_bytes:
                raise MethodError("too_large", f"{f.path.stat().st_size // 1048576} MB > {self.cfg.max_upload_mb} MB")
            done.append(f)
        return done

    async def _to_mp3(self, f: MediaFile) -> MediaFile:
        out = f.path.with_suffix(".mp3")
        if out == f.path:
            out = f.path.with_name(f.path.stem + "_a.mp3")
        rc, _o, err = await self.run("ffmpeg", "-y", "-i", str(f.path), "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
                                     str(out), timeout=300)
        if rc != 0 or not out.exists():
            raise MethodError("config" if rc == 127 else "other", f"mp3 ga o'tkazib bo'lmadi: {err[-150:]}")
        f.path.unlink(missing_ok=True)
        info = await self.probe(out)
        f.path, f.kind = out, "audio"
        f.duration = int(float((info.get("format") or {}).get("duration") or f.duration or 0))
        return f

    async def _ensure_h264(self, f: MediaFile) -> MediaFile:
        """Telegram uchun MP4/H.264 + AAC bo'lishi kerak; bo'lmasa qayta kodlaymiz."""
        info = await self.probe(f.path)
        streams = info.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if v:
            f.width, f.height = int(v.get("width") or 0), int(v.get("height") or 0)
        f.duration = int(float((info.get("format") or {}).get("duration") or f.duration or 0))
        ok = (v is not None and v.get("codec_name") == "h264" and f.path.suffix.lower() in (".mp4", ".m4v", ".mov")
              and (a is None or a.get("codec_name") in ("aac", "mp3")) and v.get("pix_fmt", "yuv420p") == "yuv420p")
        if ok or v is None:
            return f
        out = f.path.with_name(f.path.stem + "_tg.mp4")
        rc, _o, err = await self.run(
            "ffmpeg", "-y", "-i", str(f.path), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out), timeout=600,
        )
        if rc != 0 or not out.exists():
            log.warning("transcode xatosi: %s", err[-200:])
            return f  # asl fayl bilan urinib ko'ramiz
        f.path.unlink(missing_ok=True)
        f.path = out
        return f

    # ---------------------------------------------------------------- fayl yuklab olish (HTTP)
    async def _fetch_file(self, session: Any, url: str, workdir: Path, name_hint: str | None = None,
                          proxy: str | None = None, headers: dict[str, str] | None = None) -> Path:
        async with session.get(url, proxy=proxy, headers=headers or {"User-Agent": BROWSER_UA}) as r:
            if r.status >= 400:
                raise MethodError(classify_text(str(r.status)) if r.status in (401, 403, 404, 429) else "other",
                                  f"HTTP {r.status} fayl yuklashda")
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = Path(urlparse(name_hint or "").path).suffix.lower() if name_hint else ""
            if not ext:
                ext = Path(urlparse(url).path).suffix.lower()
            if ext not in VIDEO_EXT | AUDIO_EXT | PHOTO_EXT:
                ext = mimetypes.guess_extension(ctype) or ".mp4"
                if ext == ".jpe":
                    ext = ".jpg"
            if ctype.startswith("text/") or ctype == "application/json":
                raise MethodError("other", f"fayl o'rniga {ctype} keldi")
            path = workdir / f"{uuid.uuid4().hex[:8]}{ext}"
            size = 0
            with path.open("wb") as fh:
                async for chunk in r.content.iter_chunked(256 * 1024):
                    size += len(chunk)
                    if size > self.limit_bytes:
                        fh.close()
                        path.unlink(missing_ok=True)
                        raise MethodError("too_large", f">{self.cfg.max_upload_mb} MB")
                    fh.write(chunk)
        if size == 0:
            raise MethodError("other", "bo'sh fayl keldi")
        return path

    @staticmethod
    def _session(total: float) -> Any:
        import aiohttp

        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=total))

    # ================================================================ USUL 1: cobalt
    @staticmethod
    def _cobalt_reason(code: str) -> str:
        c = code.lower()
        if "auth" in c:
            return "config"
        r = classify_text(c)
        return r if r != "other" else ("not_found" if "content" in c else "other")

    async def _m_cobalt(self, url: str, platform: str, audio: bool, workdir: Path) -> list[MediaFile]:
        base = self.cfg.cobalt_url.rstrip("/")
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "NavoBot/2.0"}
        if self.cfg.cobalt_key:
            headers["Authorization"] = f"Api-Key {self.cfg.cobalt_key}"
        qualities = ["720"] if audio else ["720", "360"]
        async with self._session(self.cfg.method_timeout) as s:
            too_big: MethodError | None = None
            for q in qualities:
                body: dict[str, Any] = {"url": url, "filenameStyle": "basic"}
                if audio:
                    body.update(downloadMode="audio", audioFormat="mp3")
                else:
                    body.update(downloadMode="auto", videoQuality=q, youtubeVideoCodec="h264")
                try:
                    async with s.post(base + "/", json=body, headers=headers) as r:
                        try:
                            data = await r.json(content_type=None)
                        except Exception:  # noqa: BLE001
                            raise MethodError("other", f"cobalt javobi JSON emas (HTTP {r.status})") from None
                        http = r.status
                except MethodError:
                    raise
                except Exception as e:  # noqa: BLE001
                    raise MethodError("network", f"cobalt ga ulanib bo'lmadi: {e}") from e
                if http in (401, 403) and not data.get("status"):
                    raise MethodError("config", f"cobalt ruxsat bermadi (HTTP {http}) — COBALT_API_KEY kerak bo'lishi mumkin")
                status = data.get("status")
                if status == "error":
                    code = str((data.get("error") or {}).get("code") or data)
                    raise MethodError(self._cobalt_reason(code), code)
                try:
                    if status in ("tunnel", "redirect"):
                        p = await self._fetch_file(s, data["url"], workdir, data.get("filename"))
                        return [MediaFile(p, kind_of(p), title=Path(data.get("filename") or "").stem)]
                    if status == "picker":
                        files = []
                        for it in (data.get("picker") or [])[:10]:
                            if not it.get("url"):
                                continue
                            p = await self._fetch_file(s, it["url"], workdir, None)
                            files.append(MediaFile(p, kind_of(p)))
                        if not files and data.get("audio"):
                            p = await self._fetch_file(s, data["audio"], workdir, "a.mp3")
                            files.append(MediaFile(p, "audio"))
                        if files:
                            return files
                        raise MethodError("other", "cobalt picker bo'sh")
                except MethodError as e:
                    if e.reason == "too_large" and q != qualities[-1]:
                        too_big = e
                        self._purge(workdir)
                        continue
                    raise
                raise MethodError("other", f"cobalt kutilmagan status: {status}")
            if too_big:
                raise too_big
        raise MethodError("other", "cobalt natija bermadi")

    # ================================================================ USUL 2: yt-dlp
    @staticmethod
    def _import_ytdlp() -> Any:
        try:
            import yt_dlp
        except ImportError as e:
            raise MethodError("config", "yt-dlp o'rnatilmagan") from e
        return yt_dlp

    def ytdlp_version(self) -> str:
        try:
            from yt_dlp.version import __version__

            return __version__
        except Exception:  # noqa: BLE001
            return "o'rnatilmagan"

    async def update_ytdlp(self) -> str:
        """yt-dlp ni (nightly) yangilaydi va xotiradagi modulni tozalaydi."""
        rc, _out, err = await self.run(sys.executable, "-m", "pip", "install", "-U", "--pre",
                                       "--break-system-packages", "yt-dlp[default]", timeout=400)
        if rc != 0:
            # eski pip --break-system-packages ni tanimasa
            rc, _out, err = await self.run(sys.executable, "-m", "pip", "install", "-U", "--pre", "yt-dlp[default]",
                                           timeout=400)
        if rc != 0:
            return f"❌ Yangilanmadi: {err[-300:]}"
        import importlib

        for m in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            del sys.modules[m]
        importlib.invalidate_caches()
        return f"✅ yt-dlp: {self.ytdlp_version()}"

    def _ytdlp_opts(self, platform: str, workdir: Path) -> dict[str, Any]:
        o: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": str(workdir / "%(id)s.%(ext)s"),
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
            "restrictfilenames": True,
            "concurrent_fragment_downloads": 4,
            "merge_output_format": "mp4",
            "http_headers": {"User-Agent": BROWSER_UA},
        }
        if self.cfg.proxy:
            o["proxy"] = self.cfg.proxy
        if platform == "youtube" and not shutil.which("deno") and shutil.which("node"):
            o["js_runtimes"] = {"node": {}}  # YouTube challenge uchun JS runtime
        ck = self._cookie_copy(platform, workdir)
        if ck:
            o["cookiefile"] = ck
        return o

    async def _m_ytdlp(self, url: str, platform: str, audio: bool, workdir: Path) -> list[MediaFile]:
        return await asyncio.to_thread(self._ytdlp_sync, url, platform, audio, workdir)

    def _ytdlp_sync(self, url: str, platform: str, audio: bool, workdir: Path) -> list[MediaFile]:
        yt_dlp = self._import_ytdlp()
        opts = self._ytdlp_opts(platform, workdir)
        heights = [None] if audio else [720, 360]
        last_big: MethodError | None = None
        for h in heights:
            o = dict(opts)
            if audio:
                o["format"] = "bestaudio[ext=m4a]/bestaudio/best"
                o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
            else:
                o["format"] = (f"bv*[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<={h}]+ba/"
                               f"b[height<={h}]/bv*+ba/b")
            try:
                with yt_dlp.YoutubeDL(o) as ydl:
                    info = ydl.extract_info(url, download=True)
                    files = self._collect_ytdlp(ydl, info, workdir, audio)
            except MethodError:
                raise
            except Exception as e:  # noqa: BLE001
                msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
                raise MethodError(classify_text(msg), msg.strip().splitlines()[-1][:300] if msg.strip() else type(e).__name__) from e
            if not files:
                raise MethodError("other", "yt-dlp fayl yaratmadi")
            if any(f.path.stat().st_size > self.limit_bytes for f in files) and h and h > 360:
                last_big = MethodError("too_large", f"{h}p hajmi katta, 360p sinaladi")
                self._purge(workdir)
                if opts.get("cookiefile"):
                    opts["cookiefile"] = self._cookie_copy(platform, workdir)
                continue
            return files
        raise last_big or MethodError("too_large", "fayl juda katta")

    def _collect_ytdlp(self, ydl: Any, info: dict[str, Any] | None, workdir: Path, audio: bool) -> list[MediaFile]:
        if not info:
            return []
        entries = info.get("entries")
        items = [e for e in (entries or [info]) if e][:10]
        out: list[MediaFile] = []
        for e in items:
            path: Path | None = None
            rd = e.get("requested_downloads") or []
            if rd and rd[-1].get("filepath"):
                path = Path(rd[-1]["filepath"])
            if path is None or not path.exists():
                try:
                    cand = Path(ydl.prepare_filename(e))
                    if audio:
                        cand = cand.with_suffix(".mp3")
                    path = cand if cand.exists() else None
                except Exception:  # noqa: BLE001
                    path = None
            if path is None:
                continue
            out.append(MediaFile(
                path=path, kind=kind_of(path), title=str(e.get("track") or e.get("title") or ""),
                performer=str(e.get("artist") or e.get("uploader") or e.get("channel") or ""),
                duration=int(e.get("duration") or 0), width=int(e.get("width") or 0), height=int(e.get("height") or 0),
            ))
        if not out:  # zaxira: papkadagi yangi fayllar
            for p in sorted(workdir.iterdir(), key=lambda x: x.stat().st_mtime):
                if p.suffix.lower() in VIDEO_EXT | AUDIO_EXT | PHOTO_EXT:
                    out.append(MediaFile(p, kind_of(p)))
        return out

    # ================================================================ USUL 3: instagram embed (ochiq postlar)
    async def _m_embed(self, url: str, platform: str, audio: bool, workdir: Path) -> list[MediaFile]:
        m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
        if not m:
            raise MethodError("unsupported", "post havolasi emas")
        code = m.group(1)
        proxy = self.cfg.proxy or None
        headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
        async with self._session(60) as s:
            try:
                async with s.get(f"https://www.instagram.com/p/{code}/embed/captioned/", headers=headers, proxy=proxy) as r:
                    if r.status == 404:
                        raise MethodError("not_found", "embed HTTP 404")
                    if r.status != 200:
                        raise MethodError("blocked", f"embed HTTP {r.status}")
                    page = await r.text()
            except MethodError:
                raise
            except Exception as e:  # noqa: BLE001
                raise MethodError("network", str(e)) from e
            media_url = None
            vm = re.search(r'"video_url"\s*:\s*"([^"]+)"', page)
            if vm:
                try:
                    media_url = json.loads('"' + vm.group(1) + '"')
                except json.JSONDecodeError:
                    media_url = vm.group(1).replace("\\u0026", "&").replace("\\/", "/")
            else:
                im = re.search(r'class="EmbeddedMediaImage"[^>]*\ssrc="([^"]+)"', page)
                if im:
                    media_url = html.unescape(im.group(1))
            if not media_url:
                raise MethodError("other", "embed sahifasida media topilmadi (post yopiq yoki format o'zgargan)")
            p = await self._fetch_file(s, media_url, workdir, None, proxy=proxy)
        return [MediaFile(p, kind_of(p))]

    # ================================================================ USUL 4: pullik API (FastSaver)
    async def _m_api(self, url: str, platform: str, audio: bool, workdir: Path) -> list[MediaFile]:
        try:
            from fastsaver import AsyncFastSaver
        except ImportError as e:
            raise MethodError("config", "fastsaver o'rnatilmagan (pip install fastsaver)") from e
        targets: list[tuple[str, str]] = []
        try:
            async with AsyncFastSaver(api_key=self.cfg.fastsaver_key) as client:
                if platform == "youtube":
                    res = await client.youtube.download(url, format="audio" if audio else "720p")
                    targets.append((res.download_url, "audio" if audio else "video"))
                else:
                    res = await client.fetch(url)
                    if getattr(res, "is_album", False) and res.items:
                        targets = [(i.download_url, str(i.type)) for i in res.items[:10] if i.download_url]
                    elif audio and getattr(res, "music", None) and getattr(res.music, "download_url", None):
                        targets = [(res.music.download_url, "audio")]
                    else:
                        targets = [(res.download_url, str(res.type))]
        except MethodError:
            raise
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            reason = {"NotFoundError": "not_found", "RateLimitError": "blocked", "InsufficientCreditsError": "config",
                      "AuthenticationError": "config", "ConfigurationError": "config",
                      "RequestTimeoutError": "network", "TransportError": "network"}.get(name) or classify_text(str(e))
            raise MethodError(reason, f"{name}: {e}"[:300]) from e
        targets = [(u, k) for u, k in targets if u]
        if not targets:
            raise MethodError("other", "API havola bermadi")
        files: list[MediaFile] = []
        async with self._session(self.cfg.method_timeout) as s:
            for u, _k in targets:
                p = await self._fetch_file(s, u, workdir, None)
                files.append(MediaFile(p, kind_of(p)))
        return files

    # ================================================================ QIDIRUV (musiqa)
    async def search(self, query: str, n: int = 5) -> list[Hit]:
        query = query.strip()[:200]
        hits: list[Hit] = []
        for prefix, source in (("ytsearch", "youtube"), ("scsearch", "soundcloud")):
            try:
                hits = await asyncio.wait_for(asyncio.to_thread(self._search_sync, f"{prefix}{n + 3}:{query}", source), 60)
            except Exception as e:  # noqa: BLE001
                log.warning("%s qidiruvi xato: %s", source, e)
                hits = []
            if hits:
                return hits[:n]
        if self.cfg.fastsaver_key:
            try:
                from fastsaver import AsyncFastSaver

                async with AsyncFastSaver(api_key=self.cfg.fastsaver_key) as c:
                    res = await c.youtube.search(query)
                    for it in (res.items or [])[:n]:
                        hits.append(Hit(str(it.video_id), str(it.title), "", int(it.duration_seconds or 0),
                                        str(it.url), "api"))
            except Exception as e:  # noqa: BLE001
                log.warning("api qidiruvi xato: %s", e)
        return hits[:n]

    def _search_sync(self, q: str, source: str) -> list[Hit]:
        yt_dlp = self._import_ytdlp()
        o: dict[str, Any] = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
                             "socket_timeout": 25, "http_headers": {"User-Agent": BROWSER_UA}}
        if self.cfg.proxy:
            o["proxy"] = self.cfg.proxy
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(q, download=False)
        hits: list[Hit] = []
        for e in (info or {}).get("entries") or []:
            if not e:
                continue
            dur = int(e.get("duration") or 0)
            if dur > 1500:  # 25 daqiqadan uzun — musiqa emas
                continue
            url = e.get("webpage_url") or e.get("url") or ""
            if source == "youtube" and e.get("id") and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={e['id']}"
            if not url.startswith("http"):
                continue
            hits.append(Hit(str(e.get("id") or ""), str(e.get("title") or "?"),
                            str(e.get("uploader") or e.get("channel") or ""), dur, url, source))
        return hits

    async def download_hit(self, hit: Hit) -> MediaResult:
        """Qidiruv natijasini audio qilib yuklaydi. YouTube bloklasa SoundCloud'dan o'sha nomli trekni oladi."""
        try:
            res = await self.download(hit.url, audio=True)
        except DownloadFailed as first:
            if hit.source == "soundcloud":
                raise
            try:
                alt = await asyncio.wait_for(
                    asyncio.to_thread(self._search_sync, f"scsearch3:{hit.title}", "soundcloud"), 45)
            except Exception:  # noqa: BLE001
                alt = []
            if not alt:
                raise first from None
            res = await self.download(alt[0].url, audio=True)
        for f in res.files:
            f.title = hit.title
            f.performer = hit.uploader or f.performer
        return res

    # ================================================================ DIAGNOSTIKA
    async def diagnose(self, url: str) -> list[tuple[str, bool, str]]:
        """Har bir usulni alohida sinab, natijani qaytaradi (/test uchun)."""
        platform = detect_platform(url) or "other"
        url = normalize_url(url, platform)
        out: list[tuple[str, bool, str]] = []
        for name in ("cobalt", "ytdlp", "embed", "api"):
            if not self._usable(name, platform, False):
                why = {"cobalt": "COBALT_API_URL sozlanmagan", "embed": "faqat Instagram uchun",
                       "api": "FASTSAVER_API_KEY sozlanmagan"}.get(name, "")
                out.append((name, False, f"o'tkazib yuborildi — {why}"))
                continue
            workdir = self.new_workdir()
            t0 = time.time()
            try:
                fn = getattr(self, f"_m_{name}")
                files = await asyncio.wait_for(fn(url, platform, False, workdir), self.cfg.method_timeout)
                files = await self._finalize(files, False)
                size = sum(f.path.stat().st_size for f in files) / 1048576
                out.append((name, True, f"{time.time() - t0:.1f}s · {len(files)} fayl · {size:.1f} MB"))
            except MethodError as e:
                out.append((name, False, f"{e.reason} — {e.detail[:200]}"))
            except asyncio.TimeoutError:
                out.append((name, False, "timeout"))
            except Exception as e:  # noqa: BLE001
                out.append((name, False, f"{type(e).__name__}: {str(e)[:200]}"))
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        return out
