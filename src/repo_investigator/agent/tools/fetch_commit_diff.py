import psycopg

from repo_investigator.agent.db import resolve_repo_id
from repo_investigator.agent.schemas import CommitDiff, FileDiff


def fetch_commit_diff(conn: psycopg.Connection, repo: str, sha: str) -> CommitDiff:
    repo_id = resolve_repo_id(conn, repo)
    if repo_id is None:
        return CommitDiff(repo=repo, sha=sha, found=False)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT message, author_login, committed_at, is_bugfix "
            "FROM commits WHERE sha = %s AND repo_id = %s",
            (sha, repo_id),
        )
        commit_row = cur.fetchone()
        if commit_row is None:
            return CommitDiff(repo=repo, sha=sha, found=False)

        cur.execute(
            "SELECT filename, status, additions, deletions, patch "
            "FROM commit_files WHERE commit_sha = %s ORDER BY filename",
            (sha,),
        )
        files = [
            FileDiff(filename=row[0], status=row[1], additions=row[2], deletions=row[3], patch=row[4])
            for row in cur.fetchall()
        ]

    return CommitDiff(
        repo=repo,
        sha=sha,
        found=True,
        message=commit_row[0],
        author_login=commit_row[1],
        committed_at=commit_row[2],
        is_bugfix=commit_row[3],
        files=files,
    )
