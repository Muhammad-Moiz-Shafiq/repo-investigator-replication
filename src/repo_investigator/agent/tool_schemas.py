# OpenAI-compatible tool-calling schemas for the 6 curated tools (Variant A).
# Hand-written, not auto-generated from the Pydantic result types: explicit,
# predictable schemas are the whole point of the curated-tools design (see
# PROJECT_PLAN.md Section 2.3) -- auto-generation risks subtle schema drift
# an LLM might handle inconsistently.
#
# query_review_approval_stats added 2026-09-25: an evaluation-driven audit
# found no tool could directly answer "what fraction of merged PRs got
# approved" -- query_issues_prs only returns a raw per-PR list, and models
# mostly failed to aggregate it correctly themselves (see
# agent_methodology_log.md). Variant A was 5 tools before this.

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_ci_history",
            "description": (
                "Get CI build history and failure rate for a repository over a date range, "
                "broken down both by workflow and by day."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                    "date_from": {"type": "string", "description": "Start date, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date, YYYY-MM-DD"},
                },
                "required": ["repo", "date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_commit_diff",
            "description": (
                "Get the actual code changes (file list, stats, and diff patch text) for one "
                "specific commit, identified by its SHA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                    "sha": {"type": "string", "description": "The commit SHA to fetch"},
                },
                "required": ["repo", "sha"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_issues_prs",
            "description": (
                "Get issue and/or pull request metadata for a repository over a date range, "
                "optionally filtered by state or whether an issue is a bug."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                    "kind": {
                        "type": "string",
                        "enum": ["issues", "pull_requests", "both"],
                        "description": "Which kind of data to return",
                    },
                    "state": {
                        "type": "string",
                        "description": "Optional state filter, e.g. OPEN, CLOSED, MERGED",
                    },
                    "is_bug": {
                        "type": "boolean",
                        "description": "Optional: filter issues to only bug-labeled ones (ignored for PRs)",
                    },
                    "date_from": {"type": "string", "description": "Start date, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date, YYYY-MM-DD"},
                },
                "required": ["repo", "kind", "date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": (
                "Compare a named metric between two time periods for a repository -- a "
                "before/after comparison. Supported metrics: ci_failure_rate, "
                "avg_hours_to_first_review, avg_hours_to_merge, commit_count, pr_count, issue_count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                    "metric": {
                        "type": "string",
                        "enum": [
                            "ci_failure_rate",
                            "avg_hours_to_first_review",
                            "avg_hours_to_merge",
                            "commit_count",
                            "pr_count",
                            "issue_count",
                        ],
                    },
                    "period_a_start": {"type": "string", "description": "YYYY-MM-DD"},
                    "period_a_end": {"type": "string", "description": "YYYY-MM-DD"},
                    "period_b_start": {"type": "string", "description": "YYYY-MM-DD"},
                    "period_b_end": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": [
                    "repo",
                    "metric",
                    "period_a_start",
                    "period_a_end",
                    "period_b_start",
                    "period_b_end",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_contributor_associations",
            "description": (
                "Get, per contributor, how many of their commits are later implicated in a bug "
                "fix (touch a file a later bug-fix commit also touches). Note: computed once over "
                "the repository's full ingested history, not an arbitrary date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_review_approval_stats",
            "description": (
                "Get aggregate code-review approval statistics for merged pull requests in a "
                "repository over a date range: how many merged PRs had at least one approval "
                "vs. none, and the overall approval rate. Use this instead of manually counting "
                "approval_count across query_issues_prs results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/name format"},
                    "date_from": {"type": "string", "description": "Start date, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date, YYYY-MM-DD"},
                },
                "required": ["repo", "date_from", "date_to"],
            },
        },
    },
]
