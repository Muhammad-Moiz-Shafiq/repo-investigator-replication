from datetime import date

import psycopg

from repo_investigator.agent.schemas import DateRange, IssuePRFilters
from repo_investigator.agent.tools.compare_periods import compare_periods
from repo_investigator.agent.tools.fetch_commit_diff import fetch_commit_diff
from repo_investigator.agent.tools.query_ci_history import query_ci_history
from repo_investigator.agent.tools.query_contributor_associations import query_contributor_associations
from repo_investigator.agent.tools.query_issues_prs import query_issues_prs
from repo_investigator.agent.tools.query_review_approval_stats import query_review_approval_stats


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


_KNOWN_TOOL_NAMES = {
    "query_ci_history",
    "fetch_commit_diff",
    "query_issues_prs",
    "compare_periods",
    "query_contributor_associations",
    "query_review_approval_stats",
}


def _normalize_tool_name(name: str) -> str:
    """Some providers (found via gemini-2.5-flash-lite, routed through
    OpenRouter) prepend a namespace like "default_api." to the tool name,
    even though our schema never defines one -- confirmed via evaluation
    runs where the model picked the objectively correct tool but wrapped it,
    causing every one of those calls to fail as "unknown tool." Strip a
    dotted prefix only when the remainder is a name we actually recognize,
    so a genuinely unknown or hallucinated name still fails loudly instead
    of being silently reinterpreted into something it wasn't.
    """
    if name in _KNOWN_TOOL_NAMES:
        return name
    suffix = name.rsplit(".", 1)[-1]
    return suffix if suffix in _KNOWN_TOOL_NAMES else name


def dispatch_tool_call(conn: psycopg.Connection, name: str, arguments: dict) -> dict:
    """Executes one tool call by name with raw (already-JSON-parsed) string
    arguments, returning a plain dict (via Pydantic's model_dump) ready to
    be serialized back to the LLM as the tool result. Raises ValueError for
    an unknown tool name -- callers should treat this as a real error, not
    silently ignore it, since a curated-tools agent calling a tool that
    doesn't exist is itself a meaningful failure mode (see RQ2).
    """
    name = _normalize_tool_name(name)
    if name == "query_ci_history":
        result = query_ci_history(
            conn, arguments["repo"], _parse_date(arguments["date_from"]), _parse_date(arguments["date_to"])
        )
    elif name == "fetch_commit_diff":
        result = fetch_commit_diff(conn, arguments["repo"], arguments["sha"])
    elif name == "query_issues_prs":
        filters = IssuePRFilters(
            kind=arguments.get("kind", "both"),
            state=arguments.get("state"),
            is_bug=arguments.get("is_bug"),
        )
        result = query_issues_prs(
            conn,
            arguments["repo"],
            filters,
            _parse_date(arguments["date_from"]),
            _parse_date(arguments["date_to"]),
        )
    elif name == "compare_periods":
        result = compare_periods(
            conn,
            arguments["repo"],
            arguments["metric"],
            DateRange(start=arguments["period_a_start"], end=arguments["period_a_end"]),
            DateRange(start=arguments["period_b_start"], end=arguments["period_b_end"]),
        )
    elif name == "query_contributor_associations":
        # date_from/date_to aren't exposed to the LLM for this tool (see
        # tool_schemas.py) since the underlying metric ignores them anyway --
        # pass placeholder values the tool itself will report as overridden.
        result = query_contributor_associations(conn, arguments["repo"], date.today(), date.today())
    elif name == "query_review_approval_stats":
        result = query_review_approval_stats(
            conn, arguments["repo"], _parse_date(arguments["date_from"]), _parse_date(arguments["date_to"])
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return result.model_dump(mode="json")
