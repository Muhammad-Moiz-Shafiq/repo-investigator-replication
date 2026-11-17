"""R4: how many PRs merged in H2 had no approval before the merge, and how many of
those bots opened.

Definitions the question uses:
- h2_merged: PRs merged in H2, 2026-04-01 to 2026-09-20, by merge date
- approval_state: only APPROVED reviews are approvals
- not_author: the approval is from someone other than the PR author
- before_merge: the approval was submitted before the merge
- bot_approvals: approvals by bots don't count
- bot_prs: the second count uses the shared bot rule on the PR author

The unapproved count tells us about the first five: if it equals the key, they
were all applied. If it equals an alternative key, that names the one that went
wrong. The bot count, given the right unapproved set, tells us about bot_prs.
"""

import json

from common import (
    APPLIED,
    MISSED,
    UNCLEAR,
    Verdict,
    ck,
    fetch,
    leaf_filters,
)
from r3 import exclusion_check, ok, pairs

TEMPLATE = "R4"
DEFINITIONS = ["h2_merged", "approval_state", "not_author", "before_merge", "bot_approvals", "bot_prs"]
COUNT_DEFS = DEFINITIONS[:-1]

BOT_REVIEWER = ck.bot("v.reviewer_login")
KEY_APPROVAL = {
    "state": "v.state = 'APPROVED'",
    "self": "v.reviewer_login is distinct from p.author_login",
    "bots": f"not {BOT_REVIEWER}",
    "time": "v.submitted_at <= p.merged_at",
}
KEY_MERGED = f"p.merged_at >= '{ck.H2_0}' and p.merged_at < '{ck.W1}'"

# Each alternative switches off or changes one definition:
# name -> (definition, merged window, approval parts that differ from the key).
ALTERNATIVES = {
    "last day left out": ("h2_merged", f"p.merged_at >= '{ck.H2_0}' and p.merged_at < '2026-09-20'", {}),
    "whole window": ("h2_merged", f"p.merged_at >= '{ck.W0}' and p.merged_at < '{ck.W1}'", {}),
    "any review counts": ("approval_state", KEY_MERGED, {"state": "true"}),
    "dismissed counts too": ("approval_state", KEY_MERGED, {"state": "v.state in ('APPROVED', 'DISMISSED')"}),
    "self approvals count": ("not_author", KEY_MERGED, {"self": "true"}),
    "approvals after merge count": ("before_merge", KEY_MERGED, {"time": "true"}),
    "bot approvals count": ("bot_approvals", KEY_MERGED, {"bots": "true"}),
}
# Other bot rules for the second count, on the key's unapproved set.
BOT_RULES = {
    "renovate and dependabot only": "p.author_login in ('renovate', 'dependabot')",
}


def prepare(conn, repos):
    alt = {repo: {"unapproved": {}, "bot_prs": {}, "bots": {}} for repo in repos}
    runs = {"key (recomputed)": ("", KEY_MERGED, {})} | ALTERNATIVES
    for name, (_, merged, parts) in runs.items():
        for repo in repos:  # a repo with no row has a count of 0
            alt[repo]["unapproved"][name] = alt[repo]["bot_prs"][name] = 0
        cond = " and ".join((KEY_APPROVAL | parts).values())
        rows = fetch(
            conn,
            f"""
            select r.name repo, count(*) n,
              count(*) filter (where coalesce({ck.bot("p.author_login")}, false)) bots
            from pull_requests p join repos r on r.id = p.repo_id
            where {merged} and not exists (
              select 1 from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
                and v.reviewer_login is not null and {cond})
            group by 1""",
        )
        for r in rows:
            if r["repo"] in alt:
                alt[r["repo"]]["unapproved"][name] = r["n"]
                alt[r["repo"]]["bot_prs"][name] = r["bots"]
    cond = " and ".join(KEY_APPROVAL.values())
    for name, rule in BOT_RULES.items():
        rows = fetch(
            conn,
            f"""
            select r.name repo, count(*) filter (where {rule}) n
            from pull_requests p join repos r on r.id = p.repo_id
            where {KEY_MERGED} and not exists (
              select 1 from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
                and v.reviewer_login is not null and {cond})
            group by 1""",
        )
        for r in rows:
            if r["repo"] in alt:
                alt[r["repo"]]["bot_prs"][name] = r["n"]
    # The bot logins in play: bot reviewers who approved H2 PRs, and bot PR authors.
    for col, what, extra in [
        ("v.reviewer_login", "reviewers", "and v.state = 'APPROVED'"),
        ("p.author_login", "authors", ""),
    ]:
        rows = fetch(
            conn,
            f"""
            select distinct r.name repo, {col} login
            from pull_requests p join repos r on r.id = p.repo_id
            left join pr_reviews v on v.repo_id = p.repo_id and v.pr_number = p.number {extra}
            where {KEY_MERGED} and coalesce({ck.bot(col)}, false)""",
        )
        for r in rows:
            if r["repo"] in alt:
                alt[r["repo"]]["bots"].setdefault(what, []).append(r["login"])
    return alt


def window_on(calls, columns):
    """The H2 filter on the merge date, as the agent wrote it."""
    fs = [f for a in calls for f in leaf_filters(a) if f.get("column") in columns]
    starts = {str(f.get("value"))[:10] for f in fs if f.get("op") in ("gte", "gt")}
    ends = {(f.get("op"), str(f.get("value"))) for f in fs if f.get("op") in ("lt", "lte")}
    if not fs:
        return Verdict(UNCLEAR, "no filter on the merge date")
    if ck.H2_0 in starts and any(op == "lte" and v.startswith("2026-09-20T23:59") for op, v in ends):
        return Verdict(APPLIED, "merge date filter matches H2 (to 23:59 on the last day)")
    if ("lte", "2026-09-20") in ends:
        return Verdict(MISSED, "lte 2026-09-20 means 00:00 on the last day, so it leaves out the last day")
    if ck.H2_0 in starts and any(op == "lt" and v.startswith("2026-09-21") for op, v in ends):
        return Verdict(APPLIED, "merge date filter matches H2")
    if ck.W0 in starts and ck.H2_0 not in starts:
        return Verdict(MISSED, "merge date filter covers the whole window, not H2")
    return Verdict(UNCLEAR, f"merge date starts {sorted(starts)[:2]}, ends {sorted(ends)[:2]}")


def query_checks(t, bots):
    calls = [(n, a) for n, a, r in pairs(t) if n in ("query_pr_reviews", "query_pull_requests") and ok(r)]
    reviews = [a for n, a in calls if n == "query_pr_reviews"]
    out = {"h2_merged": window_on([a for _, a in calls], ("merged_at", "pr_merged_at"))}
    fs = [f for a in reviews for f in leaf_filters(a)]
    states = [f for f in fs if f.get("column") == "state"]
    if any(f.get("op") == "eq" and f.get("value") == "APPROVED" for f in states) or any(
        f.get("op") == "in" and f.get("value") == ["APPROVED"] for f in states
    ):
        out["approval_state"] = Verdict(APPLIED, "state eq APPROVED")
    elif states:
        out["approval_state"] = Verdict(
            UNCLEAR, f"state filter {states[0].get('op')} {states[0].get('value')}"
        )
    else:
        # Without a state filter it may still have read the states row by row.
        out["approval_state"] = Verdict(UNCLEAR, "no filter on state; it may have read the states row by row")
    pair = [f for f in fs if {f.get("column"), f.get("other_column")} == {"reviewer", "pr_author"}]
    out["not_author"] = (
        Verdict(APPLIED, "reviewer ne pr_author")
        if pair
        else Verdict(UNCLEAR, "no reviewer ne pr_author filter")
    )
    pair = [f for f in fs if {f.get("column"), f.get("other_column")} == {"submitted_at", "pr_merged_at"}]
    out["before_merge"] = (
        Verdict(APPLIED, "submitted_at compared with pr_merged_at")
        if pair
        else Verdict(UNCLEAR, "no submitted_at before pr_merged_at filter")
    )
    approvals = [a for a in reviews if "APPROVED" in json.dumps(a.get("filters"))]
    out["bot_approvals"] = exclusion_check(approvals, "reviewer", bots.get("reviewers", []), "bot approvers")
    return out


def listed_prs(t):
    """PR numbers the agent picked by hand with pr_number in [...]."""
    return {
        v
        for _, a, r in pairs(t)
        if ok(r)
        for f in leaf_filters(a)
        if f.get("column") == "pr_number" and f.get("op") == "in" and isinstance(f.get("value"), list)
        for v in f["value"]
    }


def check(t, alt):
    out = {}
    n, key_n = t.value("unapproved"), t.key["unapproved"]
    b, key_b = t.value("unapproved_bot_prs"), t.key["unapproved_bot_prs"]
    a = alt[t.repo]
    count_right = n == key_n
    # A count of 0 matches too easily (a failed query also gives 0), so it doesn't count as a match.
    matched = [
        name
        for name, v in a["unapproved"].items()
        if v == n and n != 0 and v != key_n and name != "key (recomputed)"
    ]
    prs = [r for name, _, r in pairs(t) if name == "query_pull_requests" and ok(r)]
    empty = bool(prs) and all(r.get("total") == 0 for r in prs)
    q = query_checks(t, a["bots"])
    listed = listed_prs(t)
    page = listed and len(listed) < t.key["merged_h2"] / 2 and n is not None and n <= len(listed)
    harmless = a["unapproved"]["last day left out"] == key_n
    for d in COUNT_DEFS:
        names = [m for m in matched if ALTERNATIVES[m][0] == d]
        if names:
            out[d] = Verdict(MISSED, f"unapproved count {n} equals the key with '{names[0]}'")
        elif q[d].verdict == MISSED:
            note = (
                " (no effect here: no H2 PR was merged on the last day)"
                if d == "h2_merged" and harmless
                else ""
            )
            out[d] = Verdict(MISSED, q[d].evidence + note)
        elif count_right:
            out[d] = Verdict(APPLIED, f"unapproved count {n} equals the key")
        elif matched:
            out[d] = Verdict(APPLIED, f"unapproved count {n} equals the key with only '{matched[0]}' changed")
        elif empty:
            out[d] = Verdict(UNCLEAR, "its PR queries returned no rows, so it reported 0")
        elif n is None:
            out[d] = Verdict(UNCLEAR, "no unapproved count given")
        elif page:
            out[d] = Verdict(
                UNCLEAR,
                f"it checked only {len(listed)} of {t.key['merged_h2']} merged PRs (one page of rows)",
            )
        else:
            out[d] = Verdict(
                q[d].verdict if q[d].verdict == APPLIED else UNCLEAR,
                f"unapproved count {n}, key {key_n}; {q[d].evidence}",
            )

    # bot_prs: judge the bot count against the set the agent's unapproved count came from.
    ref = matched[0] if matched else "key (recomputed)" if count_right else None
    rules = [name for name in BOT_RULES if a["bot_prs"].get(name) == b and b != key_b]
    if b is None:
        out["bot_prs"] = Verdict(UNCLEAR, "no bot count given")
    elif ref and b == a["bot_prs"][ref]:
        out["bot_prs"] = Verdict(APPLIED, f"bot count {b} is right for its unapproved set")
    elif count_right and rules:
        out["bot_prs"] = Verdict(MISSED, f"bot count {b} equals the key with '{rules[0]}'")
    elif ref:
        out["bot_prs"] = Verdict(
            MISSED, f"bot count {b}, but its unapproved set has {a['bot_prs'][ref]} bot PRs"
        )
    elif n is not None and b > n:
        out["bot_prs"] = Verdict(MISSED, f"bot count {b} is larger than its unapproved count {n}")
    else:
        out["bot_prs"] = Verdict(UNCLEAR, f"bot count {b}, key {key_b}, and the unapproved count is off too")
    return out
