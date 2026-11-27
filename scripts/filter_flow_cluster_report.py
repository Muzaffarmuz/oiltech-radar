"""Ужать готовый Lab-отчёт policy/investments без повторного LLM.

Сохраняет имена кластеров; полный корпус → *.full.json (один раз).

  # policy: релевантность ТЭК + Interfax ≤2/день + дедуп заголовков
  python scripts/filter_flow_cluster_report.py --flow policy

  # жёстче по Interfax
  python scripts/filter_flow_cluster_report.py --flow policy --interfax-per-day 1

  # без лимита Interfax, только релевантность
  python scripts/filter_flow_cluster_report.py --flow policy --interfax-per-day 0

  # оба потока
  python scripts/filter_flow_cluster_report.py --flow both

Для новых границ тем после фильтра лучше перекластеризовать:
  python scripts/cluster_flow_news_lab.py --flow policy --relevant-only --interfax-per-day 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.pipeline.flow_news_cluster import (  # noqa: E402
    ALLOWED_FLOWS,
    slim_existing_report,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Фильтр готового flow clusters_report")
    p.add_argument("--flow", choices=[*ALLOWED_FLOWS, "both"], default="policy")
    p.add_argument(
        "--relevant-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Policy: оставить ТЭК/рынок/регулятор, выкинуть дроны/аэропорты и т.п.",
    )
    p.add_argument(
        "--interfax-per-day",
        type=int,
        default=2,
        help="Макс. новостей Interfax в день (0 = без лимита)",
    )
    p.add_argument(
        "--dedupe-titles",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = p.parse_args()

    flows = list(ALLOWED_FLOWS) if args.flow == "both" else [args.flow]
    results = []
    for flow in flows:
        # investments: relevant_only пока только для policy-логики
        relevant = bool(args.relevant_only) if flow == "policy" else False
        result = slim_existing_report(
            flow,
            relevant_only=relevant,
            interfax_per_day=int(args.interfax_per_day),
            dedupe_titles=bool(args.dedupe_titles),
        )
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    ok = all(r.get("status") == "ok" for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
