from datetime import date

from repo_investigator.agent.tools.query_contributor_associations import query_contributor_associations


def test_reports_real_computed_window_not_the_requested_one(db_conn):
    # Deliberately pass a date range nowhere near the real data -- the tool
    # must not pretend it honored this narrow window; it should report what
    # was ACTUALLY computed (the full ingested window).
    result = query_contributor_associations(db_conn, "tokio-rs/tokio", date(2020, 1, 1), date(2020, 1, 2))
    assert str(result.computed_window_start) == "2025-09-29"
    assert str(result.computed_window_end) == "2026-09-23"


def test_top_contributor_matches_ground_truth(db_conn):
    result = query_contributor_associations(db_conn, "tokio-rs/tokio", date(2020, 1, 1), date(2020, 1, 2))
    top = result.contributors[0]
    assert top.author_login == "KR-bluejay"
    assert top.commit_count == 2
    assert top.association_rate == 1.0


def test_association_rate_never_exceeds_one(db_conn):
    # Regression test for a real bug: an earlier metric definition could
    # produce rates like 17.0 (see data_engineering_log.md). The corrected
    # definition is bounded [0, 1] by construction.
    result = query_contributor_associations(db_conn, "tokio-rs/tokio", date(2020, 1, 1), date(2020, 1, 2))
    assert all(0 <= c.association_rate <= 1 for c in result.contributors)
