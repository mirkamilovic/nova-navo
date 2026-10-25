from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


@dataclass(frozen=True)
class Config:
    token: str
    owner_ids: list[int]
    bot_api_url: str
    max_parallel: int
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.sqlite3"

    @property
    def cookies_dir(self) -> Path:
        return self.data_dir / "cookies"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def local_api(self) -> bool:
        return bool(self.bot_api_url)

    @property
    def upload_limit_mb(self) -> int:
        return 1900 if self.local_api else 49


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN .env faylida ko'rsatilmagan")
    cfg = Config(
        token=token,
        owner_ids=_ids(os.getenv("OWNER_IDS", "")),
        bot_api_url=os.getenv("BOT_API_URL", "").strip().rstrip("/"),
        max_parallel=max(1, int(os.getenv("MAX_PARALLEL", "4") or 4)),
        data_dir=Path(os.getenv("DATA_DIR", "data")).resolve(),
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.cookies_dir.mkdir(parents=True, exist_ok=True)
    cfg.tmp_dir.mkdir(parents=True, exist_ok=True)
    return cfg
