"""The four calculators, the same at every coverage level and in both variants.

They read no table. Each takes short lists of numbers, or a reference to a
column of an earlier query result, so the agent never copies hundreds of
numbers into a call. The tests and the rules match
scripts/answer_keys/compute_keys.py exactly, and tests/levels/test_calculators.py
checks that they give the same answers.
"""

import math
from datetime import datetime
from math import comb

import numpy as np

from repo_investigator.levels.query import QueryError, ResultStore

N_BOOT, SEED = 4000, 7


def _time(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) else v


def values(store: ResultStore, ref, missing: str = "drop") -> list[float]:
    """Numbers from a list, or from {"result_id", "column"} or {"result_id", "hours_between": [end, start]}
    or {"result_id", "sum": [a, b]}. Missing values are dropped, or counted as infinite."""
    if isinstance(ref, list):
        raw = ref
    elif isinstance(ref, dict) and "result_id" in ref:
        rid = ref["result_id"]
        if "column" in ref:
            raw = store.column(rid, ref["column"])
        elif "hours_between" in ref:
            end, start = ref["hours_between"]
            raw = [
                None if a is None or b is None else (_time(a) - _time(b)).total_seconds() / 3600
                for a, b in zip(store.column(rid, end), store.column(rid, start), strict=True)
            ]
        elif "sum" in ref:
            x, y = ref["sum"]
            raw = [
                None if a is None or b is None else a + b
                for a, b in zip(store.column(rid, x), store.column(rid, y), strict=True)
            ]
        else:
            raise QueryError(
                "A result reference needs 'column', 'hours_between' [end, start] or 'sum' [a, b]."
            )
    else:
        raise QueryError("Give a list of numbers, or {'result_id': ..., 'column': ...}.")
    if missing not in ("drop", "as_infinite"):
        raise QueryError("'missing' must be 'drop' or 'as_infinite'.")
    out = []
    for v in raw:
        if v is None:
            if missing == "as_infinite":
                out.append(math.inf)
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError) as e:
            raise QueryError(f"Not a number: {v!r}.") from e
    return out


def _num(x):
    if x is None:
        return None
    return "infinite" if math.isinf(x) else round(float(x), 6)


def percentile(sorted_values, q):
    """Linear percentile, the numpy default, written out so that infinite values
    work: numpy gives nan between two infinite values, even when the answer is finite."""
    pos = (len(sorted_values) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    a, b = sorted_values[lo], sorted_values[hi]
    if lo == hi or a == b:
        return a
    return a + (b - a) * (pos - lo)


def summarize(store, data, missing="drop") -> dict:
    v = values(store, data, missing)
    if not v:
        return {"n": 0}
    a = np.asarray(v)
    finite = a[np.isfinite(a)]
    return {
        "n": len(v),
        "n_infinite": int(len(a) - len(finite)),
        "min": _num(a.min()),
        "p25": _num(percentile(sorted(v), 25)),
        "median": _num(percentile(sorted(v), 50)),
        "p75": _num(percentile(sorted(v), 75)),
        "max": _num(a.max()),
        "mean": _num(finite.mean()) if len(finite) else None,
        "sum": _num(finite.sum()) if len(finite) else None,
    }


def fisher_p(a, b, c, d):
    n, r1, c1 = a + b + c + d, a + b, a + c
    if n == 0:
        return 1.0

    def p(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    obs = p(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def fisher_test(count_a: int, total_a: int, count_b: int, total_b: int) -> dict:
    """Did a rate change from period A to period B? Two-sided Fisher exact test."""
    for x in (count_a, total_a, count_b, total_b):
        if not isinstance(x, int) or x < 0:
            raise QueryError("All four arguments must be whole numbers, 0 or more.")
    if count_a > total_a or count_b > total_b or not total_a or not total_b:
        raise QueryError("Each count must be at most its total, and totals must be above 0.")
    p = fisher_p(count_a, total_a - count_a, count_b, total_b - count_b)
    ra, rb = count_a / total_a, count_b / total_b
    verdict = "no clear change" if p >= 0.05 else ("up" if rb > ra else "down")
    return {"rate_a": round(ra, 6), "rate_b": round(rb, 6), "p_value": round(p, 6), "verdict": verdict}


def binom_p(k, n):
    probs = [comb(n, i) / 2**n for i in range(n + 1)]
    return min(1.0, sum(p for p in probs if p <= probs[k] * (1 + 1e-9)))


def binomial_test(k: int, n: int) -> dict:
    """Is k out of n different from half? Two-sided exact binomial test."""
    if not isinstance(k, int) or not isinstance(n, int) or not 0 <= k <= n or n == 0:
        raise QueryError("Need whole numbers with 0 <= k <= n and n above 0.")
    p = binom_p(k, n)
    return {"k": k, "n": n, "share": round(k / n, 6), "p_value": round(p, 6), "differs_from_half": p < 0.05}


def median_verdict(a, b, n_boot=N_BOOT, seed=SEED):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 10 or len(b) < 10:
        return "too few"
    rng = np.random.default_rng(seed)
    boot_a = np.median(rng.choice(a, (n_boot, len(a))), axis=1)
    boot_b = np.median(rng.choice(b, (n_boot, len(b))), axis=1)
    lo, hi = np.percentile(boot_b / np.maximum(boot_a, 1e-9), [2.5, 97.5])
    ratio = np.median(b) / np.median(a) if np.median(a) else math.inf
    if lo > 1 and ratio >= 1.2:
        return "up"
    if hi < 1 and ratio <= 1 / 1.2:
        return "down"
    return "no clear change"


def compare_medians(store, a, b) -> dict:
    """Did the median change from group A to group B? Bootstrap rule from the system prompt."""
    va, vb = values(store, a), values(store, b)
    if not va or not vb:
        raise QueryError("Both groups need at least one number.")
    ma, mb = float(np.median(va)), float(np.median(vb))
    return {
        "n_a": len(va),
        "n_b": len(vb),
        "median_a": _num(ma),
        "median_b": _num(mb),
        "ratio": _num(mb / ma) if ma else None,
        "verdict": median_verdict(va, vb),
    }
