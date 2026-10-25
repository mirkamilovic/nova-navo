"""yt-dlp taqlidi: URL ichidagi so'zlarga qarab xatti-harakat qiladi (testlar uchun)."""
from __future__ import annotations

import re
import sys
import threading
import time
import types
from pathlib import Path

MB = 1024 * 1024


class DownloadError(Exception):
    pass


class FakeYoutubeDL:
    calls: list[dict] = []
    delay = 0.0
    active = 0
    max_active = 0
    _lock = threading.Lock()

    def __init__(self, opts):
        self.opts = opts
        self.dir = Path(opts["outtmpl"]).parent if "outtmpl" in opts else Path(".")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    # ----- yordamchi
    @staticmethod
    def tier(fmt: str) -> int:
        for i, key in enumerate(("<=1080", "<=720", "<=480", "<=360")):
            if f"height{key}" in fmt:
                return i
        return 3

    def prepare_filename(self, e):
        return str(self.dir / f"{e['id']}.mp4")

    def _write(self, name: str, size: int) -> str:
        p = self.dir / name
        p.write_bytes(b"x" * size)
        return str(p)

    # ----- asosiy
    def extract_info(self, url, download=True):
        with self._lock:
            FakeYoutubeDL.active += 1
            FakeYoutubeDL.max_active = max(FakeYoutubeDL.max_active, FakeYoutubeDL.active)
        try:
            FakeYoutubeDL.calls.append({"url": url, "cookiefile": self.opts.get("cookiefile"),
                                        "format": self.opts.get("format"), "audio": "postprocessors" in self.opts})
            if self.delay:
                time.sleep(self.delay)
            return self._extract(url, download)
        finally:
            with self._lock:
                FakeYoutubeDL.active -= 1

    def _extract(self, url, download):
        low = url.lower()
        if url.startswith("ytsearch"):
            n = int(re.match(r"ytsearch(\d+):", url).group(1))
            q = url.split(":", 1)[1]
            if "boom" in q:
                raise DownloadError("ERROR: search failed")
            if "nothing" in q:
                return {"entries": []}
            ents = [{"id": f"vid{i}", "title": f"Artist {i} - {q} {i} (Official Video)", "duration": 180 + i,
                     "channel": f"Artist {i} - Topic"} for i in range(n - 3)]
            ents += [None, {"id": "vid0", "title": "dup", "duration": 100},
                     {"id": "longone", "title": "10 hours", "duration": 36000}]
            return {"entries": ents}
        if "login" in low:
            raise DownloadError("ERROR: [Instagram] Sign in to confirm you're not a bot. Use --cookies")
        if "private" in low:
            raise DownloadError("ERROR: Private video. Sign in if you've been granted access")
        if "unsupported" in low:
            raise DownloadError("ERROR: Unsupported URL: " + url)
        if "boom" in low:
            raise DownloadError("ERROR: something exploded")
        vid = re.sub(r"\W", "", url)[-14:]
        info = {"id": vid, "title": "Gulsanam - Onam chiroyli (Official Music)", "uploader": "Gulsanam - Topic",
                "duration": 191, "width": 720, "height": 1280}
        if "music" in low:
            info.update(track="Onam chiroyli", artist="Gulsanam, Feat")
        if "long" in low:
            info["duration"] = 7000

        if "postprocessors" in self.opts:           # AUDIO
            mf = self.opts.get("match_filter")
            if mf and mf(info, incomplete=False):
                return info                          # filtrdan o'tmadi: fayl yo'q (haqiqiy yt-dlp kabi)
            if download:
                self._write(f"{vid}.mp3", 400_000)
                self._write(f"{vid}.webp", 5_000)
            return info

        tier = self.tier(self.opts.get("format", ""))
        limit = self.opts.get("max_filesize") or 10**12
        sizes = [3 * MB, 2 * MB, int(1.5 * MB), 300_000]
        if "tiny" in low:
            sizes = [100_000] * 4
        elif "huge" in low:
            sizes = [9 * MB] * 4                     # hech qaysi sifat sig'maydi
        size = sizes[tier] if "big" in low or "huge" in low else 200_000
        if "bigraise" in low and size > limit:
            raise DownloadError("ERROR: File is larger than max-filesize")
        if "photo" in low and "album" not in low:
            if download:
                path = self._write(f"{vid}.jpg", 80_000)
                info["requested_downloads"] = [{"filepath": path}]
            return info
        if "album" in low:
            entries = []
            take = self.opts.get("playlistend") or 10
            for i in range(min(take, 12)):
                e = {"id": f"{vid}_{i}", "title": f"item {i}", "duration": 5 if i % 3 == 2 else None}
                if download:
                    ext = "mp4" if i % 3 == 2 else "jpg"
                    path = self._write(f"{vid}_{i}.{ext}", 50_000)
                    e["requested_downloads"] = [{"filepath": path}]
                entries.append(e)
            return {"id": vid, "title": "album", "entries": entries}
        if size > limit:
            return info                              # haqiqiy yt-dlp: katta fayl o'tkazib yuboriladi, xato bermaydi
        if download:
            path = self._write(f"{vid}.mp4", size)
            info["requested_downloads"] = [{"filepath": path}]
        return info


def match_filter_func(expr):
    m = re.match(r"duration\s*<\??\s*(\d+)", expr)
    limit = int(m.group(1))
    return lambda info, incomplete=False: None if (info.get("duration") or 0) < limit else "does not pass filter"


def install():
    ydl = types.ModuleType("yt_dlp")
    ydl.YoutubeDL = FakeYoutubeDL
    utils = types.ModuleType("yt_dlp.utils")
    utils.match_filter_func = match_filter_func
    utils.DownloadError = DownloadError
    ydl.utils = utils
    ydl.version = types.SimpleNamespace(__version__="fake")
    sys.modules["yt_dlp"] = ydl
    sys.modules["yt_dlp.utils"] = utils
