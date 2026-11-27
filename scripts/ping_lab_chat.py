"""Пинг Lab LLM теми же кредами, что в .env (LAB_* / API_KEY / BASE_URL).

  py -3 scripts/ping_lab_chat.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._lab_credentials import (  # noqa: E402
    ensure_no_proxy,
    lab_api_key,
    lab_base_url,
    lab_model,
)

ensure_no_proxy()

BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = lab_model("qwen3-32b")

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    if os.environ.get(key):
        print(
            f"warn: {key}={os.environ[key]!r} — для Lab-хоста лучше, "
            "чтобы он был в NO_PROXY"
        )


def main() -> int:
    from openai import OpenAI

    if not API_KEY:
        print("FAIL: задайте LAB_API_KEY или API_KEY в .env")
        return 1

    print(f"BASE_URL={BASE_URL}")
    print(f"MODEL={MODEL_NAME}")
    print(f"NO_PROXY={os.environ.get('NO_PROXY')}")
    print()

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=60.0)

    print("1) GET /models …", flush=True)
    t0 = time.time()
    try:
        models = client.models.list()
        ids = [m.id for m in (models.data or [])]
        print(f"   OK за {time.time()-t0:.2f}s · models={ids[:12]}")
    except Exception as exc:
        print(f"   FAIL за {time.time()-t0:.2f}s · {type(exc).__name__}: {exc}")
        print("VPN к рабочей сети включён?")
        return 1

    print("2) chat.completions …", flush=True)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Ответь одним словом: ок"}],
            max_tokens=16,
        )
        content = (resp.choices[0].message.content or "").strip()
        print(f"   OK за {time.time()-t0:.2f}s · {content!r}")
    except Exception as exc:
        print(f"   FAIL за {time.time()-t0:.2f}s · {type(exc).__name__}: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
