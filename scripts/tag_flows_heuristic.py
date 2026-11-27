"""Эвристика: статьи 5 сайтов → потоки investments / policy + запись в БД.

  python scripts/tag_flows_heuristic.py
  python scripts/tag_flows_heuristic.py --apply
  python scripts/tag_flows_heuristic.py --only-untagged --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.config import FLOW_TAGS_DIR, ensure_dirs  # noqa: E402
from gartner.pipeline.heuristic_flow_split import (  # noqa: E402
    DEFAULT_SOURCES,
    apply_tags_to_db,
    load_source_articles,
    summarize,
    tag_articles,
)

OUT_DEFAULT = FLOW_TAGS_DIR / "tagged_heuristic_investments_policy.json"
REPORT_DEFAULT = FLOW_TAGS_DIR / "tagged_heuristic_investments_policy_report.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Эвристика investments/policy для 5 сайтов")
    p.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help="Домены через запятую",
    )
    p.add_argument("--only-untagged", action="store_true", help="Только статьи без flow_tags")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", type=Path, default=OUT_DEFAULT)
    p.add_argument("--apply", action="store_true", help="Записать метки в SQLite articles (merge)")
    p.add_argument(
        "--replace",
        action="store_true",
        help="С --apply заменить метки целиком (без merge со science/digital/…)",
    )
    args = p.parse_args()

    ensure_dirs()
    sources = tuple(s.strip() for s in str(args.sources).split(",") if s.strip())
    articles = load_source_articles(
        sources,
        only_untagged=bool(args.only_untagged),
        limit=int(args.limit or 0),
    )
    print(f"статей к разметке: {len(articles)} · sources={sources}")
    if not articles:
        print("нечего размечать", file=sys.stderr)
        return 1

    tagged = tag_articles(articles, merge_existing=not args.replace)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(tagged, ensure_ascii=False, indent=2), encoding="utf-8")
    report = summarize(tagged)
    REPORT_DEFAULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sidecar -> {args.out}")
    print(f"report  -> {REPORT_DEFAULT}")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.apply:
        stats = apply_tags_to_db(tagged, merge_existing=not args.replace)
        print("apply:", json.dumps(stats, ensure_ascii=False))
    else:
        print("БД не трогали. Чтобы залить: добавьте --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
