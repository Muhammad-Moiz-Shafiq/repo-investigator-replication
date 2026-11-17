from collections.abc import Callable

import psycopg

from repo_investigator.sandbox.docker_runner import run_python_in_sandbox


def make_variant_b_dispatch_fn(
    sandbox_database_url: str,
) -> Callable[[psycopg.Connection, str, dict], dict]:
    """Builds a dispatch_fn matching the same (conn, name, arguments) -> dict
    signature react_loop expects for both variants. `conn` is accepted but
    unused here -- the sandbox connects to Postgres itself, using the
    separate read-only sandbox_database_url, never the admin connection the
    rest of the loop was given for Variant A's tools.
    """

    def dispatch(conn: psycopg.Connection, name: str, arguments: dict) -> dict:
        if name != "execute_python":
            raise ValueError(f"Unknown tool: {name}")
        return run_python_in_sandbox(arguments["code"], sandbox_database_url)

    return dispatch
