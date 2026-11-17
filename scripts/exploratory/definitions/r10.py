"""R10: how many fix commits were there, and what share also changed a test file.

The worked example for the other templates. Definitions the question uses:
- window: commits from 2025-10-01 to 2026-09-20, both inclusive
- merges: merge commits are left out
- bots: commits by bots are left out (and eslint's two automation emails)
- fix_rule: the first line has fix, fixes, fixed, fixing or bugfix as a whole word
- test_rule: a test file is in a test folder or has a test-style name

The fix count tells us about the first four: if it equals the key, they were all
applied. If it equals an alternative key, that names the one that went wrong.
The share tells us about test_rule.
"""

from common import (
    APPLIED,
    MISSED,
    OTHER_READING,
    UNCLEAR,
    Verdict,
    bot_filter,
    ck,
    close,
    fetch,
    fix_filter,
    merge_filter,
    pct,
    used_tool,
    window_check,
)

TEMPLATE = "R10"
DEFINITIONS = ["window", "merges", "bots", "fix_rule", "test_rule"]

# The test-file rule using only the examples the question names. The key's rule
# also takes any folder ending in -test(s) or _test(s), Tests.java, .test.ts and
# similar. See docs/exploratory/key_issues.md (local).
LITERAL_TEST_FILE = (
    r"(f.filename ~* '(^|/)(test|tests|__tests__|testdata|testing|fixtures|playground)/' "
    r"or regexp_replace(f.filename, '^.*/', '') ~ '(_test\.go|^test_.*\.py|Test\.java|\.spec\.ts)$')"
)

NO_BOTS = f"not coalesce({ck.bot('c.author_login')}, false)"
NO_AUTOMATION = f"(c.author_login is not null or coalesce(c.author_email, '') not in {ck.AUTOMATION_EMAILS})"
SUBSTRING_FIX = r"split_part(c.message, E'\n', 1) ~* '(fix|bugfix)'"

# Each alternative switches off or changes one definition: (name, definition, where, end).
ALTERNATIVES = [
    ("merges kept", "merges", f"{NO_BOTS} and {NO_AUTOMATION} and {ck.FIX_SUBJECT}", ck.W1),
    ("bots kept", "bots", f"not c.is_merge and {NO_AUTOMATION} and {ck.FIX_SUBJECT}", ck.W1),
    ("automation emails kept", "bots", f"not c.is_merge and {NO_BOTS} and {ck.FIX_SUBJECT}", ck.W1),
    ("fix as part of a word", "fix_rule", f"{ck.HUMAN_COMMIT} and {SUBSTRING_FIX}", ck.W1),
    ("last day left out", "window", f"{ck.HUMAN_COMMIT} and {ck.FIX_SUBJECT}", "2026-09-20"),
]


def prepare(conn, repos):
    alt = {repo: {"fix_commits": {}, "share": {}} for repo in repos}
    for name, _, where, end in ALTERNATIVES:
        rows = fetch(
            conn,
            f"""
            select r.name repo, count(*) n from commits c join repos r on r.id = c.repo_id
            where {where} and c.committed_at >= '{ck.W0}' and c.committed_at < '{end}'
            group by 1""",
        )
        for r in rows:
            if r["repo"] in alt:
                alt[r["repo"]]["fix_commits"][name] = r["n"]
    rows = fetch(
        conn,
        f"""
        select r.name repo, count(*) n,
          count(*) filter (where exists (
            select 1 from commit_files f where f.commit_sha = c.sha and {LITERAL_TEST_FILE})) t
        from commits c join repos r on r.id = c.repo_id
        where {ck.HUMAN_COMMIT} and c.committed_at >= '{ck.W0}' and c.committed_at < '{ck.W1}'
          and {ck.FIX_SUBJECT}
        group by 1""",
    )
    for r in rows:
        if r["repo"] in alt:
            alt[r["repo"]]["share"]["literal test examples"] = 100 * r["t"] / r["n"]
    return alt


def check(t, alt):
    out = {}
    fixes, key_fixes = t.value("fix_commits"), t.key["fix_commits"]
    share, key_share = t.value("changed_test_pct"), pct(t.key["share_changed_test"])
    a = alt[t.repo]

    # The fix count: the key, an alternative key, or neither.
    count_right = fixes == key_fixes
    matched = [name for name, n in a["fix_commits"].items() if n == fixes and n != key_fixes]
    commit_tools = ("query_commits", "query_commit_files")
    query_checks = {
        "window": window_check(t, commit_tools, "committed_at"),
        "merges": merge_filter(t, commit_tools, "(commit_)?is_merge"),
        "bots": bot_filter(t, commit_tools, "(commit_)?author"),
        "fix_rule": fix_filter(t, commit_tools, "(commit_)?subject"),
    }
    for d in ["window", "merges", "bots", "fix_rule"]:
        names = [n for n in matched if dict((x[0], x[1]) for x in ALTERNATIVES)[n] == d]
        if count_right:
            out[d] = Verdict(APPLIED, f"fix count {fixes} equals the key")
        elif names:
            out[d] = Verdict(MISSED, f"fix count {fixes} equals the key with '{names[0]}'")
        elif query_checks[d].verdict == MISSED:
            out[d] = query_checks[d]
        elif fixes is None:
            out[d] = Verdict(UNCLEAR, "no fix count given")
        else:
            q = query_checks[d]
            out[d] = Verdict(
                q.verdict if q.verdict == APPLIED else UNCLEAR,
                f"fix count {fixes}, key {key_fixes}; {q.evidence}",
            )

    # The share: the key, the literal reading, or a test-file rule problem.
    literal = a["share"].get("literal test examples")
    if close(share, key_share, 3):
        out["test_rule"] = Verdict(APPLIED, f"share {share} is within 3 points of the key")
    elif count_right and close(share, literal, 0.01):
        out["test_rule"] = Verdict(
            OTHER_READING, f"share {share} equals the rule with only the question's examples"
        )
    elif share == 0 and used_tool(t, "query_commit_files"):
        out["test_rule"] = Verdict(MISSED, "share 0: its test-file filter matched nothing")
    elif not used_tool(t, "query_commit_files"):
        out["test_rule"] = Verdict(MISSED, "never looked at changed files")
    elif count_right:
        out["test_rule"] = Verdict(
            MISSED, f"share {share} against key {key_share:.2f} with the right fix count"
        )
    else:
        out["test_rule"] = Verdict(UNCLEAR, f"share {share}, but the fix count is off too")
    return out
