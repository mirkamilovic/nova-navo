"""Musiqa aniqlash (shazamio). Ovoz/video fayldan 20 soniyalik parcha olinadi."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("navobot.shazam")


@dataclass
class Track:
    title: str
    artist: str
    cover: str = ""
    url: str = ""

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}".strip(" -")


class ShazamService:
    def __init__(self, media: Any):
        self.media = media
        self._sh: Any = None

    async def _clip(self, src: Path) -> Path:
        """Manbadan mono WAV (20 soniya). Video bo'lsa faqat audio olinadi."""
        out = src.with_suffix(".clip.wav")
        rc, _o, err = await self.media.run(
            "ffmpeg", "-y", "-i", str(src), "-vn", "-t", "20", "-ac", "1", "-ar", "44100", str(out), timeout=120
        )
        if rc != 0 or not out.exists():
            raise RuntimeError(f"ffmpeg xatosi: {err[-200:]}")
        return out

    async def recognize(self, path: Path) -> Track | None:
        try:
            from shazamio import Shazam
        except ImportError as e:
            raise RuntimeError("shazamio o'rnatilmagan (requirements.txt ga qo'shing)") from e
        clip = await self._clip(path)
        if self._sh is None:
            self._sh = Shazam()
        fn = getattr(self._sh, "recognize", None) or getattr(self._sh, "recognize_song")
        out = await asyncio.wait_for(fn(str(clip)), timeout=60)
        track = (out or {}).get("track") if isinstance(out, dict) else None
        if not track:
            return None
        images = track.get("images") or {}
        return Track(
            title=str(track.get("title") or "").strip(),
            artist=str(track.get("subtitle") or "").strip(),
            cover=str(images.get("coverart") or ""),
            url=str(track.get("url") or ""),
        )
