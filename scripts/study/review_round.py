# ruff: noqa: E501
"""Show a practice round for review: each run's RESULTS block next to the key.

This is for developing the prompt on practice questions only. It reads
answer_keys/practice_keys.json, never the study keys, and refuses run sets
made of study questions.

Usage:
  uv run python scripts/study/review_round.py RUN_SET [RUN_SET ...] [--setup L2] [--only-problems]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
KEYS = json.loads((ROOT / "answer_keys" / "practice_keys.json").read_text())
# The must-have key fields of each template, as in scripts/floor/must_haves.py.
MUST = {
    "R1": ["h1_rate", "h2_rate", "verdict"],
    "R2": ["main_h1_min", "main_h2_min", "main_verdict"],
    "R3": ["wait_h1_h", "wait_h2_h", "after_h1_h", "after_h2_h", "wait_verdict", "after_verdict"],
    "R4": ["unapproved", "unapproved_bot_prs"],
    "R5": ["opened", "closed", "verdict", "median_days_to_close"],
    "R6": ["most_fixes_module", "top_share_module"],
    "R7": ["first_failing_sha", "next_passing_sha", "hours_red"],
    "R8": ["h1_top2_share", "h2_top2_share", "verdict"],
    "R9": ["reviewers", "top2_share"],
    "R10": ["fix_commits", "share_changed_test"],
    "R11": ["opened", "merged_share", "closed_unmerged_share", "merge_h1_h", "merge_h2_h", "merge_verdict"],
    "R12": ["h1_median_lines", "h2_median_lines", "verdict", "fix_median_lines", "other_median_lines"],
}


def results_block(answer):
    if not answer:
        return None
    m = re.search(r"RESULTS\s*\n(.*)", answer, re.DOTALL)
    return m.group(1).strip() if m else None


def fmt(k, v):
    if isinstance(v, float):
        return f"{100 * v:.2f}%" if "share" in k or "rate" in k else f"{v:.2f}"
    return str(v)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    setup = sys.argv[sys.argv.index("--setup") + 1] if "--setup" in sys.argv else None
    rows = []
    for rs in args:
        if rs == setup:
            continue
        for line in (ROOT / "study_runs" / rs / "runs.jsonl").read_text().splitlines():
            r = json.loads(line)
            if not r["question_id"].startswith("P-"):
                raise SystemExit("This script is for practice runs only.")
            rows.append(r)
    if setup:
        rows = [r for r in rows if r["setup"] == setup]
    summary = defaultdict(Counter)
    for r in sorted(rows, key=lambda r: (r["template"], r["question_id"], r["setup"], r["model"])):
        k = KEYS[r["question_id"]]["key"]
        block = results_block(r["final_answer"])
        summary[(r["model"].split("/")[-1], r["setup"])][r["stop_reason"]] += 1
        summary[(r["model"].split("/")[-1], r["setup"])]["no RESULTS block"] += (
            r["stop_reason"] == "answered" and block is None
        )
        summary[(r["model"].split("/")[-1], r["setup"])]["cost"] += r["cost_usd"]
        print(
            f"\n=== {r['question_id']} | {r['setup']} | {r['model'].split('/')[-1]} | {r['stop_reason']}, {r['turns']} turns, {r['tool_calls']} calls, {r['tool_errors']} errors, ${r['cost_usd']:.4f}"
        )
        print("KEY:    " + "; ".join(f"{f}={fmt(f, k.get(f))}" for f in MUST[r["template"]]))
        if block:
            print("ANSWER: " + block.replace("\n", "\n        "))
        elif r["final_answer"]:
            print("ANSWER (no RESULTS block): " + r["final_answer"][-500:].replace("\n", " "))
        else:
            err = next((s["content"] for s in r["steps"] if s["step_type"] == "error"), "")
            print("NO ANSWER: " + err[:300])
    print("\nSUMMARY")
    for (model, s), c in sorted(summary.items()):
        print(
            f"  {model:24s} {s:10s} "
            + ", ".join(f"{k}={v:.4f}" if k == "cost" else f"{k}={v}" for k, v in sorted(c.items()) if v)
        )


if __name__ == "__main__":
    main()
