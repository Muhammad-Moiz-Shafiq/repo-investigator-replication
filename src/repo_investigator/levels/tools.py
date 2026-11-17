"""Tool schemas and the dispatcher for the coverage level tools.

The ReAct loop calls dispatch_fn(conn, name, arguments). make_dispatch gives
each run its own result store and limits it to the tools on that run's menu.
"""

import contextlib
import json
from collections.abc import Callable

import psycopg

from repo_investigator.levels import calculators, domain, fillers
from repo_investigator.levels.query import TABLES, QueryError, ResultStore, run_query

FILTER_HELP = (
    "Each filter is {column, op, value} or {column, op, other_column}. Ops: eq, ne, lt, lte, gt, gte, "
    "in, not_in (value is a list), matches, not_matches (case-insensitive regular expression, \\b is a "
    "word boundary), is_null, not_null (no value), contains (value is in a list column). other_column "
    'compares two columns with eq, ne, lt, lte, gt or gte. All filters in a list must pass. For "or", '
    'use {"any_of": [[filters], [filters]]}: a row passes if every filter in at least one inner list '
    "passes. Dates are UTC, written YYYY-MM-DD (like 2024-01-31). A date alone means the start of that "
    "day (00:00 UTC), so to include all of 2024-01-31 use lt 2024-02-01. As in SQL, a comparison with an "
    "empty value is false, so not_in and ne leave out empty values."
)


def _query_schema(name: str) -> dict:
    t = TABLES[name]
    col_list = ", ".join(f"{c} ({k})" for c, k in t.columns.items())
    filters = {"type": "array", "description": FILTER_HELP, "items": {"type": "object"}}
    order = {
        "type": "array",
        "description": 'Sort order, like [{"column": "started_at", "desc": false}].',
        "items": {"type": "object"},
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                f"{t.description} Columns: {col_list}. Returns one page of rows (default 50, at most 200), "
                "the total number of rows or groups, and a result_id that stands for the full result and "
                "can be passed to the calculators. Steps run in this order: filters, first_per, stretches, "
                "group_by with aggregates, add_columns, post_filters, select, order_by, then the page. Each "
                "step sees the columns the step before it made."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository as owner/name."},
                    "filters": filters,
                    "first_per": {
                        "type": "object",
                        "description": (
                            'Keep only the first row of each group: {"columns": [...], "order_by": [...]}. '
                            "order_by decides which row is first."
                        ),
                    },
                    "stretches": {
                        "type": "object",
                        "description": (
                            "Split the rows, in order, into stretches: runs of consecutive rows where the "
                            '"where" filters all pass, or not. {"where": [...], "order_by": [...], '
                            '"use_rows": [...]}. use_rows (optional) are filters for the rows to use; '
                            "other rows are left out before splitting, so they don't break a stretch. "
                            "Returns one row per stretch: stretch (1, 2, ...), holds (whether where "
                            "passes), row_count, and for each column c: first_c and last_c (from the "
                            "stretch's first and last row) and next_c (from the first row after the "
                            "stretch, empty for the last stretch)."
                        ),
                    },
                    "group_by": {"type": "array", "items": {"type": "string"}},
                    "aggregates": {
                        "type": "array",
                        "description": (
                            "Each is {name, fn, column, where}. fn is count, count_distinct, min, max, sum, "
                            "avg or share (the share of rows that meet where). column is optional for count. "
                            "where is an optional list of filters "
                            "that applies to this aggregate only. Without group_by they give one row of "
                            "totals."
                        ),
                        "items": {"type": "object"},
                    },
                    "add_columns": {
                        "type": "array",
                        "description": (
                            'Computed columns: {"name": "x", "hours_between": ["end", "start"]} (two '
                            'timestamps) or {"name": "x", "sum": ["a", "b"]} (two numbers). They can be used '
                            "in post_filters, select and order_by."
                        ),
                        "items": {"type": "object"},
                    },
                    "post_filters": {
                        "type": "array",
                        "description": (
                            "Filters on the result of the steps before, for example on group columns and "
                            "aggregate names (only groups with at least 20 rows), or on stretch columns."
                        ),
                        "items": {"type": "object"},
                    },
                    "select": {
                        "type": "array",
                        "description": "Columns to return. Default: all columns at that point.",
                        "items": {"type": "string"},
                    },
                    "order_by": order,
                    "limit": {"type": "integer", "description": "Rows in this page, 0 to 200. Default 50."},
                    "offset": {"type": "integer", "description": "Rows to skip, for the next page."},
                },
                "required": ["repo"],
            },
        },
    }


DATA_HELP = (
    'A list of numbers, or a column of an earlier result: {"result_id": "r2", "column": "x"}, '
    '{"result_id": "r2", "hours_between": ["end_column", "start_column"]} or '
    '{"result_id": "r2", "sum": ["column_a", "column_b"]}.'
)

# A calculator's data: a list of numbers, or a column of an earlier result.
DATA_SCHEMA = {
    "description": DATA_HELP,
    "anyOf": [
        {"type": "array", "items": {"type": "number"}},
        {
            "type": "object",
            "properties": {
                "result_id": {"type": "string"},
                "column": {"type": "string"},
                "hours_between": {"type": "array", "items": {"type": "string"}},
                "sum": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["result_id"],
        },
    ],
}

CALCULATOR_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "summarize",
            "description": "Count, min, 25th percentile, median, 75th percentile, max, mean and sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": DATA_SCHEMA,
                    "missing": {
                        "type": "string",
                        "enum": ["drop", "as_infinite"],
                        "description": "What to do with empty values: leave them out (default), or count "
                        "them as infinitely large, for example a time to close for something never closed.",
                    },
                },
                "required": ["data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fisher_test",
            "description": "Two-sided Fisher exact test of whether a rate changed from period A to period B. "
            "Returns both rates, the p-value and the verdict under the rule in the instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count_a": {"type": "integer"},
                    "total_a": {"type": "integer"},
                    "count_b": {"type": "integer"},
                    "total_b": {"type": "integer"},
                },
                "required": ["count_a", "total_a", "count_b", "total_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "binomial_test",
            "description": "Two-sided exact binomial test of whether k out of n differs from one half.",
            "parameters": {
                "type": "object",
                "properties": {"k": {"type": "integer"}, "n": {"type": "integer"}},
                "required": ["k", "n"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_medians",
            "description": "Compares the medians of group A and group B, with the bootstrap rule in the "
            "instructions. Returns both medians, their ratio and the verdict.",
            "parameters": {
                "type": "object",
                "properties": {"a": DATA_SCHEMA, "b": DATA_SCHEMA},
                "required": ["a", "b"],
            },
        },
    },
]

QUERY_SCHEMAS = {name: _query_schema(name) for name in TABLES}
DOMAIN_SCHEMAS = {name: domain.schema(t) for name, t in domain.TOOLS.items()}
FILLER_SCHEMAS = {name: fillers.schema(name) for name in fillers.FILLERS}
ALL_SCHEMAS = {
    **QUERY_SCHEMAS,
    **DOMAIN_SCHEMAS,
    **FILLER_SCHEMAS,
    **{s["function"]["name"]: s for s in CALCULATOR_SCHEMAS},
}
CALCULATORS = [s["function"]["name"] for s in CALCULATOR_SCHEMAS]


# Arguments that hold a list or an object. Some models send these as JSON text
# ("[1, 2]" instead of [1, 2]). The content is right, so it is decoded, the
# same way for every tool and every model. Plain text arguments are never touched.
STRUCTURED = {
    "filters", "post_filters", "first_per", "stretches", "group_by", "aggregates", "add_columns",
    "select", "order_by", "data", "a", "b", "workflow_paths", "authors",
}  # fmt: skip


def decode_structured(args: dict) -> dict:
    out = dict(args)
    for k, v in args.items():
        if k in STRUCTURED and isinstance(v, str) and v.strip()[:1] in "[{":
            # Left as it is if it doesn't parse; the tool's own check then explains what's wrong.
            with contextlib.suppress(json.JSONDecodeError):
                out[k] = json.loads(v)
    return out


def call_tool(conn: psycopg.Connection, store: ResultStore, name: str, args: dict) -> dict:
    args = decode_structured(args)
    if name in TABLES:
        return run_query(conn, store, name, args)
    if name in domain.TOOLS:
        return domain.call(conn, store, name, args)
    if name in fillers.FILLERS:
        return fillers.call(conn, store, name, args)
    if name == "summarize":
        return calculators.summarize(store, args.get("data"), args.get("missing", "drop"))
    if name == "fisher_test":
        return calculators.fisher_test(
            **{k: args.get(k) for k in ("count_a", "total_a", "count_b", "total_b")}
        )
    if name == "binomial_test":
        return calculators.binomial_test(args.get("k"), args.get("n"))
    if name == "compare_medians":
        return calculators.compare_medians(store, args.get("a"), args.get("b"))
    raise QueryError(f"Unknown tool {name!r}.")


def make_dispatch(menu: list[str]) -> tuple[Callable[[psycopg.Connection, str, dict], dict], ResultStore]:
    """A dispatch function for one run, limited to the tools on its menu, with its own result store."""
    store = ResultStore()

    def dispatch(conn: psycopg.Connection, name: str, args: dict) -> dict:
        if name not in menu:
            return {"error": f"Unknown tool {name!r}. Tools: {', '.join(menu)}."}
        try:
            return call_tool(conn, store, name, args or {})
        except QueryError as e:
            return {"error": str(e)}

    return dispatch, store
