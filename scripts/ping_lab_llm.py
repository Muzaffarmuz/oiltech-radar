"""Быстрый пинг Lab LLM (qwen3-32b).

  python scripts/ping_lab_llm.py
"""
from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()


from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# --- Lab LLM: явные креды ---
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"
# -----------------------------



def _request(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, str, float]:
    url = BASE_URL.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return int(resp.status), raw, time.time() - t0
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return int(exc.code), raw, time.time() - t0
    except Exception as exc:
        return -1, f"{type(exc).__name__}: {exc}", time.time() - t0


def main() -> int:
    print(f"BASE_URL={BASE_URL}")
    print(f"MODEL={MODEL_NAME}")
    print()

    print("1) GET /models …", flush=True)
    code, body, sec = _request("GET", "/models", timeout=15)
    print(f"   → {code} за {sec:.2f}s")
    if code == 200:
        try:
            ids = [m.get("id") for m in (json.loads(body).get("data") or [])]
            print(f"   models: {ids[:12]}")
        except Exception:
            print(f"   body: {body[:200]}")
    else:
        print(f"   body: {body[:300]}")

    print()
    print("2) POST /chat/completions …", flush=True)
    code, body, sec = _request(
        "POST",
        "/chat/completions",
        {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": "Ответь одним словом: ок"}],
            "max_tokens": 16,
            "temperature": 0,
        },
        timeout=60,
    )
    print(f"   → {code} за {sec:.2f}s")
    if code == 200:
        try:
            msg = json.loads(body)["choices"][0]["message"]["content"]
            print(f"   reply: {msg!r}")
        except Exception:
            print(f"   body: {body[:400]}")
        print()
        print("OK — Lab LLM отвечает")
        return 0

    print(f"   body: {body[:400]}")
    print()
    print("FAIL — Lab LLM недоступна")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
