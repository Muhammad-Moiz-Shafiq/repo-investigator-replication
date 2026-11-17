import psycopg
from pyspark.sql import DataFrame

# Child-before-parent order: a table must be cleared before anything it
# holds a foreign key to. commit_files -> commits and pr_reviews ->
# pull_requests are the only real FK dependencies in this schema; derived
# tables and detail tables that nothing else references can be cleared in
# any order relative to each other.
_CLEAR_ORDER = [
    "commit_files",
    "pr_reviews",
    "daily_ci_failure_rate",
    "review_turnaround",
    "contributor_bugfix_association",
    "commits",
    "pull_requests",
    "issues",
    "ci_runs",
]


def get_or_create_repo(conn: psycopg.Connection, owner: str, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repos (owner, name)
            VALUES (%s, %s)
            ON CONFLICT (owner, name) DO UPDATE SET last_ingested_at = now()
            RETURNING id
            """,
            (owner, name),
        )
        repo_id = cur.fetchone()[0]
    conn.commit()
    return repo_id


def clear_repo_data(conn: psycopg.Connection, repo_id: int) -> None:
    """Deletes this repo's existing rows from every table before a fresh
    cleaning run writes new ones. Scoped to one repo_id, not a blanket
    table truncate: a table-wide clear would silently destroy other
    already-loaded repos' data in this multi-repo pipeline. commit_files
    and pr_reviews don't carry repo_id directly, so they're cleared via a
    subquery against their parent's sha/number instead.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM commit_files WHERE commit_sha IN (SELECT sha FROM commits WHERE repo_id = %s)",
            (repo_id,),
        )
        cur.execute("DELETE FROM pr_reviews WHERE repo_id = %s", (repo_id,))
        for table in _CLEAR_ORDER[2:]:
            # table name comes from the fixed internal _CLEAR_ORDER list, not user input
            cur.execute(f"DELETE FROM {table} WHERE repo_id = %s", (repo_id,))  # noqa: S608
    conn.commit()


def write_table(df: DataFrame, table_name: str, jdbc_url: str, jdbc_properties: dict) -> None:
    """Appends a Spark DataFrame's rows into an existing Postgres table.

    Deliberately mode="append", not "overwrite": overwrite mode either
    drops/recreates the table (destroying schema.sql's constraints) or, with
    truncate=true, clears the WHOLE table (wrong for a multi-repo pipeline,
    and blocked outright by Postgres on any table with FK dependents -- see
    data_engineering_log.md). clear_repo_data() must be called first to
    remove this repo's old rows so append doesn't create duplicates.
    """
    (
        df.write.format("jdbc")
        .option("url", jdbc_url)
        .option("dbtable", table_name)
        .option("user", jdbc_properties["user"])
        .option("password", jdbc_properties["password"])
        .option("driver", jdbc_properties["driver"])
        .mode("append")
        .save()
    )
