"""Применить Lab-аудит к данным портала.

Берёт data/for_recluster/_audit/*/audited.jsonl (только kept/reassigned)
и перезаписывает отчёты, которые читает Oil Radar. Старые файлы —
*.pre_audit.json рядом.

  py -3 scripts/apply_audit_to_portal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.pipeline.apply_audit import apply_all  # noqa: E402


def main() -> int:
    results = apply_all()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("\nГотово. Перезапустите портал или обновите страницы с Ctrl+F5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
