"""The shared definitions, as the level 0 and level 1 tools apply them.

These are the rules every question of a template states the same way, and the
system prompt repeats: the bot rule, the landing run rule, what counts as
failing, what a fix is, what a test or documentation file is, and the verdict
rules. Level 0 and level 1 tools build them in. Level 2 leaves them to the agent.

They are written separately from scripts/answer_keys/compute_keys.py on
purpose. The keys are frozen, and test 1 (level 0 is exact) compares the two.
Everything here works on one repo at a time, by repo id.
"""

import math
from datetime import date, timedelta

import numpy as np

from repo_investigator.levels.calculators import binom_p, fisher_p, median_verdict
from repo_investigator.levels.query import QueryError

BOT_LOGINS = (
    "renovate",
    "dependabot",
    "github-actions",
    "junit-builds",
    "copilot-pull-request-reviewer",
    "copilot-swe-agent",
    "Copilot",
)
AUTOMATION_EMAILS = ("jenkins@eslint-03", "eslint@googlegroups.com")
FAILING_RESULTS = ("failure", "timed_out", "startup_failure")
NOT_COUNTED_RESULTS = ("cancelled", "skipped")
FIX_WORDS = ("fix", "fixes", "fixed", "fixing", "bugfix")


def _list(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def bot(col: str) -> str:
    """True for a bot login, null for a null login."""
    return f"({col} in {_list(BOT_LOGINS)} or {col} like '%%[bot]' or {col} ~* 'bot$')"


def not_bot(col: str) -> str:
    """A null login is not a bot."""
    return f"not coalesce({bot(col)}, false)"


def human_commit(c: str = "c") -> str:
    return (
        f"not {c}.is_merge and {not_bot(f'{c}.author_login')} "
        f"and ({c}.author_login is not null "
        f"or coalesce({c}.author_email, '') not in {_list(AUTOMATION_EMAILS)})"
    )


def fix_subject(c: str = "c") -> str:
    return f"split_part({c}.message, E'\\n', 1) ~* '\\m({'|'.join(FIX_WORDS)})\\M'"


def test_file(f: str = "f") -> str:
    return (
        f"({f}.filename ~* '(^|/)(tests?|__tests__|testdata|testing|fixtures|playground|[^/]*[-_]tests?)/' "
        f"or regexp_replace({f}.filename, '^.*/', '') ~ "
        r"'(_test\.go|^test_.*\.py|_test\.py|Tests?\.java|Tests?\.kt|\.(test|spec)\.[cm]?[jt]sx?)$')"
    )


def doc_file(f: str = "f") -> str:
    return (
        f"({f}.filename ~* '(^|/)(doc|docs|documentation|\\.github|changelog\\.d)/' "
        f"or lower({f}.filename) ~ '\\.(md|rst|txt|adoc)$')"
    )


FAILING = f"conclusion in {_list(FAILING_RESULTS)}"


def landing_ctes(workflow_ids: list[int]) -> str:
    """CTEs main, landing and counted for one repo, given as %(repo_id)s.

    landing: each default branch commit's earliest push run of the workflow,
    with its final result. counted: landing runs that are not cancelled or
    skipped and have a result."""
    ids = ", ".join(str(int(i)) for i in workflow_ids)
    return f"""
    main as (
      select ci.* from ci_runs ci
      where ci.repo_id = %(repo_id)s and ci.workflow_id in ({ids}) and ci.event = 'push'
        and exists (select 1 from commits c where c.sha = ci.commit_sha and c.repo_id = ci.repo_id)
    ),
    landing as (
      select distinct on (commit_sha) * from main order by commit_sha, started_at, id
    ),
    counted as (
      select * from landing where conclusion is not null and conclusion not in {_list(NOT_COUNTED_RESULTS)}
    )"""


def period(start: str, end: str, name: str = "period") -> tuple[str, str]:
    """Inclusive dates, as the questions write them, to a half-open range [start, end + 1 day)."""
    try:
        a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except ValueError as e:
        raise QueryError(f"{name}: dates must look like 2024-01-31. Got {start!r} and {end!r}.") from e
    if b < a:
        raise QueryError(f"{name}: the end date {end} is before the start date {start}.")
    return a.isoformat(), (b + timedelta(days=1)).isoformat()


# Verdict rules, as the system prompt states them.


def rate_verdict(count_a: int, total_a: int, count_b: int, total_b: int) -> str:
    """Fisher exact test at 0.05: up, down or no clear change."""
    if fisher_p(count_a, total_a - count_a, count_b, total_b - count_b) >= 0.05:
        return "no clear change"
    return "up" if count_b / total_b > count_a / total_a else "down"


def concentration_verdict(top_a: int, total_a: int, top_b: int, total_b: int) -> str:
    """Fisher exact test at 0.05 and a change of at least 5 points."""
    sa, sb = top_a / total_a, top_b / total_b
    if fisher_p(top_a, total_a - top_a, top_b, total_b - top_b) < 0.05 and abs(sb - sa) >= 0.05:
        return "more concentrated" if sb > sa else "less concentrated"
    return "no clear change"


def backlog_verdict(opened: int, closed: int) -> str:
    """Two-sided binomial test of closed out of opened plus closed against one half."""
    n = opened + closed
    p = binom_p(closed, n) if n else 1.0
    if p >= 0.05:
        return "balanced"
    return "growing" if opened > closed else "shrinking"


def medians_verdict(a: list[float], b: list[float]) -> str:
    return median_verdict(a, b)


def median(values) -> float | None:
    """Median, where math.inf stands for "not yet", like a bug never closed."""
    return float(np.median(values)) if len(values) else None


def finite_or_none(x):
    return None if x is None or (isinstance(x, float) and math.isinf(x)) else x
