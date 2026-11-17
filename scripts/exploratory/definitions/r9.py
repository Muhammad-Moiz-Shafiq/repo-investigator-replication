"""R9: how many people reviewed PRs in H2, and what share of the review work the
two busiest reviewers did.

Definitions the question uses:
- h2_window: reviews submitted in H2, 2026-04-01 to 2026-09-20, by review date
- one_per_pr: one reviewer on one PR counts once, however many reviews they left
- bots: reviews by bots are left out
- self_reviews: authors reviewing their own PRs are left out
- share_base: the share is the top two's reviewer-PR pairs over all pairs

The reviewer count depends on the first three. It is matched against the key and
count variants (each switches one off, or two that agents did together); a match
names what went wrong, and the others were applied. The share, read on the
reviewer set the count came from, tells us about one_per_pr and share_base.
"""

import json
from collections import Counter

from common import (
    APPLIED,
    MISSED,
    UNCLEAR,
    Verdict,
    ck,
    fetch,
    leaf_filters,
)
from r3 import exclusion_check, ok, pairs, window_like

TEMPLATE = "R9"
DEFINITIONS = ["h2_window", "one_per_pr", "bots", "self_reviews", "share_base"]

KEY = {
    "date": "submitted",
    "end": ck.W1,
    "start": ck.H2_0,
    "per_pr": True,
    "bots": False,
    "self": False,
}
# The reviewer count depends on the first three definitions. Each count variant
# switches off or changes one of them (two pairs change two, because agents did
# both): name -> (definitions, settings that differ from the key).
COUNT_VARIANTS = {
    "key": ([], {}),
    "last day left out": (["h2_window"], {"end": "2026-09-20"}),
    "whole window": (["h2_window"], {"start": ck.W0}),
    "by PR merge date": (["h2_window"], {"date": "merged"}),
    "by PR opening date": (["h2_window"], {"date": "created"}),
    "bots kept": (["bots"], {"bots": True}),
    "self reviews kept": (["self_reviews"], {"self": True}),
    "bots and self reviews kept": (["bots", "self_reviews"], {"bots": True, "self": True}),
    "whole window, bots and self reviews kept": (
        ["h2_window", "bots", "self_reviews"],
        {"start": ck.W0, "bots": True, "self": True},
    ),
}
# The share, for a given count variant, read four ways: name -> (definition, base).
SHARE_VARIANTS = {
    "pairs": (None, "pairs"),  # the key: top two's reviewer-PR pairs over all pairs
    "every review counted": ("one_per_pr", "rows"),
    "pairs over review rows": ("one_per_pr", "mixed"),  # distinct PRs on top, every row below
    "share of PRs reviewed": ("share_base", "prs"),
}


def compute(rows, s):
    """Reviewer count, and the top two share (percent) read each way, for one set of settings."""
    pairs_, reviews = Counter(), Counter()
    prs, seen = {}, set()
    for r in rows:
        when = r[f"{s['date']}_at"]
        if when is None or not (s["start"] <= when.strftime("%Y-%m-%d") < s["end"]):
            continue
        if (r["bot"] and not s["bots"]) or (r["reviewer"] == r["author"] and not s["self"]):
            continue
        reviews[r["reviewer"]] += 1
        prs.setdefault(r["reviewer"], set()).add(r["pr"])
        if (r["reviewer"], r["pr"]) not in seen:
            seen.add((r["reviewer"], r["pr"]))
            pairs_[r["reviewer"]] += 1
    out = {"reviewers": len(pairs_)}
    if not pairs_:
        return out | {name: None for name in SHARE_VARIANTS}
    top = [name for name, _ in pairs_.most_common(2)]
    top_rows = [name for name, _ in reviews.most_common(2)]
    every = set().union(*prs.values())
    out["pairs"] = 100 * sum(pairs_[x] for x in top) / sum(pairs_.values())
    out["every review counted"] = 100 * sum(reviews[x] for x in top_rows) / sum(reviews.values())
    out["pairs over review rows"] = 100 * sum(pairs_[x] for x in top) / sum(reviews.values())
    out["share of PRs reviewed"] = 100 * len(set().union(*(prs[x] for x in top))) / len(every)
    return out


def prepare(conn, repos):
    rows = fetch(
        conn,
        f"""
        select r.name repo, v.pr_number pr, v.reviewer_login reviewer, p.author_login author,
          v.submitted_at, p.merged_at, p.created_at, coalesce({ck.bot("v.reviewer_login")}, false) bot
        from pr_reviews v join pull_requests p on p.repo_id = v.repo_id and p.number = v.pr_number
        join repos r on r.id = v.repo_id
        where v.reviewer_login is not null""",
    )
    alt = {}
    for repo in repos:
        mine = [r for r in rows if r["repo"] == repo]
        alt[repo] = {name: compute(mine, KEY | s) for name, (_, s) in COUNT_VARIANTS.items()}
        h2 = [r for r in mine if ck.H2_0 <= r["submitted_at"].strftime("%Y-%m-%d") < ck.W1]
        alt[repo]["logins"] = {
            "bots": sorted({r["reviewer"] for r in h2 if r["bot"]}),
            "others": sorted({r["reviewer"] for r in h2 if not r["bot"]}),
        }
    return alt


def query_checks(t, logins):
    calls = [a for n, a, r in pairs(t) if n == "query_pr_reviews" and ok(r)]
    # The calls that count reviewers: grouped by reviewer, or a distinct count of them.
    counting = [
        a
        for a in calls
        if "reviewer" in (a.get("group_by") or []) or "count_distinct" in json.dumps(a.get("aggregates"))
    ]
    out = {"h2_window": window_like(calls, "submitted_at", ck.H2_0)}
    if out["h2_window"].verdict == UNCLEAR:
        for col in ("pr_merged_at", "pr_created_at"):
            if any(
                f.get("column") == col and str(f.get("value")).startswith(ck.H2_0)
                for a in calls
                for f in leaf_filters(a)
            ):
                out["h2_window"] = Verdict(MISSED, f"H2 taken on {col}, not the review date")
    out["bots"] = exclusion_check(
        counting or calls, "reviewer", logins["bots"], "bot reviewers", logins["others"]
    )
    if any(
        {f.get("column"), f.get("other_column")} == {"reviewer", "pr_author"} and f.get("op") == "ne"
        for a in counting or calls
        for f in leaf_filters(a)
    ):
        out["self_reviews"] = Verdict(APPLIED, "reviewer ne pr_author")
    elif counting:
        out["self_reviews"] = Verdict(MISSED, "the queries that count reviewers keep self reviews")
    else:
        out["self_reviews"] = Verdict(UNCLEAR, "no counting query to check")
    distinct = [
        a
        for a in calls
        if "count_distinct" in json.dumps(a.get("aggregates"))
        or "pr_number" in json.dumps((a.get("first_per") or {}).get("columns"))
        or set(a.get("group_by") or []) >= {"reviewer", "pr_number"}
    ]
    if distinct:
        out["one_per_pr"] = Verdict(APPLIED, "count_distinct, first_per or group by reviewer and pr_number")
    elif counting or any("count" in json.dumps(a.get("aggregates")) for a in calls):
        out["one_per_pr"] = Verdict(MISSED, "it counted review rows, not distinct PRs per reviewer")
    else:
        out["one_per_pr"] = Verdict(UNCLEAR, "no counting query to check")
    out["share_base"] = Verdict(UNCLEAR, "the queries don't show what the share was taken over")
    return out


def near(a, b, tol=0.011):
    return isinstance(a, (int, float)) and b is not None and abs(a - b) <= tol


def check(t, alt):
    out = {}
    n, share = t.value("reviewers"), t.value("top2_pct")
    a = alt[t.repo]
    key_n = a["key"]["reviewers"]
    q = query_checks(t, a["logins"])

    # The count: the key, or the first count variant it equals (fewest changes first).
    cv = None
    if n is not None:
        cv = (
            "key"
            if n == key_n
            else next(
                (
                    name
                    for name in COUNT_VARIANTS
                    if a[name]["reviewers"] == n and a[name]["reviewers"] != key_n
                ),
                None,
            )
        )
    for d in ["h2_window", "bots", "self_reviews"]:
        if cv is not None and d in COUNT_VARIANTS[cv][0]:
            out[d] = Verdict(MISSED, f"reviewer count {n} equals the key with '{cv}'")
        elif q[d].verdict == MISSED and (cv != "key" or d != "self_reviews"):
            out[d] = q[d]
        elif cv == "key":
            out[d] = Verdict(APPLIED, f"reviewer count {n} equals the key")
        elif cv is not None:
            out[d] = Verdict(APPLIED, f"reviewer count {n} equals the key with only '{cv}' changed")
        elif n is None:
            out[d] = Verdict(UNCLEAR, "no reviewer count given")
        else:
            out[d] = Verdict(
                q[d].verdict if q[d].verdict == APPLIED else UNCLEAR,
                f"reviewer count {n} (key {key_n}) matches no variant; {q[d].evidence}",
            )

    # The share, read against the count variant the agent's count came from.
    ref = a[cv] if cv else None
    hit = next((name for name in SHARE_VARIANTS if ref and near(share, ref[name])), None)
    for d in ["one_per_pr", "share_base"]:
        if share is not None and share > 100 and d == "share_base":
            out[d] = Verdict(MISSED, f"share {share}% is over 100%")
        elif hit == "pairs":
            out[d] = Verdict(APPLIED, f"share {share}% is right for its reviewer set")
        elif hit and SHARE_VARIANTS[hit][0] == d:
            out[d] = Verdict(MISSED, f"share {share}% equals '{hit}' on its reviewer set")
        elif hit:
            out[d] = Verdict(APPLIED, f"share {share}% equals '{hit}', which changes the other definition")
        elif q[d].verdict == MISSED:
            out[d] = q[d]
        elif share is None:
            out[d] = Verdict(UNCLEAR, "no share given")
        else:
            out[d] = Verdict(
                q[d].verdict if q[d].verdict == APPLIED else UNCLEAR,
                f"share {share}% matches no reading on its set ({cv or 'unknown'}); {q[d].evidence}",
            )
    return out
