# ruff: noqa: E501
"""Scripted perfect agents for coverage level 2 (the generic query tools).

Each recipe answers one template using only the level 2 menu (7 query tools
and 4 calculators), through the same dispatcher a model uses. The answer is
graded with the must-have checks in scripts/floor/must_haves.py against the
frozen keys. A recipe passes when every must-have item passes, it uses at
most 25 tool calls, and it does its own arithmetic on at most 20 numbers read
from tool outputs (counted with Agent.use). That makes "reachable" mean
reachable for a model, not only for a script.

The recipes follow the question text and the shared definitions in the system
prompt, not the key code. Where the two give different answers, that is a
finding about the question or the key, and it is reported, never patched over.

Usage:
  uv run --env-file .env python scripts/levels/perfect_agents_level2.py [TEMPLATE ...]
"""

import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "floor"))
from must_haves import check  # noqa: E402

from repo_investigator.levels.tools import CALCULATORS, QUERY_SCHEMAS, make_dispatch  # noqa: E402

KEYS = json.loads((ROOT / "answer_keys" / "keys_primary.json").read_text())
ALTS = json.loads((ROOT / "answer_keys" / "accepted_alternatives.json").read_text())
QUESTIONS = json.loads((ROOT / "questions" / "questions.json").read_text())
MENU = [*QUERY_SCHEMAS, *CALCULATORS]
MAX_STEPS, MAX_OWN_NUMBERS = 25, 20

W0, H2, W1 = "2025-10-01", "2026-04-01", "2026-09-21"
HALVES = {"H1": (W0, H2), "H2": (H2, W1)}
# Shared definitions, as the system prompt will state them.
BOTS = ["renovate", "dependabot", "github-actions", "junit-builds", "copilot-pull-request-reviewer", "copilot-swe-agent", "Copilot"]
BOT_ENDING = r"(\[bot\]|bot)$"
AUTOMATION_EMAILS = ["jenkins@eslint-03", "eslint@googlegroups.com"]
FIX = r"\b(fix|fixes|fixed|fixing|bugfix)\b"
FAILING = ["failure", "timed_out", "startup_failure"]
TEST_PATH = r"(^|/)(tests?|__tests__|testdata|testing|fixtures|playground|[^/]*[-_]tests?)/|(_test\.go|_test\.py|tests?\.java|tests?\.kt|\.(test|spec)\.[cm]?[jt]sx?)$|(^|/)test_[^/]*\.py$"
DOC_PATH = r"(^|/)(doc|docs|documentation|\.github|changelog\.d)/|\.(md|rst|txt|adoc)$"
MAIN_CI_PATHS = {
    "tokio": [".github/workflows/ci.yml"],
    "eslint": [".github/workflows/ci.yml"],
    "sqlalchemy": [".github/workflows/run-test.yaml"],
    "vite": [".github/workflows/ci.yml"],
    "junit-framework": [".github/workflows/main.yml", ".github/workflows/ci.yml"],
    "prometheus": [".github/workflows/ci.yml"],
}


def f(column, op, value=None, other=None):
    out = {"column": column, "op": op}
    if other is not None:
        out["other_column"] = other
    elif value is not None:
        out["value"] = value
    return out


def between(column, lo, hi):
    return [f(column, "gte", lo), f(column, "lt", hi)]


def human(column):
    """Not a bot. An empty login is not a bot."""
    return [{"any_of": [[f(column, "is_null")], [f(column, "not_in", BOTS), f(column, "not_matches", BOT_ENDING)]]}]


def human_commit(login, email):
    """A human author: a login that is not a bot, or no login and not an automation email."""
    return [{"any_of": [
        [f(login, "not_in", BOTS), f(login, "not_matches", BOT_ENDING)],
        [f(login, "is_null"), f(email, "is_null")],
        [f(login, "is_null"), f(email, "not_in", AUTOMATION_EMAILS)],
    ]}]


class Agent:
    def __init__(self, conn, slug, menu=MENU):
        self.conn, self.slug = conn, slug
        self.dispatch, _ = make_dispatch(menu)
        self.steps, self.own = 0, 0
        self.log = []

    def call(self, tool, **args):
        self.steps += 1
        if tool not in CALCULATORS:
            args = {"repo": self.slug, **args}
        out = self.dispatch(self.conn, tool, args)
        if "error" in out:
            raise RuntimeError(f"{tool}: {out['error']}")
        self.log.append((tool, out))
        return out

    def one(self, tool, **args):
        """A query with one result row, returned as a dict."""
        out = self.call(tool, **args)
        return dict(zip(out["columns"], out["rows"][0], strict=True))

    def use(self, *numbers):
        """Count numbers the agent does arithmetic on itself."""
        self.own += len(numbers)
        return numbers

    def workflow_ids(self, repo):
        out = self.call("query_workflows", filters=[f("path", "in", MAIN_CI_PATHS[repo])])
        return [r[0] for r in out["rows"]]


def pct(x):
    return None if x is None else 100 * x


# Recipes. Each returns a guess in the answer format of must_haves.FIELDS.


def r1(a, repo):
    ids = a.workflow_ids(repo)
    aggs = []
    for h, (lo, hi) in HALVES.items():
        aggs.append({"name": f"{h}_counted", "fn": "count", "where": [*between("started_at", lo, hi), f("result", "not_in", ["cancelled", "skipped"])]})
        aggs.append({"name": f"{h}_failing", "fn": "count", "where": [*between("started_at", lo, hi), f("result", "in", FAILING)]})
    c = a.one(
        "query_ci_runs",
        filters=[f("workflow_id", "in", ids), f("event", "eq", "push"), f("on_default_branch", "eq", True)],
        first_per={"columns": ["commit_sha"], "order_by": [{"column": "started_at"}, {"column": "run_id"}]},
        aggregates=aggs,
    )
    t = a.call("fisher_test", count_a=c["H1_failing"], total_a=c["H1_counted"], count_b=c["H2_failing"], total_b=c["H2_counted"])
    return {"h1_failure_rate_pct": pct(t["rate_a"]), "h2_failure_rate_pct": pct(t["rate_b"]), "verdict": t["verdict"]}


def r2(a, repo):
    ids = a.workflow_ids(repo)
    landing = {}
    for h, (lo, hi) in HALVES.items():
        out = a.call(
            "query_ci_runs",
            filters=[f("workflow_id", "in", ids), f("event", "eq", "push"), f("on_default_branch", "eq", True)],
            first_per={"columns": ["commit_sha"], "order_by": [{"column": "started_at"}, {"column": "run_id"}]},
            post_filters=[*between("started_at", lo, hi), f("result", "eq", "success"), f("duration_seconds", "not_null")],
            limit=0,
        )
        landing[h] = {"result_id": out["result_id"], "column": "duration_seconds"}
    m = a.call("compare_medians", a=landing["H1"], b=landing["H2"])
    return {"main_h1_minutes": m["median_a"] / 60, "main_h2_minutes": m["median_b"] / 60, "main_verdict": m["verdict"]}


def r3(a, repo):
    res = {}
    for h, (lo, hi) in HALVES.items():
        out = a.call(
            "query_pr_reviews",
            filters=[f("pr_merged_at", "not_null"), *human("pr_author"), f("reviewer", "not_null"), f("reviewer", "ne", other="pr_author"),
                     *human("reviewer"), f("submitted_at", "lte", other="pr_merged_at"), *between("pr_merged_at", lo, hi)],
            group_by=["pr_number", "pr_created_at", "pr_merged_at"],
            aggregates=[{"name": "first_review", "fn": "min", "column": "submitted_at"}],
            limit=0,
        )
        res[h] = out["result_id"]
    wait = a.call("compare_medians", a={"result_id": res["H1"], "hours_between": ["first_review", "pr_created_at"]}, b={"result_id": res["H2"], "hours_between": ["first_review", "pr_created_at"]})
    after = a.call("compare_medians", a={"result_id": res["H1"], "hours_between": ["pr_merged_at", "first_review"]}, b={"result_id": res["H2"], "hours_between": ["pr_merged_at", "first_review"]})
    return {"wait_h1_hours": wait["median_a"], "wait_h2_hours": wait["median_b"], "wait_verdict": wait["verdict"],
            "after_h1_hours": after["median_a"], "after_h2_hours": after["median_b"], "after_verdict": after["verdict"]}


def r4(a, repo):
    merged = a.one("query_pull_requests", filters=between("merged_at", H2, W1), aggregates=[{"name": "n", "fn": "count"}])["n"]
    approved = a.one(
        "query_pr_reviews",
        filters=[f("state", "eq", "APPROVED"), f("reviewer", "not_null"), f("reviewer", "ne", other="pr_author"), *human("reviewer"),
                 f("submitted_at", "lte", other="pr_merged_at"), *between("pr_merged_at", H2, W1)],
        aggregates=[{"name": "prs", "fn": "count_distinct", "column": "pr_number"}],
    )["prs"]
    a.use(merged, approved)
    return {"unapproved": merged - approved, "unapproved_pct": 100 * (merged - approved) / merged}


BUG_LABEL = {"tokio": "C-bug", "eslint": "bug", "sqlalchemy": "bug", "vite": "p3-minor-bug", "junit-framework": "type: bug", "prometheus": "kind/bug"}


def r5(a, repo):
    label = f("labels", "contains", BUG_LABEL[repo])
    c = a.one("query_issues", filters=[label], aggregates=[
        {"name": "opened", "fn": "count", "where": between("created_at", W0, W1)},
        {"name": "closed", "fn": "count", "where": between("closed_at", W0, W1)},
    ])
    b = a.call("binomial_test", k=c["closed"], n=c["opened"] + c["closed"])
    a.use(c["opened"], c["closed"])
    verdict = "balanced" if not b["differs_from_half"] else ("growing" if c["opened"] > c["closed"] else "shrinking")
    # Bugs opened in H1. A bug not closed by the end of the window counts as not closed yet.
    h1 = a.call("query_issues", filters=[label, *between("created_at", W0, H2)], select=["number", "created_at", "closed_at"], limit=0)
    s = a.call("summarize", data={"result_id": h1["result_id"], "hours_between": ["closed_at", "created_at"]}, missing="as_infinite")
    a.use(s["median"])
    return {"opened": c["opened"], "closed": c["closed"], "verdict": verdict, "median_days_to_close": None if s["median"] == "infinite" else s["median"] / 24}


R6_MODULE = {"prometheus": ("folder1", []), "sqlalchemy": ("folder3", [f("folder2", "eq", "lib/sqlalchemy")]),
             "eslint": ("folder2", [f("folder1", "eq", "lib")]), "vite": ("folder2", [f("folder1", "eq", "packages")])}


def r6(a, repo):
    folder, extra = R6_MODULE[repo]
    base = dict(
        filters=[*between("committed_at", W0, W1), f("commit_is_merge", "eq", False), *human_commit("commit_author", "commit_author_email"),
                 f("filename", "not_matches", TEST_PATH), f("filename", "not_matches", DOC_PATH), f(folder, "not_null"), *extra],
        first_per={"columns": ["commit_sha", folder], "order_by": [{"column": "filename"}]},
        group_by=[folder],
        aggregates=[{"name": "commits", "fn": "count"}, {"name": "fixes", "fn": "count", "where": [f("commit_subject", "matches", FIX)]},
                    {"name": "fix_share", "fn": "share", "where": [f("commit_subject", "matches", FIX)]}],
        limit=1,
    )
    most = a.call("query_commit_files", **base, order_by=[{"column": "fixes", "desc": True}, {"column": "commits", "desc": True}, {"column": folder}])
    top = a.call("query_commit_files", **base, post_filters=[f("commits", "gte", 20)], order_by=[{"column": "fix_share", "desc": True}, {"column": folder}])
    return {"most_fixes_module": most["rows"][0][0], "top_share_module": top["rows"][0][0]}


def r7(a, repo):
    order = [{"column": "started_at"}, {"column": "run_id"}]
    out = a.call(
        "query_ci_runs",
        filters=[f("workflow_id", "in", a.workflow_ids(repo)), f("event", "eq", "push"), f("on_default_branch", "eq", True)],
        first_per={"columns": ["commit_sha"], "order_by": order},
        stretches={"where": [f("result", "in", FAILING)], "order_by": order, "use_rows": [f("result", "not_in", ["cancelled", "skipped"])]},
        add_columns=[{"name": "hours_red", "hours_between": ["next_finished_at", "first_finished_at"]}],
        post_filters=[f("holds", "eq", True), f("stretch", "gt", 1), *between("first_started_at", H2, W1), f("next_run_id", "not_null")],
        select=["first_commit_sha", "next_commit_sha", "row_count", "hours_red"],
        order_by=[{"column": "hours_red", "desc": True}, {"column": "row_count", "desc": True}],
        limit=1,
    )
    first, nxt, _, hours = out["rows"][0]
    a.call("query_commit_files", filters=[f("commit_sha", "eq", first)], select=["filename", "additions", "deletions", "commit_subject"])
    return {"first_failing_sha": first, "next_passing_sha": nxt, "hours_red": hours}


def r8(a, repo):
    out = {}
    shares = {}
    for h, (lo, hi) in HALVES.items():
        g = a.call("query_commits", filters=[*between("committed_at", lo, hi), f("is_merge", "eq", False), *human_commit("author", "author_email")],
                   group_by=["author"], aggregates=[{"name": "n", "fn": "count"}], order_by=[{"column": "n", "desc": True}], limit=2)
        total = a.one("query_commits", filters=[*between("committed_at", lo, hi), f("is_merge", "eq", False), *human_commit("author", "author_email")], aggregates=[{"name": "n", "fn": "count"}])["n"]
        top2 = sum(r[1] for r in g["rows"])
        a.use(g["rows"][0][1], g["rows"][1][1], total)
        shares[h] = (top2, total)
        out[f"{h.lower()}_top2_pct"] = 100 * top2 / total
    t = a.call("fisher_test", count_a=shares["H1"][0], total_a=shares["H1"][1], count_b=shares["H2"][0], total_b=shares["H2"][1])
    diff = t["rate_b"] - t["rate_a"]
    a.use(t["rate_a"], t["rate_b"])
    out["verdict"] = ("more concentrated" if diff > 0 else "less concentrated") if t["p_value"] < 0.05 and abs(diff) >= 0.05 else "no clear change"
    return out


def r9(a, repo):
    filters = [*between("submitted_at", H2, W1), f("reviewer", "not_null"), f("reviewer", "ne", other="pr_author"), *human("reviewer")]
    g = a.call("query_pr_reviews", filters=filters, first_per={"columns": ["pr_number", "reviewer"]}, group_by=["reviewer"],
               aggregates=[{"name": "prs", "fn": "count"}], order_by=[{"column": "prs", "desc": True}], limit=2)
    total = a.one("query_pr_reviews", filters=filters, first_per={"columns": ["pr_number", "reviewer"]}, aggregates=[{"name": "pairs", "fn": "count"}])["pairs"]
    a.use(g["rows"][0][1], g["rows"][1][1], total)
    return {"reviewers": g["total"], "top2_pct": 100 * (g["rows"][0][1] + g["rows"][1][1]) / total}


def r10(a, repo):
    fixes = [*between("committed_at", W0, W1), f("commit_is_merge", "eq", False), *human_commit("commit_author", "commit_author_email"), f("commit_subject", "matches", FIX)]
    n = a.one("query_commits", filters=[*between("committed_at", W0, W1), f("is_merge", "eq", False), *human_commit("author", "author_email"), f("subject", "matches", FIX)],
              aggregates=[{"name": "n", "fn": "count"}])["n"]
    t = a.one("query_commit_files", filters=[*fixes, f("filename", "matches", TEST_PATH)], aggregates=[{"name": "n", "fn": "count_distinct", "column": "commit_sha"}])["n"]
    a.use(n, t)
    return {"fix_commits": n, "changed_test_pct": 100 * t / n}


def r11(a, repo):
    bots = f("author", "in", ["renovate", "dependabot"])
    c = a.one("query_pull_requests", filters=[bots, *between("created_at", W0, W1)], aggregates=[
        {"name": "opened", "fn": "count"},
        {"name": "merged", "fn": "count", "where": [f("merged_at", "lt", W1)]},
        {"name": "closed_unmerged", "fn": "count", "where": [f("merged_at", "is_null"), f("closed_at", "lt", W1)]},
    ])
    res = {}
    for h, (lo, hi) in HALVES.items():
        res[h] = a.call("query_pull_requests", filters=[bots, *between("merged_at", lo, hi)], limit=0)["result_id"]
    m = a.call("compare_medians", a={"result_id": res["H1"], "hours_between": ["merged_at", "created_at"]}, b={"result_id": res["H2"], "hours_between": ["merged_at", "created_at"]})
    a.use(c["opened"], c["merged"], c["closed_unmerged"])
    return {"opened": c["opened"], "merged_pct": 100 * c["merged"] / c["opened"], "closed_unmerged_pct": 100 * c["closed_unmerged"] / c["opened"],
            "merge_h1_hours": m["median_a"], "merge_h2_hours": m["median_b"], "merge_verdict": m["verdict"]}


def r12(a, repo):
    human_commits = [f("is_merge", "eq", False), *human_commit("author", "author_email")]
    res = {}
    for h, (lo, hi) in HALVES.items():
        res[h] = a.call("query_commits", filters=[*human_commits, *between("committed_at", lo, hi)], limit=0)["result_id"]
    m = a.call("compare_medians", a={"result_id": res["H1"], "column": "total_lines"}, b={"result_id": res["H2"], "column": "total_lines"})
    fix = a.call("query_commits", filters=[*human_commits, *between("committed_at", W0, W1), f("subject", "matches", FIX)], limit=0)["result_id"]
    other = a.call("query_commits", filters=[*human_commits, *between("committed_at", W0, W1), f("subject", "not_matches", FIX)], limit=0)["result_id"]
    sf = a.call("summarize", data={"result_id": fix, "column": "total_lines"})
    so = a.call("summarize", data={"result_id": other, "column": "total_lines"})
    return {"h1_median_lines": m["median_a"], "h2_median_lines": m["median_b"], "verdict": m["verdict"],
            "fix_median_lines": sf["median"], "other_median_lines": so["median"]}


RECIPES = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5, "R6": r6, "R7": r7, "R8": r8, "R9": r9, "R10": r10, "R11": r11, "R12": r12}


def main():
    wanted = sys.argv[1:] or list(RECIPES)
    conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    results, bad = [], 0
    for q in QUESTIONS:
        if q["template"] not in wanted or not q["in_study"]:
            continue
        a = Agent(conn, q["repo_slug"])
        try:
            guess = RECIPES[q["template"]](a, q["repo"])
            items = check(q["template"], KEYS[q["template"]][q["repo"]], guess, ALTS.get(q["template"], {}).get(q["repo"], []))
        except Exception as e:  # noqa: BLE001
            guess, items = None, {"recipe error": False}
            print(f"  {q['id']}: {e}")
        ok = all(items.values()) and a.steps <= MAX_STEPS and a.own <= MAX_OWN_NUMBERS
        bad += not ok
        failed = [k for k, v in items.items() if not v]
        print(f"{'PASS' if ok else 'FAIL'} {q['id']:22s} steps {a.steps:2d} own numbers {a.own:2d} {('failed: ' + ', '.join(failed)) if failed else ''}")
        results.append({"id": q["id"], "pass": ok, "steps": a.steps, "own_numbers": a.own, "items": items, "guess": guess})
    out = ROOT / "levels_results" / "perfect_agents_level2.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1, default=str) + "\n")
    print(f"{len(results) - bad}/{len(results)} pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
