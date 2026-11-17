"""R7: the longest red stretch of main CI on the default branch that started in H2.

Definitions the question uses:
- workflow, push_default, landing, excluded, failing: as in R1 (the stretch is walked
  over every counted landing run, in start order)
- h2_start: the stretch's first failing run started in H2
- longest: the longest by time red, not by the number of failing commits
- hours: from the first failing run's finish to the next passing run's finish

The two commits tell us about the first six: if both equal the key's, they were applied.
If both equal an alternative key's, that names the one that went wrong. The hours, for
the stretch the agent named, tell us about hours.
"""

from dataclasses import replace

from common import APPLIED, MISSED, UNCLEAR, Verdict, ck, fetch
from r1 import (
    FAILING,
    KEY_RUNS,
    Q,
    combine,
    date_filters,
    excluded_check,
    failing_check,
    landing_check,
    last_day_cut,
    num,
    push_default_check,
    runs_cte,
    used_calls,
    workflow_check,
)

TEMPLATE = "R7"
DEFINITIONS = ["workflow", "push_default", "landing", "excluded", "failing", "h2_start", "longest", "hours"]

H2_0 = f"{ck.H2_0}T00:00:00+00:00"
W1 = f"{ck.W1}T00:00:00+00:00"

# How hours are measured: (from the first failing run's, to the next passing run's).
MEASURES = {
    "finish to finish": ("completed_at", "completed_at"),
    "start to finish": ("started_at", "completed_at"),
    "finish to start": ("completed_at", "started_at"),
    "start to start": ("started_at", "started_at"),
}


def walk(rows, measure="finish to finish", rank="hours", order="started_at", in_window=False):
    """Every red stretch that has a passing run before and after it, and the longest one
    starting in H2, like compute_keys.r7 with switches."""
    s = sorted(rows, key=lambda r: (r[order], r["id"]))
    a, b = MEASURES[measure]
    stretches, best = [], None
    i = 1
    while i < len(s):
        if s[i]["failing"] and not s[i - 1]["failing"]:
            j = i
            while j < len(s) and s[j]["failing"]:
                j += 1
            if j < len(s):
                hours = (s[j][b] - s[i][a]).total_seconds() / 3600
                start = s[i]["started_at"].isoformat()
                st = (s[i]["commit_sha"], s[j]["commit_sha"], j - i, hours, start)
                stretches.append(st)
                ok = H2_0 <= start < W1 and (not in_window or s[j]["started_at"].isoformat() < W1)
                score = (hours, j - i) if rank == "hours" else (j - i, hours)
                if ok and (best is None or score > best[0]):
                    best = (score, st)
            i = j
        else:
            i += 1
    return (best[1] if best else None), stretches


# Each alternative switches off or changes one definition:
# (name, definition, run set, failing rule, walk options).
ALTERNATIVES = [
    ("workflow by name", "workflow", replace(KEY_RUNS, workflow="name"), "key", {}),
    ("any event", "push_default", replace(KEY_RUNS, push=False), "key", {}),
    ("off-branch pushes kept", "push_default", replace(KEY_RUNS, branch=False), "key", {}),
    ("no event or branch filter", "push_default", replace(KEY_RUNS, push=False, branch=False), "key", {}),
    ("every run", "landing", replace(KEY_RUNS, pick="all"), "key", {}),
    ("latest run per commit", "landing", replace(KEY_RUNS, pick="latest"), "key", {}),
    ("first attempts only", "landing", replace(KEY_RUNS, first_attempt=True), "key", {}),
    ("cancelled left out before picking", "excluded", replace(KEY_RUNS, drop_first=True), "key", {}),
    ("cancelled kept", "excluded", replace(KEY_RUNS, keep_cancelled=True), "key", {}),
    ("failure only", "failing", KEY_RUNS, "failure only", {}),
    ("not success", "failing", KEY_RUNS, "not success", {}),
    ("runs in finish order", "h2_start", KEY_RUNS, "key", {"order": "completed_at"}),
    ("stretch must end in the window", "h2_start", KEY_RUNS, "key", {"in_window": True}),
    ("most failing commits", "longest", KEY_RUNS, "key", {"rank": "commits"}),
    *[
        (f"longest by {m}", "hours", KEY_RUNS, "key", {"measure": m})
        for m in MEASURES
        if m != "finish to finish"
    ],
]
# The question says "measured from when the first failing run finished", so a different
# measure is a mistake, not a reading. Picking runs after leaving out cancelled ones is.
READINGS = {"cancelled left out before picking"}
ALT_DEF = {a[0]: a[1] for a in ALTERNATIVES}


def rows_for(conn, o, failing="key"):
    rows = fetch(
        conn,
        f"""with {runs_cte(o)}
        select repo, id, commit_sha, started_at, completed_at, {FAILING[failing]} failing from counted""",
    )
    by = {}
    for r in rows:
        by.setdefault(r["repo"], []).append(r)
    return by


def prepare(conn, repos):
    alt = {repo: {"alternatives": {}, "stretches": [], "times": {}} for repo in repos}
    cache = {}
    for name, _, o, failing, opts in [("key (rebuilt)", None, KEY_RUNS, "key", {}), *ALTERNATIVES]:
        if (o, failing) not in cache:
            cache[(o, failing)] = rows_for(conn, o, failing)
        for repo in repos:
            best, stretches = walk(cache[(o, failing)].get(repo, []), **opts)
            alt[repo]["alternatives"][name] = best[:4] if best else None
            if name == "key (rebuilt)":
                alt[repo]["stretches"] = [st[:4] + (st[4][:19],) for st in stretches]
    # Start and finish of each commit's landing run, to measure any stretch the agent names.
    for repo, rows in cache[(KEY_RUNS, "key")].items():
        if repo in alt:
            alt[repo]["times"] = {
                r["commit_sha"]: (r["started_at"], r["completed_at"], r["failing"]) for r in rows
            }
    return alt


def same_sha(guess, sha):
    g = str(guess or "").strip().lower()
    return len(g) >= 7 and sha is not None and sha.startswith(g)


def full_sha(guess, times):
    hits = [s for s in times if same_sha(guess, s)]
    return hits[0] if len(hits) == 1 else None


def h2_check(t, calls):
    fs = date_filters(t, calls)
    if last_day_cut(fs, ("2026-09-20",)):
        return Q(MISSED, "lte 2026-09-20 on a date alone leaves out the last day")
    starts = {
        str(f.get("value"))[:10]
        for f in fs
        if f.get("op") in ("gte", "gt") and f.get("column") == "started_at"
    }
    if ck.H2_0 in starts:
        return Q(APPLIED, "runs filtered to start in H2")
    if fs:
        return Q(UNCLEAR, f"date filters on {sorted({f['column'] for f in fs})}")
    return Q(UNCLEAR, "no date filters")


def check(t, alt):
    a = alt[t.repo]
    times = a["times"]
    k = (t.key["first_failing_sha"], t.key["next_passing_sha"])
    first, nxt = t.value("first_failing_sha"), t.value("next_passing_sha")
    hours = num(t, "hours_red", "hours")
    calls = [c for c in used_calls(t) if c.get("stretches")] or used_calls(t)

    def same(pair):
        return pair is not None and same_sha(first, pair[0]) and same_sha(nxt, pair[1])

    right = same(k)
    names = [n for n, p in a["alternatives"].items() if n in ALT_DEF and same(p) and tuple(p[:2]) != k]
    text = f"commits {str(first)[:10]}, {str(nxt)[:10]} (key {k[0][:10]}, {k[1][:10]})"

    # The stretch the agent named, among the key's red stretches.
    f_sha = full_sha(first, times)
    named = [st for st in a["stretches"] if f_sha and st[0] == f_sha]
    if right:
        longest = Q(APPLIED, "the key's stretch")
        h2 = Q(APPLIED, "the key's stretch")
    elif named:
        st = named[0]
        if st[4] >= H2_0[:19]:
            best = a["alternatives"]["key (rebuilt)"]
            longest = Q(
                MISSED,
                f"a real red stretch starting in H2 ({st[3]:.1f} h), not the longest ({best[3]:.1f} h)",
            )
            h2 = Q(APPLIED, f"its stretch starts {st[4][:10]}, in H2")
        else:
            longest = Q(UNCLEAR, "its stretch starts before H2")
            h2 = Q(MISSED, f"its stretch starts {st[4][:10]}, before H2")
    else:
        longest = Q(UNCLEAR, "its first commit does not start a red stretch of landing runs")
        h2 = h2_check(t, calls)
    q = {
        "workflow": workflow_check(t, calls),
        "push_default": push_default_check(t, calls),
        "landing": landing_check(t, calls),
        "excluded": excluded_check(t, calls),
        "failing": failing_check(t, calls),
        "h2_start": h2,
        "longest": longest,
        "hours": Q(UNCLEAR, "set below"),
    }
    if first and not f_sha and not right and q["push_default"].verdict == MISSED:
        q["push_default"] = Q(
            MISSED, f"{q['push_default'].evidence}; its first commit has no landing run on the default branch"
        )
    if f_sha and not times[f_sha][2] and not right and not names:
        q["failing"] = Q(
            MISSED, "its first failing commit passed in its landing run: it took a green stretch"
        )
        q["longest"] = Q(UNCLEAR, "it took a green stretch")
    if (
        any(
            isinstance(o, dict) and o.get("column") == "row_count"
            for c in calls
            for o in (c.get("order_by") or [])
        )
        and q["longest"].verdict != APPLIED
    ):
        q["longest"] = Q(
            MISSED, "sorted the stretches by number of failing runs, not by time red", "most failing commits"
        )

    out = combine(
        right,
        names,
        q,
        ALT_DEF,
        READINGS,
        text,
        lambda n: tuple((a["alternatives"][n] or (None, None))[:2]) == k,
    )

    # Hours, measured for the stretch the agent named (its two commits' landing runs).
    n_sha = full_sha(nxt, times)
    if hours is None:
        out["hours"] = Verdict(UNCLEAR, "no hours given")
    elif f_sha and n_sha:
        (s1, c1, _), (s2, c2, _) = times[f_sha], times[n_sha]
        got = {
            "finish to finish": (c2 - c1).total_seconds() / 3600,
            "start to finish": (c2 - s1).total_seconds() / 3600,
            "finish to start": (s2 - c1).total_seconds() / 3600,
            "start to start": (s2 - s1).total_seconds() / 3600,
        }
        fits = [m for m, h in got.items() if abs(h - hours) <= max(0.02, 0.005 * h)]
        if "finish to finish" in fits:
            out["hours"] = Verdict(APPLIED, f"{hours} h is finish to finish for its two commits")
        elif fits:
            out["hours"] = Verdict(
                MISSED, f"{hours} h is {fits[0]} for its two commits, not finish to finish"
            )
        else:
            out["hours"] = Verdict(
                UNCLEAR, f"{hours} h; finish to finish for its two commits is {got['finish to finish']:.2f} h"
            )
    elif right:
        out["hours"] = Verdict(UNCLEAR, f"{hours} h against the key's {t.key['hours_red']:.2f} h")
    else:
        out["hours"] = Verdict(UNCLEAR, f"{hours} h for commits that have no landing run in the key's set")
    return out
