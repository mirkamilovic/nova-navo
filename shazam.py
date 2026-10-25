"""Shazam orqali qo'shiqni aniqlash va mamlakat reytinglari."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from shazamio import Shazam
except Exception:  # noqa: BLE001  (shazamio o'rnatilmagan bo'lsa bot baribir ishlaydi)
    Shazam = None  # type: ignore[assignment]

from .media import MediaService, _ffmpeg

log = logging.getLogger(__name__)

# (kod, bayroq, "yangi qo'shiqlar" uchun qidiruv so'zi)
COUNTRIES: list[tuple[str, str, str]] = [
    ("UZ", "🇺🇿", "yangi o'zbek qo'shiqlar"),
    ("RU", "🇷🇺", "новинки музыки"),
    ("GB", "🇬🇧", "new songs"),
    ("KZ", "🇰🇿", "жаңа әндер"),
    ("TR", "🇹🇷", "yeni şarkılar"),
    ("AZ", "🇦🇿", "yeni mahnılar"),
]
CHART_TTL = 3600


class ShazamService:
    def __init__(self, media: MediaService):
        self.media = media
        self.shazam = Shazam() if Shazam else None
        self._charts: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}

    # ----- aniqlash -----
    async def recognize_file(self, src: Path, workdir: Path) -> dict[str, str] | None:
        """Audio/video/ovozli fayldan qo'shiq nomi va ijrochini topadi."""
        if self.shazam is None:
            return None
        wav = workdir / "shazam_in.wav"
        ok = await _ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", "44100", "-t", "45", str(wav), timeout=90)
        target = wav if ok and wav.exists() else src
        try:
            fn = getattr(self.shazam, "recognize", None) or getattr(self.shazam, "recognize_song")
            out = await asyncio.wait_for(fn(str(target)), 60)
        except Exception as e:  # noqa: BLE001
            log.warning("shazam xatosi: %s", e)
            return None
        track = (out or {}).get("track")
        if not track:
            return None
        return {
            "title": track.get("title", ""),
            "artist": track.get("subtitle", ""),
            "key": str(track.get("key", "")),
        }

    # ----- reytinglar -----
    async def top(self, cc: str, limit: int = 30) -> list[dict[str, Any]]:
        ck = ("top", cc)
        cached = self._charts.get(ck)
        if cached and time.time() - cached[0] < CHART_TTL:
            return cached[1]
        items: list[dict[str, Any]] = []
        try:
            if self.shazam is None:
                raise RuntimeError("shazamio yo'q")
            data = await asyncio.wait_for(self.shazam.top_country_tracks(cc, limit=limit), 30)
            for t in (data or {}).get("tracks", []):
                title, artist = t.get("title", ""), t.get("subtitle", "")
                if title:
                    items.append({"label": f"{artist} — {title}", "query": f"{artist} {title}", "vid": None})
        except Exception as e:  # noqa: BLE001
            log.warning("top chart xatosi (%s): %s", cc, e)
        if not items:  # zaxira: YouTube qidiruvi
            try:
                word = next((w for c, _f, w in COUNTRIES if c == cc), "top songs")
                found = await self.media.search(f"top {word} {datetime.now().year}", limit + 5)
                items = [{"label": it.title, "query": it.title, "vid": it.id}
                         for it in found if 60 <= it.duration <= 600][:limit]
            except Exception as e:  # noqa: BLE001
                log.warning("top zaxira xatosi (%s): %s", cc, e)
        if items:
            self._charts[ck] = (time.time(), items)
        elif cached:
            return cached[1]
        return items

    async def new(self, cc: str, limit: int = 20) -> list[dict[str, Any]]:
        ck = ("new", cc)
        cached = self._charts.get(ck)
        if cached and time.time() - cached[0] < CHART_TTL:
            return cached[1]
        word = next((w for c, _f, w in COUNTRIES if c == cc), "new songs")
        items: list[dict[str, Any]] = []
        try:
            found = await self.media.search(f"{word} {datetime.now().year}", limit + 5)
            for it in found:
                if 60 <= it.duration <= 600:
                    items.append({"label": it.title, "query": it.title, "vid": it.id})
        except Exception as e:  # noqa: BLE001
            log.warning("new chart xatosi (%s): %s", cc, e)
        items = items[:limit]
        if items:
            self._charts[ck] = (time.time(), items)
        elif cached:
            return cached[1]
        return items
