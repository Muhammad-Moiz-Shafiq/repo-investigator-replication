import pytest

from repo_investigator.agent.schemas import DateRange
from repo_investigator.agent.tools.compare_periods import compare_periods

PERIOD_A = DateRange(start="2026-09-01", end="2026-09-10")
PERIOD_B = DateRange(start="2026-09-11", end="2026-09-22")


def test_ci_failure_rate_matches_ground_truth(db_conn):
    result = compare_periods(db_conn, "tokio-rs/tokio", "ci_failure_rate", PERIOD_A, PERIOD_B)
    assert result.period_a_value == 0.0524
    assert result.period_b_value == 0.0421


def test_commit_count_matches_ground_truth_and_percent_change_uses_unrounded_values(db_conn):
    result = compare_periods(db_conn, "tokio-rs/tokio", "commit_count", PERIOD_A, PERIOD_B)
    assert result.period_a_value == 36.0
    assert result.period_b_value == 25.0
    assert result.percent_change == round((25 - 36) / 36 * 100, 2)


def test_unsupported_metric_raises_immediately(db_conn):
    with pytest.raises(ValueError, match="Unsupported metric"):
        compare_periods(db_conn, "tokio-rs/tokio", "not_a_real_metric", PERIOD_A, PERIOD_B)
