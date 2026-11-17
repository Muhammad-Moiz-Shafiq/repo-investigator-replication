from collections.abc import Iterator
from datetime import datetime, timedelta

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 60


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


_retry_on_transient_error = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)


@_retry_on_transient_error
def _get_with_retry(client: httpx.Client, path: str, params: dict) -> httpx.Response:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response


def fetch_workflow_runs(
    github_pat: str,
    owner: str,
    repo: str,
    since_iso: str,
    until_iso: str | None = None,
) -> Iterator[dict]:
    """Yields workflow (CI) runs for a repo, newest first, stopping once
    results cross the since_iso cutoff. Runs created at or after until_iso
    (if given) are skipped, so a repo ingested later can still be cut to the
    same window as one ingested earlier. Uses REST because GitHub's GraphQL
    schema does not expose Actions run history with equivalent depth.
    Transient network errors are retried with exponential backoff, since
    this can be 100+ sequential calls for an active repo.
    """
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
    }
    page = 1
    with httpx.Client(base_url=GITHUB_API_BASE, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        while True:
            response = _get_with_retry(
                client, f"/repos/{owner}/{repo}/actions/runs", {"per_page": 100, "page": page}
            )
            runs = response.json()["workflow_runs"]
            if not runs:
                return
            for run in runs:
                if run["created_at"] < since_iso:
                    return
                if until_iso and run["created_at"] >= until_iso:
                    continue
                yield run
            page += 1


# GitHub returns at most 1000 runs for a query filtered by `created`
FILTERED_QUERY_CAP = 1000


def fetch_workflow_runs_by_day(
    github_pat: str,
    owner: str,
    repo: str,
    since_dt: datetime,
    until_dt: datetime,
) -> Iterator[dict]:
    """Yields workflow runs created in [since_dt, until_dt), one UTC day at a time.

    fetch_workflow_runs pages back from the newest run, and GitHub stops that
    at 40,000 results (page 401 returns 422). prometheus has more than that,
    so this asks for each day separately instead. A day filter is capped at
    1000 runs, so a day at or over the cap is split into hours.
    """
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client(base_url=GITHUB_API_BASE, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        day = since_dt
        while day < until_dt:
            next_day = min(day + timedelta(days=1), until_dt)
            yield from _runs_in_range(client, owner, repo, day, next_day)
            day = next_day


def _runs_in_range(
    client: httpx.Client, owner: str, repo: str, start: datetime, end: datetime
) -> Iterator[dict]:
    # GitHub's created range is inclusive at both ends, so stop one second early
    created = f"{start:%Y-%m-%dT%H:%M:%SZ}..{end - timedelta(seconds=1):%Y-%m-%dT%H:%M:%SZ}"
    path = f"/repos/{owner}/{repo}/actions/runs"
    first = _get_with_retry(client, path, {"per_page": 100, "page": 1, "created": created}).json()
    if first["total_count"] >= FILTERED_QUERY_CAP:
        if end - start <= timedelta(hours=1):
            raise RuntimeError(f"{owner}/{repo}: over {FILTERED_QUERY_CAP} runs in one hour at {start}")
        step = timedelta(hours=1)
        cursor = start
        while cursor < end:
            yield from _runs_in_range(client, owner, repo, cursor, min(cursor + step, end))
            cursor += step
        return
    yield from first["workflow_runs"]
    page = 2
    while (page - 1) * 100 < first["total_count"]:
        runs = _get_with_retry(client, path, {"per_page": 100, "page": page, "created": created}).json()
        yield from runs["workflow_runs"]
        page += 1


def fetch_commit_files(
    github_pat: str,
    owner: str,
    repo: str,
    sha: str,
) -> dict:
    """Fetches file-level change data (paths, add/delete counts, unified
    diff patch text) for one commit via GitHub's REST commit-detail
    endpoint. No cloning required: GraphQL's Commit type does not expose
    file paths, but this REST endpoint does, directly. Note: GitHub omits
    the 'patch' field for very large per-file diffs (undocumented exact
    threshold) — callers must handle files with no 'patch' key gracefully,
    not assume it is always present.
    """
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client(base_url=GITHUB_API_BASE, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = _get_with_retry(client, f"/repos/{owner}/{repo}/commits/{sha}", {})
        data = response.json()
        return {
            "sha": data["sha"],
            "files": [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch"),
                }
                for f in data.get("files", [])
            ],
        }
