"""R1: did the share of default branch commits that fail main CI change between H1 and H2.

Definitions the question uses:
- workflow: the main CI workflow, by id (eslint has two other workflows also named
  "CI", junit has two ids for one workflow)
- push_default: push runs on commits that are on the default branch
- landing: one run per commit, its earliest push run, with its final result
- excluded: cancelled and skipped landing runs are left out, and the share is out of
  the commits that are left
- failing: failure, timed_out or startup_failure
- halves: H1 2025-10-01 to 2026-03-31 and H2 2026-04-01 to 2026-09-20 by the run's
  start, both days inclusive

The two rates tell us about all six: if both equal the key, they were all applied. If
both equal an alternative key, that names the one that went wrong. Otherwise the
queries behind the answer decide. The CI helpers here (the run set builder, the used
calls, the query checks, the verdict rule) are shared with r2.py and r7.py.
"""

import json
import re
from dataclasses import dataclass, replace

from common import (
    APPLIED,
    MISSED,
    OTHER_READING,
    UNCLEAR,
    Verdict,
    ck,
    close,
    fetch,
    leaf_filters,
    parse_args,
    pct,
)

TEMPLATE = "R1"
DEFINITIONS = ["workflow", "push_default", "landing", "excluded", "failing", "halves"]

ON_BRANCH = "exists (select 1 from commits c where c.sha = ci.commit_sha and c.repo_id = ci.repo_id)"
# The main workflow by its display name. Only sqlalchemy's is not called "CI".
BY_NAME = "ci.workflow_name = case r.name when 'sqlalchemy' then 'Run tests' else 'CI' end"
LEFT_OUT = "('cancelled', 'skipped')"
FAILING = {
    "key": ck.FAILING,
    "failure only": "conclusion = 'failure'",
    "not success": "conclusion <> 'success'",
}


@dataclass(frozen=True)
class RunSet:
    """Which runs count. The defaults are the key's reading."""

    workflow: str = "id"  # id or name
    push: bool = True  # only push events
    branch: bool = True  # only commits on the default branch
    pick: str = "earliest"  # earliest, latest, earliest success, or all (no one run per commit)
    first_attempt: bool = False  # only runs whose latest attempt is 1
    drop_first: bool = False  # leave out cancelled and skipped before picking the run
    keep_cancelled: bool = False  # cancelled and skipped stay in the count


KEY_RUNS = RunSet()


def runs_cte(o: RunSet) -> str:
    """CTEs main, picked and counted, like compute_keys.LANDING_CTE with switches changed."""
    where = [ck.MAIN_CI if o.workflow == "id" else BY_NAME]
    if o.push:
        where.append("ci.event = 'push'")
    if o.branch:
        where.append(ON_BRANCH)
    if o.first_attempt:
        where.append("ci.run_attempt = 1")
    if o.drop_first:
        where.append(f"ci.conclusion is not null and ci.conclusion not in {LEFT_OUT}")
    if o.pick == "all":
        picked = "select * from main"
    else:
        order = "started_at desc, id desc" if o.pick == "latest" else "started_at, id"
        only = " where conclusion = 'success'" if o.pick == "earliest success" else ""
        picked = f"select distinct on (repo, commit_sha) * from main{only} order by repo, commit_sha, {order}"
    kept = "conclusion is not null" + ("" if o.keep_cancelled else f" and conclusion not in {LEFT_OUT}")
    return f"""
    main as (
      select r.name repo, ci.*,
        (select min(c.committed_at) from commits c
         where c.sha = ci.commit_sha and c.repo_id = ci.repo_id) committed_at
      from ci_runs ci join repos r on r.id = ci.repo_id where {" and ".join(where)}
    ),
    picked as ({picked}),
    counted as (select * from picked where {kept})"""


def half(col, last_day=False):
    """H1 or H2. With last_day (a date alone with lte), each half loses its last day."""
    h1_end, w_end = ("2026-03-31", "2026-09-20") if last_day else (ck.H2_0, ck.W1)
    return (
        f"case when {col} >= '{ck.W0}' and {col} < '{h1_end}' then 'H1' "
        f"when {col} >= '{ck.H2_0}' and {col} < '{w_end}' then 'H2' end"
    )


# ---- Values ----

UNIT_TO = {
    "percent": {"percent": 1, "fraction": 100},
    "minutes": {"minutes": 1, "seconds": 1 / 60, "hours": 60, "days": 1440},
    "hours": {"hours": 1, "minutes": 1 / 60, "seconds": 1 / 3600, "days": 24},
    "days": {"days": 1, "hours": 1 / 24, "minutes": 1 / 1440, "seconds": 1 / 86400},
}


def num(t, name, unit):
    """The copied value as a number in this unit. The judges record the unit the answer used."""
    v = t.value(name)
    try:
        v = float(str(v).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    got = ((t.grade.get("final_extracted") or {}).get(name) or {}).get("unit")
    return v * UNIT_TO[unit].get(got, 1)


# ---- The calls behind the answer ----


def call_results(t):
    """(tool, args, result, turn) for every call that didn't return an error."""
    out, pending = [], []
    for s in t.run["steps"]:
        if s["step_type"] == "tool_call":
            pending.append((s.get("tool_name"), parse_args(s.get("tool_arguments")), s.get("turn")))
        elif s["step_type"] == "tool_result" and pending:
            name, args, turn = pending.pop(0)
            try:
                res = json.loads(s.get("content") or "")
            except (json.JSONDecodeError, TypeError):
                res = {}
            if isinstance(res, dict) and "error" not in res:
                out.append((name, args, res, turn))
    return out


def is_pr_call(args):
    return any(
        f.get("column") == "event" and str(f.get("value")).lower() in ("pull_request", "pull_request_target")
        for f in leaf_filters(args.get("filters"))
    )


def shape(args):
    """A call without its dates and paging, so the H1 and H2 versions of a query match."""

    def strip(x):
        if isinstance(x, dict):
            if re.fullmatch(DATE_COLS, str(x.get("column"))):
                return None
            return {k: strip(v) for k, v in sorted(x.items()) if k not in ("limit", "offset", "name")}
        if isinstance(x, list):
            return [y for y in map(strip, x) if y is not None]
        return x

    return json.dumps(strip(args), sort_keys=True, default=str)


def used_calls(t, tool="query_ci_runs", skip=is_pr_call):
    """The queries the reported numbers came from: the successful calls of this tool in
    the last turn that had any rows, plus earlier calls of the same shape (the other half).
    Calls that skip() picks are left out (pull request runs, for the default branch
    numbers)."""
    calls = [
        (a, turn)
        for name, a, r, turn in call_results(t)
        if name == tool and not skip(a) and r.get("total") != 0
    ]
    if not calls:
        return []
    last = calls[-1][1]
    shapes = {shape(a) for a, turn in calls if turn == last}
    return [a for a, turn in calls if turn == last or shape(a) in shapes]


def flt(calls, column, where=("filters", "post_filters")):
    """Leaf filters on a column (a regex) in the given parts of the calls."""
    out = []
    for a in calls:
        for part in where:
            for f in leaf_filters(a.get(part)):
                if re.fullmatch(column, str(f.get("column"))):
                    out.append(f)
    return out


def values(f):
    v = f.get("value")
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


# ---- Query checks for the CI templates ----


@dataclass
class Q(Verdict):
    """A query check's verdict, with the alternative key that matches what the query did."""

    alt: str | None = None


NO_CALLS = Q(UNCLEAR, "no successful CI query")


def workflow_check(t, calls):
    if not calls:
        return NO_CALLS
    ids = {str(i) for i in ck.MAIN_CI_IDS[t.repo]}
    by_id = [f for f in flt(calls, "workflow_id", ("filters",)) if f.get("op") in ("eq", "in")]
    if by_id:
        got = {v for f in by_id for v in values(f)}
        if ids <= got:
            return Q(APPLIED, f"workflow_id {sorted(got)}")
        if got & ids:
            return Q(MISSED, f"workflow_id {sorted(got)} keeps only one of the workflow's ids {sorted(ids)}")
        return Q(MISSED, f"workflow_id {sorted(got)} is not the main CI ({sorted(ids)})")
    by_name = [f for f in flt(calls, "workflow_name", ("filters",)) if f.get("op") in ("eq", "in", "matches")]
    if by_name:
        got = {v for f in by_name for v in values(f)}
        if any("/" in v or v.endswith((".yml", ".yaml")) for v in got):
            return Q(
                MISSED, f"workflow_name filtered by a file path {sorted(got)}, which matches almost no runs"
            )
        if t.repo == "eslint":
            return Q(
                MISSED,
                f"workflow_name {sorted(got)}: two other eslint workflows also logged runs named CI",
                "workflow by name",
            )
        return Q(APPLIED, f"workflow_name {sorted(got)}, unique to the main CI in this repo")
    return Q(MISSED, "no workflow filter in the queries behind the answer")


def push_default_check(t, calls):
    if not calls:
        return NO_CALLS
    ev = flt(calls, "event")
    br = [
        f
        for f in flt(calls, "on_default_branch")
        if (f.get("op") == "eq" and str(f.get("value")).lower() == "true")
        or (f.get("op") == "ne" and str(f.get("value")).lower() == "false")
    ]
    br += [
        f for a in calls for f in leaf_filters(a.get("stretches")) if f.get("column") == "on_default_branch"
    ]
    push = [f for f in ev if f.get("op") in ("eq", "in") and "push" in values(f)]
    caps = [f for f in ev if any(v != v.lower() for v in values(f))]
    gaps = []
    if caps:
        gaps.append(f"event value in capitals {values(caps[0])}, which matches nothing")
    elif not push:
        gaps.append("no event = push filter" + (f" (only {ev[0]['op']} {values(ev[0])})" if ev else ""))
    if not br:
        gaps.append("no on_default_branch filter")
    if not gaps:
        return Q(APPLIED, "event = push and on_default_branch = true")
    if caps:
        return Q(MISSED, "; ".join(gaps))
    alt = "no event or branch filter" if len(gaps) == 2 else "off-branch pushes kept" if push else "any event"
    return Q(MISSED, "; ".join(gaps), alt)


def first_per_order(a):
    fp = a.get("first_per")
    if not isinstance(fp, dict) or "commit_sha" not in (fp.get("columns") or []):
        return None
    order = fp.get("order_by") or [{"column": "started_at"}]
    o = order[0] if isinstance(order, list) and order and isinstance(order[0], dict) else {}
    desc = str(o.get("desc")).lower() == "true"
    return f"{o.get('column', 'started_at')}{' desc' if desc else ''}"


def landing_check(t, calls):
    if not calls:
        return NO_CALLS
    orders = {first_per_order(a) for a in calls} - {None}
    if orders:
        o = sorted(orders)[0]
        if o in ("started_at", "run_id"):
            return Q(APPLIED, f"first_per commit_sha ordered by {o}")
        alt = "latest run per commit" if o.endswith("desc") else None
        return Q(MISSED, f"first_per commit_sha ordered by {o}, not the earliest run", alt)
    if any("commit_sha" in (a.get("group_by") or []) for a in calls):
        return Q(MISSED, "grouped by commit and took min or max of each column, not one whole run")
    if any(f.get("op") == "eq" and str(f.get("value")) == "1" for f in flt(calls, "attempt", ("filters",))):
        return Q(MISSED, "no first run per commit; kept runs with attempt = 1 instead", "first attempts only")
    return Q(MISSED, "no first run per commit: every run counted", "every run")


def cancelled_check(t, calls):
    if not calls:
        return NO_CALLS
    res = flt(calls, "result", ("filters",))
    post = flt(calls, "result", ("post_filters",))
    agg = [f for a in calls for f in leaf_filters(a.get("aggregates")) if f.get("column") == "result"]

    def drops(fs):
        out = set()
        for f in fs:
            vs = {v.lower() for v in values(f)}
            if f.get("op") in ("not_in", "ne"):
                out |= vs
            if f.get("op") in ("in", "eq") and "cancelled" not in vs:
                out |= {"cancelled", "skipped"}  # keeps only the named results
        return out

    caps = [f for f in res + post if any(v != v.lower() for v in values(f))]
    if caps:
        return Q(MISSED, f"result values in capitals {values(caps[0])}, which match nothing")
    both = {"cancelled", "skipped"}
    if both <= drops(post) or both <= drops(agg):
        return Q(APPLIED, "cancelled and skipped left out after the landing run was picked")
    if both <= drops(res):
        if any(first_per_order(a) for a in calls):
            return Q(
                OTHER_READING,
                "cancelled and skipped left out before picking the landing run, not after",
                "cancelled left out before picking",
            )
        return Q(APPLIED, "cancelled and skipped left out")
    if "cancelled" in drops(res + post):
        return Q(MISSED, "cancelled left out but not skipped")
    if any("result" in (a.get("group_by") or []) for a in calls):
        return Q(MISSED, "counted by result with cancelled runs still in the total", "cancelled kept")
    return Q(MISSED, "no filter leaving out cancelled and skipped runs", "cancelled kept")


def commit_base(t):
    """Totals of the agent's commit queries that it then used as a share's base, in a
    Fisher test or as "of N" in the answer."""
    res = [r for name, _, r, _ in call_results(t) if name == "query_commits"]
    totals = {r.get("total") for r in res}
    totals |= {r["rows"][0][0] for r in res if r.get("total") == 1 and r.get("rows") and r["rows"][0]}
    totals = {x for x in totals if isinstance(x, int) and x > 1}
    used = set()
    for name, a, _, _ in call_results(t):
        if name == "fisher_test":
            used |= {a.get("total_a"), a.get("total_b")}
    used |= {int(m) for m in re.findall(r"\bof (\d+)", t.run.get("final_answer") or "")}
    return sorted(totals & used)


def page_cut(t):
    """A commit_sha list of exactly one page (50 rows) passed as a filter."""
    return any(
        f.get("column") == "commit_sha" and isinstance(f.get("value"), list) and len(f["value"]) == 50
        for name, a, _, _ in call_results(t)
        for f in leaf_filters(a.get("filters"))
    )


def excluded_check(t, calls, base=False):
    """Cancelled and skipped left out after the landing run and, for R1, the share's base."""
    q = cancelled_check(t, calls)
    hit = commit_base(t) if base else []
    if not hit:
        return q
    text = f"the share's base is every commit in the half ({hit})"
    if page_cut(t):
        text += ", while its failing count came from one page of 50 commits"
    return Q(OTHER_READING, f"{text}; {q.evidence}", "all commits as the base")


def failing_check(t, calls):
    if not calls:
        return NO_CALLS
    fs = [f for f in flt(calls, "result") if f.get("op") in ("in", "eq")]
    for part in ("aggregates", "stretches"):
        fs += [f for a in calls for f in leaf_filters(a.get(part)) if f.get("column") == "result"]
    # A filter that also keeps success only sets which runs count, not which ones fail.
    fail = [
        f
        for f in fs
        if f.get("op") in ("in", "eq")
        and "failure" in {v.lower() for v in values(f)}
        and "success" not in values(f)
    ]
    not_ok = [
        f
        for f in flt(calls, "result", ("filters",))
        if f.get("op") in ("ne", "not_in") and "success" in values(f)
    ]
    if not_ok and any(first_per_order(a) for a in calls):
        return Q(
            MISSED,
            "left out successful runs before picking one run per commit, "
            "so a commit with any failing run counts as failing",
        )
    if not fail:
        text = (t.run.get("final_answer") or "").lower()
        if "timed_out" in text and "startup_failure" in text:
            return Q(
                APPLIED, "no failing filter, but the answer names failure, timed_out and startup_failure"
            )
        if any("result" in (a.get("group_by") or []) for a in calls):
            return Q(UNCLEAR, "counted by result; which ones it called failing is in the text only")
        return Q(UNCLEAR, "no filter naming the failing results")
    vs = {v for f in fail for v in values(f)}
    if any(v != v.lower() for v in vs):
        return Q(MISSED, f"failing results in capitals {sorted(vs)}")
    if {"failure", "timed_out", "startup_failure"} <= vs:
        return Q(APPLIED, "failure, timed_out and startup_failure")
    return Q(MISSED, f"failing means only {sorted(vs)}", "failure only" if vs == {"failure"} else None)


DATE_COLS = "started_at|finished_at|committed_at|first_started_at|first_run_started_at"


def date_filters(t, calls):
    """Date filters in the calls behind the answer, and in summarize, compare and commit calls."""
    fs = flt(calls, DATE_COLS)
    for name, a, _, _ in call_results(t):
        if name in ("summarize", "compare_medians", "query_commits"):
            fs += [f for f in leaf_filters(a) if re.fullmatch(DATE_COLS, str(f.get("column")))]
    return fs


def last_day_cut(fs, days=("2026-03-31", "2026-09-20")):
    """lte on a date alone (no time) at the end of a half."""
    return [f for f in fs if f.get("op") == "lte" and str(f.get("value")) in days]


def halves_check(t, calls):
    fs = date_filters(t, calls)
    if not fs:
        return Q(UNCLEAR, "no date filters")
    if last_day_cut(fs):
        return Q(
            MISSED,
            "lte on a date alone (2026-03-31 or 2026-09-20) leaves out the last day",
            "last day of each half left out",
        )
    ends = {(f.get("op"), str(f.get("value"))[:10]) for f in fs if f.get("op") in ("lt", "lte")}
    starts = {str(f.get("value"))[:10] for f in fs if f.get("op") in ("gte", "gt")}
    cols = sorted({f["column"] for f in fs})
    split = "2026-04-01" in starts and (("lt", "2026-04-01") in ends or ("lte", "2026-03-31") in ends)
    if split and cols == ["committed_at"]:
        return Q(OTHER_READING, "halves by commit date, not by the run's start", "halves by commit date")
    if split:
        return Q(APPLIED, f"H1 and H2 filters on {cols}")
    return Q(UNCLEAR, f"date filters on {cols}: starts {sorted(starts)}, ends {sorted(ends)}")


# ---- The verdict rule for the CI templates ----


def combine(right, alt_names, query_checks, alt_def, readings, value_text, same_as_key):
    """right: the values equal the key. alt_names: alternatives (not the key) the values
    equal. same_as_key(name): that alternative gives the key's values in this repo.

    A definition is applied when the values equal the key, and missed (or other_reading
    for a reading the wording allows) when they equal its alternative. Otherwise its
    query check decides. A query mistake whose alternative gives the key here is marked
    as having no effect, and a reading is only kept when the values follow it.
    """
    out = {}
    for d, q in query_checks.items():
        names = [n for n in alt_names if alt_def.get(n) == d]
        if right:
            out[d] = Verdict(APPLIED, f"{value_text} equal the key")
        elif names:
            v = OTHER_READING if names[0] in readings else MISSED
            out[d] = Verdict(v, f"{value_text} equal the key with '{names[0]}'")
        elif q.verdict == OTHER_READING:
            if q.alt and same_as_key(q.alt):
                out[d] = Verdict(APPLIED, f"{q.evidence}, which gives the key in this repo")
            else:
                out[d] = Verdict(UNCLEAR, f"{q.evidence}; the values don't match that reading's key")
        elif q.verdict == MISSED and q.alt and same_as_key(q.alt):
            out[d] = Verdict(MISSED, f"{q.evidence} (no effect in this repo); {value_text}")
        else:
            out[d] = Verdict(q.verdict, f"{q.evidence}; {value_text}")
    return out


# ---- Alternatives ----

# Each alternative switches off or changes one definition:
# (name, definition, run set, failing rule, half column, last day left out, all commits as base).
ALTERNATIVES = [
    ("workflow by name", "workflow", replace(KEY_RUNS, workflow="name"), "key", "started_at", False, False),
    ("any event", "push_default", replace(KEY_RUNS, push=False), "key", "started_at", False, False),
    (
        "off-branch pushes kept",
        "push_default",
        replace(KEY_RUNS, branch=False),
        "key",
        "started_at",
        False,
        False,
    ),
    (
        "no event or branch filter",
        "push_default",
        replace(KEY_RUNS, push=False, branch=False),
        "key",
        "started_at",
        False,
        False,
    ),
    ("every run", "landing", replace(KEY_RUNS, pick="all"), "key", "started_at", False, False),
    ("latest run per commit", "landing", replace(KEY_RUNS, pick="latest"), "key", "started_at", False, False),
    (
        "first attempts only",
        "landing",
        replace(KEY_RUNS, first_attempt=True),
        "key",
        "started_at",
        False,
        False,
    ),
    (
        "cancelled left out before picking",
        "excluded",
        replace(KEY_RUNS, drop_first=True),
        "key",
        "started_at",
        False,
        False,
    ),
    ("cancelled kept", "excluded", replace(KEY_RUNS, keep_cancelled=True), "key", "started_at", False, False),
    ("all commits as the base", "excluded", KEY_RUNS, "key", "started_at", False, True),
    ("failure only", "failing", KEY_RUNS, "failure only", "started_at", False, False),
    ("not success", "failing", KEY_RUNS, "not success", "started_at", False, False),
    ("last day of each half left out", "halves", KEY_RUNS, "key", "started_at", True, False),
    ("halves by commit date", "halves", KEY_RUNS, "key", "committed_at", False, False),
]
# Readings the question's wording allows ("share of commits on the default branch").
READINGS = {"cancelled left out before picking", "all commits as the base", "halves by commit date"}
ALT_DEF = {a[0]: a[1] for a in ALTERNATIVES}


def rates(conn, o, failing="key", col="started_at", last_day=False, all_commits=False):
    rows = fetch(
        conn,
        f"""
        with {runs_cte(o)},
        h as (select *, {half(col, last_day)} half from counted)
        select repo, half, count(*) n, count(*) filter (where {FAILING[failing]}) f
        from h where half is not null group by 1, 2""",
    )
    out = {}
    for r in rows:
        out.setdefault(r["repo"], {})[r["half"]] = [r["f"], r["n"]]
    if all_commits:
        for r in fetch(
            conn,
            f"""select r.name repo, {half("c.committed_at")} half, count(*) n
            from commits c join repos r on r.id = c.repo_id group by 1, 2""",
        ):
            if r["half"] and r["repo"] in out:
                out[r["repo"]][r["half"]][1] = r["n"]
    return {repo: (pct(h["H1"][0] / h["H1"][1]), pct(h["H2"][0] / h["H2"][1])) for repo, h in out.items()}


def prepare(conn, repos):
    alt = {repo: {} for repo in repos}
    for name, _, o, failing, col, last_day, all_commits in ALTERNATIVES:
        got = rates(conn, o, failing, col, last_day, all_commits)
        for repo in repos:
            alt[repo][name] = got[repo]
    # The key rebuilt with the same code, as a check on the builder.
    key = rates(conn, KEY_RUNS)
    for repo in repos:
        alt[repo]["key (rebuilt)"] = key[repo]
    return alt


def matches(pair, got, tol=0.01):
    return close(got[0], pair[0], tol) and close(got[1], pair[1], tol)


def check(t, alt):
    a = alt[t.repo]
    key = (pct(t.key["h1_rate"]), pct(t.key["h2_rate"]))
    got = (num(t, "h1_failure_rate_pct", "percent"), num(t, "h2_failure_rate_pct", "percent"))
    calls = used_calls(t)
    q = {
        "workflow": workflow_check(t, calls),
        "push_default": push_default_check(t, calls),
        "landing": landing_check(t, calls),
        "excluded": excluded_check(t, calls, base=True),
        "failing": failing_check(t, calls),
        "halves": halves_check(t, calls),
    }
    names = [n for n, p in a.items() if n in ALT_DEF and matches(p, got) and not matches(p, key)]
    text = f"rates {got[0]}, {got[1]} (key {key[0]:.2f}, {key[1]:.2f})"
    return combine(matches(key, got), names, q, ALT_DEF, READINGS, text, lambda n: matches(a[n], key))
