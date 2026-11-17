# ruff: noqa: E501
"""Grade the no-tool floor against the frozen keys and apply the drop rule.

Rule (written before the first run): a question is floor-solved, and dropped
from the study, if any floor model meets every must-have item in at least 2 of
its 3 tries. The report also lists items that guessing gets right often, which
the main grader should not lean on.

Writes floor_results/floor_report.md and floor_results/floor_summary.json.

Usage:
  uv run python scripts/floor/grade_floor.py            # grade the floor
  uv run python scripts/floor/grade_floor.py --selftest # check the grader itself
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from must_haves import check  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
KEYS = json.loads((ROOT / "answer_keys" / "keys_primary.json").read_text())
ALTS = json.loads((ROOT / "answer_keys" / "accepted_alternatives.json").read_text())
QUESTIONS = json.loads((ROOT / "questions" / "questions.json").read_text())
RAW = ROOT / "floor_results" / "raw"
REPORT = ROOT / "floor_results" / "floor_report.md"
SUMMARY = ROOT / "floor_results" / "floor_summary.json"
TRIES = 3


def grade(q, guess):
    key = KEYS[q["template"]][q["repo"]]
    alts = ALTS.get(q["template"], {}).get(q["repo"], [])
    return check(q["template"], key, guess or {}, alts)


def key_as_guess(q):
    """Write a key in the answer format, to check that a perfect answer passes."""
    k = KEYS[q["template"]][q["repo"]]
    pct = lambda x: None if x is None else 100 * x  # noqa: E731
    t = q["template"]
    return {
        "R1": lambda: {"h1_failure_rate_pct": pct(k["h1_rate"]), "h2_failure_rate_pct": pct(k["h2_rate"]),
                       "verdict": k["verdict"]},
        "R2": lambda: {"main_h1_minutes": k["main_h1_min"], "main_h2_minutes": k["main_h2_min"],
                       "main_verdict": k["main_verdict"]},
        "R3": lambda: {"wait_h1_hours": k["wait_h1_h"], "wait_h2_hours": k["wait_h2_h"],
                       "after_h1_hours": k["after_h1_h"], "after_h2_hours": k["after_h2_h"],
                       "wait_verdict": k["wait_verdict"], "after_verdict": k["after_verdict"]},
        "R4": lambda: {"unapproved": k["unapproved"], "unapproved_bot_prs": k["unapproved_bot_prs"]},
        "R5": lambda: {"opened": k["opened"], "closed": k["closed"], "verdict": k["verdict"],
                       "median_days_to_close": k["median_days_to_close"]},
        "R6": lambda: {"most_fixes_module": k["most_fixes_module"], "top_share_module": k["top_share_module"]},
        "R7": lambda: {"first_failing_sha": k["first_failing_sha"][:8], "next_passing_sha": k["next_passing_sha"],
                       "hours_red": k["hours_red"]},
        "R8": lambda: {"h1_top2_pct": pct(k["h1_top2_share"]), "h2_top2_pct": pct(k["h2_top2_share"]),
                       "verdict": k["verdict"]},
        "R9": lambda: {"top2_pct": pct(k["top2_share"])},
        "R10": lambda: {"changed_test_pct": pct(k["share_changed_test"])},
        "R11": lambda: {"opened": k["opened"], "merged_pct": pct(k["merged_share"]), "merge_h1_hours": k["merge_h1_h"],
                        "merge_h2_hours": k["merge_h2_h"], "merge_verdict": k["merge_verdict"]},
        "R12": lambda: {f: k[f] for f in ("h1_median_lines", "h2_median_lines", "verdict", "fix_median_lines",
                                          "other_median_lines")},
    }[t]()  # fmt: skip


def selftest():
    perfect = [all(grade(q, key_as_guess(q)).values()) for q in QUESTIONS]
    empty = [any(grade(q, {}).values()) for q in QUESTIONS]
    alt = {"first_failing_sha": "ad922b18", "next_passing_sha": "05b4ea07", "hours_red": 33.1}
    junit = next(q for q in QUESTIONS if q["id"] == "R7-junit-framework")
    near = dict(key_as_guess(QUESTIONS[0]))
    near["h1_failure_rate_pct"] = near["h1_failure_rate_pct"] + 1.6
    ok = (
        all(perfect)
        and not any(empty)
        and all(grade(junit, alt).values())
        and not all(grade(QUESTIONS[0], near).values())
    )
    print(f"perfect answers pass: {sum(perfect)}/{len(QUESTIONS)}")
    print(f"empty answers pass any item: {sum(empty)}/{len(QUESTIONS)}")
    print(f"junit near-tie alternative accepted: {all(grade(junit, alt).values())}")
    print(f"1.6 points off on an R1 rate fails: {not all(grade(QUESTIONS[0], near).values())}")
    print("selftest", "passed" if ok else "FAILED")
    sys.exit(0 if ok else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    replies = [r for p in sorted(RAW.glob("*.json")) for r in json.loads(p.read_text())]
    by_q = {q["id"]: q for q in QUESTIONS}
    full = defaultdict(lambda: defaultdict(int))  # question -> model -> tries meeting all must-haves
    items = defaultdict(lambda: [0, 0])  # (template, item) -> [hits, tries]
    models = sorted({r["model"] for r in replies})
    cost = sum(r.get("cost") or 0 for r in replies)
    unparsed = sum(r.get("guess") is None for r in replies)
    for r in replies:
        q = by_q[r["id"]]
        result = grade(q, r.get("guess"))
        if all(result.values()):
            full[q["id"]][r["model"]] += 1
        for item, passed in result.items():
            items[(q["template"], item)][0] += passed
            items[(q["template"], item)][1] += 1

    dropped = sorted(qid for qid, per_model in full.items() if any(n >= 2 for n in per_model.values()))
    lines = [
        "# No-tool floor",
        "",
        f"Models: {', '.join(models)}. Each answered each of the {len(QUESTIONS)} questions {TRIES} times "
        f"with no tools and no data. Replies: {len(replies)}, unparsed: {unparsed}, cost: ${cost:.2f}.",
        "",
        "Rule, written before the first run: a question is dropped if any model meets every must-have "
        "item in at least 2 of its 3 tries.",
        "",
        "## Dropped",
        "",
    ]
    lines += [f"- {qid} ({dict(full[qid])})" for qid in dropped] or ["None."]
    lines += ["", "## Met every must-have at least once, but not dropped", ""]
    once = sorted(qid for qid in full if qid not in dropped)
    lines += [f"- {qid} ({dict(full[qid])})" for qid in once] or ["None."]
    lines += [
        "",
        "## How often guessing gets each must-have item",
        "",
        "| Template | Item | Hit rate |",
        "|---|---|---|",
    ]
    for (t, item), (hits, n) in sorted(items.items(), key=lambda x: (int(x[0][0][1:]), x[0][1])):
        lines.append(f"| {t} | {item} | {hits}/{n} ({100 * hits / n:.0f}%) |")
    REPORT.write_text("\n".join(lines) + "\n")
    SUMMARY.write_text(
        json.dumps(
            {
                "dropped": dropped,
                "solved_once": once,
                "cost_usd": cost,
                "replies": len(replies),
                "unparsed": unparsed,
                "models": models,
            },
            indent=2,
        )
        + "\n"  # fmt: skip
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
