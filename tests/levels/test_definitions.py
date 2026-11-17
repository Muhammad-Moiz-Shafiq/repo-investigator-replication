import pytest

from repo_investigator.levels import definitions as d
from repo_investigator.levels.calculators import fisher_p
from repo_investigator.levels.query import QueryError


def test_period_is_inclusive():
    assert d.period("2024-01-01", "2024-01-31") == ("2024-01-01", "2024-02-01")
    assert d.period("2024-02-28", "2024-02-29") == ("2024-02-28", "2024-03-01")


def test_period_errors():
    with pytest.raises(QueryError):
        d.period("2024-02-01", "2024-01-01")
    with pytest.raises(QueryError):
        d.period("Jan 1", "2024-01-31")


def test_verdict_rules():
    assert d.rate_verdict(10, 100, 30, 100) == "up"
    assert d.backlog_verdict(100, 100) == "balanced"
    assert d.backlog_verdict(200, 50) == "growing"
    assert d.backlog_verdict(50, 200) == "shrinking"
    # A significant change smaller than 5 points is not a change in concentration.
    assert fisher_p(800, 1200, 880, 1120) < 0.05
    assert d.concentration_verdict(800, 2000, 880, 2000) == "no clear change"
    assert d.concentration_verdict(400, 1000, 600, 1000) == "more concentrated"
