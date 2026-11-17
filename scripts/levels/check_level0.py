# ruff: noqa: E501
"""Fairness test 1: level 0 is exact.

For every study question, call its direct tool with the question's own
arguments and check three things:
1. every argument value the tool gets is written in the question text (or is
   one of the shared dates), so the call uses nothing the question doesn't say;
2. the unrounded output equals the frozen key on every key field (1e-9);
3. the rounded output, as the agent sees it, passes every must-have check.

If a check fails, the tool has a bug. The key is never touched.

Usage:
  uv run --env-file .env python scripts/levels/check_level0.py [TEMPLATE ...]
"""

import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
from must_haves import check  # noqa: E402

from repo_investigator.levels import domain  # noqa: E402
from repo_investigator.levels.query import ResultStore  # noqa: E402

KEYS = json.loads((ROOT / "answer_keys" / "keys_primary.json").read_text())
ALTS = json.loads((ROOT / "answer_keys" / "accepted_alternatives.json").read_text())
QUESTIONS = json.loads((ROOT / "questions" / "questions.json").read_text())

W = ("2025-10-01", "2026-09-20")
H1 = ("2025-10-01", "2026-03-31")
H2 = ("2026-04-01", "2026-09-20")
MAIN_CI_PATHS = {
    "tokio": [".github/workflows/ci.yml"],
    "eslint": [".github/workflows/ci.yml"],
    "sqlalchemy": [".github/workflows/run-test.yaml"],
    "vite": [".github/workflows/ci.yml"],
    # As the junit questions write it: "main.yml, renamed to ci.yml".
    "junit-framework": [".github/workflows/main.yml", "ci.yml"],
    "prometheus": [".github/workflows/ci.yml"],
}
BUG_LABEL = {"tokio": "C-bug", "vite": "p3-minor-bug", "junit-framework": "type: bug", "prometheus": "kind/bug"}
MODULE_UNDER = {"prometheus": "", "sqlalchemy": "lib/sqlalchemy", "eslint": "lib", "vite": "packages"}


def ab(a, b):
    return {"period_a_start": a[0], "period_a_end": a[1], "period_b_start": b[0], "period_b_end": b[1]}


def args_for(q):
    """The direct tool and its arguments, read off the question."""
    t, repo = q["template"], q["repo"]
    base = {"repo": q["repo_slug"]}
    ci = {"workflow_paths": MAIN_CI_PATHS[repo]}
    return {
        "R1": ("ci_failure_trend", {**base, **ci, **ab(H1, H2)}),
        "R2": ("ci_duration_trend", {**base, **ci, **ab(H1, H2)}),
        "R3": ("pr_review_timing_trend", {**base, **ab(H1, H2)}),
        "R4": ("unapproved_merges", {**base, "start": H2[0], "end": H2[1]}),
        "R5": ("bug_backlog_report", {**base, "label": BUG_LABEL.get(repo, "bug"), "window_start": W[0], "window_end": W[1], "opened_start": H1[0], "opened_end": H1[1]}),
        "R6": ("fix_hotspots", {**base, "module_under": MODULE_UNDER.get(repo, ""), "start": W[0], "end": W[1], "min_commits": 20}),
        "R7": ("longest_red_streak", {**base, **ci, "start": H2[0], "end": H2[1]}),
        "R8": ("commit_concentration_trend", {**base, **ab(H1, H2)}),
        "R9": ("review_load", {**base, "start": H2[0], "end": H2[1]}),
        "R10": ("fix_test_coverage", {**base, "start": W[0], "end": W[1]}),
        "R11": ("dependency_pr_report", {**base, "authors": ["renovate", "dependabot"], "window_start": W[0], "window_end": W[1], **ab(H1, H2)}),
        "R12": ("commit_size_trend", {**base, **ab(H1, H2), "window_start": W[0], "window_end": W[1]}),
    }[t]


def stated(q, args):
    """Argument values that are not written in the question text."""
    text = q["question"]
    missing = []
    for k, v in args.items():
        for item in v if isinstance(v, list) else [v]:
            if isinstance(item, int) and str(item) in text:
                continue
            if isinstance(item, str) and (item in text or (k == "module_under" and item == "" and "top-level folder" in text)):
                continue
            missing.append(f"{k}={item!r}")
    return missing


def pct(x):
    return None if x is None else 100 * x


def compare(t, out):
    """Key fields from the unrounded output, in the key's own units."""
    if t == "R1":
        a, b = out["period_a"], out["period_b"]
        return {"h1_failing": a["failing"], "h1_counted": a["commits_counted"], "h1_rate": a["failing"] / a["commits_counted"],
                "h2_failing": b["failing"], "h2_counted": b["commits_counted"], "h2_rate": b["failing"] / b["commits_counted"],
                "verdict": out["verdict"], "h1_rerun_pass_share": a["passed_after_rerun_pct"] / 100, "h2_rerun_pass_share": b["passed_after_rerun_pct"] / 100}
    if t == "R2":
        p, r = out["push"], out["pull_request"]
        return {"main_h1_min": p["period_a_median_minutes"], "main_h2_min": p["period_b_median_minutes"], "main_verdict": p["verdict"],
                "pr_h1_min": r["period_a_median_minutes"], "pr_h2_min": r["period_b_median_minutes"], "pr_verdict": r["verdict"]}
    if t == "R3":
        a, b = out["period_a"], out["period_b"]
        return {"wait_h1_h": a["median_wait_hours"], "wait_h2_h": b["median_wait_hours"], "wait_verdict": out["wait_verdict"],
                "after_h1_h": a["median_after_review_hours"], "after_h2_h": b["median_after_review_hours"], "after_verdict": out["after_review_verdict"],
                "h2_no_review_share": b["no_review_pct"] / 100}
    if t == "R4":
        return {"merged_h2": out["merged_prs"], "unapproved": out["unapproved"], "unapproved_share": out["unapproved_pct"] / 100, "unapproved_bot_prs": out["unapproved_opened_by_bots"]}
    if t == "R5":
        return {"opened": out["opened"], "closed": out["closed"], "verdict": out["verdict"], "h1_bugs": out["issues_opened_in_close_time_period"],
                "median_days_to_close": out["median_days_to_close"], "share_not_closed": out["not_closed_pct"] / 100}
    if t == "R6":
        return {"most_fixes_module": out["most_fixes_module"], "most_fixes_count": out["most_fixes_module_fix_commits"], "most_fixes_module_commits": out["most_fixes_module_commits"],
                "top_share_module": out["top_fix_share_module"], "top_share": out["top_fix_share_pct"] / 100}
    if t == "R7":
        return {"first_failing_sha": out["first_failing_sha"], "next_passing_sha": out["next_passing_sha"], "failing_commits": out["failing_commits"], "hours_red": out["hours_red"]}
    if t == "R8":
        return {"h1_top2_share": out["period_a"]["top2_pct"] / 100, "h2_top2_share": out["period_b"]["top2_pct"] / 100, "verdict": out["verdict"]}
    if t == "R9":
        return {"reviewers": out["reviewers"], "top2_share": out["top2_pct"] / 100}
    if t == "R10":
        return {"fix_commits": out["fix_commits"], "share_changed_test": out["changed_test_pct"] / 100}
    if t == "R11":
        return {"opened": out["opened"], "merged_share": out["merged_pct"] / 100, "closed_unmerged_share": out["closed_unmerged_pct"] / 100,
                "closed_autoclosed_share": None if out["closed_unmerged_autoclosed_pct"] is None else out["closed_unmerged_autoclosed_pct"] / 100,
                "merge_h1_h": out["period_a_median_hours_to_merge"], "merge_h2_h": out["period_b_median_hours_to_merge"], "merge_verdict": out["merge_time_verdict"]}
    if t == "R12":
        return {"h1_median_lines": out["period_a_median_lines"], "h2_median_lines": out["period_b_median_lines"], "verdict": out["verdict"],
                "fix_median_lines": out["window_fix_median_lines"], "other_median_lines": out["window_other_median_lines"]}


def guess(t, out):
    """What a faithful agent would report, from the rounded output."""
    c = compare(t, out)
    if t == "R1":
        return {"h1_failure_rate_pct": out["period_a"]["failure_pct"], "h2_failure_rate_pct": out["period_b"]["failure_pct"], "verdict": out["verdict"]}
    if t == "R2":
        return {"main_h1_minutes": c["main_h1_min"], "main_h2_minutes": c["main_h2_min"], "main_verdict": c["main_verdict"],
                "pr_h1_minutes": c["pr_h1_min"], "pr_h2_minutes": c["pr_h2_min"], "pr_verdict": c["pr_verdict"]}
    if t == "R3":
        return {"wait_h1_hours": c["wait_h1_h"], "wait_h2_hours": c["wait_h2_h"], "wait_verdict": c["wait_verdict"], "after_h1_hours": c["after_h1_h"],
                "after_h2_hours": c["after_h2_h"], "after_verdict": c["after_verdict"], "h2_no_review_pct": out["period_b"]["no_review_pct"]}
    if t == "R4":
        return {"merged_h2": out["merged_prs"], "unapproved": out["unapproved"], "unapproved_pct": out["unapproved_pct"], "unapproved_bot_prs": out["unapproved_opened_by_bots"]}
    if t == "R5":
        return {"opened": out["opened"], "closed": out["closed"], "verdict": out["verdict"], "median_days_to_close": out["median_days_to_close"], "still_open_pct": out["not_closed_pct"]}
    if t == "R6":
        return {"most_fixes_module": out["most_fixes_module"], "top_share_module": out["top_fix_share_module"]}
    if t == "R7":
        return {"first_failing_sha": out["first_failing_sha"], "next_passing_sha": out["next_passing_sha"], "hours_red": out["hours_red"]}
    if t == "R8":
        return {"h1_top2_pct": out["period_a"]["top2_pct"], "h2_top2_pct": out["period_b"]["top2_pct"], "verdict": out["verdict"]}
    if t == "R9":
        return {"reviewers": out["reviewers"], "top2_pct": out["top2_pct"]}
    if t == "R10":
        return {"fix_commits": out["fix_commits"], "changed_test_pct": out["changed_test_pct"]}
    if t == "R11":
        return {"opened": out["opened"], "merged_pct": out["merged_pct"], "closed_unmerged_pct": out["closed_unmerged_pct"],
                "merge_h1_hours": c["merge_h1_h"], "merge_h2_hours": c["merge_h2_h"], "merge_verdict": c["merge_verdict"]}
    if t == "R12":
        return {k: c[k] for k in ("h1_median_lines", "h2_median_lines", "verdict", "fix_median_lines", "other_median_lines")}


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) <= 1e-9 * max(1, abs(float(b)))
    return a == b


def main():
    wanted = sys.argv[1:]
    conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    conn.read_only = True
    bad = n = 0
    for q in QUESTIONS:
        t = q["template"]
        if not q["in_study"] or (wanted and t not in wanted):
            continue
        n += 1
        name, args = args_for(q)
        problems = [f"not in question: {m}" for m in stated(q, args)]
        exact = domain.call(conn, ResultStore(), name, args, exact=True)
        key = KEYS[t][q["repo"]]
        got = compare(t, exact)
        problems += [f"{k}: tool {got[k]!r}, key {key[k]!r}" for k in key if not same(got.get(k), key[k])]
        shown = domain.call(conn, ResultStore(), name, args)
        items = check(t, key, guess(t, shown), ALTS.get(t, {}).get(q["repo"], []))
        problems += [f"must-have failed: {k}" for k, v in items.items() if not v]
        bad += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'} {q['id']:22s} {name}")
        for p in problems:
            print(f"     {p}")
    print(f"{n - bad}/{n} pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
