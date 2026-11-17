"""R5: bugs opened and closed in the window, is the backlog growing, and the H1 median time to close.

Definitions the question uses:
- label: the repo's bug label, matched exactly (C-bug, bug, p3-minor-bug, type: bug, kind/bug)
- opened: bugs created in the window, both end days included
- closed: bugs closed in the window, whenever they were opened
- backlog_test: the binomial test of closed out of opened plus closed
- h1_cohort: the median is over bugs opened in H1
- open_bugs: a bug still open at the window's end (or closed after it) counts as not
  closed, longer than every closed one, never left out

The counts tell us about label, opened and closed; the verdict, given the agent's own
counts, about backlog_test; the median about h1_cohort and open_bugs.
"""

import math

import numpy as np
from common import APPLIED, MISSED, UNCLEAR, Verdict, ck, close, fetch, leaf_filters, window_check
from r1 import call_results, num

TEMPLATE = "R5"
DEFINITIONS = ["label", "opened", "closed", "backlog_test", "h1_cohort", "open_bugs"]

LABEL = {
    "tokio": "C-bug",
    "eslint": "bug",
    "sqlalchemy": "bug",
    "vite": "p3-minor-bug",
    "junit-framework": "type: bug",
    "prometheus": "kind/bug",
}
HAS_LABEL = f"{ck.BUG_LABEL} = any(i.labels)"
ANY_BUG_LABEL = "exists (select 1 from unnest(i.labels) l where l ~* 'bug')"
IN_WINDOW = f"i.created_at >= '{ck.W0}' and i.created_at < '{ck.W1}'"
CLOSED_IN_WINDOW = f"i.closed_at >= '{ck.W0}' and i.closed_at < '{ck.W1}'"

# Each alternative switches off or changes one definition: (name, definition, value, SQL).
# Counts are count(*) where the SQL holds. Medians are in days over the rows the SQL keeps,
# with open marking the ones counted as not closed.
COUNT_ALTERNATIVES = [
    ("any label with bug", "label", "opened", f"{ANY_BUG_LABEL} and {IN_WINDOW}"),
    ("any label with bug", "label", "closed", f"{ANY_BUG_LABEL} and {CLOSED_IN_WINDOW}"),
    ("last day left out", "opened", "opened", f"{HAS_LABEL} and {IN_WINDOW.replace(ck.W1, '2026-09-20')}"),
    (
        "last day left out",
        "closed",
        "closed",
        f"{HAS_LABEL} and {CLOSED_IN_WINDOW.replace(ck.W1, '2026-09-20')}",
    ),
    ("closed of the opened", "closed", "closed", f"{HAS_LABEL} and {IN_WINDOW} and {CLOSED_IN_WINDOW}"),
    ("opened ever closed", "closed", "closed", f"{HAS_LABEL} and {IN_WINDOW} and i.closed_at is not null"),
]
H1 = f"i.created_at >= '{ck.W0}' and i.created_at < '{ck.H2_0}'"
CLOSED_BY_END = f"i.closed_at is not null and i.closed_at < '{ck.W1}'"
MEDIAN_ALTERNATIVES = [
    ("open bugs left out", "open_bugs", f"{HAS_LABEL} and {H1} and {CLOSED_BY_END}", CLOSED_BY_END),
    ("closed after the window counted", "open_bugs", f"{HAS_LABEL} and {H1}", "i.closed_at is not null"),
    ("whole window cohort", "h1_cohort", f"{HAS_LABEL} and {IN_WINDOW}", CLOSED_BY_END),
    ("every bug ever", "h1_cohort", HAS_LABEL, CLOSED_BY_END),
    ("every bug ever, open left out", "h1_cohort", f"{HAS_LABEL} and {CLOSED_BY_END}", CLOSED_BY_END),
]


def prepare(conn, repos):
    alt = {repo: {"opened": {}, "closed": {}, "median": {}} for repo in repos}
    for name, _, field, where in COUNT_ALTERNATIVES:
        for r in fetch(
            conn,
            f"""select r.name repo, count(*) n from issues i join repos r on r.id = i.repo_id
            where {where} group by 1""",
        ):
            if r["repo"] in alt:
                alt[r["repo"]][field][name] = r["n"]
    for name, _, where, done in MEDIAN_ALTERNATIVES:
        rows = fetch(
            conn,
            f"""select r.name repo,
              case when {done} then extract(epoch from i.closed_at - i.created_at) / 86400 end d
            from issues i join repos r on r.id = i.repo_id where {where}""",
        )
        for repo in repos:
            days = [math.inf if x["d"] is None else float(x["d"]) for x in rows if x["repo"] == repo]
            m = float(np.median(days)) if days else None
            alt[repo]["median"][name] = None if m is None or math.isinf(m) else m
    return alt


def binom_verdict(opened, closed):
    n = opened + closed
    if not n:
        return None
    if ck.binom_p(closed, n) >= 0.05:
        return "balanced"
    return "growing" if opened > closed else "shrinking"


def issue_calls(t):
    return [(a, r) for name, a, r, _ in call_results(t) if name == "query_issues"]


def cols(a, part="filters"):
    """Columns of the top-level filters (not inside any_of)."""
    fs = a.get(part) or []
    return (
        {f.get("column") for f in fs if isinstance(f, dict) and "column" in f}
        if isinstance(fs, list)
        else set()
    )


def counts_in(r):
    """Every whole number a result gave: its total and single-row aggregate values."""
    out = {r.get("total")}
    rows = r.get("rows") or []
    if len(rows) == 1:
        out |= {v for v in rows[0] if isinstance(v, int) and not isinstance(v, bool)}
    return {x for x in out if isinstance(x, int)}


def label_check(t):
    fs = [f for a, _ in issue_calls(t) for f in leaf_filters(a.get("filters")) if f.get("column") == "labels"]
    if not fs:
        return Verdict(MISSED, "no label filter: counted every issue")
    want = LABEL[t.repo]
    if any(isinstance(f.get("value"), list) for f in fs) and not any(f.get("value") == want for f in fs):
        return Verdict(
            MISSED,
            f"label written as a list {fs[0].get('value')}, which matches no issue, so every count was 0",
        )
    if any(f.get("op") == "contains" and f.get("value") == want for f in fs):
        return Verdict(APPLIED, f"labels contains '{want}'")
    return Verdict(MISSED, f"label filter {fs[0].get('op')} {fs[0].get('value')}, not exactly '{want}'")


def reported_vs_query(t, field, got, key):
    """A query returned the key, but the answer reports something else."""
    results = [counts_in(r) for _, r in issue_calls(t)]
    if got is None or got == key or not any(key in c for c in results):
        return None
    for c in results:
        for x in c:
            if x and key - x == got:
                return Verdict(
                    MISSED, f"a query returned the key {key}, then it took off {x} and reported {got}"
                )
    return Verdict(UNCLEAR, f"a query returned the key {key}, but it reported {got}")


def closed_query(t):
    calls = issue_calls(t)
    by_close = [a for a, _ in calls if "closed_at" in cols(a) and "created_at" not in cols(a)]
    among = [
        a
        for a, _ in calls
        if "created_at" in cols(a)
        and any(f.get("column") == "closed_at" for f in leaf_filters([a.get("filters"), a.get("aggregates")]))
    ]
    if by_close:
        ops = {
            f.get("op")
            for a in by_close
            for f in leaf_filters(a.get("filters"))
            if f.get("column") == "closed_at"
        }
        if ops & {"gte", "gt"}:
            return Verdict(APPLIED, "closed counted by closed_at in the window, whatever the open date")
    if among:
        return Verdict(MISSED, "closed counted only among bugs opened in the window")
    return Verdict(UNCLEAR, "no query counting closed bugs")


H1_ENDS = {"2026-04-01", "2026-03-31"}


def is_h1(a):
    return any(
        f.get("column") == "created_at"
        and f.get("op") in ("lt", "lte")
        and str(f.get("value"))[:10] in H1_ENDS
        for f in leaf_filters(a.get("filters"))
    )


def median_queries(t):
    """(H1 cohort, open bugs handling) from the last summarize call and the query it read."""
    calls = call_results(t)
    source = {r.get("result_id"): a for name, a, r, _ in calls if name == "query_issues"}
    sums = [a for name, a, _, _ in calls if name == "summarize"]
    if not sums:
        return None, None
    a = sums[-1]
    data = a.get("data")
    if isinstance(data, list):
        h1 = any(is_h1(x) for name, x, _, _ in calls if name == "query_issues")
        if any(isinstance(v, (int, float)) and v >= 99999 for v in data):
            return h1, "placeholder"
        return h1, f"median of a typed list of {len(data)} closed times, with no open bugs"
    data = data if isinstance(data, dict) else {}
    src = source.get(data.get("result_id") or a.get("result_id"), {})
    infinite = "as_infinite" in (a.get("missing"), data.get("missing"))
    only_closed = any(
        f.get("column") == "closed_at" and f.get("op") in ("not_null", "ne", "lt", "lte")
        for f in leaf_filters(src.get("filters"))
    )
    if only_closed:
        how = "the median's rows kept only bugs closed by the end"
    else:
        how = "as_infinite" if infinite else "open bugs dropped (missing values dropped)"
    return is_h1(src), how


def check(t, alt):
    a = alt[t.repo]
    key = t.key
    opened, closed = num(t, "opened", "days"), num(t, "closed", "days")  # counts carry no time unit
    opened = None if opened is None else int(opened)
    closed = None if closed is None else int(closed)
    med = num(t, "median_days_to_close", "days")
    verdict = t.value("verdict")
    out = {}

    # Label: the right count says it was right; an alternative says it wasn't.
    lab = label_check(t)
    if opened == key["opened"] or closed == key["closed"]:
        out["label"] = Verdict(APPLIED, f"opened {opened} or closed {closed} equals the key")
    elif opened is not None and opened == a["opened"].get("any label with bug") != key["opened"]:
        out["label"] = Verdict(MISSED, f"opened {opened} equals the key for any label with 'bug'")
    else:
        out["label"] = lab

    for field, got in (("opened", opened), ("closed", closed)):
        k = key[field]
        alts = [n for n, v in a[field].items() if v == got and v != k]
        rq = reported_vs_query(t, field, got, k)
        if lab.verdict == MISSED and got == 0:
            q = window_check(t, ("query_issues",), "created_at") if field == "opened" else closed_query(t)
            out[field] = Verdict(
                q.verdict if q.verdict == MISSED else UNCLEAR, f"count 0 from the label filter; {q.evidence}"
            )
        elif got == k:
            out[field] = Verdict(APPLIED, f"{field} {got} equals the key")
        elif alts and not alts[0].startswith("any label"):
            out[field] = Verdict(MISSED, f"{field} {got} equals the key with '{alts[0]}'")
        elif rq:
            out[field] = rq
        elif field == "closed":
            q = closed_query(t)
            out[field] = Verdict(q.verdict, f"{q.evidence}; reported {got}, key {k}")
        else:
            q = window_check(t, ("query_issues",), "created_at")
            out[field] = Verdict(
                q.verdict if q.verdict == MISSED else UNCLEAR, f"{q.evidence}; reported {got}, key {k}"
            )

    # The backlog test, on the agent's own counts.
    if verdict is None:
        out["backlog_test"] = Verdict(UNCLEAR, "no verdict given")
    elif opened is not None and closed is not None and (opened or closed):
        own = binom_verdict(opened, closed)
        if str(verdict).lower() == own:
            out["backlog_test"] = Verdict(
                APPLIED, f"'{verdict}' follows the test on its own counts {opened}/{closed}"
            )
        else:
            out["backlog_test"] = Verdict(
                MISSED,
                f"on its own counts {opened} opened, {closed} closed the test gives '{own}', "
                f"it said '{verdict}'",
            )
    else:
        tests = [x for name, x, _, _ in call_results(t) if name == "binomial_test"]
        out["backlog_test"] = Verdict(
            UNCLEAR if tests else MISSED,
            f"no window counts given; it said '{verdict}'"
            + (f", testing {tests[0]}" if tests else " with no binomial test"),
        )

    # The median.
    k = key["median_days_to_close"]
    h1, how = median_queries(t)
    alts = (
        [n for n, v in a["median"].items() if close(med, v, 0.005 * v) and not close(med, k, 0.005 * k)]
        if med
        else []
    )
    adef = {n: d for n, d, _, _ in MEDIAN_ALTERNATIVES}
    queries = {
        "h1_cohort": Verdict(APPLIED, "the median's rows are bugs opened in H1")
        if h1
        else Verdict(UNCLEAR, "no H1 filter on the median's rows"),
        "open_bugs": Verdict(APPLIED, f"open bugs counted as not closed ({how})")
        if how in ("as_infinite", "placeholder")
        else Verdict(MISSED, how)
        if how
        else Verdict(UNCLEAR, "no successful summarize call behind the median"),
    }
    both = {adef[n] for n in alts} == {"h1_cohort", "open_bugs"}
    for d in ("h1_cohort", "open_bugs"):
        names = [n for n in alts if adef[n] == d]
        if med is not None and close(med, k, 0.005 * k):
            out[d] = Verdict(APPLIED, f"median {med:.3f} days equals the key {k:.3f}")
        elif names and both and queries[d].verdict == APPLIED:
            # The value fits two alternatives here; the queries say which one it was.
            out[d] = Verdict(APPLIED, f"{queries[d].evidence} (median {med:.3f} also fits '{names[0]}')")
        elif names:
            out[d] = Verdict(MISSED, f"median {med:.3f} days equals the key with '{names[0]}'")
        elif med is None and queries[d].verdict == APPLIED:
            out[d] = Verdict(UNCLEAR, f"{queries[d].evidence}, but no median given")
        else:
            out[d] = Verdict(
                queries[d].verdict,
                queries[d].evidence + ("" if med is None else f"; median {med:.3f} days, key {k:.3f}"),
            )
    return out
