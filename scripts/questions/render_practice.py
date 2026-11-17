# ruff: noqa: E501
"""Write the practice set: questions/practice.json and answer_keys/practice_keys.json.

The practice set is for developing the system prompt. The study questions are
never used for that. It follows the usual train, dev and test split: the same
twelve question types as the study, but different instances. Each practice
question uses a template's exact study wording with a different window, split
into two quarter-length halves, so every number and answer differs from the
study's. "H1" here means different dates than in the study, which also checks
that the prompt takes dates from the question, not from habit.

Keys come from the level 0 direct tools, which equal the frozen key code on
all 63 study questions (scripts/levels/check_level0.py).

Usage:
  uv run --env-file .env python scripts/questions/render_practice.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "questions"))
sys.path.insert(0, str(ROOT / "scripts" / "levels"))
from check_level0 import BUG_LABEL, MAIN_CI_PATHS, MODULE_UNDER, compare  # noqa: E402
from render_questions import FIX_RULE, LANDING, REPOS, TEMPLATES, TEST_FILE  # noqa: E402

from repo_investigator.levels import domain  # noqa: E402
from repo_investigator.levels.query import ResultStore  # noqa: E402

OUT_Q = ROOT / "questions" / "practice.json"
OUT_K = ROOT / "answer_keys" / "practice_keys.json"
WINDOWS = {
    "A": {"w": ("2025-10-01", "2026-03-31"), "h1": ("2025-10-01", "2025-12-31"), "h2": ("2026-01-01", "2026-03-31")},
    "B": {"w": ("2026-04-01", "2026-09-20"), "h1": ("2026-04-01", "2026-06-30"), "h2": ("2026-07-01", "2026-09-20")},
}
# One practice question per template, on a mix of repos and both windows.
PRACTICE = [
    ("R1", "vite", "B"),
    ("R2", "prometheus", "A"),
    ("R3", "eslint", "A"),
    ("R4", "junit-framework", "A"),
    ("R5", "prometheus", "B"),
    ("R6", "prometheus", "B"),
    ("R7", "junit-framework", "A"),
    ("R8", "vite", "A"),
    ("R9", "prometheus", "B"),
    ("R10", "junit-framework", "B"),
    ("R11", "vite", "B"),
    ("R12", "tokio", "A"),
]


def window_text(win):
    w, h1, h2 = WINDOWS[win]["w"], WINDOWS[win]["h1"], WINDOWS[win]["h2"]
    return f"All dates are in UTC. The window is {w[0]} to {w[1]}. H1 is {h1[0]} to {h1[1]} and H2 is {h2[0]} to {h2[1]}, both inclusive."


def tool_args(template, repo, slug, win):
    w, h1, h2 = WINDOWS[win]["w"], WINDOWS[win]["h1"], WINDOWS[win]["h2"]
    ab = {"period_a_start": h1[0], "period_a_end": h1[1], "period_b_start": h2[0], "period_b_end": h2[1]}
    base, ci = {"repo": slug}, {"workflow_paths": MAIN_CI_PATHS[repo]}
    return {
        "R1": ("ci_failure_trend", {**base, **ci, **ab}),
        "R2": ("ci_duration_trend", {**base, **ci, **ab}),
        "R3": ("pr_review_timing_trend", {**base, **ab}),
        "R4": ("unapproved_merges", {**base, "start": h2[0], "end": h2[1]}),
        "R5": ("bug_backlog_report", {**base, "label": BUG_LABEL.get(repo, "bug"), "window_start": w[0], "window_end": w[1], "opened_start": h1[0], "opened_end": h1[1]}),
        "R6": ("fix_hotspots", {**base, "module_under": MODULE_UNDER.get(repo, ""), "start": w[0], "end": w[1], "min_commits": 20}),
        "R7": ("longest_red_streak", {**base, **ci, "start": h2[0], "end": h2[1]}),
        "R8": ("commit_concentration_trend", {**base, **ab}),
        "R9": ("review_load", {**base, "start": h2[0], "end": h2[1]}),
        "R10": ("fix_test_coverage", {**base, "start": w[0], "end": w[1]}),
        "R11": ("dependency_pr_report", {**base, "authors": ["renovate", "dependabot"], "window_start": w[0], "window_end": w[1], **ab}),
        "R12": ("commit_size_trend", {**base, **ab, "window_start": w[0], "window_end": w[1]}),
    }[template]


def main():
    conn = psycopg.connect(os.environ["STUDY_SANDBOX_DATABASE_URL"])
    questions, keys = [], {}
    for template, repo, win in PRACTICE:
        s = REPOS[repo]
        body = TEMPLATES[template][1].format(slug=s["slug"], ci=s["ci"], label=s["label"], module=s["module"], landing=LANDING, fix=FIX_RULE, test=TEST_FILE)
        qid = f"P-{template}-{repo}-{win}"
        name, args = tool_args(template, repo, s["slug"], win)
        out = domain.call(conn, ResultStore(), name, args, exact=True)
        questions.append({"id": qid, "set": "practice", "template": template, "repo": repo, "repo_slug": s["slug"], "window": win, "question": f"{body} {window_text(win)}", "in_study": True})
        keys[qid] = {"template": template, "key": compare(template, out), "direct_tool": name, "args": args}
        print(qid, json.dumps(keys[qid]["key"], default=str)[:200])
    OUT_Q.write_text(json.dumps(questions, indent=2) + "\n")
    OUT_K.write_text(json.dumps(keys, indent=2, default=str) + "\n")
    print(f"wrote {OUT_Q} and {OUT_K}")


if __name__ == "__main__":
    main()
