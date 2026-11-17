"""Run the definition checks on every wrong level 2 answer and add them up.

Exploratory. See common.py for the method and the verdicts.

Usage:
  uv run --env-file .env python scripts/exploratory/definitions/run_checks.py [R10 R5 ...]
"""

import importlib
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_targets  # noqa: E402

OUT = ROOT / "analysis_results" / "exploratory" / "definitions"
ALL = [f"R{n}" for n in range(1, 13)]


def run(template, conn):
    mod = importlib.import_module(template.lower())
    targets = load_targets(template)
    alt = mod.prepare(conn, sorted({t.repo for t in targets}))
    rows = []
    for t in targets:
        verdicts = mod.check(t, alt)
        missing = [d for d in mod.DEFINITIONS if d not in verdicts]
        if missing:
            raise SystemExit(f"{template} {t.run_id}: no verdict for {missing}")
        rows.append(
            {
                "run_id": t.run_id,
                "repo": t.repo,
                "model": t.model,
                "attempt": t.attempt,
                "verdicts": {d: asdict(verdicts[d]) for d in mod.DEFINITIONS},
            }
        )
    summary = {d: Counter(r["verdicts"][d]["verdict"] for r in rows) for d in mod.DEFINITIONS}
    by_model = defaultdict(Counter)
    for r in rows:
        for d, v in r["verdicts"].items():
            if v["verdict"] in ("missed", "other_reading"):
                by_model[r["model"]][f"{d}: {v['verdict']}"] += 1
    return {
        "template": template,
        "runs": len(rows),
        "alternative_keys": alt,
        "summary": summary,
        "by_model": by_model,
        "rows": rows,
    }


def main():
    templates = sys.argv[1:] or [t for t in ALL if (Path(__file__).parent / f"{t.lower()}.py").exists()]
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for template in templates:
            res = run(template, conn)
            (OUT / f"{template.lower()}.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
            print(f"{template}: {res['runs']} runs")
            for d, c in res["summary"].items():
                print(f"  {d:12} {dict(c)}")
            for m, c in sorted(res["by_model"].items()):
                print(f"  {m:24} {dict(c)}")


if __name__ == "__main__":
    main()
