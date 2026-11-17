"""The generic query tools, on the real data. Skipped without SANDBOX_DATABASE_URL."""

import os

import pytest

from repo_investigator.levels.query import QueryError, ResultStore, run_query

REPO = "tokio-rs/tokio"


@pytest.fixture(scope="module")
def conn():
    url = os.environ.get("SANDBOX_DATABASE_URL")
    if not url:
        pytest.skip("SANDBOX_DATABASE_URL not set")
    import psycopg

    c = psycopg.connect(url)
    c.read_only = True
    yield c
    c.close()


def q(conn, tool, **args):
    return run_query(conn, ResultStore(), tool, {"repo": REPO, "limit": 200, **args})


def count(conn, tool, filters):
    return q(conn, tool, filters=filters, aggregates=[{"name": "n", "fn": "count"}])["rows"][0][0]


def test_any_of_is_or(conn):
    a = {"column": "event", "op": "eq", "value": "push"}
    b = {"column": "result", "op": "eq", "value": "failure"}
    both = count(conn, "query_ci_runs", [a, b])
    either = count(conn, "query_ci_runs", [{"any_of": [[a], [b]]}])
    assert either == count(conn, "query_ci_runs", [a]) + count(conn, "query_ci_runs", [b]) - both


def test_not_in_leaves_out_empty_values_as_documented(conn):
    total = count(conn, "query_commits", [])
    no_login = count(conn, "query_commits", [{"column": "author", "op": "is_null"}])
    not_in = count(conn, "query_commits", [{"column": "author", "op": "not_in", "value": ["nobody"]}])
    assert not_in == total - no_login


def test_stretches_cover_every_row_and_link_to_the_next(conn):
    filters = [
        {"column": "event", "op": "eq", "value": "push"},
        {"column": "on_default_branch", "op": "eq", "value": True},
    ]
    n = count(conn, "query_ci_runs", filters)
    out = run_query(
        conn,
        ResultStore(),
        "query_ci_runs",
        {
            "repo": REPO,
            "filters": filters,
            "stretches": {"where": [{"column": "result", "op": "eq", "value": "failure"}]},
            "limit": 200,
        },
    )
    store_rows = out["rows"]
    cols = out["columns"]
    assert out["total"] <= 200, "pick a smaller sample"
    i = {c: cols.index(c) for c in ("stretch", "holds", "row_count", "first_run_id", "next_run_id")}
    assert sum(r[i["row_count"]] for r in store_rows) == n
    for a, b in zip(store_rows, store_rows[1:], strict=False):
        assert a[i["holds"]] != b[i["holds"]]
        assert a[i["next_run_id"]] == b[i["first_run_id"]]
    assert store_rows[-1][i["next_run_id"]] is None


def test_add_columns_hours(conn):
    out = q(
        conn,
        "query_pull_requests",
        filters=[{"column": "merged_at", "op": "not_null"}],
        add_columns=[{"name": "h", "hours_between": ["merged_at", "created_at"]}],
        select=["created_at", "merged_at", "h"],
        limit=5,
    )
    from datetime import datetime

    for created, merged, h in out["rows"]:
        t = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
        assert h == pytest.approx((t(merged) - t(created)).total_seconds() / 3600, abs=1e-3)


@pytest.mark.parametrize(
    "args",
    [
        {"filters": [{"column": "nope", "op": "eq", "value": 1}]},
        {"filters": [{"column": "sha", "op": "between", "value": 1}]},
        {"group_by": ["author"], "aggregates": [{"name": "x", "fn": "median", "column": "additions"}]},
        {"stretches": {"order_by": [{"column": "committed_at"}]}},
        {"add_columns": [{"name": "x", "hours_between": ["additions", "deletions"]}]},
        {"limit": 1000},
        {"bogus": 1},
    ],
)
def test_bad_arguments_give_a_clear_error(conn, args):
    with pytest.raises(QueryError):
        q(conn, "query_commits", **args)
