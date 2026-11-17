"""Primary answer keys for the ten question templates (R1 to R10).

Follows docs/key_spec_for_independent_check.md exactly. SQL does the
selection, joins and counting. Python only does the statistical tests and
the R7 streak walk. An independent pandas version is written separately
from the same spec, and scripts/answer_keys/compare_keys.py compares them.

Reads through SANDBOX_DATABASE_URL (read only).

Usage:
  uv run --env-file .env python scripts/answer_keys/compute_keys.py
"""

import json
import math
import os
from math import comb
from pathlib import Path

import numpy as np
import psycopg

OUT = Path(__file__).parent.parent.parent / "answer_keys" / "keys_primary.json"

W0, H2_0, W1 = "2025-10-01", "2026-04-01", "2026-09-21"
REPOS = ["tokio", "eslint", "sqlalchemy", "vite", "junit-framework", "prometheus"]
NO_GITHUB_REVIEW = {"sqlalchemy"}
R6_REPOS = ["eslint", "prometheus", "sqlalchemy", "vite"]
# R11 needs at least 20 dependency bot PRs opened in the window. tokio (6) and
# sqlalchemy (11, and it merges on Gerrit) have fewer.
R11_REPOS = ["eslint", "vite", "junit-framework", "prometheus"]
DEP_BOTS = "('renovate', 'dependabot')"
# Main CI by workflow id, not name. In eslint two other workflows (docs-ci.yml,
# types-integration.yml) logged runs named "CI" until January 2026, at the same
# second as the real one. junit renamed main.yml to ci.yml on 2026-05-15, which
# gave the same workflow a new id, so it has two.
MAIN_CI_IDS = {
    "tokio": [1972898],  # .github/workflows/ci.yml
    "eslint": [27292],  # .github/workflows/ci.yml
    "sqlalchemy": [971063],  # .github/workflows/run-test.yaml
    "vite": [6990137],  # .github/workflows/ci.yml
    "junit-framework": [24797, 277287548],  # main.yml, then ci.yml
    "prometheus": [34174364],  # .github/workflows/ci.yml
}
MAIN_CI = (
    "("
    + " or ".join(
        f"(r.name = '{repo}' and ci.workflow_id in ({', '.join(map(str, ids))}))"
        for repo, ids in MAIN_CI_IDS.items()
    )
    + ")"
)
BUG_LABEL = (
    "case r.name when 'tokio' then 'C-bug' when 'vite' then 'p3-minor-bug' "
    "when 'junit-framework' then 'type: bug' when 'prometheus' then 'kind/bug' else 'bug' end"
)
MODULE_DEPTH = "case r.name when 'eslint' then 2 when 'vite' then 2 when 'sqlalchemy' then 3 else 1 end"


# The bot rule (keys v3). scripts/answer_keys/audit_bots.py checks every person
# field for accounts it misses, and its output is in answer_keys/bot_audit.txt.
# A login is a bot if it is named below, or ends in "[bot]" or in "bot" (any
# case). junit-builds is junit's build account. No human login in the data ends in "bot".
def bot(col: str) -> str:
    return (
        f"({col} in ('renovate', 'dependabot', 'github-actions', 'junit-builds', "
        f"'copilot-pull-request-reviewer', 'copilot-swe-agent', 'Copilot') "
        f"or {col} like '%[bot]' or {col} ~* 'bot$')"
    )


# Commits with no login made by automation, found by the audit. eslint's daily
# README job sets git user.email to eslint@googlegroups.com in
# .github/workflows/update-readme.yml. jenkins@eslint-03 makes eslint's release commits.
AUTOMATION_EMAILS = "('jenkins@eslint-03', 'eslint@googlegroups.com')"


def half(col: str) -> str:
    return (
        f"case when {col} >= '{W0}' and {col} < '{H2_0}' then 'H1' "
        f"when {col} >= '{H2_0}' and {col} < '{W1}' then 'H2' end"
    )


HUMAN_COMMIT = (
    f"not c.is_merge and not coalesce({bot('c.author_login')}, false) "
    f"and (c.author_login is not null or coalesce(c.author_email, '') not in {AUTOMATION_EMAILS})"
)
FIX_SUBJECT = r"split_part(c.message, E'\n', 1) ~* '\m(fix|fixes|fixed|fixing|bugfix)\M'"
TEST_FILE = (
    r"(f.filename ~* '(^|/)(tests?|__tests__|testdata|testing|fixtures|playground|[^/]*[-_]tests?)/' "
    r"or regexp_replace(f.filename, '^.*/', '') ~ '(_test\.go|^test_.*\.py|_test\.py|Tests?\.java|Tests?\.kt"
    r"|\.(test|spec)\.[cm]?[jt]sx?)$')"
)
DOC_FILE = (
    r"(f.filename ~* '(^|/)(doc|docs|documentation|\.github|changelog\.d)/' "
    r"or lower(f.filename) ~ '\.(md|rst|txt|adoc)$')"
)

LANDING_CTE = f"""
main as (
  select r.name repo, ci.* from ci_runs ci join repos r on r.id = ci.repo_id
  where {MAIN_CI} and ci.event = 'push'
    and exists (select 1 from commits c where c.sha = ci.commit_sha and c.repo_id = ci.repo_id)
),
landing as (
  select distinct on (repo, commit_sha) * from main order by repo, commit_sha, started_at, id
),
counted as (
  select * from landing where conclusion is not null and conclusion not in ('cancelled', 'skipped')
)"""
FAILING = "conclusion in ('failure', 'timed_out', 'startup_failure')"


def fetch(conn, sql):
    cur = conn.execute(sql)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def fisher_p(a, b, c, d):
    n, r1, c1 = a + b + c + d, a + b, a + c
    if n == 0:
        return 1.0

    def p(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    obs = p(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def binom_p(k, n):
    probs = [comb(n, i) / 2**n for i in range(n + 1)]
    return min(1.0, sum(p for p in probs if p <= probs[k] * (1 + 1e-9)))


def rate_verdict(f1, n1, f2, n2):
    if fisher_p(f1, n1 - f1, f2, n2 - f2) >= 0.05:
        return "no clear change"
    return "up" if f2 / n2 > f1 / n1 else "down"


def median_verdict(a, b, n_boot=4000, seed=7):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 10 or len(b) < 10:
        return "too few"
    rng = np.random.default_rng(seed)
    boot_a = np.median(rng.choice(a, (n_boot, len(a))), axis=1)
    boot_b = np.median(rng.choice(b, (n_boot, len(b))), axis=1)
    lo, hi = np.percentile(boot_b / np.maximum(boot_a, 1e-9), [2.5, 97.5])
    ratio = np.median(b) / np.median(a) if np.median(a) else math.inf
    if lo > 1 and ratio >= 1.2:
        return "up"
    if hi < 1 and ratio <= 1 / 1.2:
        return "down"
    return "no clear change"


def med(values):
    return float(np.median(values)) if len(values) else None


def r1(conn):
    rows = fetch(
        conn,
        f"""
    with {LANDING_CTE},
    h as (select *, {half("started_at")} half from counted)
    select repo, half, count(*) counted, count(*) filter (where {FAILING}) failing,
           count(*) filter (where run_attempt > 1 and conclusion = 'success') rerun_pass
    from h where half is not null group by 1, 2
    """,
    )
    by = {(r["repo"], r["half"]): r for r in rows}
    out = {}
    for repo in REPOS:
        a, b = by[(repo, "H1")], by[(repo, "H2")]
        out[repo] = {
            "h1_failing": a["failing"],
            "h1_counted": a["counted"],
            "h1_rate": a["failing"] / a["counted"],
            "h2_failing": b["failing"],
            "h2_counted": b["counted"],
            "h2_rate": b["failing"] / b["counted"],
            "verdict": rate_verdict(a["failing"], a["counted"], b["failing"], b["counted"]),
            "h1_rerun_pass_share": a["rerun_pass"] / a["counted"],
            "h2_rerun_pass_share": b["rerun_pass"] / b["counted"],
        }
    return out


def r2(conn):
    rows = fetch(
        conn,
        f"""
    with {LANDING_CTE}
    select repo, 'main' part, {half("started_at")} half, duration_seconds / 60.0 minutes
    from landing where conclusion = 'success' and duration_seconds is not null
    union all
    select r.name, 'pr', {half("ci.started_at")}, ci.duration_seconds / 60.0
    from ci_runs ci join repos r on r.id = ci.repo_id
    where {MAIN_CI} and ci.event = 'pull_request'
      and ci.conclusion = 'success' and ci.duration_seconds is not null
    """,
    )
    out = {}
    for repo in REPOS:
        res = {}
        for part in ["main", "pr"]:
            a = [
                float(r["minutes"])
                for r in rows
                if r["repo"] == repo and r["part"] == part and r["half"] == "H1"
            ]
            b = [
                float(r["minutes"])
                for r in rows
                if r["repo"] == repo and r["part"] == part and r["half"] == "H2"
            ]
            res[f"{part}_h1_min"], res[f"{part}_h2_min"] = med(a), med(b)
            res[f"{part}_verdict"] = median_verdict(a, b) if a or b else "none"
        out[repo] = res
    return out


def r3(conn):
    rows = fetch(
        conn,
        f"""
    with prs as (
      select r.name repo, p.repo_id, p.number, p.author_login, p.created_at, p.merged_at,
             {half("p.merged_at")} half
      from pull_requests p join repos r on r.id = p.repo_id
      where p.merged_at is not null and not coalesce({bot("p.author_login")}, false)
    ),
    first_review as (
      select p.repo_id, p.number, min(v.submitted_at) first_at
      from prs p join pr_reviews v on v.repo_id = p.repo_id and v.pr_number = p.number
      where v.reviewer_login is not null and v.reviewer_login is distinct from p.author_login
        and not {bot("v.reviewer_login")} and v.submitted_at <= p.merged_at
      group by 1, 2
    )
    select p.repo, p.half,
      extract(epoch from f.first_at - p.created_at) / 3600 wait_h,
      extract(epoch from p.merged_at - f.first_at) / 3600 after_h
    from prs p left join first_review f using (repo_id, number)
    where p.half is not null
    """,
    )
    out = {}
    for repo in REPOS:
        if repo in NO_GITHUB_REVIEW:
            continue
        g = [r for r in rows if r["repo"] == repo]

        def vals(h, col, g=g):
            return [float(r[col]) for r in g if r["half"] == h and r[col] is not None]

        h2 = [r for r in g if r["half"] == "H2"]
        out[repo] = {
            "wait_h1_h": med(vals("H1", "wait_h")),
            "wait_h2_h": med(vals("H2", "wait_h")),
            "wait_verdict": median_verdict(vals("H1", "wait_h"), vals("H2", "wait_h")),
            "after_h1_h": med(vals("H1", "after_h")),
            "after_h2_h": med(vals("H2", "after_h")),
            "after_verdict": median_verdict(vals("H1", "after_h"), vals("H2", "after_h")),
            "h2_no_review_share": sum(r["wait_h"] is None for r in h2) / len(h2),
        }
    return out


def r4(conn):
    rows = fetch(
        conn,
        f"""
    select r.name repo, count(*) merged_h2,
      count(*) filter (where not approved) unapproved,
      count(*) filter (where not approved and coalesce({bot("author_login")}, false)) unapproved_bot_prs
    from (
      select p.*, exists (
        select 1 from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
          and v.state = 'APPROVED' and v.reviewer_login is not null
          and v.reviewer_login is distinct from p.author_login and not {bot("v.reviewer_login")}
          and v.submitted_at <= p.merged_at
      ) approved
      from pull_requests p where p.merged_at >= '{H2_0}' and p.merged_at < '{W1}'
    ) p join repos r on r.id = p.repo_id
    group by 1
    """,
    )
    return {
        r["repo"]: {
            **{k: r[k] for k in ["merged_h2", "unapproved", "unapproved_bot_prs"]},
            "unapproved_share": r["unapproved"] / r["merged_h2"],
        }
        for r in rows
        if r["repo"] not in NO_GITHUB_REVIEW
    }


def r5(conn):
    counts = fetch(
        conn,
        f"""
    select r.name repo,
      count(*) filter (where i.created_at >= '{W0}' and i.created_at < '{W1}') opened,
      count(*) filter (where i.closed_at >= '{W0}' and i.closed_at < '{W1}') closed
    from issues i join repos r on r.id = i.repo_id where {BUG_LABEL} = any(i.labels) group by 1
    """,
    )
    h1 = fetch(
        conn,
        f"""
    select r.name repo,
      case when i.closed_at is not null and i.closed_at < '{W1}'
           then extract(epoch from i.closed_at - i.created_at) / 86400 end days
    from issues i join repos r on r.id = i.repo_id
    where {BUG_LABEL} = any(i.labels) and i.created_at >= '{W0}' and i.created_at < '{H2_0}'
    """,
    )
    out = {}
    for c in counts:
        n, k = c["opened"] + c["closed"], c["closed"]
        p = binom_p(k, n) if n else 1.0
        verdict = "balanced" if p >= 0.05 else ("growing" if c["opened"] > c["closed"] else "shrinking")
        days = [math.inf if r["days"] is None else float(r["days"]) for r in h1 if r["repo"] == c["repo"]]
        m = float(np.median(days)) if days else None
        out[c["repo"]] = {
            "opened": c["opened"],
            "closed": c["closed"],
            "verdict": verdict,
            "h1_bugs": len(days),
            "median_days_to_close": None if m is None or math.isinf(m) else m,
            "share_not_closed": sum(math.isinf(d) for d in days) / len(days) if days else None,
        }
    return out


def r6(conn):
    rows = fetch(
        conn,
        f"""
    with files as (
      select r.name repo, c.sha, ({FIX_SUBJECT}) is_fix,
             string_to_array(f.filename, '/') parts, {MODULE_DEPTH} depth
      from commits c join repos r on r.id = c.repo_id join commit_files f on f.commit_sha = c.sha
      where {HUMAN_COMMIT} and c.committed_at >= '{W0}' and c.committed_at < '{W1}'
        and not {TEST_FILE} and not {DOC_FILE}
    ),
    touches as (
      select distinct repo, sha, is_fix, array_to_string(parts[1:depth], '/') module
      from files where array_length(parts, 1) - 1 >= depth
    )
    select repo, module, count(*) commits, count(*) filter (where is_fix) fixes
    from touches group by 1, 2
    """,
    )
    out = {}
    for repo in R6_REPOS:
        g = [r for r in rows if r["repo"] == repo]
        most = sorted(g, key=lambda r: (-r["fixes"], -r["commits"], r["module"]))[0]
        busy = sorted(
            (r for r in g if r["commits"] >= 20), key=lambda r: (-r["fixes"] / r["commits"], r["module"])
        )[0]
        out[repo] = {
            "most_fixes_module": most["module"],
            "most_fixes_count": most["fixes"],
            "most_fixes_module_commits": most["commits"],
            "top_share_module": busy["module"],
            "top_share": busy["fixes"] / busy["commits"],
        }
    return out


def r7(conn):
    rows = fetch(
        conn,
        f"""
    with {LANDING_CTE}
    select repo, commit_sha, started_at, completed_at, {FAILING} failing
    from counted order by repo, started_at, id
    """,
    )
    out = {}
    for repo in REPOS:
        s = [r for r in rows if r["repo"] == repo]
        best = None
        i = 1
        while i < len(s):
            if s[i]["failing"] and not s[i - 1]["failing"]:
                j = i
                while j < len(s) and s[j]["failing"]:
                    j += 1
                start = s[i]["started_at"].isoformat()
                if j < len(s) and H2_0 <= start[:10] < W1:
                    hours = (s[j]["completed_at"] - s[i]["completed_at"]).total_seconds() / 3600
                    key = (hours, j - i)
                    if best is None or key > best[0]:
                        best = (key, s[i]["commit_sha"], s[j]["commit_sha"])
                i = j
            else:
                i += 1
        (hours, n), first, nxt = best
        out[repo] = {
            "first_failing_sha": first,
            "next_passing_sha": nxt,
            "failing_commits": n,
            "hours_red": hours,
        }
    return out


def r8(conn):
    rows = fetch(
        conn,
        f"""
    select r.name repo, {half("c.committed_at")} half,
           coalesce(c.author_login, c.author_email) person, count(*) n
    from commits c join repos r on r.id = c.repo_id
    where {HUMAN_COMMIT} group by 1, 2, 3
    """,
    )
    out = {}
    for repo in REPOS:
        res = {}
        tops = {}
        for h in ["H1", "H2"]:
            counts = sorted((r["n"] for r in rows if r["repo"] == repo and r["half"] == h), reverse=True)
            tops[h] = (sum(counts[:2]), sum(counts))
            res[f"{h.lower()}_top2_share"] = tops[h][0] / tops[h][1]
        (t1, n1), (t2, n2) = tops["H1"], tops["H2"]
        s1, s2 = t1 / n1, t2 / n2
        p = fisher_p(t1, n1 - t1, t2, n2 - t2)
        res["verdict"] = (
            ("more concentrated" if s2 > s1 else "less concentrated")
            if p < 0.05 and abs(s2 - s1) >= 0.05
            else "no clear change"
        )
        out[repo] = res
    return out


def r9(conn):
    rows = fetch(
        conn,
        f"""
    select r.name repo, v.reviewer_login, count(distinct v.pr_number) prs
    from pr_reviews v join pull_requests p on p.repo_id = v.repo_id and p.number = v.pr_number
    join repos r on r.id = v.repo_id
    where v.submitted_at >= '{H2_0}' and v.submitted_at < '{W1}'
      and v.reviewer_login is not null and v.reviewer_login is distinct from p.author_login
      and not {bot("v.reviewer_login")}
    group by 1, 2
    """,
    )
    out = {}
    for repo in REPOS:
        if repo in NO_GITHUB_REVIEW:
            continue
        counts = sorted((r["prs"] for r in rows if r["repo"] == repo), reverse=True)
        out[repo] = {"reviewers": len(counts), "top2_share": sum(counts[:2]) / sum(counts)}
    return out


def r10(conn):
    rows = fetch(
        conn,
        f"""
    select r.name repo, count(*) fix_commits,
      count(*) filter (
        where exists (select 1 from commit_files f where f.commit_sha = c.sha and {TEST_FILE})
      ) tested
    from commits c join repos r on r.id = c.repo_id
    where {HUMAN_COMMIT} and c.committed_at >= '{W0}' and c.committed_at < '{W1}' and {FIX_SUBJECT}
    group by 1
    """,
    )
    return {
        r["repo"]: {"fix_commits": r["fix_commits"], "share_changed_test": r["tested"] / r["fix_commits"]}
        for r in rows
    }


def r11(conn):
    opened = fetch(
        conn,
        f"""
    select r.name repo, count(*) opened,
      count(*) filter (where p.merged_at < '{W1}') merged,
      count(*) filter (where p.merged_at is null and p.closed_at < '{W1}') closed_unmerged,
      count(*) filter (
        where p.merged_at is null and p.closed_at < '{W1}' and p.title ilike '%autoclosed%'
      ) autoclosed
    from pull_requests p join repos r on r.id = p.repo_id
    where p.author_login in {DEP_BOTS} and p.created_at >= '{W0}' and p.created_at < '{W1}'
    group by 1
    """,
    )
    merged = fetch(
        conn,
        f"""
    select r.name repo, {half("p.merged_at")} half,
      extract(epoch from p.merged_at - p.created_at) / 3600 hours
    from pull_requests p join repos r on r.id = p.repo_id
    where p.author_login in {DEP_BOTS} and p.merged_at >= '{W0}' and p.merged_at < '{W1}'
    """,
    )
    out = {}
    for row in opened:
        repo = row["repo"]
        if repo not in R11_REPOS:
            continue
        a = [float(m["hours"]) for m in merged if m["repo"] == repo and m["half"] == "H1"]
        b = [float(m["hours"]) for m in merged if m["repo"] == repo and m["half"] == "H2"]
        out[repo] = {
            "opened": row["opened"],
            "merged_share": row["merged"] / row["opened"],
            "closed_unmerged_share": row["closed_unmerged"] / row["opened"],
            "closed_autoclosed_share": row["autoclosed"] / row["closed_unmerged"]
            if row["closed_unmerged"]
            else None,
            "merge_h1_h": med(a),
            "merge_h2_h": med(b),
            "merge_verdict": median_verdict(a, b),
        }
    return out


def r12(conn):
    rows = fetch(
        conn,
        f"""
    select r.name repo, {half("c.committed_at")} half, c.additions + c.deletions lines, ({FIX_SUBJECT}) is_fix
    from commits c join repos r on r.id = c.repo_id
    where {HUMAN_COMMIT} and c.committed_at >= '{W0}' and c.committed_at < '{W1}'
    """,
    )
    out = {}
    for repo in REPOS:
        g = [r for r in rows if r["repo"] == repo]
        a = [r["lines"] for r in g if r["half"] == "H1"]
        b = [r["lines"] for r in g if r["half"] == "H2"]
        out[repo] = {
            "h1_median_lines": med(a),
            "h2_median_lines": med(b),
            "verdict": median_verdict(a, b),
            "fix_median_lines": med([r["lines"] for r in g if r["is_fix"]]),
            "other_median_lines": med([r["lines"] for r in g if not r["is_fix"]]),
        }
    return out


def main():
    with psycopg.connect(os.environ["SANDBOX_DATABASE_URL"]) as conn:
        keys = {
            name: fn(conn)
            for name, fn in [
                ("R1", r1),
                ("R2", r2),
                ("R3", r3),
                ("R4", r4),
                ("R5", r5),
                ("R6", r6),
                ("R7", r7),
                ("R8", r8),
                ("R9", r9),
                ("R10", r10),
                ("R11", r11),
                ("R12", r12),
            ]
        }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(keys, indent=2, sort_keys=True))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
