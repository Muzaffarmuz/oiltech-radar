"""Креды Lab LLM только из окружения / .env — без хардкода секретов.

Использование в скриптах:
  from scripts._lab_credentials import lab_base_url, lab_api_key, ensure_no_proxy
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


_load_dotenv()


def lab_base_url(default: str = "http://127.0.0.1:54000/v1") -> str:
    return (
        os.environ.get("LAB_BASE_URL")
        or os.environ.get("BASE_URL")
        or default
    ).rstrip("/")


def lab_api_key() -> str:
    return (
        os.environ.get("LAB_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    ).strip()


def lab_model(default: str = "gpt-oss-120b") -> str:
    return (
        os.environ.get("LAB_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
        or default
    ).strip()


def ensure_no_proxy(*hosts: str) -> None:
    """Не гонять внутренние Lab-хосты через системный HTTP-прокси."""
    extra = {h.strip() for h in hosts if h and h.strip()}
    extra.update({"localhost", "127.0.0.1"})
    # хост из LAB_BASE_URL / BASE_URL
    for url in (lab_base_url(""), os.environ.get("BASE_URL") or ""):
        if "://" in url:
            host = url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
            if host:
                extra.add(host)
    current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = {p.strip() for p in current.split(",") if p.strip()}
    parts |= extra
    joined = ",".join(sorted(parts))
    os.environ["NO_PROXY"] = joined
    os.environ["no_proxy"] = joined
