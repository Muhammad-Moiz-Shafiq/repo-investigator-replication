"""Three filler tools, only for the menu size side check.

The main menus are never padded. The side check runs level 2 once more,
padded to its template's level 0 size with these tools, to measure whether
menu size alone changes accuracy. They work and show true data (from
tool_data/repo_extras.json), but no study question can use them: releases,
code languages and basic repo facts say nothing about CI, reviews, issues or
commits in the window.
"""

import json
from pathlib import Path

import psycopg

from repo_investigator.levels.query import QueryError, ResultStore, resolve_repo

EXTRAS_FILE = Path(__file__).parent.parent.parent.parent / "tool_data" / "repo_extras.json"
READS = ("repo_extras_snapshot",)
REPO = {"type": "string", "description": "Repository as owner/name."}


def _repo(conn, args) -> dict:
    if "repo" not in args:
        raise QueryError("'repo' is required, like 'owner/name'.")
    _, name = resolve_repo(conn, args["repo"])
    return json.loads(EXTRAS_FILE.read_text())["repos"][name]


def list_releases(conn, args):
    releases = _repo(conn, args)["releases"]
    limit = args.get("limit", 20)
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise QueryError("'limit' must be a whole number from 1 to 100.")
    return {"releases": len(releases), "latest": releases[:limit]}


def repo_languages(conn, args):
    langs = _repo(conn, args)["languages"]
    total = sum(langs.values()) or 1
    return {
        "languages": [[k, round(100 * v / total, 2)] for k, v in sorted(langs.items(), key=lambda x: -x[1])]
    }


def repo_info(conn, args):
    return _repo(conn, args)["info"]


FILLERS = {
    "list_releases": (
        list_releases,
        "Published releases of the repository, newest first: tag, name, date and pre-release or not.",
        {
            "repo": REPO,
            "limit": {"type": "integer", "description": "How many releases to show, 1 to 100. Default 20."},
        },
    ),
    "repo_languages": (
        repo_languages,
        "The programming languages of the repository, by share of code.",
        {"repo": REPO},
    ),
    "repo_info": (
        repo_info,
        "Basic facts about the repository: description, license, topics, creation date, default branch.",
        {"repo": REPO},
    ),
}


def schema(name: str) -> dict:
    _, description, params = FILLERS[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": params, "required": ["repo"]},
        },
    }


def call(conn: psycopg.Connection, store: ResultStore, name: str, args: dict) -> dict:
    unknown = set(args) - set(FILLERS[name][2])
    if unknown:
        raise QueryError(f"Unknown argument(s) {', '.join(sorted(unknown))}.")
    return FILLERS[name][0](conn, args)
