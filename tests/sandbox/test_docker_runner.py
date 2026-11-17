from repo_investigator.sandbox.docker_runner import run_python_in_sandbox


def test_runs_simple_python_and_captures_stdout(sandbox_database_url):
    result = run_python_in_sandbox("print('hello from the sandbox')", sandbox_database_url)

    assert result["exit_code"] == 0
    assert "hello from the sandbox" in result["stdout"]
    assert result["timed_out"] is False


def test_can_read_from_the_database_through_the_readonly_role(sandbox_database_url):
    code = (
        "import os, psycopg\n"
        "conn = psycopg.connect(os.environ['DATABASE_URL'])\n"
        "with conn.cursor() as cur:\n"
        "    cur.execute('SELECT count(*) FROM commits')\n"
        "    print(cur.fetchone()[0])\n"
    )
    result = run_python_in_sandbox(code, sandbox_database_url)

    assert result["exit_code"] == 0
    assert result["stdout"].strip().isdigit()


def test_write_attempts_are_rejected_by_the_readonly_role(sandbox_database_url):
    # This is the sandbox's real security boundary (see
    # agent_methodology_log.md) -- confirm it actually holds from inside a
    # container, not just when tested from the host.
    code = (
        "import os, psycopg\n"
        "conn = psycopg.connect(os.environ['DATABASE_URL'])\n"
        "with conn.cursor() as cur:\n"
        "    cur.execute(\"DELETE FROM commits WHERE sha = 'nonexistent'\")\n"
        "print('DELETE SUCCEEDED')\n"
    )
    result = run_python_in_sandbox(code, sandbox_database_url)

    assert result["exit_code"] != 0
    assert "InsufficientPrivilege" in result["stderr"] or "permission denied" in result["stderr"]
    assert "DELETE SUCCEEDED" not in result["stdout"]


def test_nonzero_exit_code_and_traceback_on_a_python_error(sandbox_database_url):
    result = run_python_in_sandbox("raise ValueError('boom')", sandbox_database_url)

    assert result["exit_code"] != 0
    assert "ValueError" in result["stderr"]
    assert result["timed_out"] is False


def test_infinite_loop_is_killed_after_the_timeout(sandbox_database_url):
    result = run_python_in_sandbox(
        "import time\nwhile True:\n    time.sleep(1)\n", sandbox_database_url, timeout_seconds=3
    )

    assert result["timed_out"] is True
    assert result["exit_code"] is None
