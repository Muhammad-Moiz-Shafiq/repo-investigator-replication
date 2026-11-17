import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import ComparisonResult, DateRange

# Each metric's SQL returns exactly one nullable numeric value for a given
# (repo_id, start, end). review_turnaround has no date column of its own --
# it's joined to pull_requests.created_at to bound it by period, since a
# review's "date" for this purpose is when the PR that prompted it opened.
_METRIC_QUERIES = {
    "ci_failure_rate": """
        SELECT CASE WHEN sum(total_runs) > 0 THEN sum(failed_runs)::float / sum(total_runs) END
        FROM daily_ci_failure_rate WHERE repo_id = %s AND date BETWEEN %s AND %s
    """,
    "avg_hours_to_first_review": """
        SELECT avg(rt.hours_to_first_review)::float
        FROM review_turnaround rt JOIN pull_requests pr
          ON rt.repo_id = pr.repo_id AND rt.pr_number = pr.number
        WHERE rt.repo_id = %s AND pr.created_at BETWEEN %s AND %s
    """,
    "avg_hours_to_merge": """
        SELECT avg(rt.hours_to_merge)::float
        FROM review_turnaround rt JOIN pull_requests pr
          ON rt.repo_id = pr.repo_id AND rt.pr_number = pr.number
        WHERE rt.repo_id = %s AND pr.created_at BETWEEN %s AND %s
    """,
    "commit_count": (
        "SELECT count(*)::float FROM commits WHERE repo_id = %s AND committed_at BETWEEN %s AND %s"
    ),
    "pr_count": (
        "SELECT count(*)::float FROM pull_requests WHERE repo_id = %s AND created_at BETWEEN %s AND %s"
    ),
    "issue_count": ("SELECT count(*)::float FROM issues WHERE repo_id = %s AND created_at BETWEEN %s AND %s"),
}


def _compute_metric(conn: psycopg.Connection, metric: str, repo_id: int, period: DateRange) -> float | None:
    with conn.cursor() as cur:
        cur.execute(_METRIC_QUERIES[metric], (repo_id, period.start, period.end))
        row = cur.fetchone()
        return row[0] if row else None


def compare_periods(
    conn: psycopg.Connection, repo: str, metric: str, period_a: DateRange, period_b: DateRange
) -> ComparisonResult:
    if metric not in _METRIC_QUERIES:
        raise ValueError(f"Unsupported metric '{metric}'. Supported: {sorted(_METRIC_QUERIES)}")

    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return ComparisonResult(
            repo=repo,
            metric=metric,
            period_a=period_a,
            period_a_value=None,
            period_b=period_b,
            period_b_value=None,
            absolute_change=None,
            percent_change=None,
        )

    value_a = _compute_metric(conn, metric, repo_id, period_a)
    value_b = _compute_metric(conn, metric, repo_id, period_b)

    absolute_change = (value_b - value_a) if (value_a is not None and value_b is not None) else None
    percent_change = (
        round((value_b - value_a) / value_a * 100, 2)
        if (value_a is not None and value_b is not None and value_a != 0)
        else None
    )

    return ComparisonResult(
        repo=repo,
        metric=metric,
        period_a=period_a,
        period_a_value=round(value_a, 4) if value_a is not None else None,
        period_b=period_b,
        period_b_value=round(value_b, 4) if value_b is not None else None,
        absolute_change=round(absolute_change, 4) if absolute_change is not None else None,
        percent_change=percent_change,
    )
