"""R12: did the median commit size (lines added plus deleted) change from H1 to H2,
and what are the median sizes of fix commits and of all other commits.

Definitions the question uses:
- window: H1 is 2025-10-01 to 2026-03-31 and H2 is 2026-04-01 to 2026-09-20, both inclusive
- merges: merge commits are left out
- bots: commits by bot logins are left out, and an empty login is not a bot
- automation: eslint's two automation emails (with no login) are left out
- size: lines added plus lines deleted
- fix_rule: the first line has fix, fixes, fixed, fixing or bugfix as a whole word
- other_group: "all other commits" are the human non-fix commits in the window
- verdict_test: the bootstrap rule for medians

As in r8.py, the alternatives are single switches and pairs, and the smallest set
of switches that gives each of the agent's medians names what went wrong. Medians
are coarse numbers, so a switch is not used when the queries show that definition
was applied.
"""

from common import (
    APPLIED,
    MISSED,
    UNCLEAR,
    Verdict,
    ck,
    fetch,
)
from r8 import (
    automation_check,
    bot_probe,
    call_results,
    explain,
    grid,
    half_checks,
    merge_probe,
    ok_calls,
    partial_pages,
    verdicts_from,
)

TEMPLATE = "R12"
DEFINITIONS = ["window", "merges", "bots", "automation", "size", "fix_rule", "other_group", "verdict_test"]

# Each switch changes one definition: (name, definition).
ALTERNATIVES = [
    ("merges kept", "merges"),
    ("bots kept", "bots"),
    ("only [bot] logins left out", "bots"),
    ("empty logins left out", "bots"),
    ("automation emails kept", "automation"),
    ("last day of H1 left out", "window"),
    ("last day of H2 left out", "window"),
    ("fix as part of a word", "fix_rule"),
    ("fix only at the start", "fix_rule"),
    ("fix filter had no effect", "fix_rule"),
    ("other means all commits", "other_group"),
    ("additions only", "size"),
]
SWITCH_DEF = dict(ALTERNATIVES)
FIELDS = {
    "h1": "h1_median_lines",
    "h2": "h2_median_lines",
    "fix": "fix_median_lines",
    "other": "other_median_lines",
}


def _medians(rows, sw):
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

    def is_fix(r):
        if "fix as part of a word" in sw:
            return r["fix_sub"]
        if "fix only at the start" in sw:
            return r["fix_start"]
        if "fix filter had no effect" in sw:
            return True
        return r["fix"]

    h1_end = "2026-03-31" if "last day of H1 left out" in sw else ck.H2_0
    h2_end = "2026-09-20" if "last day of H2 left out" in sw else ck.W1
    size = "adds" if "additions only" in sw else "lines"
    hs = [r for r in rows if human(r)]
    h1 = [r[size] for r in hs if ck.W0 <= r["at"] < h1_end]
    h2 = [r[size] for r in hs if ck.H2_0 <= r["at"] < h2_end]
    win = [r for r in hs if (ck.W0 <= r["at"] < h1_end) or (ck.H2_0 <= r["at"] < h2_end)]
    # With no working fix filter, "other" is every commit too.
    nofix = "other means all commits" in sw or "fix filter had no effect" in sw
    other = win if nofix else [r for r in win if not is_fix(r)]
    return {
        "h1": ck.med(h1),
        "h2": ck.med(h2),
        "fix": ck.med([r[size] for r in win if is_fix(r)]),
        "other": ck.med([r[size] for r in other]),
        "verdict": ck.median_verdict(h1, h2) if h1 and h2 else None,
    }


def prepare(conn, repos):
    rows = fetch(
        conn,
        rf"""
        select r.name repo, to_char(c.committed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') at,
          c.author_login login, c.is_merge merge, c.additions + c.deletions lines, c.additions adds,
          coalesce({ck.bot("c.author_login")}, false) bot,
          (c.author_login is null and coalesce(c.author_email, '') in {ck.AUTOMATION_EMAILS}) auto,
          {ck.FIX_SUBJECT} fix,
          split_part(c.message, E'\n', 1) ~* '(fix|bugfix)' fix_sub,
          split_part(c.message, E'\n', 1) ~* '^(fix|fixes|fixed|fixing|bugfix)\M' fix_start
        from commits c join repos r on r.id = c.repo_id
        where c.committed_at >= '{ck.W0}' and c.committed_at < '{ck.W1}'""",
    )
    alt = {}
    for repo in repos:
        rs = [r for r in rows if r["repo"] == repo]
        alt[repo] = {
            "bots": sorted({r["login"] for r in rs if r["bot"]}),
            "key": _medians(rs, set()),
            "alts": {" + ".join(c): _medians(rs, set(c)) for c in grid(ALTERNATIVES)},
        }
    return alt


def affects(label):
    """The definitions one median depends on."""
    base = {"window", "merges", "bots", "automation", "size"}
    if label.startswith("fix"):
        return base | {"fix_rule"}
    if label.startswith("other"):
        return base | {"fix_rule", "other_group"}
    return base


def size_check(t):
    """Did the size the medians were taken on come from total_lines or additions plus deletions?"""
    text = str([a for n, a, _ in call_results(t)])
    if (
        "total_lines" in text
        or ("'sum': ['additions', 'deletions']" in text)
        or ("'sum': ['deletions', 'additions']" in text)
    ):
        return Verdict(APPLIED, "it measured size as total_lines or additions plus deletions")
    return Verdict(UNCLEAR, "no total_lines or additions plus deletions in its calls")


def check(t, alt):
    a = alt[t.repo]
    if not ok_calls(t, ("query_commits",)):
        return {
            d: Verdict(UNCLEAR, "no successful commit query, so its numbers are not from the data")
            for d in DEFINITIONS
        }
    tools = ("query_commits",)
    halves = half_checks(t, tools)
    bot_v, empty_v = bot_probe(t, a["bots"], tools)
    query_checks = {
        "window": halves["H1"] if halves["H1"].verdict != APPLIED else halves["H2"],
        "merges": merge_probe(t, tools),
        "bots": bot_v if bot_v.verdict == MISSED else empty_v if empty_v.verdict == MISSED else bot_v,
        "automation": automation_check(t, tools),
        "size": size_check(t),
    }
    ruled_out = {
        "merges kept": query_checks["merges"],
        "bots kept": bot_v,
        "only [bot] logins left out": bot_v,
        "empty logins left out": empty_v,
        "automation emails kept": query_checks["automation"],
        "last day of H1 left out": halves["H1"],
        "last day of H2 left out": halves["H2"],
        "additions only": query_checks["size"],
    }
    blocked = [n for n, v in ruled_out.items() if v.verdict == APPLIED]

    expl = {}
    for f, field in FIELDS.items():
        v = t.value(field)
        v = float(v) if isinstance(v, (int, float)) else None
        if v is None:
            continue
        alts = {n: x[f] for n, x in a["alts"].items()}
        ex = explain(v, a["key"][f], alts, 0.01, blocked)
        expl[f"{f} median {v:g}"] = ex
        if f == "fix" and ex and not any("fix filter had no effect" in e for e in ex):
            # Its fix median shows the fix filter worked, so "other" can't be all commits for that reason.
            blocked = [*blocked, "fix filter had no effect"]
    if not expl:
        return {d: Verdict(UNCLEAR, "no medians given") for d in DEFINITIONS}
    out = verdicts_from(expl, SWITCH_DEF, DEFINITIONS[:-1], query_checks, affects)
    for d in ("fix_rule", "other_group"):
        if out[d].evidence == "no query check":
            out[d] = Verdict(UNCLEAR, "no fix or other median given")
    pages = partial_pages(t)
    for v in out.values():
        if v.verdict == UNCLEAR and "match no alternative" in v.evidence and pages:
            v.evidence += f"; it read {pages}"

    # The verdict test: the agent's verdict against the bootstrap on its own groups.
    verdict, key_verdict = t.value("verdict"), t.key["verdict"]
    h1, h2 = t.value("h1_median_lines"), t.value("h2_median_lines")
    tests = [r for n, _, r in call_results(t) if n == "compare_medians" and r is not None]
    matching = [
        r
        for r in tests
        if h1 is not None and h2 is not None and r.get("median_a") == h1 and r.get("median_b") == h2
    ]
    if verdict is None:
        out["verdict_test"] = Verdict(UNCLEAR, "no verdict given")
    elif matching:
        tool = matching[-1]["verdict"]
        if tool == verdict:
            out["verdict_test"] = Verdict(APPLIED, f"'{verdict}' is the bootstrap verdict on its own halves")
        else:
            out["verdict_test"] = Verdict(
                MISSED, f"its bootstrap on its halves said '{tool}', it said '{verdict}'"
            )
    elif verdict == key_verdict:
        out["verdict_test"] = Verdict(APPLIED, f"'{verdict}' equals the key")
    elif tests:
        tool = tests[-1]["verdict"]
        out["verdict_test"] = Verdict(
            APPLIED if tool == verdict else MISSED,
            f"its last bootstrap said '{tool}' (medians {tests[-1].get('median_a')} and "
            f"{tests[-1].get('median_b')}), it said '{verdict}'",
        )
    else:
        out["verdict_test"] = Verdict(MISSED, f"no bootstrap run, and '{verdict}' differs from the key")
    return out
