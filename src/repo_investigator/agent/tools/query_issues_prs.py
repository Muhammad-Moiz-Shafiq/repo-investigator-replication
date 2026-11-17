from datetime import date

import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import IssuePRFilters, IssuePRResult, IssueSummary, PRSummary


def query_issues_prs(
    conn: psycopg.Connection,
    repo: str,
    filters: IssuePRFilters,
    date_from: date,
    date_to: date,
) -> IssuePRResult:
    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return IssuePRResult(repo=repo, date_from=date_from, date_to=date_to, issues=[], pull_requests=[])

    issues: list[IssueSummary] = []
    prs: list[PRSummary] = []

    with conn.cursor() as cur:
        if filters.kind in ("issues", "both"):
            query = (
                "SELECT number, title, state, author_login, created_at, closed_at, "
                "labels, is_bug, comment_count "
                "FROM issues WHERE repo_id = %s AND created_at BETWEEN %s AND %s"
            )
            params: list = [repo_id, date_from, date_to]
            if filters.state is not None:
                query += " AND state = %s"
                params.append(filters.state)
            if filters.is_bug is not None:
                query += " AND is_bug = %s"
                params.append(filters.is_bug)
            cur.execute(query + " ORDER BY number", params)
            issues = [
                IssueSummary(
                    number=r[0],
                    title=r[1],
                    state=r[2],
                    author_login=r[3],
                    created_at=r[4],
                    closed_at=r[5],
                    labels=r[6],
                    is_bug=r[7],
                    comment_count=r[8],
                )
                for r in cur.fetchall()
            ]

        if filters.kind in ("pull_requests", "both"):
            query = (
                "SELECT number, title, state, author_login, created_at, merged_at, "
                "review_comment_count, approval_count, time_to_merge_seconds "
                "FROM pull_requests WHERE repo_id = %s AND created_at BETWEEN %s AND %s"
            )
            params = [repo_id, date_from, date_to]
            if filters.state is not None:
                query += " AND state = %s"
                params.append(filters.state)
            cur.execute(query + " ORDER BY number", params)
            prs = [
                PRSummary(
                    number=r[0],
                    title=r[1],
                    state=r[2],
                    author_login=r[3],
                    created_at=r[4],
                    merged_at=r[5],
                    review_comment_count=r[6],
                    approval_count=r[7],
                    time_to_merge_seconds=r[8],
                )
                for r in cur.fetchall()
            ]

    return IssuePRResult(repo=repo, date_from=date_from, date_to=date_to, issues=issues, pull_requests=prs)
