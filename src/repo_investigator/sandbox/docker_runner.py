"""Runs arbitrary Python inside a throwaway Docker container -- Variant B's
open code-execution tool. Uses subprocess.run(["docker", ...]) directly, not
the Docker Python SDK: the job here is narrow (run one script, return its
output, tear down), so a subprocess call is simpler to reason about and test
than adding a SDK + daemon-socket dependency for a one-shot operation (same
reasoning as the original Phase 0 sandboxing design).

Security boundary is the read-only `sandbox_readonly` Postgres role passed in
as DATABASE_URL, not network isolation -- the container needs to reach
Supabase, so `--network=none` isn't an option here (see
agent_methodology_log.md for the full reasoning). Resource/time limits below
guard against a runaway or infinite-looping generated script.
"""

import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

SANDBOX_IMAGE = "repo-investigator-sandbox:latest"
DEFAULT_TIMEOUT_SECONDS = 30
MEMORY_LIMIT = "256m"
CPU_LIMIT = "1"
_MAX_OUTPUT_CHARS = 5000

# The scaled study's sandbox: its own image (sandbox/study.Dockerfile) and no
# internet. Containers run on an internal network whose only way out is a
# relay that forwards one port to the database host
# (scripts/study/build_sandbox.sh builds both images).
STUDY_SANDBOX_IMAGE = "repo-investigator-study-sandbox:v2"
RELAY_IMAGE = "repo-investigator-db-relay:v1"
SANDBOX_NETWORK = "repo-investigator-sandbox-net"
RELAY_NAME = "repo-investigator-db-relay"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def isolated_network(database_url: str) -> list[str]:
    """Set up the internal network and the relay once, and return the docker
    run arguments that put a container on it. Inside, the database's own
    hostname points at the relay, so the URL stays the same and TLS still
    sees the real host name (Supabase's pooler needs it to find the database).
    Safe to call again: it reuses a running relay that points at the same
    host, and replaces one that doesn't."""
    parts = urlsplit(database_url)
    target = f"{parts.hostname}:{parts.port or 5432}"
    if _docker("network", "inspect", SANDBOX_NETWORK, check=False).returncode != 0:
        _docker("network", "create", "--internal", SANDBOX_NETWORK)
    state = _docker(
        "inspect", "-f", '{{.State.Running}} {{index .Config.Labels "target"}}', RELAY_NAME, check=False
    )
    if state.stdout.strip() != f"true {target}":
        _docker("rm", "-f", RELAY_NAME, check=False)
        _docker(
            "run", "-d", "--name", RELAY_NAME, "--label", f"target={target}", "--restart", "unless-stopped",
            RELAY_IMAGE, "socat", f"TCP-LISTEN:{parts.port or 5432},fork,reuseaddr", f"TCP:{target}",
        )  # fmt: skip
        _docker("network", "connect", SANDBOX_NETWORK, RELAY_NAME)
    ip = _docker(
        "inspect",
        "-f",
        f'{{{{(index .NetworkSettings.Networks "{SANDBOX_NETWORK}").IPAddress}}}}',
        RELAY_NAME,
    ).stdout.strip()
    return ["--network", SANDBOX_NETWORK, "--add-host", f"{parts.hostname}:{ip}"]


def run_python_in_sandbox(
    code: str,
    database_url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    read_only_files: dict[str, str] | None = None,
    image: str = SANDBOX_IMAGE,
    docker_args: list[str] | None = None,
) -> dict:
    """Executes `code` as a standalone Python script in the sandbox image,
    with DATABASE_URL available as an environment variable for the script to
    connect with. Returns stdout/stderr (truncated) and the exit code;
    never raises for a failing/erroring script -- that's a normal outcome
    the LLM needs to see and react to, not an exception in our own code.

    read_only_files maps a host file to a path inside the container, mounted
    read-only (the scaled study uses it for the workflow list). image and
    docker_args let the scaled study use its own image on the internal
    network (see isolated_network).
    """
    container_name = f"repo-investigator-sandbox-{uuid.uuid4().hex[:12]}"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                "--memory",
                MEMORY_LIMIT,
                "--cpus",
                CPU_LIMIT,
                *(docker_args or []),
                "-e",
                f"DATABASE_URL={database_url}",
                "-v",
                f"{script_path}:/sandbox/script.py:ro",
                *[
                    arg
                    for host, inside in (read_only_files or {}).items()
                    for arg in ("-v", f"{host}:{inside}:ro")
                ],
                image,
                "python",
                "/sandbox/script.py",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "stdout": result.stdout[:_MAX_OUTPUT_CHARS],
            "stderr": result.stderr[:_MAX_OUTPUT_CHARS],
            "exit_code": result.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        # --rm alone doesn't help here: the container is still running when
        # subprocess gives up waiting, so it has to be killed explicitly or
        # it leaks as an orphaned process.
        subprocess.run(["docker", "kill", container_name], capture_output=True, check=False)
        return {
            "stdout": "",
            "stderr": f"Execution exceeded {timeout_seconds}s and was killed.",
            "exit_code": None,
            "timed_out": True,
        }
    finally:
        Path(script_path).unlink(missing_ok=True)
