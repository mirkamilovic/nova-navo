"""Sozlamalar: hammasi muhit o'zgaruvchilaridan (Railway → Variables) o'qiladi."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and v.strip() != "":
            return v.strip()
    return default


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on", "ha")


def _int(v: str, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _load_dotenv() -> None:
    """Oddiy .env o'quvchi (mavjud o'zgaruvchilarni almashtirmaydi)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        f = base / ".env"
        if not f.is_file():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass


@dataclass
class Config:
    token: str
    owner_ids: set[int]
    data_dir: Path
    db_path: Path
    tmp_dir: Path
    cookies_dir: Path
    local_api: bool
    bot_api_url: str
    max_upload_mb: int
    cobalt_url: str
    cobalt_key: str
    proxy: str
    fastsaver_key: str
    source_order: list[str]
    max_parallel: int
    method_timeout: int


def load_config() -> Config:
    _load_dotenv()
    token = _env("BOT_TOKEN", "TOKEN", "TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN o'rnatilmagan! Railway → Variables ga BOT_TOKEN qo'shing.")

    owners: set[int] = set()
    for part in _env("OWNER_IDS", "OWNER_ID", "ADMIN_IDS").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            owners.add(int(part))

    # Railway Volume ulangan bo'lsa shu yo'l avtomatik beriladi: baza va cookies deploy'dan keyin ham saqlanadi
    data_dir = Path(_env("DATA_DIR", "RAILWAY_VOLUME_MOUNT_PATH", default="./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = data_dir / "tmp"
    cookies_dir = data_dir / "cookies"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cookies_dir.mkdir(parents=True, exist_ok=True)

    local_api = _bool(_env("LOCAL_API", default="0"))
    default_mb = 1900 if local_api else 50
    order = [x.strip().lower() for x in _env("SOURCE_ORDER", default="cobalt,ytdlp,embed,api").split(",") if x.strip()]

    return Config(
        token=token,
        owner_ids=owners,
        data_dir=data_dir,
        db_path=Path(_env("DB_PATH", default=str(data_dir / "bot.db"))),
        tmp_dir=tmp_dir,
        cookies_dir=cookies_dir,
        local_api=local_api,
        bot_api_url=_env("BOT_API_URL", default="http://localhost:8081"),
        max_upload_mb=_int(_env("MAX_UPLOAD_MB", default=str(default_mb)), default_mb),
        cobalt_url=_env("COBALT_API_URL", "COBALT_URL"),
        cobalt_key=_env("COBALT_API_KEY"),
        proxy=_env("PROXY_URL", "YTDLP_PROXY"),
        fastsaver_key=_env("FASTSAVER_API_KEY"),
        source_order=order,
        max_parallel=max(1, _int(_env("MAX_PARALLEL", default="3"), 3)),
        method_timeout=max(30, _int(_env("METHOD_TIMEOUT", default="150"), 150)),
    )
