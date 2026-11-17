# ruff: noqa: E501
"""Level 0 and level 1 tools: one direct tool and one or two part tools per template.

The line between the levels:
- Level 0 (direct tool): one call returns every value the question asks for,
  including the verdict. The agent picks the tool, passes what the question
  states and reports the output.
- Level 1 (part tools): each call returns one correctly defined piece, such as
  the landing runs of one period, as counts and a result id that the
  calculators accept. The shared definitions are built in. The agent combines
  the pieces: several calls, the calculators, the thresholds.
- Level 2 (query tools, in query.py): the agent also applies the definitions.

What is an argument and what is built in. Anything the question states that
differs between repos or questions is an argument: dates, workflow paths, the
bug label, the module folder, the bot names of R11 and the 20 commit threshold.
The rules every question of a template repeats are built in, and each tool's
description states them so the agent can check them against the question.

Dates are inclusive, as the questions write them. Level 0 is built from the
same functions as level 1, so the two can never disagree.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from repo_investigator.levels import definitions as d
from repo_investigator.levels.query import QueryError, ResultStore, _plain, resolve_repo

WORKFLOWS_FILE = Path(__file__).parent.parent.parent.parent / "tool_data" / "workflows.json"
PREVIEW_ROWS = 10


@dataclass(frozen=True)
class Ctx:
    conn: psycopg.Connection
    store: ResultStore
    repo_id: int
    repo: str


def _rows(ctx: Ctx, sql: str, params: dict | None = None) -> list[dict]:
    cur = ctx.conn.execute(sql, {"repo_id": ctx.repo_id, **(params or {})})
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, (_plain(v) for v in r), strict=True)) for r in cur.fetchall()]


def _workflow_ids(ctx: Ctx, paths) -> list[int]:
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise QueryError(
            "'workflow_paths' needs a list of workflow file paths, like ['.github/workflows/ci.yml']."
        )
    listed = json.loads(WORKFLOWS_FILE.read_text())["repos"][ctx.repo]["workflows"]
    # Like GitHub's API, a workflow can be named by its path or by its file name.
    by_path = {}
    for w in listed:
        by_path.setdefault(w["path"], []).append(w["id"])
        if w["path"].startswith(".github/workflows/"):
            by_path.setdefault(w["path"].rsplit("/", 1)[1], []).append(w["id"])
    unknown = [p for p in paths if p not in by_path]
    if unknown:
        known = ", ".join(sorted(p for p in by_path if p.startswith(".github")))
        raise QueryError(
            f"No workflow with path {', '.join(unknown)} in {ctx.repo}. Workflow paths: {known}."
        )
    return [i for p in paths for i in by_path[p]]


def _stored(ctx: Ctx, columns: list[str], rows: list[dict]) -> dict:
    """Store a full list for the calculators, and show a short preview."""
    table = [[r[c] for c in columns] for r in rows]
    rid = ctx.store.add(columns, table)
    return {"result_id": rid, "columns": columns, "preview": table[:PREVIEW_ROWS], "total_rows": len(table)}


def _round(x):
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def _pct(part, whole):
    return 100 * part / whole if whole else None


# R1 CI stability


def landing_counts(ctx, workflow_paths, start, end):
    lo, hi = d.period(start, end)
    r = _rows(
        ctx,
        f"""with {d.landing_ctes(_workflow_ids(ctx, workflow_paths))}
        select count(*) counted, count(*) filter (where {d.FAILING}) failing,
               count(*) filter (where run_attempt > 1 and conclusion = 'success') passed_after_rerun
        from counted where started_at >= %(lo)s and started_at < %(hi)s""",
        {"lo": lo, "hi": hi},
    )[0]
    return r


def landing_run_counts(ctx, a):
    return landing_counts(ctx, a.get("workflow_paths"), a.get("start"), a.get("end"))


def ci_failure_trend(ctx, a):
    out = {}
    for p in ("a", "b"):
        c = landing_counts(ctx, a.get("workflow_paths"), a.get(f"period_{p}_start"), a.get(f"period_{p}_end"))
        out[f"period_{p}"] = {
            "commits_counted": c["counted"],
            "failing": c["failing"],
            "failure_pct": _pct(c["failing"], c["counted"]),
            "passed_after_rerun_pct": _pct(c["passed_after_rerun"], c["counted"]),
        }
    pa, pb = out["period_a"], out["period_b"]
    if not pa["commits_counted"] or not pb["commits_counted"]:
        raise QueryError("A period has no counted commits, so the rates can't be compared.")
    out["verdict"] = d.rate_verdict(
        pa["failing"], pa["commits_counted"], pb["failing"], pb["commits_counted"]
    )
    return out


# R2 CI speed


def durations(ctx, workflow_paths, event, start, end):
    lo, hi = d.period(start, end)
    ids = _workflow_ids(ctx, workflow_paths)
    if event == "push":
        sql = f"""with {d.landing_ctes(ids)}
            select id run_id, commit_sha, duration_seconds / 60.0 minutes from landing
            where conclusion = 'success' and duration_seconds is not null
              and started_at >= %(lo)s and started_at < %(hi)s order by started_at, id"""
    elif event == "pull_request":
        sql = f"""select id run_id, commit_sha, duration_seconds / 60.0 minutes from ci_runs
            where repo_id = %(repo_id)s and workflow_id in ({", ".join(map(str, ids))})
              and event = 'pull_request' and conclusion = 'success' and duration_seconds is not null
              and started_at >= %(lo)s and started_at < %(hi)s order by started_at, id"""
    else:
        raise QueryError("'event' must be 'push' (landing runs on the default branch) or 'pull_request'.")
    return _rows(ctx, sql, {"lo": lo, "hi": hi})


def run_durations(ctx, a):
    rows = durations(ctx, a.get("workflow_paths"), a.get("event"), a.get("start"), a.get("end"))
    return {"successful_runs": len(rows), **_stored(ctx, ["run_id", "commit_sha", "minutes"], rows)}


def ci_duration_trend(ctx, a):
    out = {}
    for event in ("push", "pull_request"):
        va, vb = (
            [
                r["minutes"]
                for r in durations(
                    ctx, a.get("workflow_paths"), event, a.get(f"period_{p}_start"), a.get(f"period_{p}_end")
                )
            ]
            for p in ("a", "b")
        )
        out[event] = {
            "period_a_runs": len(va),
            "period_a_median_minutes": d.median(va),
            "period_b_runs": len(vb),
            "period_b_median_minutes": d.median(vb),
            "verdict": d.medians_verdict(va, vb) if va or vb else "none",
        }
    return out


# R3 PR time to first review and merge


def review_times(ctx, start, end):
    lo, hi = d.period(start, end)
    return _rows(
        ctx,
        f"""with prs as (
          select p.number, p.author_login, p.created_at, p.merged_at from pull_requests p
          where p.repo_id = %(repo_id)s and p.merged_at >= %(lo)s and p.merged_at < %(hi)s
            and {d.not_bot("p.author_login")}
        ),
        first_review as (
          select p.number, min(v.submitted_at) first_at from prs p
          join pr_reviews v on v.repo_id = %(repo_id)s and v.pr_number = p.number
          where v.reviewer_login is not null and v.reviewer_login is distinct from p.author_login
            and {d.not_bot("v.reviewer_login")} and v.submitted_at <= p.merged_at
          group by 1
        )
        select p.number pr_number, p.created_at, f.first_at first_review_at, p.merged_at,
               extract(epoch from f.first_at - p.created_at) / 3600 wait_hours,
               extract(epoch from p.merged_at - f.first_at) / 3600 after_review_hours
        from prs p left join first_review f using (number) order by p.merged_at, p.number""",
        {"lo": lo, "hi": hi},
    )


def first_review_times(ctx, a):
    rows = review_times(ctx, a.get("merged_start"), a.get("merged_end"))
    reviewed = [r for r in rows if r["wait_hours"] is not None]
    return {
        "merged_prs": len(rows),
        "with_first_review": len(reviewed),
        "without_review": len(rows) - len(reviewed),
        **_stored(ctx, ["pr_number", "wait_hours", "after_review_hours"], reviewed),
    }


def pr_review_timing_trend(ctx, a):
    out = {}
    vals = {}
    for p in ("a", "b"):
        rows = review_times(ctx, a.get(f"period_{p}_start"), a.get(f"period_{p}_end"))
        reviewed = [r for r in rows if r["wait_hours"] is not None]
        vals[p] = ([r["wait_hours"] for r in reviewed], [r["after_review_hours"] for r in reviewed])
        out[f"period_{p}"] = {
            "merged_prs": len(rows),
            "median_wait_hours": d.median(vals[p][0]),
            "median_after_review_hours": d.median(vals[p][1]),
            "no_review_pct": _pct(len(rows) - len(reviewed), len(rows)),
        }
    out["wait_verdict"] = d.medians_verdict(vals["a"][0], vals["b"][0])
    out["after_review_verdict"] = d.medians_verdict(vals["a"][1], vals["b"][1])
    return out


# R4 Merges without approval


def _merged_prs(ctx, start, end, author, approved_only):
    lo, hi = d.period(start, end)
    who = {
        "any": "true",
        "bot": f"coalesce({d.bot('p.author_login')}, false)",
        "human": d.not_bot("p.author_login"),
    }
    if author not in who:
        raise QueryError("'author' must be 'any', 'bot' or 'human'.")
    approved = f"""exists (select 1 from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
          and v.state = 'APPROVED' and v.reviewer_login is not null
          and v.reviewer_login is distinct from p.author_login and {d.not_bot("v.reviewer_login")}
          and v.submitted_at <= p.merged_at)"""
    return _rows(
        ctx,
        f"""select count(*) n from pull_requests p
        where p.repo_id = %(repo_id)s and p.merged_at >= %(lo)s and p.merged_at < %(hi)s
          and {who[author]} and {approved if approved_only else "true"}""",
        {"lo": lo, "hi": hi},
    )[0]["n"]


def merged_pr_count(ctx, a):
    return {"merged_prs": _merged_prs(ctx, a.get("start"), a.get("end"), a.get("author", "any"), False)}


def approved_pr_count(ctx, a):
    return {
        "approved_merged_prs": _merged_prs(ctx, a.get("start"), a.get("end"), a.get("author", "any"), True)
    }


def unapproved_merges(ctx, a):
    s, e = a.get("start"), a.get("end")
    merged = _merged_prs(ctx, s, e, "any", False)
    unapproved = merged - _merged_prs(ctx, s, e, "any", True)
    bots = _merged_prs(ctx, s, e, "bot", False) - _merged_prs(ctx, s, e, "bot", True)
    return {
        "merged_prs": merged,
        "unapproved": unapproved,
        "unapproved_pct": _pct(unapproved, merged),
        "unapproved_opened_by_bots": bots,
    }


# R5 Bug intake


def _issue_count(ctx, label, event, start, end):
    lo, hi = d.period(start, end)
    if event not in ("opened", "closed"):
        raise QueryError("'event' must be 'opened' or 'closed'.")
    col = "created_at" if event == "opened" else "closed_at"
    return _rows(
        ctx,
        f"""select count(*) n from issues where repo_id = %(repo_id)s and %(label)s = any(labels)
        and {col} >= %(lo)s and {col} < %(hi)s""",
        {"label": str(label), "lo": lo, "hi": hi},
    )[0]["n"]


def close_times(ctx, label, start, end, as_of):
    lo, hi = d.period(start, end)
    _, cutoff = d.period(as_of, as_of, "as_of")
    return _rows(
        ctx,
        """select number, created_at, closed_at,
          case when closed_at is not null and closed_at < %(cutoff)s
               then extract(epoch from closed_at - created_at) / 86400 end days_to_close
        from issues where repo_id = %(repo_id)s and %(label)s = any(labels)
          and created_at >= %(lo)s and created_at < %(hi)s order by created_at, number""",
        {"label": str(label), "lo": lo, "hi": hi, "cutoff": cutoff},
    )


def issue_counts(ctx, a):
    return {"issues": _issue_count(ctx, a.get("label"), a.get("event"), a.get("start"), a.get("end"))}


def time_to_close(ctx, a):
    rows = close_times(ctx, a.get("label"), a.get("opened_start"), a.get("opened_end"), a.get("as_of"))
    return {
        "issues_opened": len(rows),
        "not_closed_by_as_of": sum(r["days_to_close"] is None for r in rows),
        "note": "days_to_close is empty for an issue not closed by the as_of date.",
        **_stored(ctx, ["number", "days_to_close"], rows),
    }


def bug_backlog_report(ctx, a):
    label, ws, we = a.get("label"), a.get("window_start"), a.get("window_end")
    opened = _issue_count(ctx, label, "opened", ws, we)
    closed = _issue_count(ctx, label, "closed", ws, we)
    rows = close_times(ctx, label, a.get("opened_start"), a.get("opened_end"), we)
    days = [float("inf") if r["days_to_close"] is None else float(r["days_to_close"]) for r in rows]
    m = d.median(days)
    return {
        "opened": opened,
        "closed": closed,
        "verdict": d.backlog_verdict(opened, closed),
        "issues_opened_in_close_time_period": len(days),
        "median_days_to_close": d.finite_or_none(m),
        "median_note": "empty when more than half were not closed by the window end"
        if days and m == float("inf")
        else None,
        "not_closed_pct": _pct(sum(x == float("inf") for x in days), len(days)),
    }


# R6 Fix hotspots


def module_counts(ctx, module_under, start, end):
    lo, hi = d.period(start, end)
    under = str(module_under or "").strip("/")
    depth = len(under.split("/")) + 1 if under else 1
    return _rows(
        ctx,
        f"""with files as (
          select c.sha, ({d.fix_subject()}) is_fix, string_to_array(f.filename, '/') parts
          from commits c join commit_files f on f.commit_sha = c.sha
          where c.repo_id = %(repo_id)s and {d.human_commit()}
            and c.committed_at >= %(lo)s and c.committed_at < %(hi)s
            and not {d.test_file()} and not {d.doc_file()}
            and (%(under)s = '' or f.filename like %(prefix)s)
        ),
        touches as (
          select distinct sha, is_fix, array_to_string(parts[1:{depth}], '/') module
          from files where array_length(parts, 1) - 1 >= {depth}
        )
        select module, count(*) commits, count(*) filter (where is_fix) fix_commits
        from touches group by 1 order by 1""",
        {"lo": lo, "hi": hi, "under": under, "prefix": under.replace("%", r"\%").replace("_", r"\_") + "/%"},
    )


def module_commit_counts(ctx, a):
    rows = module_counts(ctx, a.get("module_under"), a.get("start"), a.get("end"))
    return {
        "modules": len(rows),
        "columns": ["module", "commits", "fix_commits", "fix_pct"],
        "rows": [
            [r["module"], r["commits"], r["fix_commits"], _pct(r["fix_commits"], r["commits"])] for r in rows
        ],
    }


def fix_hotspots(ctx, a):
    rows = module_counts(ctx, a.get("module_under"), a.get("start"), a.get("end"))
    min_commits = a.get("min_commits")
    if not isinstance(min_commits, int) or min_commits < 1:
        raise QueryError("'min_commits' must be a whole number, 1 or more.")
    if not rows:
        raise QueryError("No module has a commit in this period.")
    most = sorted(rows, key=lambda r: (-r["fix_commits"], -r["commits"], r["module"]))[0]
    busy = [r for r in rows if r["commits"] >= min_commits]
    top = sorted(busy, key=lambda r: (-r["fix_commits"] / r["commits"], r["module"]))[0] if busy else None
    return {
        "most_fixes_module": most["module"],
        "most_fixes_module_fix_commits": most["fix_commits"],
        "most_fixes_module_commits": most["commits"],
        "top_fix_share_module": top and top["module"],
        "top_fix_share_pct": top and _pct(top["fix_commits"], top["commits"]),
        "top_fix_share_module_commits": top and top["commits"],
        "modules_with_min_commits": len(busy),
    }


# R7 Broken build


def stretches(ctx, workflow_paths, start, end):
    """Red stretches whose first failing landing run started in the period and that ended."""
    lo, hi = d.period(start, end)
    runs = _rows(
        ctx,
        f"""with {d.landing_ctes(_workflow_ids(ctx, workflow_paths))}
        select commit_sha, started_at, completed_at, {d.FAILING} failing from counted order by started_at, id""",
    )
    out, i = [], 1
    while i < len(runs):
        if runs[i]["failing"] and not runs[i - 1]["failing"]:
            j = i
            while j < len(runs) and runs[j]["failing"]:
                j += 1
            if j < len(runs) and lo <= runs[i]["started_at"][:10] < hi:
                first, nxt = runs[i], runs[j]
                out.append(
                    {
                        "first_failing_sha": first["commit_sha"],
                        "first_failing_finished_at": first["completed_at"],
                        "next_passing_sha": nxt["commit_sha"],
                        "next_passing_finished_at": nxt["completed_at"],
                        "failing_commits": j - i,
                        "hours_red": (
                            _time(nxt["completed_at"]) - _time(first["completed_at"])
                        ).total_seconds()
                        / 3600,
                    }
                )
            i = j
        else:
            i += 1
    return out


def _time(s):
    from datetime import datetime

    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def red_stretches(ctx, a):
    rows = stretches(ctx, a.get("workflow_paths"), a.get("start"), a.get("end"))
    cols = [
        "first_failing_sha",
        "first_failing_finished_at",
        "next_passing_sha",
        "next_passing_finished_at",
        "failing_commits",
        "hours_red",
    ]
    table = [[r[c] for c in cols] for r in rows]
    return {
        "stretches": len(rows),
        "result_id": ctx.store.add(cols, table),
        "columns": cols,
        "rows": table[:200],
    }


def _commit(ctx, sha):
    if not isinstance(sha, str) or len(sha) < 7:
        raise QueryError("'sha' needs at least 7 characters of a commit sha.")
    found = _rows(
        ctx,
        """select sha, author_login author, committed_at, split_part(message, E'\\n', 1) subject,
                  additions, deletions, changed_files
           from commits where repo_id = %(repo_id)s and sha like %(p)s""",
        {"p": sha.lower() + "%"},
    )
    if len(found) != 1:
        raise QueryError(
            f"{'No' if not found else 'More than one'} commit on the default branch starts with {sha!r}."
        )
    files = _rows(
        ctx,
        "select filename, additions, deletions from commit_files where commit_sha = %(s)s order by additions + deletions desc, filename limit 30",
        {"s": found[0]["sha"]},
    )
    return {**found[0], "files": [[f["filename"], f["additions"], f["deletions"]] for f in files]}


def commit_details(ctx, a):
    return _commit(ctx, a.get("sha"))


def longest_red_streak(ctx, a):
    rows = stretches(ctx, a.get("workflow_paths"), a.get("start"), a.get("end"))
    if not rows:
        return {"found": False, "note": "No red stretch started in this period and ended."}
    best = max(rows, key=lambda r: (r["hours_red"], r["failing_commits"]))
    c = _commit(ctx, best["first_failing_sha"])
    return {
        "found": True,
        **best,
        "first_failing_commit_subject": c["subject"],
        "first_failing_commit_files": c["files"],
        "red_stretches_in_period": len(rows),
    }


# R8 Commit concentration


def people(ctx, start, end):
    lo, hi = d.period(start, end)
    return _rows(
        ctx,
        f"""select coalesce(c.author_login, c.author_email) person, count(*) commits from commits c
        where c.repo_id = %(repo_id)s and {d.human_commit()} and c.committed_at >= %(lo)s and c.committed_at < %(hi)s
        group by 1 order by 2 desc, 1""",
        {"lo": lo, "hi": hi},
    )


def commits_by_person(ctx, a):
    rows = people(ctx, a.get("start"), a.get("end"))
    return {
        "human_commits": sum(r["commits"] for r in rows),
        "people": len(rows),
        "columns": ["person", "commits"],
        "rows": [[r["person"], r["commits"]] for r in rows[:20]],
        "note": "people are sorted by commits, most first; only the first 20 are shown",
    }


def commit_concentration_trend(ctx, a):
    out, top = {}, {}
    for p in ("a", "b"):
        rows = people(ctx, a.get(f"period_{p}_start"), a.get(f"period_{p}_end"))
        total = sum(r["commits"] for r in rows)
        top[p] = (sum(r["commits"] for r in rows[:2]), total)
        out[f"period_{p}"] = {
            "human_commits": total,
            "top2_people": [r["person"] for r in rows[:2]],
            "top2_pct": _pct(*top[p]),
        }
    if not top["a"][1] or not top["b"][1]:
        raise QueryError("A period has no human commits.")
    out["verdict"] = d.concentration_verdict(*top["a"], *top["b"])
    return out


# R9 Review load


def reviewer_pairs(ctx, start, end):
    lo, hi = d.period(start, end)
    return _rows(
        ctx,
        f"""select v.reviewer_login reviewer, count(distinct v.pr_number) prs
        from pr_reviews v join pull_requests p on p.repo_id = v.repo_id and p.number = v.pr_number
        where v.repo_id = %(repo_id)s and v.submitted_at >= %(lo)s and v.submitted_at < %(hi)s
          and v.reviewer_login is not null and v.reviewer_login is distinct from p.author_login
          and {d.not_bot("v.reviewer_login")}
        group by 1 order by 2 desc, 1""",
        {"lo": lo, "hi": hi},
    )


def review_pairs_by_reviewer(ctx, a):
    rows = reviewer_pairs(ctx, a.get("start"), a.get("end"))
    return {
        "reviewers": len(rows),
        "pr_reviewer_pairs": sum(r["prs"] for r in rows),
        "columns": ["reviewer", "prs_reviewed"],
        "rows": [[r["reviewer"], r["prs"]] for r in rows[:20]],
        "note": "reviewers are sorted by PRs reviewed, most first; only the first 20 are shown",
    }


def review_load(ctx, a):
    rows = reviewer_pairs(ctx, a.get("start"), a.get("end"))
    total = sum(r["prs"] for r in rows)
    return {
        "reviewers": len(rows),
        "pr_reviewer_pairs": total,
        "top2_reviewers": [r["reviewer"] for r in rows[:2]],
        "top2_pct": _pct(sum(r["prs"] for r in rows[:2]), total),
    }


# R10 Tests with fixes


def _fix_count(ctx, start, end, changed_test_file):
    lo, hi = d.period(start, end)
    cond = {
        "any": "true",
        "yes": f"exists (select 1 from commit_files f where f.commit_sha = c.sha and {d.test_file()})",
        "no": f"not exists (select 1 from commit_files f where f.commit_sha = c.sha and {d.test_file()})",
    }
    if changed_test_file not in cond:
        raise QueryError("'changed_test_file' must be 'any', 'yes' or 'no'.")
    return _rows(
        ctx,
        f"""select count(*) n from commits c where c.repo_id = %(repo_id)s and {d.human_commit()}
        and c.committed_at >= %(lo)s and c.committed_at < %(hi)s and {d.fix_subject()} and {cond[changed_test_file]}""",
        {"lo": lo, "hi": hi},
    )[0]["n"]


def fix_commit_count(ctx, a):
    return {"fix_commits": _fix_count(ctx, a.get("start"), a.get("end"), a.get("changed_test_file", "any"))}


def fix_test_coverage(ctx, a):
    n = _fix_count(ctx, a.get("start"), a.get("end"), "any")
    t = _fix_count(ctx, a.get("start"), a.get("end"), "yes")
    return {"fix_commits": n, "fix_commits_changing_tests": t, "changed_test_pct": _pct(t, n)}


# R11 Dependency updates


def _authors(a):
    authors = a.get("authors")
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list) or not authors:
        raise QueryError("'authors' needs a list of PR author logins, like ['renovate'].")
    return [str(x) for x in authors]


def bot_prs(ctx, authors, start, end):
    lo, hi = d.period(start, end)
    return _rows(
        ctx,
        """select number, title, created_at, merged_at, closed_at,
                  merged_at < %(hi)s merged, merged_at is null and closed_at < %(hi)s closed_unmerged
           from pull_requests where repo_id = %(repo_id)s and author_login = any(%(authors)s)
             and created_at >= %(lo)s and created_at < %(hi)s order by created_at, number""",
        {"authors": authors, "lo": lo, "hi": hi},
    )


def merge_hours(ctx, authors, start, end):
    lo, hi = d.period(start, end)
    return _rows(
        ctx,
        """select number, extract(epoch from merged_at - created_at) / 3600 hours_to_merge
           from pull_requests where repo_id = %(repo_id)s and author_login = any(%(authors)s)
             and merged_at >= %(lo)s and merged_at < %(hi)s order by merged_at, number""",
        {"authors": authors, "lo": lo, "hi": hi},
    )


def bot_pr_counts(ctx, a):
    rows = bot_prs(ctx, _authors(a), a.get("opened_start"), a.get("opened_end"))
    closed = [r for r in rows if r["closed_unmerged"]]
    return {
        "opened": len(rows),
        "merged_by_end": sum(bool(r["merged"]) for r in rows),
        "closed_unmerged_by_end": len(closed),
        "closed_unmerged_titles": [r["title"] for r in closed[:30]],
    }


def merge_times(ctx, a):
    rows = merge_hours(ctx, _authors(a), a.get("merged_start"), a.get("merged_end"))
    return {"merged_prs": len(rows), **_stored(ctx, ["number", "hours_to_merge"], rows)}


def dependency_pr_report(ctx, a):
    authors = _authors(a)
    rows = bot_prs(ctx, authors, a.get("window_start"), a.get("window_end"))
    closed = [r for r in rows if r["closed_unmerged"]]
    va, vb = (
        [
            r["hours_to_merge"]
            for r in merge_hours(ctx, authors, a.get(f"period_{p}_start"), a.get(f"period_{p}_end"))
        ]
        for p in ("a", "b")
    )
    return {
        "opened": len(rows),
        "merged_pct": _pct(sum(bool(r["merged"]) for r in rows), len(rows)),
        "closed_unmerged_pct": _pct(len(closed), len(rows)),
        "closed_unmerged_autoclosed_pct": _pct(
            sum("autoclosed" in r["title"].lower() for r in closed), len(closed)
        ),
        "closed_unmerged_titles": [r["title"] for r in closed[:10]],
        "period_a_merged": len(va),
        "period_a_median_hours_to_merge": d.median(va),
        "period_b_merged": len(vb),
        "period_b_median_hours_to_merge": d.median(vb),
        "merge_time_verdict": d.medians_verdict(va, vb),
    }


# R12 Change size


def sizes(ctx, start, end, kind):
    lo, hi = d.period(start, end)
    cond = {"all": "true", "fix": d.fix_subject(), "other": f"not ({d.fix_subject()})"}
    if kind not in cond:
        raise QueryError("'kind' must be 'all', 'fix' or 'other'.")
    return _rows(
        ctx,
        f"""select c.sha, c.additions + c.deletions lines from commits c
        where c.repo_id = %(repo_id)s and {d.human_commit()} and c.committed_at >= %(lo)s and c.committed_at < %(hi)s
          and {cond[kind]} order by c.committed_at, c.sha""",
        {"lo": lo, "hi": hi},
    )


def commit_sizes(ctx, a):
    rows = sizes(ctx, a.get("start"), a.get("end"), a.get("kind", "all"))
    return {"commits": len(rows), **_stored(ctx, ["sha", "lines"], rows)}


def commit_size_trend(ctx, a):
    va, vb = (
        [r["lines"] for r in sizes(ctx, a.get(f"period_{p}_start"), a.get(f"period_{p}_end"), "all")]
        for p in ("a", "b")
    )
    fix = [r["lines"] for r in sizes(ctx, a.get("window_start"), a.get("window_end"), "fix")]
    other = [r["lines"] for r in sizes(ctx, a.get("window_start"), a.get("window_end"), "other")]
    return {
        "period_a_commits": len(va),
        "period_a_median_lines": d.median(va),
        "period_b_commits": len(vb),
        "period_b_median_lines": d.median(vb),
        "verdict": d.medians_verdict(va, vb),
        "window_fix_commits": len(fix),
        "window_fix_median_lines": d.median(fix),
        "window_other_commits": len(other),
        "window_other_median_lines": d.median(other),
    }


# Schemas

REPO = {"type": "string", "description": "Repository as owner/name."}
WORKFLOWS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Workflows by file path or file name, like ['.github/workflows/ci.yml'] or ['ci.yml']. List more than one if the question says to treat them as one workflow.",
}


def DATE(what):
    return {"type": "string", "description": f"{what}, as YYYY-MM-DD, inclusive."}


def _periods(*names):
    out = {}
    for n in names:
        out[f"{n}_start"] = DATE(f"First day of {n.replace('_', ' ')}")
        out[f"{n}_end"] = DATE(f"Last day of {n.replace('_', ' ')}")
    return out


PERIOD = _periods("period")
AB = _periods("period_a", "period_b")
SE = {"start": DATE("First day"), "end": DATE("Last day")}

LANDING_RULE = (
    "For each commit on the default branch it uses the commit's landing run: its earliest push run of the "
    "workflow, with its final result. Cancelled and skipped runs are left out. Failing means failure, "
    "timed_out or startup_failure. A commit belongs to the period of its landing run's start time."
)
BOT_RULE = (
    "A bot is a login that is renovate, dependabot, github-actions, junit-builds, copilot-pull-request-reviewer, "
    "copilot-swe-agent or Copilot, or ends in [bot] or in bot. "
)
HUMAN_RULE = (
    "Human commits are non-merge commits whose author is not a bot; commits with no login from "
    "jenkins@eslint-03 or eslint@googlegroups.com are automation, not human. "
)
FIX_RULE = "A fix commit is a human commit whose first message line contains the word fix, fixes, fixed, fixing or bugfix. "
TEST_RULE = (
    "A test file is inside a test folder (test, tests, __tests__, testdata, testing, fixtures, playground, or a "
    "folder ending in -test or _test) or has a test-style name (*_test.go, test_*.py, *_test.py, *Test.java, "
    "*Tests.java, *Test.kt, *.test.js, *.spec.ts and similar). "
)
DOC_RULE = "A documentation file is inside a doc, docs, documentation, .github or changelog.d folder, or ends in .md, .rst, .txt or .adoc. "
VERDICT_RATE = "Verdict: a two-sided Fisher exact test at 0.05 gives up or down, otherwise no clear change. "
VERDICT_MEDIAN = (
    "Verdict: a bootstrap of the median ratio (4,000 resamples) gives up or down only if the 95% interval "
    "excludes 1 and the medians differ by at least 20%; too few if either side has under 10 values; otherwise "
    "no clear change. "
)


@dataclass(frozen=True)
class DomainTool:
    name: str
    template: str
    level: int
    description: str
    params: dict
    required: tuple[str, ...]
    reads: tuple[str, ...]
    fn: Callable


def _t(name, template, level, description, params, reads, fn, optional=()):
    props = {"repo": REPO, **params}
    required = tuple(k for k in props if k not in optional)
    return DomainTool(name, template, level, description, props, required, reads, fn)


CI = ("ci_runs", "commits", "workflows_snapshot")
TOOLS = {
    t.name: t
    for t in [
        # R1
        _t(
            "ci_failure_trend",
            "R1",
            0,
            "Compares the failure rate of a CI workflow on the default branch between two periods, and how often a run passed only after a re-run. "
            + LANDING_RULE
            + " "
            + VERDICT_RATE,
            {"workflow_paths": WORKFLOWS, **AB},
            CI,
            ci_failure_trend,
        ),
        _t(
            "landing_run_counts",
            "R1",
            1,
            "Counts landing runs of a CI workflow in one period: commits counted, failing, and passed after a re-run (attempt above 1 with result success). "
            + LANDING_RULE,
            {"workflow_paths": WORKFLOWS, **SE},
            CI,
            landing_run_counts,
        ),
        # R2
        _t(
            "ci_duration_trend",
            "R2",
            0,
            "Compares the median duration (start to finish, in minutes) of successful runs of a CI workflow between two periods, for landing runs on the default branch (push) and for pull request runs. "
            + LANDING_RULE
            + " Pull request runs are all successful pull_request runs of the workflow, by start time. "
            + VERDICT_MEDIAN
            + "The verdict is none if there are no runs.",
            {"workflow_paths": WORKFLOWS, **AB},
            CI,
            ci_duration_trend,
        ),
        _t(
            "run_durations",
            "R2",
            1,
            "Durations in minutes (start to finish) of successful runs of a CI workflow in one period, as a result id for the calculators. event 'push': landing runs on the default branch. event 'pull_request': all successful pull request runs, by start time. "
            + LANDING_RULE,
            {
                "workflow_paths": WORKFLOWS,
                "event": {"type": "string", "enum": ["push", "pull_request"]},
                **SE,
            },
            CI,
            run_durations,
        ),
        # R3
        _t(
            "pr_review_timing_trend",
            "R3",
            0,
            "For PRs merged in each of two periods (by merge date, PRs opened by bots left out): median hours from opening to the first review by someone other than the author, and from that first review to the merge, with a verdict for each, and the share merged with no such review. A first review is the earliest submitted review of any state before the merge, by a reviewer who is not the author and not a bot. "
            + BOT_RULE
            + VERDICT_MEDIAN,
            AB,
            ("pull_requests", "pr_reviews"),
            pr_review_timing_trend,
        ),
        _t(
            "first_review_times",
            "R3",
            1,
            "PRs merged in one period (by merge date, PRs opened by bots left out): how many, how many had a first review, and for those, hours from opening to first review and from first review to merge, as a result id. A first review is the earliest submitted review of any state before the merge, by a reviewer who is not the author and not a bot. "
            + BOT_RULE,
            {"merged_start": DATE("First merge day"), "merged_end": DATE("Last merge day")},
            ("pull_requests", "pr_reviews"),
            first_review_times,
        ),
        # R4
        _t(
            "unapproved_merges",
            "R4",
            0,
            "PRs merged in a period, how many and what share were merged without an approval before the merge, and how many of those were opened by bots. An approval is an APPROVED review submitted before the merge by someone who is not the PR author and not a bot. "
            + BOT_RULE,
            SE,
            ("pull_requests", "pr_reviews"),
            unapproved_merges,
        ),
        _t(
            "merged_pr_count",
            "R4",
            1,
            "Counts PRs merged in a period. author: any, bot or human (by the PR author). " + BOT_RULE,
            {**SE, "author": {"type": "string", "enum": ["any", "bot", "human"]}},
            ("pull_requests",),
            merged_pr_count,
            optional=("author",),
        ),
        _t(
            "approved_pr_count",
            "R4",
            1,
            "Counts PRs merged in a period that had an approval before the merge: an APPROVED review by someone who is not the PR author and not a bot. author: any, bot or human (by the PR author). "
            + BOT_RULE,
            {**SE, "author": {"type": "string", "enum": ["any", "bot", "human"]}},
            ("pull_requests", "pr_reviews"),
            approved_pr_count,
            optional=("author",),
        ),
        # R5
        _t(
            "bug_backlog_report",
            "R5",
            0,
            "Issues with a label: how many were opened and how many closed in the window (whenever opened), whether the backlog is growing, shrinking or balanced (two-sided binomial test of closed out of opened plus closed against one half, at 0.05), and for issues opened in a second period, the median days to close, counting an issue not closed by the window end as not closed yet.",
            {"label": {"type": "string"}, **_periods("window", "opened")},
            ("issues",),
            bug_backlog_report,
        ),
        _t(
            "issue_counts",
            "R5",
            1,
            "Counts issues with a label that were opened, or closed, in a period.",
            {"label": {"type": "string"}, "event": {"type": "string", "enum": ["opened", "closed"]}, **SE},
            ("issues",),
            issue_counts,
        ),
        _t(
            "time_to_close",
            "R5",
            1,
            "For issues with a label opened in a period: days from opening to closing, as a result id. days_to_close is empty for an issue not closed by the as_of date.",
            {
                "label": {"type": "string"},
                **_periods("opened"),
                "as_of": DATE("Day after which a close doesn't count"),
            },
            ("issues",),
            time_to_close,
        ),
        # R6
        _t(
            "fix_hotspots",
            "R6",
            0,
            "Finds the module with the most fix commits in a period, and among modules with at least min_commits commits, the one with the highest share of fix commits. A module is a folder directly under module_under (empty for top-level folders). A commit counts once per module it touches, leaving out test files, documentation files and files that are not inside a module folder. "
            + HUMAN_RULE
            + FIX_RULE
            + TEST_RULE
            + DOC_RULE
            + "Ties: more fix commits, then more commits, then name.",
            {
                "module_under": {
                    "type": "string",
                    "description": "The folder whose subfolders are modules, like lib/sqlalchemy. Empty for top-level folders.",
                },
                **SE,
                "min_commits": {"type": "integer"},
            },
            ("commits", "commit_files"),
            fix_hotspots,
        ),
        _t(
            "module_commit_counts",
            "R6",
            1,
            "For each module, the human commits and fix commits in a period that touch it, and the fix share in percent. A module is a folder directly under module_under (empty for top-level folders). Test files, documentation files and files not inside a module folder are left out. "
            + HUMAN_RULE
            + FIX_RULE
            + TEST_RULE
            + DOC_RULE,
            {"module_under": {"type": "string"}, **SE},
            ("commits", "commit_files"),
            module_commit_counts,
        ),
        # R7
        _t(
            "longest_red_streak",
            "R7",
            0,
            "Finds the longest stretch where a CI workflow stayed red on the default branch, among stretches whose first failing landing run started in the period and that ended with a passing run. Time red is from when the first failing run finished to when the next passing run finished. Returns both commits, what the first failing commit changed, the failing commits and hours red. Ties: more failing commits. "
            + LANDING_RULE,
            {"workflow_paths": WORKFLOWS, **SE},
            CI + ("commit_files",),
            longest_red_streak,
        ),
        _t(
            "red_stretches",
            "R7",
            1,
            "Lists stretches where a CI workflow stayed red on the default branch, whose first failing landing run started in the period and that ended, in time order: first failing commit, next passing commit, failing commits and hours red (from the first failing run's finish to the next passing run's finish). Also a result id. "
            + LANDING_RULE,
            {"workflow_paths": WORKFLOWS, **SE},
            CI,
            red_stretches,
        ),
        _t(
            "commit_details",
            "R7",
            1,
            "One commit on the default branch: author, time, first message line, lines added and deleted, and up to 30 changed files (largest first).",
            {"sha": {"type": "string", "description": "A commit sha, at least 7 characters."}},
            ("commits", "commit_files"),
            commit_details,
        ),
        # R8
        _t(
            "commit_concentration_trend",
            "R8",
            0,
            "Share of human commits made by the two most active people, in each of two periods, and whether the work became more or less concentrated (two-sided Fisher exact test at 0.05 and a change of at least 5 points, otherwise no clear change). A person is the commit's login, or its email when there is no login. "
            + HUMAN_RULE
            + BOT_RULE,
            AB,
            ("commits",),
            commit_concentration_trend,
        ),
        _t(
            "commits_by_person",
            "R8",
            1,
            "Human commits in a period: the total, the number of people, and the people with the most commits. A person is the commit's login, or its email when there is no login. "
            + HUMAN_RULE
            + BOT_RULE,
            SE,
            ("commits",),
            commits_by_person,
        ),
        # R9
        _t(
            "review_load",
            "R9",
            0,
            "Reviews submitted in a period: how many people reviewed PRs, and the share of (PR, reviewer) pairs from the two busiest reviewers. One reviewer on one PR counts once. Bots and authors reviewing their own PRs are left out. "
            + BOT_RULE,
            SE,
            ("pr_reviews", "pull_requests"),
            review_load,
        ),
        _t(
            "review_pairs_by_reviewer",
            "R9",
            1,
            "Reviews submitted in a period, counted as (PR, reviewer) pairs: one reviewer on one PR counts once. Bots and authors reviewing their own PRs are left out. Returns the number of reviewers, the number of pairs, and the reviewers with the most PRs reviewed. "
            + BOT_RULE,
            SE,
            ("pr_reviews", "pull_requests"),
            review_pairs_by_reviewer,
        ),
        # R10
        _t(
            "fix_test_coverage",
            "R10",
            0,
            "Fix commits in a period, and the share of them that also changed a test file. "
            + HUMAN_RULE
            + FIX_RULE
            + TEST_RULE,
            SE,
            ("commits", "commit_files"),
            fix_test_coverage,
        ),
        _t(
            "fix_commit_count",
            "R10",
            1,
            "Counts fix commits in a period. changed_test_file: any, yes (also changed a test file) or no. "
            + HUMAN_RULE
            + FIX_RULE
            + TEST_RULE,
            {**SE, "changed_test_file": {"type": "string", "enum": ["any", "yes", "no"]}},
            ("commits", "commit_files"),
            fix_commit_count,
            optional=("changed_test_file",),
        ),
        # R11
        _t(
            "dependency_pr_report",
            "R11",
            0,
            "PRs opened by the given authors in the window: how many, the share merged and the share closed without merging by the window end, the share of those closed ones whose title says autoclosed, and some of their titles. For PRs by those authors merged in each of two periods (by merge date): the median hours from opening to merge and a verdict. "
            + VERDICT_MEDIAN,
            {"authors": {"type": "array", "items": {"type": "string"}}, **_periods("window"), **AB},
            ("pull_requests",),
            dependency_pr_report,
        ),
        _t(
            "bot_pr_counts",
            "R11",
            1,
            "PRs opened by the given authors in a period: how many, how many were merged by the period end, how many closed without merging by the period end, and the titles of the closed ones.",
            {"authors": {"type": "array", "items": {"type": "string"}}, **_periods("opened")},
            ("pull_requests",),
            bot_pr_counts,
        ),
        _t(
            "merge_times",
            "R11",
            1,
            "For PRs by the given authors merged in a period (by merge date): hours from opening to merge, as a result id.",
            {"authors": {"type": "array", "items": {"type": "string"}}, **_periods("merged")},
            ("pull_requests",),
            merge_times,
        ),
        # R12
        _t(
            "commit_size_trend",
            "R12",
            0,
            "Median size (lines added plus deleted) of human commits in each of two periods, with a verdict, and over a window the median size of fix commits and of all other human commits. "
            + HUMAN_RULE
            + FIX_RULE
            + VERDICT_MEDIAN,
            {**AB, **_periods("window")},
            ("commits",),
            commit_size_trend,
        ),
        _t(
            "commit_sizes",
            "R12",
            1,
            "Sizes (lines added plus deleted) of human commits in a period, as a result id. kind: all, fix, or other (not fix). "
            + HUMAN_RULE
            + FIX_RULE,
            {**SE, "kind": {"type": "string", "enum": ["all", "fix", "other"]}},
            ("commits",),
            commit_sizes,
            optional=("kind",),
        ),
    ]
}


def schema(t: DomainTool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": {"type": "object", "properties": t.params, "required": list(t.required)},
        },
    }


def call(conn: psycopg.Connection, store: ResultStore, name: str, args: dict, exact: bool = False) -> dict:
    """Run one domain tool. exact=True skips rounding, for the tests."""
    t = TOOLS[name]
    unknown = set(args) - set(t.params)
    if unknown:
        raise QueryError(
            f"Unknown argument(s) {', '.join(sorted(unknown))}. Arguments: {', '.join(t.params)}."
        )
    missing = [k for k in t.required if args.get(k) in (None, "") and not (k == "module_under" and k in args)]
    if missing:
        raise QueryError(f"Missing argument(s): {', '.join(missing)}.")
    conn.execute("set time zone 'UTC'")
    repo_id, repo = resolve_repo(conn, args["repo"])
    with conn.transaction():
        out = t.fn(Ctx(conn, store, repo_id, repo), args)
    return out if exact else _round(out)
