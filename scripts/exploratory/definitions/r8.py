"""R8: what share of human non-merge commits came from the two most active people
in H1 and in H2, and did the work become more or less concentrated.

Definitions the question uses:
- window: H1 is 2025-10-01 to 2026-03-31 and H2 is 2026-04-01 to 2026-09-20, both inclusive
- merges: merge commits are left out
- bots: commits by bot logins are left out, and an empty login is not a bot
- automation: eslint's two automation emails (with no login) are left out
- person: a commit's person is its login, or its email when there is no login
- top_two: the two most active people in each half, picked per half
- denominator: the share is out of human non-merge commits in that half
- verdict_test: Fisher test, p < 0.05 and a change of at least 5 points

The two shares are given with two decimals, so an exact match with an alternative
key is strong evidence. Agents often make two mistakes at once (for example the
top two of the whole window and a last day left out), so the alternatives are
single switches and pairs of switches. For each half, the smallest set of
switches that gives the agent's share names the definitions that went wrong. A
switch is not used when the queries show that definition was applied.

This module also holds helpers that r6.py and r12.py use: pairing calls with
their results, and checking an agent's filters on probe rows.
"""

import json
import re
import warnings
from collections import Counter
from itertools import combinations

from common import (
    APPLIED,
    MISSED,
    UNCLEAR,
    Verdict,
    ck,
    fetch,
    parse_args,
)

TEMPLATE = "R8"
DEFINITIONS = ["window", "merges", "bots", "automation", "person", "top_two", "denominator", "verdict_test"]

COMMIT_TOOLS = ("query_commits", "query_commit_files")
PERSON_COLUMNS = {"author", "author_email", "commit_author", "commit_author_email"}


# Helpers shared with r6.py and r12.py.


def call_results(t):
    """(tool, args, result) for every call. result is None when the call failed."""
    out, pending = [], []
    for s in t.run["steps"]:
        if s["step_type"] == "tool_call":
            pending.append((s.get("tool_name"), parse_args(s.get("tool_arguments"))))
        elif s["step_type"] == "tool_result" and pending:
            name, args = pending.pop(0)
            try:
                res = json.loads(s["content"]) if isinstance(s["content"], str) else s["content"]
            except (json.JSONDecodeError, TypeError):
                res = None
            if not isinstance(res, dict) or "error" in res:
                res = None
            out.append((name, args, res))
    return out


def ok_calls(t, tools=COMMIT_TOOLS):
    """Successful calls to these tools, as (tool, args, result)."""
    return [(n, a, r) for n, a, r in call_results(t) if n in tools and r is not None]


def _rx(p):
    # Postgres word boundaries (\y, \m, \M) as Python's \b. The tool matches ignore case.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        return re.compile(re.sub(r"\\[ymM]", r"\\b", str(p)), re.I)


def _and(a, b):
    return False if a is False or b is False else None if a is None or b is None else True


def _or(values):
    return True if True in values else None if None in values else False


def _leaf(f, row):
    """One filter on one row, with SQL null logic. Columns not in the row pass."""
    col, op = f.get("column"), f.get("op")
    if col not in row:
        return True
    v, val = row[col], f.get("value")
    if op == "is_null":
        return v is None
    if op == "not_null":
        return v is not None
    if v is None:
        return None
    if op in ("eq", "ne"):
        same = str(v).lower() == str(val).lower() if isinstance(v, bool) else str(v) == str(val)
        return same if op == "eq" else not same
    if op in ("in", "not_in"):
        inside = str(v) in [str(x) for x in (val or [])]
        return inside if op == "in" else not inside
    if op in ("matches", "not_matches"):
        try:
            hit = bool(_rx(val).search(str(v)))
        except re.error:
            return True
        return hit if op == "matches" else not hit
    return True


def passes(filters, row):
    """Does the row pass this filter list (True), fail it (False) or give null (None)?"""
    if isinstance(filters, dict):
        filters = [filters]
    res = True
    for f in filters or []:
        if isinstance(f, dict) and set(f) == {"any_of"}:
            groups = f["any_of"] if isinstance(f["any_of"], list) else []
            r = _or([passes(g if isinstance(g, list) else [g], row) for g in groups])
        elif isinstance(f, dict):
            r = _leaf(f, row)
        else:
            r = True
        res = _and(res, r)
    return res


def kept(args, row):
    """Is the row kept by the call's row filters? post_filters run after grouping, so
    they only count when nothing was grouped."""
    fs = list(args.get("filters") or []) if isinstance(args.get("filters"), list) else [args.get("filters")]
    if not args.get("group_by") and not args.get("aggregates"):
        post = args.get("post_filters") or []
        fs += post if isinstance(post, list) else [post]
    return passes([f for f in fs if f], row) is True


def person_row(login, email="dev@example.com"):
    return {"author": login, "commit_author": login, "author_email": email, "commit_author_email": email}


def merge_row(merge):
    return {"is_merge": merge, "commit_is_merge": merge}


def population_calls(t, tools=COMMIT_TOOLS):
    """The successful calls that build the commit sets the answer counts: grouped or
    counted queries, or queries a calculator reads. If there are none, every successful
    query with a date filter."""
    calls = call_results(t)
    used = set()
    for name, args, _ in calls:
        if name not in tools:
            used |= set(re.findall(r'"result_id": "(r\d+)"', json.dumps(args)))
    good = [(n, a, r) for n, a, r in calls if n in tools and r is not None]
    pop = [
        (n, a, r)
        for n, a, r in good
        if a.get("group_by") or a.get("aggregates") or r.get("result_id") in used
    ]
    return pop or [(n, a, r) for n, a, r in good if "committed_at" in json.dumps(a.get("filters"))]


def bot_probe(t, bots, tools=COMMIT_TOOLS):
    """Which of the repo's real bot logins, and which human probes, the population
    calls keep. Returns (verdict for bots, verdict for empty logins)."""
    pop = population_calls(t, tools)
    if not pop:
        return Verdict(UNCLEAR, "no successful commit queries"), Verdict(
            UNCLEAR, "no successful commit queries"
        )
    kept_bots = sorted({b for b in bots for _, a, _ in pop if kept(a, person_row(b))})
    all_out = all(not kept(a, person_row(b)) for b in bots for _, a, _ in pop)
    empty_out = [a for _, a, _ in pop if not kept(a, person_row(None))]
    if not bots:
        bot_v = Verdict(UNCLEAR, "no bot commits in this repo's window")
    elif all_out:
        bot_v = Verdict(APPLIED, "every counting query leaves out all of the repo's bot logins")
    elif len(kept_bots) == len(bots) and all(kept(a, person_row(b)) for b in bots for _, a, _ in pop):
        bot_v = Verdict(MISSED, f"the counting queries keep every bot login ({', '.join(kept_bots[:3])})")
    else:
        bot_v = Verdict(UNCLEAR, f"some counting queries keep bot logins {', '.join(kept_bots[:3])}")
    if not empty_out:
        empty_v = Verdict(APPLIED, "commits with no login are kept")
    elif len(empty_out) == len(pop):
        empty_v = Verdict(
            MISSED, "its author filter also drops every commit with no login (an empty login is not a bot)"
        )
    else:
        empty_v = Verdict(UNCLEAR, "some counting queries drop commits with no login")
    return bot_v, empty_v


def merge_probe(t, tools=COMMIT_TOOLS):
    pop = population_calls(t, tools)
    if not pop:
        return Verdict(UNCLEAR, "no successful commit queries")
    keeps = [kept(a, merge_row(True)) for _, a, _ in pop]
    if not any(keeps):
        return Verdict(APPLIED, "every counting query leaves out merge commits")
    if all(keeps):
        return Verdict(MISSED, "no counting query leaves out merge commits")
    return Verdict(UNCLEAR, "some counting queries keep merge commits")


def automation_probe(t, tools=COMMIT_TOOLS):
    pop = population_calls(t, tools)
    rows = [person_row(None, e) for e in ("jenkins@eslint-03", "eslint@googlegroups.com")]
    if not pop:
        return Verdict(UNCLEAR, "no successful commit queries")
    if all(not kept(a, r) for _, a, _ in pop for r in rows):
        return Verdict(APPLIED, "the counting queries leave out the two automation emails")
    if all(kept(a, r) for _, a, _ in pop for r in rows):
        return Verdict(MISSED, "the counting queries keep the two automation emails")
    return Verdict(UNCLEAR, "some counting queries keep the automation emails")


def automation_check(t, tools=COMMIT_TOOLS):
    """The automation emails only exist in eslint. Elsewhere they make no difference,
    so only a query that leaves them out counts."""
    v = automation_probe(t, tools)
    if t.repo == "eslint" or v.verdict == APPLIED:
        return v
    return Verdict(UNCLEAR, "no automation commits in this repo, so it makes no difference")


def date_ends(t, tools=COMMIT_TOOLS):
    """(op, value) of every date filter on committed_at in successful calls."""
    out = set()
    for _, args, _ in ok_calls(t, tools):
        for f in _leaves(args):
            if re.fullmatch("committed_at", str(f.get("column"))):
                out.add((f.get("op"), str(f.get("value"))))
    return out


def _leaves(obj):
    if isinstance(obj, dict):
        if "column" in obj and "op" in obj:
            yield obj
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)


def half_checks(t, tools=COMMIT_TOOLS):
    """Query evidence on the two half ends. Returns {"H1": Verdict, "H2": Verdict}."""
    ends = date_ends(t, tools)
    out = {}
    for h, day, nxt in (("H1", "2026-03-31", "2026-04-01"), ("H2", "2026-09-20", "2026-09-21")):
        short = [
            (op, v)
            for op, v in ends
            if (op == "lte" and v in (day, f"{day}T00:00:00Z")) or (op == "lt" and v == day)
        ]
        right = [
            (op, v)
            for op, v in ends
            if (op == "lt" and v.startswith(nxt)) or (op == "lte" and "23:59" in v and v.startswith(day))
        ]
        if short and not right:
            out[h] = Verdict(MISSED, f"{short[0][0]} {short[0][1]} leaves out the last day of {h}")
        elif right and not short:
            out[h] = Verdict(APPLIED, f"{h} ends with {right[0][0]} {right[0][1]}")
        else:
            out[h] = Verdict(UNCLEAR, f"{h} end filters {sorted(short + right)[:2]}")
    return out


def explain(value, key_value, alts, tol, blocked=()):
    """The smallest sets of switches whose alternative key equals the agent's value.
    Returns [] when the key itself matches ([set()]), or None when nothing matches."""
    if value is None:
        return None
    if key_value is not None and abs(value - key_value) <= tol:
        return [set()]
    hits = [
        set(name.split(" + "))
        for name, v in alts.items()
        if v is not None and abs(value - v) <= tol and not (set(name.split(" + ")) & set(blocked))
    ]
    if not hits:
        return None
    n = min(len(h) for h in hits)
    return [h for h in hits if len(h) == n]


def grid(switches, max_size=2):
    """Every single switch and every pair, as tuples of names."""
    names = [s[0] for s in switches]
    return [c for k in range(1, max_size + 1) for c in combinations(names, k)]


def verdicts_from(explanations, switch_def, definitions, query_checks, affects=None):
    """Turn per-value explanations into one verdict per definition.

    explanations: {value label: list of switch sets, or None if nothing matched}.
    affects(label) gives the definitions a value depends on (all by default). A
    definition is missed if every smallest explanation of some value uses it, and
    unclear if only some do. If a value it affects matches nothing, the query check
    decides. If every value it affects is explained without it, it is applied, as in
    r10.py when the count equals the key."""
    out = {}
    for d in definitions:
        uses, partial, clean, unexplained = [], [], [], []
        for lab, ex in explanations.items():
            if affects and d not in affects(lab):
                continue
            if ex is None:
                unexplained.append(lab)
                continue
            with_d = [s for s in ex if any(switch_def[x] == d for x in s)]
            if with_d and len(with_d) == len(ex):
                uses.append(f"{lab} equals the key with '{' + '.join(sorted(with_d[0]))}'")
            elif with_d:
                partial.append(f"{lab} matches '{' + '.join(sorted(with_d[0]))}' or another reading")
            else:
                clean.append(lab)
        q = query_checks.get(d, Verdict(UNCLEAR, "no query check"))
        if uses:
            out[d] = Verdict(MISSED, "; ".join(uses))
        elif partial:
            out[d] = Verdict(UNCLEAR, "; ".join(partial))
        elif unexplained:
            text = f"{labels(unexplained)} match no alternative; {q.evidence}"
            out[d] = (
                q if q.verdict == MISSED else Verdict(q.verdict if q.verdict == APPLIED else UNCLEAR, text)
            )
        elif clean:
            note = (
                f" (the queries show: {q.evidence}, but it made no difference here)"
                if q.verdict == MISSED
                else ""
            )
            out[d] = Verdict(APPLIED, f"{labels(clean)} explained without it{note}")
        else:
            out[d] = q
    return out


def labels(xs):
    return " and ".join(xs)


# R8 itself.

# Each switch changes one definition: (name, definition).
ALTERNATIVES = [
    ("merges kept", "merges"),
    ("bots kept", "bots"),
    ("only [bot] logins left out", "bots"),
    ("empty logins left out", "bots"),
    ("automation emails kept", "automation"),
    ("empty logins as one person", "person"),
    ("person by email", "person"),
    ("last day of H1 left out", "window"),
    ("last day of H2 left out", "window"),
    ("top two of the whole window", "top_two"),
    ("H1's top two used for H2", "top_two"),
    ("all commits in the denominator", "denominator"),
]
# Two more ways the total went wrong, found from the agent's own results.
SWITCH_DEF = dict(ALTERNATIVES) | {
    "total summed from one page of people": "denominator",
    "number of people as the total": "denominator",
}


def affects(label):
    """The definitions one value depends on."""
    if "top-two count" in label:
        return {"window", "merges", "bots", "automation", "person", "top_two"}
    if "total" in label:
        return {"window", "merges", "bots", "automation", "denominator"}
    return set(DEFINITIONS)


def agent_counts(t, h, share):
    """The agent's (top-two count, total) for one half: from its Fisher test if the
    rates match its shares, else the first pair of whole numbers in its answer whose
    ratio is its share."""
    if share is None:
        return None
    for name, args, _ in reversed(call_results(t)):
        if name != "fisher_test":
            continue
        try:
            c, n = (
                (int(args["count_a"]), int(args["total_a"]))
                if h == "h1"
                else (int(args["count_b"]), int(args["total_b"]))
            )
        except (KeyError, TypeError, ValueError):
            continue
        if n and abs(100 * c / n - share) <= 0.011:
            return c, n
    text = (t.run.get("final_answer") or "").replace(",", "")
    pairs = re.findall(r"(?<![\d.])(\d+)\)?\s*(?:/|out of|of)\s*(\d+)(?![\d.])", text)
    pairs += re.findall(r"count_[ab]\s*=\s*(\d+)\W+total_[ab]\s*=\s*(\d+)", text)
    for c, n in pairs:
        c, n = int(c), int(n)
        if 0 < c < n and abs(100 * c / n - share) <= 0.006:
            return c, n
    return None


def page_sums(t):
    """Sums of a count column over the one page shown, for grouped results with more
    groups than the page held."""
    sums = set()
    for _, args, r in ok_calls(t):
        if not args.get("group_by") or r["total"] <= len(r["rows"]):
            continue
        for i in range(len(r["columns"])):
            vals = [row[i] for row in r["rows"]]
            if vals and all(isinstance(x, int) and not isinstance(x, bool) for x in vals):
                sums.add(sum(vals))
    return sums


def group_counts(t):
    """How many people the grouped-by-person results had (the tool's total)."""
    return {
        r["total"]
        for _, args, r in ok_calls(t)
        if set(args.get("group_by") or []) & PERSON_COLUMNS and r["total"] > 2
    }


def partial_pages(t):
    """Text naming the lists it saw only one page of, when it never asked for a later
    page. Empty if there are none."""
    calls = ok_calls(t)
    if any(a.get("offset") for _, a, _ in calls):
        return ""
    seen = [f"{len(r['rows'])} of {r['total']} rows" for _, _, r in calls if r["total"] > len(r["rows"])]
    return f"only the first page of some lists ({', '.join(seen[:3])})" if seen else ""


def _shares(rows, sw):
    """The two top-two shares (and counts) with these switches on."""

    def human(r):
        if r["merge"] and "merges kept" not in sw:
            return False
        if "bots kept" not in sw:
            if "only [bot] logins left out" in sw:
                if r["login"] and r["login"].endswith("[bot]"):
                    return False
            elif r["bot"]:
                return False
        if r["auto"] and "automation emails kept" not in sw:
            return False
        return not (r["login"] is None and "empty logins left out" in sw)

    def person(r):
        if "person by email" in sw:
            return r["email"]
        if "empty logins as one person" in sw:
            return r["login"] or "(no login)"
        return r["login"] or r["email"]

    h1_end = "2026-03-31" if "last day of H1 left out" in sw else ck.H2_0
    h2_end = "2026-09-20" if "last day of H2 left out" in sw else ck.W1
    halves = {
        "h1": [r for r in rows if ck.W0 <= r["at"] < h1_end],
        "h2": [r for r in rows if ck.H2_0 <= r["at"] < h2_end],
    }
    counts = {h: Counter(person(r) for r in rs if human(r)) for h, rs in halves.items()}
    if "top two of the whole window" in sw:
        both = counts["h1"] + counts["h2"]
        tops = {h: [p for p, _ in both.most_common(2)] for h in halves}
    else:
        tops = {h: [p for p, _ in c.most_common(2)] for h, c in counts.items()}
        if "H1's top two used for H2" in sw:
            tops["h2"] = tops["h1"]
    out = {}
    for h, rs in halves.items():
        top = sum(counts[h][p] for p in tops[h])
        n = len(rs) if "all commits in the denominator" in sw else sum(counts[h].values())
        out[h] = top / n if n else None
        out[f"{h}_counts"] = (top, n)
    return out


def prepare(conn, repos):
    rows = fetch(
        conn,
        f"""
        select r.name repo, to_char(c.committed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') at,
          c.author_login login, c.author_email email, c.is_merge merge,
          coalesce({ck.bot("c.author_login")}, false) bot,
          (c.author_login is null and coalesce(c.author_email, '') in {ck.AUTOMATION_EMAILS}) auto
        from commits c join repos r on r.id = c.repo_id
        where c.committed_at >= '{ck.W0}' and c.committed_at < '{ck.W1}'""",
    )
    alt = {}
    for repo in repos:
        rs = [r for r in rows if r["repo"] == repo]
        alt[repo] = {
            "bots": sorted({r["login"] for r in rs if r["bot"]}),
            "key": _shares(rs, set()),
            "alts": {" + ".join(c): _shares(rs, set(c)) for c in grid(ALTERNATIVES)},
        }
    return alt


def fisher_rule(top1, n1, top2, n2):
    s1, s2 = top1 / n1, top2 / n2
    p = ck.fisher_p(top1, n1 - top1, top2, n2 - top2)
    if p < 0.05 and abs(s2 - s1) >= 0.05:
        return ("more concentrated" if s2 > s1 else "less concentrated"), p
    return "no clear change", p


def check(t, alt):
    a = alt[t.repo]
    if not ok_calls(t):
        return {
            d: Verdict(UNCLEAR, "no successful commit query, so its numbers are not from the data")
            for d in DEFINITIONS
        }
    halves = half_checks(t, ("query_commits",))
    bot_v, empty_v = bot_probe(t, a["bots"], ("query_commits",))
    query_checks = {
        "window": halves["H1"] if halves["H1"].verdict != APPLIED else halves["H2"],
        "merges": merge_probe(t, ("query_commits",)),
        "bots": bot_v if bot_v.verdict == MISSED else empty_v if empty_v.verdict == MISSED else bot_v,
        "automation": automation_check(t, ("query_commits",)),
    }
    # Switches the queries rule out.
    ruled_out = {
        "merges kept": query_checks["merges"],
        "bots kept": bot_v,
        "only [bot] logins left out": bot_v,
        "empty logins left out": empty_v,
        "automation emails kept": query_checks["automation"],
        "last day of H1 left out": halves["H1"],
        "last day of H2 left out": halves["H2"],
    }
    blocked = [n for n, v in ruled_out.items() if v.verdict == APPLIED]
    values = {"h1": t.value("h1_top2_pct"), "h2": t.value("h2_top2_pct")}
    expl = {}
    for h in ("h1", "h2"):
        v = values[h]
        v = float(v) if isinstance(v, (int, float)) else None
        alts = {n: (x[h] * 100 if x[h] is not None else None) for n, x in a["alts"].items()}
        ex = explain(v, a["key"][h] * 100, alts, 0.011, blocked)
        pair = agent_counts(t, h, v)
        if ex is None and pair:
            # The share matches nothing: look at its two counts one by one.
            top, n = pair
            tops = {name: x[f"{h}_counts"][0] for name, x in a["alts"].items()}
            totals = {name: x[f"{h}_counts"][1] for name, x in a["alts"].items()}
            key_top, key_n = a["key"][f"{h}_counts"]
            expl[f"{h.upper()} top-two count {top}"] = explain(top, key_top, tops, 0, blocked)
            ex_n = explain(n, key_n, totals, 0, blocked)
            if ex_n is None and n in page_sums(t):
                ex_n = [{"total summed from one page of people"}]
            elif ex_n is None and n in group_counts(t):
                ex_n = [{"number of people as the total"}]
            expl[f"{h.upper()} total {n}"] = ex_n
        else:
            expl[f"{h.upper()} share {v}"] = ex
    pages = partial_pages(t)
    out = verdicts_from(expl, SWITCH_DEF, DEFINITIONS[:-1], query_checks, affects)
    if pages:
        for v in out.values():
            if v.verdict == UNCLEAR and "match no alternative" in v.evidence:
                v.evidence += f"; it read {pages}"

    # The verdict test, on the agent's own counts where it ran a Fisher test.
    verdict, key_verdict = t.value("verdict"), t.key["verdict"]
    pairs = [
        agent_counts(t, h, values[h] if isinstance(values[h], (int, float)) else None) for h in ("h1", "h2")
    ]
    fishers = [
        (args, r)
        for n, args, r in call_results(t)
        if n == "fisher_test"
        and r is not None
        and all(pairs)
        and [args.get("count_a"), args.get("total_a"), args.get("count_b"), args.get("total_b")]
        == [pairs[0][0], pairs[0][1], pairs[1][0], pairs[1][1]]
    ]
    if verdict is None:
        out["verdict_test"] = Verdict(UNCLEAR, "no verdict given")
    elif fishers:
        args, r = fishers[-1]
        try:
            rule, p = fisher_rule(
                int(args["count_a"]), int(args["total_a"]), int(args["count_b"]), int(args["total_b"])
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            rule, p = None, None
        if rule is None:
            out["verdict_test"] = Verdict(UNCLEAR, "could not read its Fisher test")
        elif rule == verdict:
            out["verdict_test"] = Verdict(
                APPLIED, f"'{verdict}' follows from its own Fisher test (p {p:.3g})"
            )
        else:
            out["verdict_test"] = Verdict(
                MISSED,
                f"its Fisher test (p {p:.3g}, shares {r.get('rate_a')} and {r.get('rate_b')}) "
                f"gives '{rule}', it said '{verdict}'",
            )
    elif all(pairs):
        # No test on these counts: apply the rule to its own counts.
        (t1, n1), (t2, n2) = pairs
        rule, p = fisher_rule(t1, n1, t2, n2)
        out["verdict_test"] = Verdict(
            APPLIED if rule == verdict else MISSED,
            f"no Fisher test on its counts; the rule on {t1}/{n1} and {t2}/{n2} "
            f"gives '{rule}' (p {p:.3g}), it said '{verdict}'",
        )
    elif verdict == key_verdict:
        out["verdict_test"] = Verdict(APPLIED, f"'{verdict}' equals the key, without a Fisher test")
    else:
        out["verdict_test"] = Verdict(UNCLEAR, f"no Fisher test and no counts to check '{verdict}' against")
    return out
