# ruff: noqa: E501
"""Scripted perfect agents for coverage level 1 (the part tools), and fairness test 3.

Each recipe answers one template with only its part tools and the calculators,
through the same dispatcher a model uses, graded with the must-have checks
against the frozen keys. Same limits as level 2: at most 25 tool calls and at
most 20 numbers of its own arithmetic. (The real budget is 25 model turns,
which allows more calls, so this is the stricter test.)

Fairness test 3 (no shortcuts) is checked on every part tool output. No
output may hold every must-have value of the question as top-level fields, and
none may hold a finished statistic (a verdict, a median, an overall percentage
or share) at the top level. Per-row values, like each module's fix share, are
parts: the agent still has to choose among them by the question's rules.

Usage:
  uv run --env-file .env python scripts/levels/perfect_agents_level1.py [TEMPLATE ...]
"""

import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
sys.path.insert(0, str(ROOT / "scripts" / "levels"))
from check_level0 import BUG_LABEL, H1, H2, MAIN_CI_PATHS, MODULE_UNDER, W  # noqa: E402
from must_haves import check  # noqa: E402
from perfect_agents_level2 import ALTS, KEYS, MAX_OWN_NUMBERS, MAX_STEPS, QUESTIONS, Agent  # noqa: E402

from repo_investigator.levels.domain import TOOLS  # noqa: E402
from repo_investigator.levels.menus import menu  # noqa: E402

FINISHED = ("verdict", "median", "pct", "share", "p_value")


def same_value(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 0.01 * max(1, abs(b))
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def holds_whole_answer(out, guess):
    """True if one output has every must-have value as a top-level field."""
    tops = [v for v in out.values() if not isinstance(v, (list, dict))]
    wanted = [v for v in guess.values() if v is not None]
    return all(any(same_value(t, w) for t in tops) for w in wanted)


def ci(repo):
    return {"workflow_paths": MAIN_CI_PATHS[repo]}


def r1(a, repo):
    c = {h: a.call("landing_run_counts", **ci(repo), start=p[0], end=p[1]) for h, p in (("H1", H1), ("H2", H2))}
    t = a.call("fisher_test", count_a=c["H1"]["failing"], total_a=c["H1"]["counted"], count_b=c["H2"]["failing"], total_b=c["H2"]["counted"])
    a.use(c["H1"]["failing"], c["H1"]["counted"], c["H2"]["failing"], c["H2"]["counted"])
    return {"h1_failure_rate_pct": 100 * t["rate_a"], "h2_failure_rate_pct": 100 * t["rate_b"], "verdict": t["verdict"]}


def r2(a, repo):
    r = {h: a.call("run_durations", **ci(repo), event="push", start=p[0], end=p[1])["result_id"] for h, p in (("H1", H1), ("H2", H2))}
    m = a.call("compare_medians", a={"result_id": r["H1"], "column": "minutes"}, b={"result_id": r["H2"], "column": "minutes"})
    return {"main_h1_minutes": m["median_a"], "main_h2_minutes": m["median_b"], "main_verdict": m["verdict"]}


def r3(a, repo):
    out = {h: a.call("first_review_times", merged_start=p[0], merged_end=p[1]) for h, p in (("H1", H1), ("H2", H2))}
    ra, rb = out["H1"]["result_id"], out["H2"]["result_id"]
    wait = a.call("compare_medians", a={"result_id": ra, "column": "wait_hours"}, b={"result_id": rb, "column": "wait_hours"})
    after = a.call("compare_medians", a={"result_id": ra, "column": "after_review_hours"}, b={"result_id": rb, "column": "after_review_hours"})
    a.use(out["H2"]["without_review"], out["H2"]["merged_prs"])
    return {"wait_h1_hours": wait["median_a"], "wait_h2_hours": wait["median_b"], "wait_verdict": wait["verdict"],
            "after_h1_hours": after["median_a"], "after_h2_hours": after["median_b"], "after_verdict": after["verdict"],
            "h2_no_review_pct": 100 * out["H2"]["without_review"] / out["H2"]["merged_prs"]}


def r4(a, repo):
    merged = a.call("merged_pr_count", start=H2[0], end=H2[1])["merged_prs"]
    approved = a.call("approved_pr_count", start=H2[0], end=H2[1])["approved_merged_prs"]
    a.use(merged, approved)
    return {"unapproved": merged - approved, "unapproved_pct": 100 * (merged - approved) / merged}


def r5(a, repo):
    label = BUG_LABEL.get(repo, "bug")
    opened = a.call("issue_counts", label=label, event="opened", start=W[0], end=W[1])["issues"]
    closed = a.call("issue_counts", label=label, event="closed", start=W[0], end=W[1])["issues"]
    b = a.call("binomial_test", k=closed, n=opened + closed)
    a.use(opened, closed)
    verdict = "balanced" if not b["differs_from_half"] else ("growing" if opened > closed else "shrinking")
    t = a.call("time_to_close", label=label, opened_start=H1[0], opened_end=H1[1], as_of=W[1])
    s = a.call("summarize", data={"result_id": t["result_id"], "column": "days_to_close"}, missing="as_infinite")
    return {"opened": opened, "closed": closed, "verdict": verdict, "median_days_to_close": None if s["median"] == "infinite" else s["median"]}


def r6(a, repo):
    out = a.call("module_commit_counts", module_under=MODULE_UNDER[repo], start=W[0], end=W[1])
    rows = out["rows"]
    most = sorted(rows, key=lambda r: (-r[2], -r[1], r[0]))[0]
    top = sorted((r for r in rows if r[1] >= 20), key=lambda r: (-r[3], r[0]))[0]
    return {"most_fixes_module": most[0], "top_share_module": top[0]}


def r7(a, repo):
    out = a.call("red_stretches", **ci(repo), start=H2[0], end=H2[1])
    longest = a.call("summarize", data={"result_id": out["result_id"], "column": "hours_red"})["max"]
    i = out["columns"].index("hours_red")
    # Ties on time red go to the stretch with more failing commits.
    best = max((r for r in out["rows"] if r[i] == round(longest, 2)), key=lambda r: r[out["columns"].index("failing_commits")])
    first = best[out["columns"].index("first_failing_sha")]
    a.call("commit_details", sha=first)
    return {"first_failing_sha": first, "next_passing_sha": best[out["columns"].index("next_passing_sha")], "hours_red": best[i]}


def r8(a, repo):
    top = {}
    for h, p in (("H1", H1), ("H2", H2)):
        out = a.call("commits_by_person", start=p[0], end=p[1])
        a.use(out["rows"][0][1], out["rows"][1][1], out["human_commits"])
        top[h] = (out["rows"][0][1] + out["rows"][1][1], out["human_commits"])
    t = a.call("fisher_test", count_a=top["H1"][0], total_a=top["H1"][1], count_b=top["H2"][0], total_b=top["H2"][1])
    a.use(t["rate_a"], t["rate_b"])
    diff = t["rate_b"] - t["rate_a"]
    verdict = ("more concentrated" if diff > 0 else "less concentrated") if t["p_value"] < 0.05 and abs(diff) >= 0.05 else "no clear change"
    return {"h1_top2_pct": 100 * t["rate_a"], "h2_top2_pct": 100 * t["rate_b"], "verdict": verdict}


def r9(a, repo):
    out = a.call("review_pairs_by_reviewer", start=H2[0], end=H2[1])
    a.use(out["rows"][0][1], out["rows"][1][1], out["pr_reviewer_pairs"])
    return {"reviewers": out["reviewers"], "top2_pct": 100 * (out["rows"][0][1] + out["rows"][1][1]) / out["pr_reviewer_pairs"]}


def r10(a, repo):
    n = a.call("fix_commit_count", start=W[0], end=W[1])["fix_commits"]
    t = a.call("fix_commit_count", start=W[0], end=W[1], changed_test_file="yes")["fix_commits"]
    a.use(n, t)
    return {"fix_commits": n, "changed_test_pct": 100 * t / n}


def r11(a, repo):
    bots = ["renovate", "dependabot"]
    c = a.call("bot_pr_counts", authors=bots, opened_start=W[0], opened_end=W[1])
    r = {h: a.call("merge_times", authors=bots, merged_start=p[0], merged_end=p[1])["result_id"] for h, p in (("H1", H1), ("H2", H2))}
    m = a.call("compare_medians", a={"result_id": r["H1"], "column": "hours_to_merge"}, b={"result_id": r["H2"], "column": "hours_to_merge"})
    a.use(c["opened"], c["merged_by_end"], c["closed_unmerged_by_end"])
    return {"opened": c["opened"], "merged_pct": 100 * c["merged_by_end"] / c["opened"], "closed_unmerged_pct": 100 * c["closed_unmerged_by_end"] / c["opened"],
            "merge_h1_hours": m["median_a"], "merge_h2_hours": m["median_b"], "merge_verdict": m["verdict"]}


def r12(a, repo):
    r = {h: a.call("commit_sizes", start=p[0], end=p[1])["result_id"] for h, p in (("H1", H1), ("H2", H2))}
    m = a.call("compare_medians", a={"result_id": r["H1"], "column": "lines"}, b={"result_id": r["H2"], "column": "lines"})
    fix = a.call("commit_sizes", start=W[0], end=W[1], kind="fix")["result_id"]
    other = a.call("commit_sizes", start=W[0], end=W[1], kind="other")["result_id"]
    sf = a.call("summarize", data={"result_id": fix, "column": "lines"})
    so = a.call("summarize", data={"result_id": other, "column": "lines"})
    return {"h1_median_lines": m["median_a"], "h2_median_lines": m["median_b"], "verdict": m["verdict"], "fix_median_lines": sf["median"], "other_median_lines": so["median"]}


RECIPES = {f"R{i}": f for i, f in enumerate([r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12], start=1)}


def finished_fields(out):
    """Top-level fields of a part tool output that look like a finished statistic.
    Per-row columns (like each module's fix share) are parts, not answers."""
    return [k for k in out if any(w in k.lower() for w in FINISHED)]


def main():
    wanted = sys.argv[1:] or list(RECIPES)
    conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    conn.read_only = True
    results, bad = [], 0
    for q in QUESTIONS:
        t = q["template"]
        if t not in wanted or not q["in_study"]:
            continue
        a = Agent(conn, q["repo_slug"], menu(t, 1))
        problems = []
        try:
            guess = RECIPES[t](a, q["repo"])
            items = check(t, KEYS[t][q["repo"]], guess, ALTS.get(t, {}).get(q["repo"], []))
        except Exception as e:  # noqa: BLE001
            guess, items = None, {"recipe error": False}
            problems.append(str(e))
        used = [tool for tool, _ in a.log]
        if any(u not in TOOLS and u not in ("summarize", "fisher_test", "binomial_test", "compare_medians") for u in used):
            problems.append("used a query tool")
        for tool, out in a.log:
            if tool in TOOLS:
                problems += [f"{tool} returns a finished statistic: {f}" for f in finished_fields(out)]
                if guess and holds_whole_answer(out, guess):
                    problems.append(f"{tool} alone holds every must-have value")
        problems += [f"must-have failed: {k}" for k, v in items.items() if not v]
        if a.steps > MAX_STEPS or a.own > MAX_OWN_NUMBERS:
            problems.append(f"over the limits: {a.steps} calls, {a.own} own numbers")
        bad += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'} {q['id']:22s} calls {a.steps:2d} own numbers {a.own:2d}")
        for p in problems:
            print(f"     {p}")
        results.append({"id": q["id"], "pass": not problems, "calls": a.steps, "own_numbers": a.own, "problems": problems, "guess": guess})
    out = ROOT / "levels_results" / "perfect_agents_level1.json"
    out.write_text(json.dumps(results, indent=1, default=str) + "\n")
    print(f"{len(results) - bad}/{len(results)} pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
