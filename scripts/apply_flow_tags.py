"""Залить sidecar с flow_tags в SQLite articles (для портала /flows/investments|policy).

  # эвристика (после tag_flows_heuristic.py)
  python scripts/apply_flow_tags.py --path data/runs/flow_tags/tagged_heuristic_investments_policy.json

  # Lab LLM (после tag_flows_lab.py)
  python scripts/apply_flow_tags.py --path data/runs/flow_tags/tagged_lab_investments_policy.json

  # стандартные sidecar пайплайна
  python scripts/apply_flow_tags.py
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
from gartner.pipeline.heuristic_flow_split import apply_tags_to_db  # noqa: E402
from gartner.pipeline.tag_flows import apply_flow_tags_from_sidecars  # noqa: E402


def load_sidecar(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: ожидался JSON-массив")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Импорт flow_tags в articles")
    p.add_argument(
        "--path",
        type=Path,
        action="append",
        default=[],
        help="Sidecar JSON. Можно несколько. По умолчанию — tagged.json + tagged_radar.json",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="Не merge, а заменить метки целиком (только для --path)",
    )
    p.add_argument(
        "--only-untagged",
        action="store_true",
        help="Режим стандартных sidecar: не трогать уже размеченные",
    )
    args = p.parse_args()
    ensure_dirs()

    if not args.path:
        report = apply_flow_tags_from_sidecars(only_untagged=bool(args.only_untagged))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    for path in args.path:
        if not path.exists():
            # относительный от корня
            alt = ROOT / path
            if alt.exists():
                path = alt
            else:
                print(f"нет файла: {path}", file=sys.stderr)
                return 2
        rows = load_sidecar(path)
        stats = apply_tags_to_db(rows, merge_existing=not args.replace)
        print(f"{path}: {json.dumps(stats, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
