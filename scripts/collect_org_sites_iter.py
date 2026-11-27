"""Итеративный сбор сайтов батчами (устойчиво к зависаниям DDG).

Каждый батч — отдельный процесс collect_org_sites.py --max-new N.
Heartbeat: data/exports/org_sites_prompt/_sites_iter_status.json

  python scripts/collect_org_sites_iter.py
  python scripts/collect_org_sites_iter.py --batch-size 8 --batch-timeout 120
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "data" / "exports" / "org_sites_prompt"
PROGRESS = EXPORT / "_sites_collect_progress.json"
STATUS = EXPORT / "_sites_iter_status.json"
UNIQUE = ROOT / "data" / "runs" / "patents" / "unique_orgs.json"
COLLECT = ROOT / "scripts" / "collect_org_sites.py"


def progress_count() -> int:
    if not PROGRESS.exists():
        return 0
    data = json.loads(PROGRESS.read_text(encoding="utf-8"))
    return int(data.get("count") or len(data.get("by_name") or {}))


def total_orgs() -> int:
    data = json.loads(UNIQUE.read_text(encoding="utf-8"))
    return len(data.get("items") or [])


def write_status(**kwargs) -> None:
    EXPORT.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **kwargs}
    STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def run_batch(batch_size: int, batch_timeout: int) -> tuple[bool, str]:
    """True = batch finished OK; False = timeout/error."""
    cmd = [
        sys.executable,
        "-u",
        str(COLLECT),
        "--resume",
        "--max-new",
        str(batch_size),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=batch_timeout,
        )
        out = (proc.stdout or "")[-2000:]
        err = (proc.stderr or "")[-500:]
        ok = proc.returncode == 0
        return ok, out + (("\nSTDERR:\n" + err) if err else "")
    except subprocess.TimeoutExpired as e:
        # kill tree best-effort
        return False, f"TIMEOUT after {batch_timeout}s; partial stdout:\n{(e.stdout or b'')[-1000:]!r}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--batch-timeout", type=int, default=180, help="сек на один батч")
    ap.add_argument("--pause", type=float, default=1.5, help="пауза между батчами")
    args = ap.parse_args()

    total = total_orgs()
    batch_i = 0
    stalls = 0
    prev = progress_count()

    write_status(
        event="start",
        saved=prev,
        total=total,
        remaining=total - prev,
        batch=0,
    )

    while True:
        saved_before = progress_count()
        if saved_before >= total:
            # finalize outputs
            subprocess.run(
                [sys.executable, "-u", str(COLLECT), "--resume", "--max-new", "0", "--finalize"],
                cwd=str(ROOT),
                timeout=120,
            )
            # max-new 0 still need finalize - call write via finalize with empty pending
            # Actually max-new 0 processes nothing; finalize flag writes. Good if remaining==0.
            write_status(event="done", saved=saved_before, total=total, remaining=0, batch=batch_i)
            break

        batch_i += 1
        t0 = time.time()
        ok, log = run_batch(args.batch_size, args.batch_timeout)
        elapsed = round(time.time() - t0, 1)
        saved_after = progress_count()
        delta = saved_after - saved_before

        if delta <= 0:
            stalls += 1
            event = "stall" if ok else "timeout_or_error"
        else:
            stalls = 0
            event = "progress" if ok else "progress_with_error"

        write_status(
            event=event,
            saved=saved_after,
            total=total,
            remaining=max(0, total - saved_after),
            batch=batch_i,
            delta=delta,
            elapsed_sec=elapsed,
            stalls=stalls,
            ok=ok,
            tail=log[-800:] if log else "",
        )

        if stalls >= 5:
            write_status(
                event="abort_stalls",
                saved=saved_after,
                total=total,
                remaining=max(0, total - saved_after),
                batch=batch_i,
                stalls=stalls,
            )
            sys.exit(2)

        time.sleep(args.pause)


if __name__ == "__main__":
    main()
