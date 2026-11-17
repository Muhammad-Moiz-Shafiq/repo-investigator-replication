"""R2: did successful default branch runs of main CI get slower or faster between H1 and H2.

Definitions the question uses (the must-haves are the default branch medians and verdict):
- workflow, push_default, landing: as in R1
- success: of the landing runs, only the successful ones (a commit whose landing run
  failed or was cancelled is left out, not replaced by a later run)
- duration: from the run's start to its finish (duration_seconds is exactly that)
- halves: H1 and H2 by the run's start, both days inclusive

The two medians tell us about these: if both equal the key, they were all applied. If
both equal an alternative key, that names the one that went wrong.
"""

from dataclasses import replace

from common import APPLIED, MISSED, OTHER_READING, UNCLEAR, close, fetch, leaf_filters
from r1 import (
    KEY_RUNS,
    Q,
    call_results,
    combine,
    first_per_order,
    flt,
    half,
    halves_check,
    landing_check,
    num,
    push_default_check,
    runs_cte,
    used_calls,
    values,
    workflow_check,
)

TEMPLATE = "R2"
DEFINITIONS = ["workflow", "push_default", "landing", "success", "duration", "halves"]

# Each alternative switches off or changes one definition:
# (name, definition, run set, half column, last day left out).
ALTERNATIVES = [
    ("workflow by name", "workflow", replace(KEY_RUNS, workflow="name"), "started_at", False),
    ("any event", "push_default", replace(KEY_RUNS, push=False), "started_at", False),
    ("off-branch pushes kept", "push_default", replace(KEY_RUNS, branch=False), "started_at", False),
    (
        "no event or branch filter",
        "push_default",
        replace(KEY_RUNS, push=False, branch=False),
        "started_at",
        False,
    ),
    ("every successful run", "landing", replace(KEY_RUNS, pick="all"), "started_at", False),
    ("latest run per commit", "landing", replace(KEY_RUNS, pick="latest"), "started_at", False),
    ("first attempts only", "landing", replace(KEY_RUNS, first_attempt=True), "started_at", False),
    (
        "first successful run per commit",
        "success",
        replace(KEY_RUNS, pick="earliest success"),
        "started_at",
        False,
    ),
    ("last day of each half left out", "halves", KEY_RUNS, "started_at", True),
    ("halves by commit date", "halves", KEY_RUNS, "committed_at", False),
]
# "Successful runs" read as each commit's first successful run is allowed by the wording.
READINGS = {"first successful run per commit", "halves by commit date"}
ALT_DEF = {a[0]: a[1] for a in ALTERNATIVES}


def medians(conn, o, col="started_at", last_day=False):
    rows = fetch(
        conn,
        f"""
        with {runs_cte(o)},
        h as (select *, {half(col, last_day)} half from counted
              where conclusion = 'success' and duration_seconds is not null)
        select repo, half, percentile_cont(0.5) within group (order by duration_seconds / 60.0) m
        from h where half is not null group by 1, 2""",
    )
    out = {}
    for r in rows:
        out.setdefault(r["repo"], {})[r["half"]] = float(r["m"])
    return {repo: (h.get("H1"), h.get("H2")) for repo, h in out.items()}


def prepare(conn, repos):
    alt = {repo: {} for repo in repos}
    for name, _, o, col, last_day in ALTERNATIVES:
        got = medians(conn, o, col, last_day)
        for repo in repos:
            alt[repo][name] = got.get(repo, (None, None))
    key = medians(conn, KEY_RUNS)
    for repo in repos:
        alt[repo]["key (rebuilt)"] = key[repo]
    return alt


def matches(pair, got):
    return all(
        close(g, p, max(0.01, 0.002 * p)) for g, p in zip(got, pair, strict=True) if p is not None
    ) and all(g is not None for g in got)


def success_check(t, calls):
    if not calls:
        return Q(UNCLEAR, "no successful CI query")
    fs = flt(calls, "result")
    caps = [f for f in fs if any(v != v.lower() for v in values(f))]
    if caps:
        return Q(MISSED, f"result values in capitals {values(caps[0])}, which match nothing")
    ok = [f for f in fs if f.get("op") in ("eq", "in") and "success" in values(f)]
    if not ok:
        return Q(MISSED, "no filter keeping only successful runs")
    before = [f for f in flt(calls, "result", ("filters",)) if f in ok]
    if before and any(first_per_order(a) for a in calls):
        return Q(
            OTHER_READING,
            "kept successful runs before picking one per commit: each commit's first successful run",
            "first successful run per commit",
        )
    return Q(APPLIED, "result = success")


def duration_check(t, calls):
    text = str([a for _, a, _, _ in call_results(t)])
    if "duration_seconds" in text or ("finished_at" in text and "started_at" in text):
        return Q(APPLIED, "durations from duration_seconds or finished_at minus started_at")
    return Q(UNCLEAR, "no duration column in the queries")


def same_halves(t):
    """A median comparison whose two halves had the same rows: the half filter did nothing."""
    for name, a, r, _ in call_results(t):
        if (
            name == "compare_medians"
            and r.get("n_a") == r.get("n_b")
            and r.get("median_a") == r.get("median_b")
            and any(f.get("column") == "started_at" for f in leaf_filters(a))
        ):
            return f"compare_medians got the same {r.get('n_a')} rows for both halves"
    return None


def check(t, alt):
    a = alt[t.repo]
    key = (t.key["main_h1_min"], t.key["main_h2_min"])
    got = (num(t, "main_h1_minutes", "minutes"), num(t, "main_h2_minutes", "minutes"))
    calls = used_calls(t)
    same = same_halves(t)
    q = {
        "workflow": workflow_check(t, calls),
        "push_default": push_default_check(t, calls),
        "landing": landing_check(t, calls),
        "success": success_check(t, calls),
        "duration": duration_check(t, calls),
        "halves": Q(MISSED, f"{same}: its 'where' on the half had no effect")
        if same
        else halves_check(t, calls),
    }
    if q["landing"].alt == "every run":
        q["landing"] = Q(MISSED, q["landing"].evidence, "every successful run")
    names = [n for n, p in a.items() if n in ALT_DEF and matches(p, got) and not matches(p, key)]
    if None in got:
        text = "no default branch medians given"
    else:
        text = f"medians {got[0]:.2f}, {got[1]:.2f} min (key {key[0]:.2f}, {key[1]:.2f})"
    return combine(matches(key, got), names, q, ALT_DEF, READINGS, text, lambda n: matches(a[n], key))
