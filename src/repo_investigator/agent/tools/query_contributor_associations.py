from datetime import date

import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import ContributorAssociation, ContributorAssociationResult


def query_contributor_associations(
    conn: psycopg.Connection, repo: str, date_from: date, date_to: date
) -> ContributorAssociationResult:
    """date_from/date_to are accepted for interface consistency with the
    other tools, but NOT used to filter the underlying computation --
    contributor_bugfix_association is computed once, over the full
    ingested window, at cleaning time (see agent_methodology_log.md).
    The result's computed_window_start/end report what was ACTUALLY
    computed, which may not match the caller's requested range -- this is
    stated explicitly rather than silently pretending the narrower window
    was honored.
    """
    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return ContributorAssociationResult(
            repo=repo, computed_window_start=date_from, computed_window_end=date_to, contributors=[]
        )

    with conn.cursor() as cur:
        cur.execute("SELECT min(committed_at), max(committed_at) FROM commits WHERE repo_id = %s", (repo_id,))
        window_start, window_end = cur.fetchone()

        cur.execute(
            """
            SELECT author_login, commit_count, implicated_commit_count, association_rate
            FROM contributor_bugfix_association
            WHERE repo_id = %s
            ORDER BY association_rate DESC, commit_count DESC
            """,
            (repo_id,),
        )
        contributors = [
            ContributorAssociation(
                author_login=r[0],
                commit_count=r[1],
                implicated_commit_count=r[2],
                association_rate=float(r[3]),
            )
            for r in cur.fetchall()
        ]

    return ContributorAssociationResult(
        repo=repo,
        computed_window_start=window_start.date(),
        computed_window_end=window_end.date(),
        contributors=contributors,
    )
