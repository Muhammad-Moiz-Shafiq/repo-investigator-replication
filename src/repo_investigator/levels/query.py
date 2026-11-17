"""Generic query tools for coverage level 2.

One tool per table. Every tool takes the same kind of arguments, modeled on
PostgREST (the API Supabase puts on every table): filters, column choice,
ordering, paging, exact counts, linked fields, basic aggregates and "any of"
filters. On top of that, a few generic additions, each a standard SQL feature:
comparing two columns, keeping the first row per group (DISTINCT ON), a
condition on a single aggregate (FILTER), consecutive stretches of rows (the
"gaps and islands" pattern, with window functions), computed columns, and a
result id for every query that the calculators accept.

Nothing here knows about any study question. There are no question-specific
filters, names or thresholds; tests/levels/test_query.py checks that.

Each table declares the database tables it reads, so the level 3 test can
prove a removed table is really out of reach.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql

WORKFLOWS_FILE = Path(__file__).parent.parent.parent.parent / "tool_data" / "workflows.json"
MAX_PAGE = 200
DEFAULT_PAGE = 50


@dataclass(frozen=True)
class Table:
    tool: str
    description: str
    columns: dict[str, str]  # name -> short type, shown to the agent
    reads: tuple[str, ...]
    view: str  # a SELECT for one repo, using %(repo_id)s
    natural_order: tuple[str, ...]


def _folder(n: int) -> str:
    # The first n folders of a path, only when the file sits inside them.
    return (
        f"case when array_length(string_to_array(f.filename, '/'), 1) > {n} "
        f"then array_to_string((string_to_array(f.filename, '/'))[1:{n}], '/') end"
    )


TABLES = {
    t.tool: t
    for t in [
        Table(
            tool="query_ci_runs",
            description=(
                "CI workflow runs (GitHub Actions). One row per run, with its latest attempt. "
                "on_default_branch is true when the run's commit is on the default branch."
            ),
            columns={
                "run_id": "integer",
                "workflow_id": "integer",
                "workflow_name": "text",
                "commit_sha": "text",
                "event": "text",
                "result": "text",
                "attempt": "integer",
                "started_at": "timestamp",
                "finished_at": "timestamp",
                "duration_seconds": "integer",
                "on_default_branch": "boolean",
            },
            reads=("ci_runs", "commits"),
            view="""
                select ci.id run_id, ci.workflow_id, ci.workflow_name, ci.commit_sha, ci.event,
                       ci.conclusion result, ci.run_attempt attempt, ci.started_at,
                       ci.completed_at finished_at, ci.duration_seconds,
                       exists (select 1 from commits c
                               where c.sha = ci.commit_sha and c.repo_id = ci.repo_id) on_default_branch
                from ci_runs ci where ci.repo_id = %(repo_id)s
            """,
            natural_order=("started_at", "run_id"),
        ),
        Table(
            tool="query_commits",
            description=(
                "Commits on the default branch. author is the GitHub login, empty when the commit's "
                "email is not linked to a GitHub account. subject is the first line of the message. "
                "total_lines is lines added plus lines deleted."
            ),
            columns={
                "sha": "text",
                "author": "text",
                "author_email": "text",
                "committed_at": "timestamp",
                "subject": "text",
                "additions": "integer",
                "deletions": "integer",
                "total_lines": "integer",
                "is_merge": "boolean",
            },
            reads=("commits",),
            view="""
                select c.sha, c.author_login author, c.author_email, c.committed_at,
                       split_part(c.message, E'\\n', 1) subject, c.additions, c.deletions,
                       c.additions + c.deletions total_lines, c.is_merge
                from commits c where c.repo_id = %(repo_id)s
            """,
            natural_order=("committed_at", "sha"),
        ),
        Table(
            tool="query_commit_files",
            description=(
                "Files changed by commits on the default branch, one row per commit and file, with "
                "fields of the commit. folder1, folder2 and folder3 are the first one, two or three "
                "folders of the path (for lib/rules/x.js: lib, lib/rules, and empty), empty when the "
                "file is not that deep."
            ),
            columns={
                "commit_sha": "text",
                "filename": "text",
                "folder1": "text",
                "folder2": "text",
                "folder3": "text",
                "additions": "integer",
                "deletions": "integer",
                "commit_author": "text",
                "commit_author_email": "text",
                "committed_at": "timestamp",
                "commit_subject": "text",
                "commit_is_merge": "boolean",
            },
            reads=("commit_files", "commits"),
            view=f"""
                select f.commit_sha, f.filename, {_folder(1)} folder1, {_folder(2)} folder2,
                       {_folder(3)} folder3, f.additions, f.deletions, c.author_login commit_author,
                       c.author_email commit_author_email, c.committed_at,
                       split_part(c.message, E'\\n', 1) commit_subject,
                       c.is_merge commit_is_merge
                from commit_files f join commits c on c.sha = f.commit_sha
                where c.repo_id = %(repo_id)s
            """,
            natural_order=("committed_at", "commit_sha", "filename"),
        ),
        Table(
            tool="query_pull_requests",
            description="Pull requests. merged_at is empty if never merged, closed_at if never closed.",
            columns={
                "number": "integer",
                "title": "text",
                "author": "text",
                "created_at": "timestamp",
                "merged_at": "timestamp",
                "closed_at": "timestamp",
            },
            reads=("pull_requests",),
            view="""
                select p.number, p.title, p.author_login author, p.created_at, p.merged_at, p.closed_at
                from pull_requests p where p.repo_id = %(repo_id)s
            """,
            natural_order=("created_at", "number"),
        ),
        Table(
            tool="query_pr_reviews",
            description=(
                "Submitted pull request reviews, one row per review, with fields of the reviewed PR. "
                "state is APPROVED, COMMENTED, CHANGES_REQUESTED or DISMISSED."
            ),
            columns={
                "pr_number": "integer",
                "reviewer": "text",
                "state": "text",
                "submitted_at": "timestamp",
                "pr_author": "text",
                "pr_created_at": "timestamp",
                "pr_merged_at": "timestamp",
            },
            reads=("pr_reviews", "pull_requests"),
            view="""
                select v.pr_number, v.reviewer_login reviewer, v.state, v.submitted_at,
                       p.author_login pr_author, p.created_at pr_created_at, p.merged_at pr_merged_at
                from pr_reviews v
                left join pull_requests p on p.repo_id = v.repo_id and p.number = v.pr_number
                where v.repo_id = %(repo_id)s
            """,
            natural_order=("submitted_at", "pr_number"),
        ),
        Table(
            tool="query_issues",
            description="Issues (not pull requests). labels is a list of label names.",
            columns={
                "number": "integer",
                "title": "text",
                "author": "text",
                "labels": "list of text",
                "created_at": "timestamp",
                "closed_at": "timestamp",
            },
            reads=("issues",),
            view="""
                select i.number, i.title, i.author_login author, i.labels, i.created_at, i.closed_at
                from issues i where i.repo_id = %(repo_id)s
            """,
            natural_order=("created_at", "number"),
        ),
        Table(
            tool="query_workflows",
            description=(
                "CI workflows of the repository: id, name and file path. Names can repeat, the "
                "path is unique."
            ),
            columns={"id": "integer", "name": "text", "path": "text"},
            reads=("workflows_snapshot",),
            view="""
                select (w->>'id')::bigint id, w->>'name' name, w->>'path' path
                from jsonb_array_elements(%(workflows)s::jsonb) w
            """,
            natural_order=("id",),
        ),
    ]
}

VALUE_OPS = {
    "eq": "=",
    "ne": "<>",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
}
AGG_FNS = {"count", "count_distinct", "min", "max", "sum", "avg", "share"}
SQL_TYPES = {
    "number": "double precision",
    "integer": "bigint",
    "text": "text",
    "timestamp": "timestamptz",
    "boolean": "boolean",
    "list of text": "text",
}


class QueryError(ValueError):
    """A bad argument from the agent. Its message goes back to the agent."""


@dataclass
class ResultStore:
    """Full results of one agent run, by id, for the calculators."""

    results: dict[str, dict] = field(default_factory=dict)

    def add(self, columns: list[str], rows: list[list]) -> str:
        rid = f"r{len(self.results) + 1}"
        self.results[rid] = {"columns": columns, "rows": rows}
        return rid

    def column(self, rid: str, name: str) -> list:
        if rid not in self.results:
            raise QueryError(f"Unknown result id {rid!r}. Known ids: {', '.join(self.results) or 'none'}.")
        res = self.results[rid]
        if name not in res["columns"]:
            raise QueryError(
                f"Result {rid} has no column {name!r}. Its columns: {', '.join(res['columns'])}."
            )
        i = res["columns"].index(name)
        return [row[i] for row in res["rows"]]


def _pattern(p: str) -> str:
    # Postgres regex uses \y for a word boundary, where most regex flavors use \b
    # (which Postgres reads as a backspace). Accept the usual spelling.
    return re.sub(r"(?<!\\)\\b", r"\\y", p)


class Params(dict):
    """Named query values, so their order in the SQL text never matters."""

    def add(self, value) -> sql.Composable:
        name = f"p{len(self)}"
        self[name] = value
        return sql.Placeholder(name)


def _filter_sql(f: dict, columns: dict[str, str], params: Params) -> sql.Composable:
    if isinstance(f, dict) and set(f) == {"any_of"}:
        groups = f["any_of"]
        if not isinstance(groups, list) or not groups:
            raise QueryError("'any_of' needs a list of filter lists: a row passes if any list passes.")
        parts = []
        for g in groups:
            g = g if isinstance(g, list) else [g]
            if not g:
                raise QueryError("Each list inside 'any_of' needs at least one filter.")
            parts.append(sql.SQL("({})").format(_conditions(g, columns, params)))
        return sql.SQL("({})").format(sql.SQL(" or ").join(parts))
    if not isinstance(f, dict) or "column" not in f or "op" not in f:
        raise QueryError(
            f"Each filter needs 'column' and 'op', or is {{'any_of': [[...], [...]]}}. Got {f!r}."
        )
    col, op = f["column"], f["op"]
    if col not in columns:
        raise QueryError(f"No column {col!r}. Columns: {', '.join(columns)}.")
    ident = sql.Identifier(col)
    if "other_column" in f:
        other = f["other_column"]
        if other not in columns:
            raise QueryError(f"No column {other!r}. Columns: {', '.join(columns)}.")
        if op not in VALUE_OPS:
            raise QueryError(f"Comparing two columns supports {', '.join(VALUE_OPS)}. Got {op!r}.")
        return sql.SQL("{} {} {}").format(ident, sql.SQL(VALUE_OPS[op]), sql.Identifier(other))
    if op in ("is_null", "not_null"):
        return sql.SQL("{} is null" if op == "is_null" else "{} is not null").format(ident)
    if "value" not in f:
        raise QueryError(f"Filter on {col!r} with op {op!r} needs a 'value'.")
    value = f["value"]
    # Values are cast to the column's type, so 42, "42", true and "true" all work.
    cast = sql.SQL(SQL_TYPES[columns[col]])
    if op in VALUE_OPS:
        if isinstance(value, (list, dict)):
            raise QueryError(f"Op {op!r} needs a single value, not a list.")
        return sql.SQL("{} {} {}::{}").format(ident, sql.SQL(VALUE_OPS[op]), params.add(str(value)), cast)
    if op in ("in", "not_in"):
        if not isinstance(value, list):
            raise QueryError(f"Op {op!r} needs a list value.")
        template = "{} = any({}::{}[])" if op == "in" else "not ({} = any({}::{}[]))"
        return sql.SQL(template).format(ident, params.add([str(v) for v in value]), cast)
    if op in ("matches", "not_matches"):
        template = "{} ~* {}" if op == "matches" else "{} !~* {}"
        return sql.SQL(template).format(ident, params.add(_pattern(str(value))))
    if op == "contains":
        if columns[col] != "list of text":
            raise QueryError(f"Op 'contains' only works on list columns. {col!r} is {columns[col]}.")
        return sql.SQL("{}::text = any({})").format(params.add(str(value)), ident)
    raise QueryError(
        f"Unknown op {op!r}. Ops: {', '.join([*VALUE_OPS, 'in', 'not_in', 'matches', 'not_matches'])}, "
        "is_null, not_null, contains."
    )


def _conditions(filters, columns, params) -> sql.Composable | None:
    if not filters:
        return None
    if isinstance(filters, dict):
        filters = [filters]  # one filter given on its own
    if not isinstance(filters, list):
        raise QueryError("'filters' must be a list of filters.")
    return sql.SQL(" and ").join(_filter_sql(f, columns, params) for f in filters)


def _where(filters, columns, params) -> sql.Composable:
    cond = _conditions(filters, columns, params)
    return sql.SQL(" where ") + cond if cond else sql.SQL("")


def _order_items(order_by, allowed: list[str], default: tuple[str, ...]) -> list[sql.Composable]:
    items = order_by or [{"column": c} for c in default if c in allowed]
    if not isinstance(items, list):
        raise QueryError("'order_by' must be a list like [{'column': 'x', 'desc': true}].")
    parts = []
    for o in items:
        name = o.get("column") if isinstance(o, dict) else None
        if name not in allowed:
            raise QueryError(f"Can't order by {name!r}. Allowed: {', '.join(allowed)}.")
        direction = sql.SQL("desc" if o.get("desc") else "asc")
        parts.append(sql.SQL("{} {} nulls last").format(sql.Identifier(name), direction))
    return parts


def _order(order_by, allowed: list[str], default: tuple[str, ...]) -> sql.Composable:
    parts = _order_items(order_by, allowed, default)
    return sql.SQL(" order by ") + sql.SQL(", ").join(parts) if parts else sql.SQL("")


def _plain(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def resolve_repo(conn: psycopg.Connection, repo: str) -> tuple[int, str]:
    owner, _, name = repo.rpartition("/")
    row = conn.execute(
        "select id, name from repos where name = %s and (%s = '' or owner = %s)", (name, owner, owner)
    ).fetchone()
    if row is None:
        known = ", ".join(f"{o}/{n}" for o, n in conn.execute("select owner, name from repos order by name"))
        raise QueryError(f"Unknown repo {repo!r}. Known repos: {known}.")
    return row


KNOWN_ARGS = (
    "repo",
    "filters",
    "first_per",
    "stretches",
    "group_by",
    "aggregates",
    "add_columns",
    "post_filters",
    "select",
    "order_by",
    "limit",
    "offset",
)


def _check_keys(name: str, spec, allowed: set[str], required: set[str]) -> None:
    if not isinstance(spec, dict):
        raise QueryError(f"'{name}' must be an object with {', '.join(sorted(allowed))}.")
    unknown, missing = set(spec) - allowed, required - set(spec)
    if unknown or missing:
        raise QueryError(
            f"'{name}' takes {', '.join(sorted(allowed))}"
            + (f"; {', '.join(sorted(required))} required" if required else "")
            + f". Got {', '.join(sorted(spec)) or 'nothing'}."
        )


def _first_per(query, types, spec, natural_order, params):
    _check_keys("first_per", spec, {"columns", "order_by"}, {"columns"})
    group = spec["columns"]
    if not isinstance(group, list) or not group:
        raise QueryError("'first_per' needs 'columns' (the group) and 'order_by' (which row is first).")
    for c in group:
        if c not in types:
            raise QueryError(f"No column {c!r}. Columns: {', '.join(types)}.")
    keys = [sql.Identifier(c) for c in group]
    order = keys + _order_items(spec.get("order_by"), list(types), natural_order)
    return sql.SQL("select distinct on ({}) * from ({}) q order by {}").format(
        sql.SQL(", ").join(keys), query, sql.SQL(", ").join(order)
    )


def _stretches(query, types, spec, natural_order, params):
    """Split the rows, in order, into stretches where the condition holds or doesn't
    (gaps and islands). One row per stretch, with its first and last row and the
    first row of the next stretch."""
    _check_keys("stretches", spec, {"where", "order_by", "use_rows"}, {"where"})
    inner = sql.SQL("select * from ({}) q").format(query) + _where(spec.get("use_rows"), types, params)
    cond = _conditions(spec["where"], types, params)
    if cond is None:
        raise QueryError("'stretches' needs 'where': the condition that defines a stretch.")
    order_cols = [o["column"] for o in spec.get("order_by") or [] if isinstance(o, dict)]
    # Ties are broken by the table's natural order, so the result never depends on chance.
    ties = [{"column": c} for c in natural_order if c in types and c not in order_cols]
    order = sql.SQL(", ").join(
        _order_items([*(spec.get("order_by") or []), *ties], list(types), natural_order)
    )
    kept = [c for c, k in types.items() if k != "list of text"]
    firsts = [
        sql.SQL(
            "(array_agg({c} order by {o}))[1] as {f}, (array_agg({c} order by {o}))[count(*)] as {l}"
        ).format(c=sql.Identifier(c), o=order, f=sql.Identifier(f"first_{c}"), l=sql.Identifier(f"last_{c}"))
        for c in kept
    ]
    nexts = [
        sql.SQL("lead({}) over (order by stretch) as {}").format(
            sql.Identifier(f"first_{c}"), sql.Identifier(f"next_{c}")
        )
        for c in kept
    ]
    query = sql.SQL(
        """select * from (
        with x as (select *, coalesce(({cond}), false) as __holds from ({inner}) q),
        y as (select *, __holds is distinct from lag(__holds) over (order by {o}) as __change from x),
        z as (select *, count(*) filter (where __change)
                over (order by {o} rows between unbounded preceding and current row) as __stretch from y),
        g as (select __stretch as stretch, bool_and(__holds) as holds, count(*) as row_count, {firsts}
              from z group by __stretch)
        select *, {nexts} from g) st"""
    ).format(
        cond=cond, inner=inner, o=order, firsts=sql.SQL(", ").join(firsts), nexts=sql.SQL(", ").join(nexts)
    )
    out = {"stretch": "integer", "holds": "boolean", "row_count": "integer"}
    for prefix in ("first", "last", "next"):
        out |= {f"{prefix}_{c}": types[c] for c in kept}
    return query, out


def _group(query, types, group_by, aggs, params):
    for c in group_by:
        if not isinstance(c, str):
            raise QueryError(f"'group_by' is a list of column names, like ['author']. Got {c!r}.")
        if c not in types:
            raise QueryError(f"Can't group by {c!r}. Columns: {', '.join(types)}.")
    select_parts = [sql.Identifier(c) for c in group_by]
    out = {c: types[c] for c in group_by}
    for a in aggs or [{"name": "count", "fn": "count"}]:
        if not isinstance(a, dict):
            raise QueryError("Each aggregate is an object: {name, fn, column, where}.")
        fn, name, col = a.get("fn"), a.get("name") or a.get("fn"), a.get("column")
        if fn not in AGG_FNS:
            raise QueryError(f"Unknown aggregate {fn!r}. Aggregates: {', '.join(sorted(AGG_FNS))}.")
        if col is not None and col not in types:
            raise QueryError(f"No column {col!r}. Columns: {', '.join(types)}.")
        if fn not in ("count", "share") and col is None:
            raise QueryError(f"Aggregate {fn!r} needs a 'column'.")
        if fn == "share" and not a.get("where"):
            raise QueryError("Aggregate 'share' needs a 'where': the share of rows that meet it.")
        if name in out or name in types:
            raise QueryError(f"Aggregate name {name!r} is already used. Give each aggregate its own 'name'.")
        if fn in ("count", "share"):
            expr = sql.SQL("count({})").format(sql.Identifier(col)) if col else sql.SQL("count(*)")
        elif fn == "count_distinct":
            expr = sql.SQL("count(distinct {})").format(sql.Identifier(col))
        else:
            expr = sql.SQL("{}({})").format(sql.SQL(fn), sql.Identifier(col))
        cond = _conditions(a.get("where"), types, params)
        if fn == "share":
            expr = sql.SQL("(count(*) filter (where {}))::float / count(*)").format(cond)
        elif cond:
            expr = sql.SQL("{} filter (where {})").format(expr, cond)
        out[name] = (
            "integer"
            if fn in ("count", "count_distinct")
            else types[col]
            if fn in ("min", "max")
            else "number"
        )
        select_parts.append(sql.SQL("{} as {}").format(expr, sql.Identifier(name)))
    query = sql.SQL("select {} from ({}) g{}").format(
        sql.SQL(", ").join(select_parts),
        query,
        sql.SQL(" group by ") + sql.SQL(", ").join(map(sql.Identifier, group_by))
        if group_by
        else sql.SQL(""),
    )
    return query, out


def _add_columns(query, types, specs):
    if not isinstance(specs, list):
        raise QueryError(
            "'add_columns' must be a list like [{'name': 'x', 'hours_between': ['end', 'start']}]."
        )
    parts, out = [], dict(types)
    for spec in specs:
        if not isinstance(spec, dict) or "name" not in spec or len(spec) != 2:
            raise QueryError(
                "Each added column is {name, hours_between: [end, start]} or {name, sum: [a, b]}."
            )
        name = spec["name"]
        if name in out:
            raise QueryError(f"Column name {name!r} is already used.")
        kind = next(k for k in spec if k != "name")
        pair = spec[kind]
        if kind not in ("hours_between", "sum") or not isinstance(pair, list) or len(pair) != 2:
            raise QueryError(
                "Each added column is {name, hours_between: [end, start]} or {name, sum: [a, b]}."
            )
        for c in pair:
            if c not in types:
                raise QueryError(f"No column {c!r}. Columns: {', '.join(types)}.")
        a, b = map(sql.Identifier, pair)
        if kind == "hours_between":
            if any(types[c] != "timestamp" for c in pair):
                raise QueryError("'hours_between' needs two timestamp columns.")
            expr = sql.SQL("extract(epoch from ({} - {})) / 3600").format(a, b)
        else:
            if any(types[c] not in ("integer", "number") for c in pair):
                raise QueryError("'sum' needs two number columns.")
            expr = sql.SQL("({} + {})").format(a, b)
        parts.append(sql.SQL("{} as {}").format(expr, sql.Identifier(name)))
        out[name] = "number"
    return sql.SQL("select *, {} from ({}) a").format(sql.SQL(", ").join(parts), query), out


def run_query(conn: psycopg.Connection, store: ResultStore, tool: str, args: dict) -> dict:
    """Run one generic query and return one page of it, plus a result id for the full result.

    Steps run in a fixed order: filters, first_per, stretches, group_by with
    aggregates, add_columns, post_filters, select, order_by, then the page.
    Each step after the first sees the columns the step before it made."""
    table = TABLES[tool]
    unknown = set(args) - set(KNOWN_ARGS)
    if unknown:
        raise QueryError(
            f"Unknown argument(s) {', '.join(sorted(unknown))}. Arguments: {', '.join(KNOWN_ARGS)}."
        )
    if "repo" not in args:
        raise QueryError("'repo' is required, like 'owner/name'.")
    # Dates in filters are read as UTC, like every timestamp shown.
    conn.execute("set time zone 'UTC'")
    repo_id, repo_name = resolve_repo(conn, args["repo"])
    params = Params()
    workflows = "[]"
    if tool == "query_workflows":
        listed = json.loads(WORKFLOWS_FILE.read_text())["repos"][repo_name]["workflows"]
        workflows = json.dumps([{k: w[k] for k in ("id", "name", "path")} for w in listed])
    base = sql.SQL(
        table.view.replace("%(repo_id)s", "{repo_id}").replace("%(workflows)s", "{workflows}")
    ).format(repo_id=sql.Literal(repo_id), workflows=sql.Literal(workflows))
    types = dict(table.columns)
    default_order = table.natural_order
    query = sql.SQL("select * from ({}) base").format(base) + _where(args.get("filters"), types, params)

    if args.get("first_per"):
        query = _first_per(query, types, args["first_per"], table.natural_order, params)
    if args.get("stretches"):
        query, types = _stretches(query, types, args["stretches"], table.natural_order, params)
        default_order = ("stretch",)
    group_by, aggs = args.get("group_by") or [], args.get("aggregates") or []
    if group_by or aggs:
        if not isinstance(group_by, list) or not isinstance(aggs, list):
            raise QueryError("'group_by' and 'aggregates' must be lists.")
        query, types = _group(query, types, group_by, aggs, params)
        default_order = tuple(group_by)
    if args.get("add_columns"):
        query, types = _add_columns(query, types, args["add_columns"])
    query = sql.SQL("select * from ({}) h").format(query) + _where(args.get("post_filters"), types, params)
    out_cols = args.get("select") or list(types)
    if not isinstance(out_cols, list):
        raise QueryError("'select' must be a list of column names.")
    for c in out_cols:
        if c not in types:
            raise QueryError(f"Can't select {c!r}. Columns at this point: {', '.join(types)}.")
    query = sql.SQL("select {} from ({}) s").format(sql.SQL(", ").join(map(sql.Identifier, out_cols)), query)
    query = query + _order(args.get("order_by"), list(types), default_order)

    try:
        with conn.transaction():
            rows = [[_plain(v) for v in r] for r in conn.execute(query, params).fetchall()]
    except psycopg.errors.DataError as e:
        raise QueryError(f"Bad value in a filter: {str(e).splitlines()[0]}") from e
    except psycopg.errors.InvalidRegularExpression as e:
        raise QueryError(f"Bad pattern: {str(e).splitlines()[0]}") from e
    except psycopg.errors.UndefinedFunction as e:
        raise QueryError(
            f"That comparison doesn't work on these column types: {str(e).splitlines()[0]}"
        ) from e

    limit = args.get("limit", DEFAULT_PAGE)
    offset = args.get("offset", 0)
    if not isinstance(limit, int) or not 0 <= limit <= MAX_PAGE:
        raise QueryError(f"'limit' must be a whole number from 0 to {MAX_PAGE}.")
    if not isinstance(offset, int) or offset < 0:
        raise QueryError("'offset' must be a whole number, 0 or more.")
    rid = store.add(out_cols, rows)
    page = rows[offset : offset + limit]
    nxt = offset + limit
    return {
        "result_id": rid,
        "total": len(rows),
        "offset": offset,
        "columns": out_cols,
        "rows": page,
        "next_offset": nxt if nxt < len(rows) else None,
    }
