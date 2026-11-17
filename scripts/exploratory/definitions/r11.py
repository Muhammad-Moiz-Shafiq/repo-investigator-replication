"""R11: dependency bot PRs opened in the window, the shares merged and closed
unmerged, and the median time to merge in H1 and H2.

Definitions the question uses:
- dep_bots: PRs by the logins renovate and dependabot, no other bots
- opened_window: PRs opened from 2025-10-01 to 2026-09-20
- outcome_shares: merged, or closed without merge, by the window end, over opened
- merge_halves: medians over bot PRs merged in H1 and H2, split by merge date,
  whenever they were opened
- median_test: the verdict follows the shared bootstrap rule

The opened count tells us about dep_bots and opened_window, the shares about
outcome_shares, and the medians about merge_halves (and dep_bots). A value that
equals an alternative key names the definition that went wrong.
"""

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
    pct,
)
from r3 import ok, pairs, test_check, window_like

TEMPLATE = "R11"
DEFINITIONS = ["dep_bots", "opened_window", "outcome_shares", "merge_halves", "median_test"]
FIELDS = {
    "opened": ["opened"],
    "shares": ["merged_pct", "closed_unmerged_pct"],
    "medians": ["merge_h1_hours", "merge_h2_hours"],
}

ALL_BOTS = f"coalesce({ck.bot('p.author_login')}, false)"
DEP = f"p.author_login in {ck.DEP_BOTS}"
KEY = {"who": DEP, "end": ck.W1, "only_opened": False, "half_by": "merged_at", "no_cut": False}
# Each alternative switches off or changes one definition: name -> (definition, settings).
ALTERNATIVES = {
    "every bot counted": ("dep_bots", {"who": ALL_BOTS}),
    "last day left out": ("opened_window", {"end": "2026-09-20"}),
    "outcomes after the window counted": ("outcome_shares", {"no_cut": True}),
    "only PRs opened in the window": ("merge_halves", {"only_opened": True}),
    "split by opening date": ("merge_halves", {"half_by": "created_at"}),
}

# Readings the question's wording supports, which the key doesn't accept.
LITERAL = {
    "outcomes after the window counted": "the question doesn't say outcomes are cut at the window end; "
    "the closed share is not graded",
}


def compute(prs, s):
    opened = [p for p in prs if p[s["who"]] and ck.W0 <= p["created_at"].strftime("%Y-%m-%d") < s["end"]]

    def done(ts):
        return ts is not None and (s["no_cut"] or ts.strftime("%Y-%m-%d") < ck.W1)

    merged = sum(done(p["merged_at"]) for p in opened)
    closed = sum(p["merged_at"] is None and done(p["closed_at"]) for p in opened)
    pool = opened if s["only_opened"] else [p for p in prs if p[s["who"]]]
    halves = {"H1": [], "H2": []}
    for p in pool:
        if p["merged_at"] is None or not (ck.W0 <= p["merged_at"].strftime("%Y-%m-%d") < s["end"]):
            continue
        d = p[s["half_by"]].strftime("%Y-%m-%d")
        h = "H1" if ck.W0 <= d < ck.H2_0 else "H2" if ck.H2_0 <= d < s["end"] else None
        if h:
            halves[h].append((p["merged_at"] - p["created_at"]).total_seconds() / 3600)
    n = len(opened)
    return {
        "opened": n,
        "merged_pct": 100 * merged / n if n else None,
        "closed_unmerged_pct": 100 * closed / n if n else None,
        "merge_h1_hours": ck.med(halves["H1"]),
        "merge_h2_hours": ck.med(halves["H2"]),
        "merge_verdict": ck.median_verdict(halves["H1"], halves["H2"]),
    }


def prepare(conn, repos):
    prs = fetch(
        conn,
        f"""
        select r.name repo, p.number, p.created_at, p.merged_at, p.closed_at,
          {DEP} dep, {ALL_BOTS} anybot
        from pull_requests p join repos r on r.id = p.repo_id
        where {ALL_BOTS}""",
    )
    for p in prs:
        p[DEP], p[ALL_BOTS] = p["dep"], p["anybot"]
    alt = {}
    for repo in repos:
        mine = [p for p in prs if p["repo"] == repo]
        alt[repo] = {name: compute(mine, KEY | s) for name, (_, s) in ALTERNATIVES.items()}
        alt[repo]["key (recomputed)"] = compute(mine, KEY)
    return alt


def near(a, b, rel=0.005, tol=0.011):
    return isinstance(a, (int, float)) and b is not None and abs(a - b) <= max(tol, rel * abs(b))


def query_checks(t):
    calls = [a for n, a, r in pairs(t) if n == "query_pull_requests" and ok(r)]
    out = {"opened_window": window_like(calls, "created_at", ck.W0)}
    authors = [f for a in calls for f in leaf_filters(a) if f.get("column") == "author"]
    wide = [f for f in authors if f.get("op") in ("matches",) and "bot" in str(f.get("value")).lower()]
    if any(
        f.get("op") in ("in", "eq") and set(_as_list(f.get("value"))) <= {"renovate", "dependabot"}
        for f in authors
    ):
        out["dep_bots"] = Verdict(APPLIED, "author in renovate, dependabot")
    elif wide:
        out["dep_bots"] = Verdict(
            MISSED, f"author matches {wide[0].get('value')}, which takes other bots too"
        )
    else:
        out["dep_bots"] = Verdict(UNCLEAR, "no author filter naming the two bots")
    merged = window_like(calls, "merged_at", ck.W0)
    out["merge_halves"] = (
        merged
        if merged.verdict == MISSED
        else Verdict(
            merged.verdict,
            "medians from merge date filters" if merged.verdict == APPLIED else merged.evidence,
        )
    )
    out["outcome_shares"] = Verdict(UNCLEAR, "the queries don't show the outcome cut-off")
    return out


def _as_list(v):
    return v if isinstance(v, list) else [v]


def check(t, alt):
    out = {}
    a = alt[t.repo]
    got = {
        f: t.value(f)
        for f in ["opened", "merged_pct", "closed_unmerged_pct", "merge_h1_hours", "merge_h2_hours"]
    }
    key = {
        "opened": t.key["opened"],
        "merged_pct": pct(t.key["merged_share"]),
        "closed_unmerged_pct": pct(t.key["closed_unmerged_share"]),
        "merge_h1_hours": t.key["merge_h1_h"],
        "merge_h2_hours": t.key["merge_h2_h"],
    }
    q = query_checks(t)

    def match(fields):
        """The key, or the first alternative these fields equal (and the key doesn't)."""
        if all(near(got[f], key[f]) if f != "opened" else got[f] == key[f] for f in fields):
            return "key"
        for name in ALTERNATIVES:
            ref = a[name]
            same = all((got[f] == ref[f]) if f == "opened" else near(got[f], ref[f]) for f in fields)
            if same and not all(near(ref[f], key[f]) for f in fields):
                return name
        return None

    parts = {p: match(fs) for p, fs in FIELDS.items()}
    uses = {
        "dep_bots": ["opened", "medians"],
        "opened_window": ["opened"],
        "outcome_shares": ["shares"],
        "merge_halves": ["medians"],
    }
    for d, ps in uses.items():
        # Only the parts the agent gave a value for.
        ps = [p for p in ps if all(got[f] is not None for f in FIELDS[p])] or ps
        blamed = [
            (p, parts[p]) for p in ps if parts[p] not in (None, "key") and ALTERNATIVES[parts[p]][0] == d
        ]
        if blamed:
            p, n = blamed[0]
            if n in LITERAL:
                out[d] = Verdict(OTHER_READING, f"{p} equal the key with '{n}' ({LITERAL[n]})")
            else:
                out[d] = Verdict(MISSED, f"{p} equal the key with '{n}'")
        elif all(parts[p] is not None for p in ps):
            out[d] = Verdict(APPLIED, f"{' and '.join(ps)} equal the key ({', '.join(parts[p] for p in ps)})")
        elif q.get(d) and q[d].verdict == MISSED:
            out[d] = q[d]
        elif any(got[f] is None for p in ps for f in FIELDS[p]):
            out[d] = Verdict(UNCLEAR, "value not given")
        else:
            shown = {p: parts[p] for p in ps}
            out[d] = Verdict(
                q[d].verdict if d in q and q[d].verdict == APPLIED else UNCLEAR,
                f"no match for {shown}; {q[d].evidence if d in q else ''}",
            )
    if parts["shares"] is None and close(got["merged_pct"], key["merged_pct"] / 100, 0.0002):
        out["outcome_shares"] = Verdict(
            MISSED, f"merged share {got['merged_pct']} is a fraction, not a percent"
        )

    # median_test: the rule on its own sample when we know it, else its compare_medians calls.
    given = t.value("merge_verdict")
    ref = t.key if parts["medians"] == "key" else a.get(parts["medians"] or "", None)
    if given is None:
        out["median_test"] = Verdict(UNCLEAR, "no verdict given")
    elif ref is not None:
        right = ref["merge_verdict"]
        out["median_test"] = (
            Verdict(APPLIED, "verdict follows the rule on its own sample")
            if given.lower() == right
            else Verdict(MISSED, f"verdict {given}, the rule gives {right} on its sample")
        )
    else:
        out["median_test"] = test_check(t, "compare_medians", {"merge_verdict": given})
    return out
