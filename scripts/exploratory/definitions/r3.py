"""R3: median time from opening to first review, and from first review to merge.

Definitions the question uses:
- halves: PRs merged in H1 and H2, split by merge date
- bot_prs: PRs opened by bots are left out
- not_author: the first review is by someone other than the PR author
- review_states: any submitted review counts (the key also counts DISMISSED)
- before_merge: only reviews up to the merge count
- bot_reviewers: reviews by bots don't count
- first_review: only the first such review per PR counts
- no_review: PRs with no such review are left out of both medians
- median_test: the verdicts follow the shared bootstrap rule

The two wait medians and the two after medians are matched separately against
the key and the alternative keys. A part that equals an alternative names the
definition that went wrong, and the others were applied. The verdicts tell us
about median_test.

This module also holds helpers that r4, r9 and r11 use (pairs, drops,
exclusion_check, test_check).
"""

import json
import math
import re
from collections import defaultdict

from common import (
    APPLIED,
    BOT_WORDS,
    MISSED,
    OTHER_READING,
    UNCLEAR,
    WINDOW_END_DAY,
    Verdict,
    ck,
    fetch,
    leaf_filters,
    parse_args,
)

TEMPLATE = "R3"
DEFINITIONS = [
    "halves",
    "bot_prs",
    "not_author",
    "review_states",
    "before_merge",
    "bot_reviewers",
    "first_review",
    "no_review",
    "median_test",
]
VALUE_DEFS = DEFINITIONS[:-1]
PARTS = {"wait": ["wait_h1_hours", "wait_h2_hours"], "after": ["after_h1_hours", "after_h2_hours"]}
KEY_FIELDS = {
    "wait_h1_hours": "wait_h1_h",
    "wait_h2_hours": "wait_h2_h",
    "after_h1_hours": "after_h1_h",
    "after_h2_hours": "after_h2_h",
}
KEY = {
    "half_by": "merged",
    "end": ck.W1,
    "bot_prs": False,
    "self": False,
    "states": None,
    "after_merge": False,
    "bot_reviewers": False,
    "no_review_inf": False,
    "all_reviews": False,
}
LITERAL_STATES = {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}

# Each alternative switches off or changes one definition (one pair changes two,
# because two runs did both): name -> (definitions, settings that differ from the key).
ALTERNATIVES = {
    "split by opening date": (["halves"], {"half_by": "created"}),
    "last day left out": (["halves"], {"end": "2026-09-20"}),
    "bot PRs kept": (["bot_prs"], {"bot_prs": True}),
    "self reviews kept": (["not_author"], {"self": True}),
    # The question lists approved, commented or changes requested. Read literally,
    # DISMISSED reviews are out. The key counts every submitted review.
    "dismissed left out": (["review_states"], {"states": LITERAL_STATES}),
    "approvals only": (["review_states"], {"states": {"APPROVED"}}),
    "reviews after merge kept": (["before_merge"], {"after_merge": True}),
    "bot reviewers kept": (["bot_reviewers"], {"bot_reviewers": True}),
    "every review, not the first": (["first_review"], {"all_reviews": True}),
    "no-review PRs as infinite wait": (["no_review"], {"no_review_inf": True}),
    "dismissed left out, no-review PRs as infinite wait": (
        ["review_states", "no_review"],
        {"states": LITERAL_STATES, "no_review_inf": True},
    ),
}
# Readings the question's wording supports, which the key doesn't accept.
LITERAL = {"review_states": {"dismissed left out", "dismissed left out, no-review PRs as infinite wait"}}


# Helpers shared with r4, r9 and r11.


def pairs(t):
    """Each tool call with its parsed result: (tool, args, result or None)."""
    out, pending = [], []
    for s in t.run["steps"]:
        if s["step_type"] == "tool_call":
            pending.append(len(out))
            out.append([s.get("tool_name"), parse_args(s.get("tool_arguments")), None])
        elif s["step_type"] == "tool_result":
            i = next((i for i in pending if out[i][0] == s.get("tool_name")), None)
            if i is None:
                continue
            pending.remove(i)
            try:
                out[i][2] = json.loads(s.get("content") or "")
            except (json.JSONDecodeError, TypeError):
                out[i][2] = None
    return [tuple(x) for x in out]


def ok(res):
    return isinstance(res, dict) and "error" not in res


def pg_regex(p):
    """A Postgres regex as a Python one, close enough for login names."""
    p = re.sub(r"^\(\?i\)", "", str(p)).replace("\\m", r"\b").replace("\\M", r"\b")
    try:
        return re.compile(p, re.I)
    except re.error:
        return None


def drops(fs, login, column):
    """Would these exclusion filters on this column leave out this login?"""
    for f in fs:
        if not re.fullmatch(column, str(f.get("column"))):
            continue
        op, v = f.get("op"), f.get("value")
        if op == "ne" and str(v) == login:
            return True
        if op == "not_in" and isinstance(v, list) and login in map(str, v):
            return True
        if op == "not_matches" and (rx := pg_regex(v)) and rx.search(login):
            return True
    return False


def exclusion_check(calls, column, logins, what, others=()):
    """Did the calls behind the values leave out these logins?

    calls: the args of the calls behind the values. logins: the bots that appear in
    the data for this question. others: logins in the data that are not bots; if the
    agent's filters leave one of them out too, its bot rule was wider than the
    shared one. The best call counts, since agents often run a first look without
    filters. Returns applied, missed (naming the logins) or unclear."""
    if not calls:
        return Verdict(UNCLEAR, "no query behind the values to check")
    best = min(calls, key=lambda a: sum(not drops(list(leaf_filters(a)), b, column) for b in logins))
    fs = list(leaf_filters(best))
    kept = sorted(b for b in logins if not drops(fs, b, column))
    # Any call that also left out a non-bot login shows a wider bot rule.
    # Only filters that look like a bot rule count, not a filter on one person.
    rules = [f for a in calls for f in leaf_filters(a) if BOT_WORDS.search(json.dumps(f.get("value")))]
    extra = sorted({o for o in others for f in rules if drops([f], o, column)})
    if kept and len(kept) == len(logins):
        return Verdict(MISSED, f"no filter leaves out {what} ({', '.join(kept[:4])})")
    if kept:
        return Verdict(MISSED, f"its filters keep some {what}: {', '.join(kept[:4])}")
    if extra:
        return Verdict(
            MISSED,
            f"its filters also leave out {', '.join(extra[:3])}, which the shared rule doesn't call bots",
        )
    if not logins:
        return Verdict(APPLIED, f"no {what} in the data, so nothing to leave out")
    return Verdict(APPLIED, f"its filters leave out every {what} in the data")


def window_like(calls, columns, start):
    """Did the date filters on these columns cover start to the window end, as stated?"""
    columns = (columns,) if isinstance(columns, str) else columns
    fs = [f for a in calls for f in leaf_filters(a) if f.get("column") in columns]
    if not fs:
        return Verdict(UNCLEAR, f"no filter on {columns[0]}")
    starts = {str(f.get("value"))[:10] for f in fs if f.get("op") in ("gte", "gt")}
    ends = {(f.get("op"), str(f.get("value"))) for f in fs if f.get("op") in ("lt", "lte")}
    if ("lte", WINDOW_END_DAY) in ends:
        return Verdict(
            MISSED, f"lte {WINDOW_END_DAY} means 00:00 on the last day, so it leaves out the last day"
        )
    full_end = any(
        (op == "lt" and v.startswith(ck.W1)) or (op == "lte" and v.startswith(WINDOW_END_DAY + "T23:59"))
        for op, v in ends
    )
    late = sorted(v for op, v in ends if op == "lt" and v[:10] > ck.W1)
    if late:
        return Verdict(MISSED, f"{fs[0]['column']} filter ends at {late[0][:10]}, after the window ends")
    if start in starts and full_end:
        return Verdict(APPLIED, f"{fs[0]['column']} filter matches the question")
    if start != ck.W0 and ck.W0 in starts and start not in starts:
        return Verdict(MISSED, f"{fs[0]['column']} filter starts at the window start, not {start}")
    return Verdict(UNCLEAR, f"starts {sorted(starts)[:2]}, ends {sorted(ends)[:2]}")


def test_check(t, tool, given):
    """The agent's verdicts against the verdicts its own test calls returned.

    given: {field: verdict the agent gave}. If each one equals what a call of this
    tool returned on two halves with ten or more values each, it applied the rule
    to its own sample."""
    results = [(a, r) for n, a, r in pairs(t) if n == tool and ok(r)]
    if not results:
        return Verdict(MISSED, f"never ran {tool} successfully")
    bad = []
    for f, v in given.items():
        if v is None:
            continue
        hits = [r for _, r in results if str(r.get("verdict")).lower() == str(v).lower()]
        if not hits:
            bad.append(f"{f} {v} is not a verdict any {tool} call returned")
        elif str(v).lower() == "too few" and all(min(r.get("n_a", 0), r.get("n_b", 0)) <= 2 for r in hits):
            bad.append(f"{f} too few: it compared {hits[0].get('n_a')} against {hits[0].get('n_b')} values")
    if bad:
        return Verdict(MISSED, "; ".join(bad))
    return Verdict(APPLIED, f"verdicts come from its {tool} calls")


# R3 itself.


def half(ts, end):
    s = ts.strftime("%Y-%m-%d")
    if ck.W0 <= s < ck.H2_0:
        return "H1"
    if ck.H2_0 <= s < end:
        return "H2"
    return None


def medians(prs, reviews, s):
    """The four medians and two verdicts for one set of settings."""
    vals = {(h, p): [] for h in ("H1", "H2") for p in ("wait", "after")}
    for pr in prs:
        if pr["bot"] and not s["bot_prs"]:
            continue
        if half(pr["merged_at"], ck.W1) is None:
            continue
        h = half(pr[f"{s['half_by']}_at"], s["end"])
        if h is None:
            continue
        times = [
            v["submitted_at"]
            for v in reviews.get(pr["number"], [])
            if (s["self"] or v["reviewer"] != pr["author"])
            and (s["bot_reviewers"] or not v["bot"])
            and (s["states"] is None or v["state"] in s["states"])
            and (s["after_merge"] or v["submitted_at"] <= pr["merged_at"])
        ]
        if not times:
            if s["no_review_inf"]:
                vals[(h, "wait")].append(math.inf)
            continue
        for first in times if s["all_reviews"] else [min(times)]:
            vals[(h, "wait")].append((first - pr["created_at"]).total_seconds() / 3600)
            vals[(h, "after")].append((pr["merged_at"] - first).total_seconds() / 3600)
    # Bootstrap on infinite values breaks the ratio, so the infinite reading only
    # gives medians.
    finite = not s["no_review_inf"]
    return {
        "wait_h1_hours": ck.med(vals[("H1", "wait")]),
        "wait_h2_hours": ck.med(vals[("H2", "wait")]),
        "after_h1_hours": ck.med(vals[("H1", "after")]),
        "after_h2_hours": ck.med(vals[("H2", "after")]),
        "wait_verdict": ck.median_verdict(vals[("H1", "wait")], vals[("H2", "wait")]) if finite else None,
        "after_verdict": ck.median_verdict(vals[("H1", "after")], vals[("H2", "after")]),
    }


def prepare(conn, repos):
    prs = fetch(
        conn,
        f"""
        select r.name repo, p.number, p.author_login author, p.created_at, p.merged_at,
          coalesce({ck.bot("p.author_login")}, false) bot
        from pull_requests p join repos r on r.id = p.repo_id
        where p.merged_at >= '{ck.W0}' and p.merged_at < '{ck.W1}'""",
    )
    revs = fetch(
        conn,
        f"""
        select r.name repo, v.pr_number, v.reviewer_login reviewer, v.state, v.submitted_at,
          coalesce({ck.bot("v.reviewer_login")}, false) bot
        from pr_reviews v join repos r on r.id = v.repo_id
        where v.reviewer_login is not null""",
    )
    alt = {}
    for repo in repos:
        mine = [p for p in prs if p["repo"] == repo]
        numbers = {p["number"] for p in mine}
        reviews = defaultdict(list)
        for v in revs:
            if v["repo"] == repo:
                reviews[v["pr_number"]].append(v)
        alt[repo] = {name: medians(mine, reviews, KEY | s) for name, (_, s) in ALTERNATIVES.items()}
        alt[repo]["key (recomputed)"] = medians(mine, reviews, KEY)
        alt[repo]["bots"] = {
            "authors": sorted({p["author"] for p in mine if p["bot"]}),
            "reviewers": sorted({v["reviewer"] for n in numbers for v in reviews.get(n, []) if v["bot"]}),
        }
    return alt


def near(a, b):
    """Same median, allowing for two-decimal rounding and lt against lte."""
    return isinstance(a, (int, float)) and b is not None and abs(a - b) <= max(0.011, 0.005 * abs(b))


def used_ids(t, tools=("summarize", "compare_medians")):
    """Result ids the agent passed to its statistics tools."""
    return {
        rid
        for n, a, _ in pairs(t)
        if n in tools
        for rid in re.findall(r'"result_id": "(r\d+)"', json.dumps(a))
    }


def source_calls(t, tool, extra=None):
    """The successful calls of this tool whose results fed the statistics tools.
    If none did, the calls that pass the extra test."""
    ids = used_ids(t)
    calls = [(a, r) for n, a, r in pairs(t) if n == tool and ok(r)]
    fed = [a for a, r in calls if r.get("result_id") in ids]
    return fed if fed or not extra else [a for a, _ in calls if extra(a)]


def typed_lists(t, tool="compare_medians"):
    """Did the agent type values into a statistics tool by hand?"""
    return any(n == tool and isinstance(a.get("a"), list) and len(a["a"]) > 2 for n, a, _ in pairs(t))


def median_calls(t):
    """The review queries that built the durations: they fed summarize or
    compare_medians, or added an hours column."""
    return source_calls(t, "query_pr_reviews", lambda a: "hours_between" in json.dumps(a.get("add_columns")))


def has_pair(calls, cols, ops):
    """Does every call compare these two columns, like reviewer ne pr_author?"""
    return calls and all(
        any({f.get("column"), f.get("other_column")} == cols and f.get("op") in ops for f in leaf_filters(a))
        for a in calls
    )


def query_checks(t, bots):
    calls = median_calls(t)
    out = {}
    merged = [f for a in calls for f in leaf_filters(a) if f.get("column") == "pr_merged_at"]
    created = [f for a in calls for f in leaf_filters(a) if f.get("column") == "pr_created_at"]
    if any(str(f.get("value")).startswith(ck.H2_0) for f in merged):
        out["halves"] = Verdict(APPLIED, "halves split on the merge date")
    elif any(str(f.get("value")).startswith(ck.H2_0) for f in created):
        out["halves"] = Verdict(MISSED, "halves split on the opening date")
    else:
        out["halves"] = Verdict(UNCLEAR, "no half boundary in the duration queries")
    out["bot_prs"] = exclusion_check(calls, "pr_author", bots["authors"], "bot PR authors")
    if out["bot_prs"].verdict == MISSED and any(
        f.get("column") == "pr_number" and f.get("op") == "in" for a in calls for f in leaf_filters(a)
    ):
        out["bot_prs"] = Verdict(UNCLEAR, "it picked PRs by a list of numbers, which may leave bot PRs out")
    out["bot_reviewers"] = exclusion_check(calls, "reviewer", bots["reviewers"], "bot reviewers")
    if not calls:
        none = Verdict(UNCLEAR, "no duration query to check")
        if typed_lists(t):
            none = Verdict(UNCLEAR, "it typed values into compare_medians by hand from pages of rows")
        return out | {
            "not_author": none,
            "before_merge": none,
            "review_states": none,
            "first_review": none,
            "no_review": none,
        }
    if has_pair(calls, {"reviewer", "pr_author"}, ("ne",)):
        out["not_author"] = Verdict(APPLIED, "reviewer ne pr_author in the duration queries")
    else:
        out["not_author"] = Verdict(
            MISSED, "the duration queries keep self reviews (no reviewer ne pr_author)"
        )
    if has_pair(calls, {"submitted_at", "pr_merged_at"}, ("lt", "lte", "gt", "gte")):
        out["before_merge"] = Verdict(APPLIED, "submitted_at before pr_merged_at in the duration queries")
    else:
        out["before_merge"] = Verdict(MISSED, "the duration queries keep reviews after the merge")
    states = [f for a in calls for f in leaf_filters(a) if f.get("column") == "state"]
    if not states:
        out["review_states"] = Verdict(APPLIED, "no state filter, so every submitted review counts")
    elif any(f.get("op") == "eq" and f.get("value") == "APPROVED" for f in states):
        out["review_states"] = Verdict(MISSED, "only APPROVED reviews counted")
    elif any(f.get("op") == "in" and set(f.get("value") or []) == LITERAL_STATES for f in states):
        out["review_states"] = Verdict(
            UNCLEAR, "it left out DISMISSED, as the question's list reads (the key keeps them)"
        )
    else:
        out["review_states"] = Verdict(
            UNCLEAR, f"state filter {states[0].get('op')} {states[0].get('value')}"
        )
    if all(
        "pr_number" in json.dumps(a.get("first_per"))
        or ("pr_number" in (a.get("group_by") or []) and '"min"' in json.dumps(a.get("aggregates")))
        for a in calls
    ):
        out["first_review"] = Verdict(APPLIED, "first review per PR (first_per or min by pr_number)")
    else:
        out["first_review"] = Verdict(MISSED, "the duration queries use every review, not the first per PR")
    out["no_review"] = Verdict(UNCLEAR, "the values don't show how it treated PRs with no review")
    return out


def check(t, alt):
    out = {}
    got = {f: t.value(f) for f in KEY_FIELDS}
    key = {f: t.key[k] for f, k in KEY_FIELDS.items()}
    a = alt[t.repo]
    names = [n for n in ALTERNATIVES]

    # For each part, the key or the alternatives its two medians equal.
    part_match = {}
    for p, fs in PARTS.items():
        if all(near(got[f], key[f]) for f in fs):
            part_match[p] = "key"
        else:
            hits = [n for n in names if all(near(got[f], a[n][f]) for f in fs)]
            hits = [n for n in hits if not all(near(a[n][f], key[f]) for f in fs)]
            part_match[p] = hits[0] if hits else None
    shown = ", ".join(str(got[f]) for f in KEY_FIELDS)
    negative = any(isinstance(v, (int, float)) and v < 0 for v in got.values())
    q = query_checks(t, a["bots"])
    for d in VALUE_DEFS:
        blamed = [(p, n) for p, n in part_match.items() if n not in (None, "key") and d in ALTERNATIVES[n][0]]
        if blamed:
            p, n = blamed[0]
            v = OTHER_READING if n in LITERAL.get(d, set()) else MISSED
            out[d] = Verdict(
                v, f"{p} medians {', '.join(str(got[f]) for f in PARTS[p])} equal the key with '{n}'"
            )
        elif all(n == "key" for n in part_match.values()):
            out[d] = Verdict(APPLIED, "the four medians equal the key")
        elif all(n is not None for n in part_match.values()):
            out[d] = Verdict(
                APPLIED,
                f"each part equals the key or an alternative that changes another definition ({part_match})",
            )
        elif q[d].verdict == MISSED:
            out[d] = Verdict(
                MISSED, q[d].evidence + (" (negative medians: hours_between reversed)" if negative else "")
            )
        elif any(got[f] is None for f in KEY_FIELDS) and q[d].verdict != APPLIED:
            out[d] = Verdict(UNCLEAR, f"not every median given; {q[d].evidence}")
        else:
            out[d] = Verdict(
                q[d].verdict if q[d].verdict == APPLIED else UNCLEAR,
                f"medians {shown} match no alternative; {q[d].evidence}",
            )

    # median_test: the rule on the agent's own sample when we know it, otherwise
    # the verdicts its compare_medians calls returned.
    given = {v: t.value(v) for v in ("wait_verdict", "after_verdict")}
    refs = {"wait_verdict": part_match["wait"], "after_verdict": part_match["after"]}
    wrong, known = [], 0
    for v, n in refs.items():
        ref = t.key if n == "key" else a.get(n) if n else None
        if ref is None or ref.get(v) is None or given[v] is None:
            continue
        known += 1
        if given[v].lower() != ref[v]:
            wrong.append(f"{v} {given[v]}, the rule gives {ref[v]} on its sample")
    if wrong:
        out["median_test"] = Verdict(MISSED, "; ".join(wrong))
    elif known == 2:
        out["median_test"] = Verdict(APPLIED, "verdicts follow the rule on its own sample")
    else:
        out["median_test"] = test_check(t, "compare_medians", given)
    return out
