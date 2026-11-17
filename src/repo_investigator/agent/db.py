from datetime import date

import psycopg


def get_data_coverage_window(conn: psycopg.Connection) -> tuple[date, date] | None:
    """Queried live, not hardcoded: an agent needs to know what date range
    its data actually covers before investigating "recent" trends, and a
    hardcoded window would silently go stale the moment more data is
    ingested. Returns None if there are no commits at all.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT min(committed_at), max(committed_at) FROM commits")
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return row[0].date(), row[1].date()


def resolve_repo_id(conn: psycopg.Connection, repo: str) -> int | None:
    """Looks up the internal repo_id for a human-readable "owner/name" string.
    Returns None if not found -- callers must handle this explicitly (an
    unknown repo is a real, expected case: the agent might ask about a repo
    we never ingested), not silently return empty results indistinguishable
    from "found, but no data".
    """
    owner, _, name = repo.partition("/")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM repos WHERE owner = %s AND name = %s", (owner, name))
        row = cur.fetchone()
        return row[0] if row else None
