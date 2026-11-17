import os
import subprocess

import pytest


@pytest.fixture
def sandbox_database_url():
    """Provides the read-only SANDBOX_DATABASE_URL for tests that need to
    actually run the Docker sandbox. Skips cleanly (not a failure) when
    either the credential or Docker itself isn't available -- CI has
    neither the Supabase credentials nor the sandbox image built, and
    shouldn't: same reasoning as db_conn below.
    """
    database_url = os.environ.get("SANDBOX_DATABASE_URL")
    if not database_url:
        pytest.skip("SANDBOX_DATABASE_URL not set -- skipping test that needs the sandbox")
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Docker daemon not reachable -- skipping test that needs the sandbox")
    return database_url


@pytest.fixture
def db_conn():
    """Provides a real Postgres connection for tests that need one.

    Skips cleanly (not a failure) when DATABASE_URL isn't set -- CI doesn't
    have our production Supabase credentials, and shouldn't: these tests
    exist for local runs against real data, not as CI's only test coverage.
    Pure-logic tests (no DB needed) always run in CI regardless.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set -- skipping test that needs a live database")

    import psycopg

    conn = psycopg.connect(database_url)
    yield conn
    conn.close()
