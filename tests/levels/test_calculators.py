import json
import math
import random

import numpy as np
import pytest

from repo_investigator.levels import calculators as c
from repo_investigator.levels.query import QueryError, ResultStore


def test_percentile_matches_numpy_on_finite_lists():
    rng = random.Random(1)
    for _ in range(500):
        v = sorted(rng.random() * 100 for _ in range(rng.randint(1, 40)))
        for q in (0, 25, 50, 75, 100):
            assert c.percentile(v, q) == pytest.approx(np.percentile(v, q))


def test_percentile_next_to_infinite_values():
    # numpy gives nan here; the answer is 2.
    v = [1.0, 2.0, math.inf, math.inf, math.inf]
    assert c.percentile(v, 25) == 2.0
    assert c.percentile(v, 75) == math.inf
    s = c.summarize(ResultStore(), [1, 2, None, None, None], "as_infinite")
    assert (s["p25"], s["median"], s["p75"], s["n_infinite"]) == (2.0, "infinite", "infinite", 3)


def test_missing_values_dropped_by_default():
    assert c.summarize(ResultStore(), [1, None, 3])["n"] == 2


def test_result_references():
    store = ResultStore()
    rid = store.add(["a", "b", "t0", "t1"], [[1, 2, "2024-01-01T00:00:00Z", "2024-01-01T06:00:00Z"]])
    assert c.values(store, {"result_id": rid, "sum": ["a", "b"]}) == [3.0]
    assert c.values(store, {"result_id": rid, "hours_between": ["t1", "t0"]}) == [6.0]
    with pytest.raises(QueryError):
        c.values(store, {"result_id": "r99", "column": "a"})


def test_fisher_and_binomial_known_values():
    # Two-sided Fisher exact p for [[3, 1], [1, 3]] is 0.4857.
    assert c.fisher_p(3, 1, 1, 3) == pytest.approx(0.485714, abs=1e-6)
    assert c.fisher_test(10, 100, 30, 100)["verdict"] == "up"
    assert c.fisher_test(10, 100, 11, 100)["verdict"] == "no clear change"
    assert c.binom_p(5, 10) == pytest.approx(1.0)
    assert c.binomial_test(1, 20)["differs_from_half"] is True


def test_median_rule():
    assert c.median_verdict(list(range(5)), list(range(50))) == "too few"
    a = [10.0 + i % 3 for i in range(50)]
    assert c.median_verdict(a, [x * 2 for x in a]) == "up"
    assert c.median_verdict(a, [x * 1.05 for x in a]) == "no clear change"
    assert c.compare_medians(ResultStore(), a, [x / 2 for x in a])["verdict"] == "down"


def test_bad_arguments():
    with pytest.raises(QueryError):
        c.fisher_test(5, 3, 1, 2)
    with pytest.raises(QueryError):
        c.binomial_test(3, 2)


def test_json_text_arguments_are_decoded():
    from repo_investigator.levels.tools import call_tool

    store = ResultStore()
    out = call_tool(None, store, "summarize", {"data": "[1, 2, 3]"})
    assert out["median"] == 2.0
    rid = store.add(["x"], [[1], [2], [3], [4]])
    out = call_tool(None, store, "summarize", {"data": json.dumps({"result_id": rid, "column": "x"})})
    assert out["n"] == 4


def test_calculator_schemas_are_typed():
    from repo_investigator.levels.tools import ALL_SCHEMAS

    for name, params in (("summarize", ["data"]), ("compare_medians", ["a", "b"])):
        props = ALL_SCHEMAS[name]["function"]["parameters"]["properties"]
        for p in params:
            assert "anyOf" in props[p]
