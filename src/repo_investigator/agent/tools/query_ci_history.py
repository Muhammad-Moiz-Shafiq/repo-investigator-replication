from datetime import date

import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import CIHistoryResult, DailyCIStats, WorkflowCIStats


def query_ci_history(conn: psycopg.Connection, repo: str, date_from: date, date_to: date) -> CIHistoryResult:
    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return CIHistoryResult(
            repo=repo,
            date_from=date_from,
            date_to=date_to,
            total_runs=0,
            failed_runs=0,
            overall_failure_rate=None,
            by_workflow=[],
            by_day=[],
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT workflow_name, sum(total_runs), sum(failed_runs)
            FROM daily_ci_failure_rate
            WHERE repo_id = %s AND date BETWEEN %s AND %s
            GROUP BY workflow_name
            ORDER BY workflow_name
            """,
            (repo_id, date_from, date_to),
        )
        by_workflow = [
            WorkflowCIStats(
                workflow_name=row[0],
                total_runs=row[1],
                failed_runs=row[2],
                failure_rate=round(row[2] / row[1], 4),
            )
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT date, sum(total_runs), sum(failed_runs)
            FROM daily_ci_failure_rate
            WHERE repo_id = %s AND date BETWEEN %s AND %s
            GROUP BY date
            ORDER BY date
            """,
            (repo_id, date_from, date_to),
        )
        by_day = [
            DailyCIStats(
                date=row[0],
                total_runs=row[1],
                failed_runs=row[2],
                failure_rate=round(row[2] / row[1], 4),
            )
            for row in cur.fetchall()
        ]

    total_runs = sum(w.total_runs for w in by_workflow)
    failed_runs = sum(w.failed_runs for w in by_workflow)

    return CIHistoryResult(
        repo=repo,
        date_from=date_from,
        date_to=date_to,
        total_runs=total_runs,
        failed_runs=failed_runs,
        overall_failure_rate=round(failed_runs / total_runs, 4) if total_runs else None,
        by_workflow=by_workflow,
        by_day=by_day,
    )
