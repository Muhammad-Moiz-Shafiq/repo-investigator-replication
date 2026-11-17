from datetime import date

import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import PRApprovalStats


def query_review_approval_stats(
    conn: psycopg.Connection, repo: str, date_from: date, date_to: date
) -> PRApprovalStats:
    """Directly answers "what fraction of merged PRs got at least one
    approval" -- filters by created_at, matching query_issues_prs's date
    semantics for consistency between the two tools.
    """
    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return PRApprovalStats(
            repo=repo,
            date_from=date_from,
            date_to=date_to,
            total_merged_prs=0,
            prs_with_approval=0,
            prs_without_approval=0,
            approval_rate=None,
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*),
                count(*) FILTER (WHERE approval_count > 0)
            FROM pull_requests
            WHERE repo_id = %s AND state = 'MERGED' AND created_at BETWEEN %s AND %s
            """,
            (repo_id, date_from, date_to),
        )
        total, with_approval = cur.fetchone()

    return PRApprovalStats(
        repo=repo,
        date_from=date_from,
        date_to=date_to,
        total_merged_prs=total,
        prs_with_approval=with_approval,
        prs_without_approval=total - with_approval,
        approval_rate=round(with_approval / total, 4) if total else None,
    )
