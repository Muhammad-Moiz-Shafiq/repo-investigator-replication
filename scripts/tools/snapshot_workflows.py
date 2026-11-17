# ruff: noqa: E501
"""Save each repo's workflow list (id, name, file path) from the GitHub API.

The ci_runs table has each run's workflow id and name, but not the file path,
and names repeat (eslint has two workflows named CI). The questions name
workflows by path, so the list_workflows tool needs the paths. They are fetched
once and saved, so every agent run sees the same list and nothing depends on
the live API.

The API only lists workflows whose file still exists. For any workflow id that
appears in ci_runs but not in that list, the path is read from one of its runs.

Checks before writing:
- every workflow id in ci_runs gets a path;
- the main CI ids in compute_keys.py have the paths written next to them there.

Usage:
  uv run --env-file .env python scripts/tools/snapshot_workflows.py
"""

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "tool_data" / "workflows.json"
API = "https://api.github.com"
EXPECTED_MAIN_CI = {
    ("tokio", 1972898): ".github/workflows/ci.yml",
    ("eslint", 27292): ".github/workflows/ci.yml",
    ("sqlalchemy", 971063): ".github/workflows/run-test.yaml",
    ("vite", 6990137): ".github/workflows/ci.yml",
    ("junit-framework", 24797): ".github/workflows/main.yml",
    ("junit-framework", 277287548): ".github/workflows/ci.yml",
    ("prometheus", 34174364): ".github/workflows/ci.yml",
}


def get(client, url, params=None):
    for attempt in range(4):
        r = client.get(url, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429, 502, 503):
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
    r.raise_for_status()


def main():
    conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    repos = conn.execute("select id, owner, name from repos order by name").fetchall()
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_PAT']}", "Accept": "application/vnd.github+json"}
    out = {"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "repos": {}}
    problems = []
    with httpx.Client(headers=headers, timeout=30) as client:
        for repo_id, owner, name in repos:
            listed, page = {}, 1
            while True:
                d = get(
                    client, f"{API}/repos/{owner}/{name}/actions/workflows", {"per_page": 100, "page": page}
                )
                for w in d["workflows"]:
                    listed[w["id"]] = {
                        "id": w["id"],
                        "name": w["name"],
                        "path": w["path"],
                        "source": "workflow list",
                    }
                if len(d["workflows"]) < 100:
                    break
                page += 1
            seen = conn.execute(
                "select workflow_id, max(id), count(*) from ci_runs where repo_id = %s group by 1", (repo_id,)
            ).fetchall()
            for wf_id, run_id, _ in seen:
                if wf_id in listed:
                    continue
                run = get(client, f"{API}/repos/{owner}/{name}/actions/runs/{run_id}")
                if run.get("workflow_id") != wf_id:
                    problems.append(
                        f"{name}: run {run_id} has workflow id {run.get('workflow_id')}, expected {wf_id}"
                    )
                    continue
                listed[wf_id] = {
                    "id": wf_id,
                    "name": run["name"],
                    "path": run["path"],
                    "source": f"run {run_id}",
                }
            runs = {wf_id: n for wf_id, _, n in seen}
            for w in listed.values():
                w["runs_in_data"] = runs.get(w["id"], 0)
            missing = [wf_id for wf_id in runs if wf_id not in listed]
            problems += [f"{name}: no path for workflow id {wf_id}" for wf_id in missing]
            out["repos"][name] = {
                "slug": f"{owner}/{name}",
                "workflows": sorted(listed.values(), key=lambda w: w["id"]),
            }
            print(f"{name}: {len(listed)} workflows, {len(runs)} with runs in the data")

    for (repo, wf_id), path in EXPECTED_MAIN_CI.items():
        got = next((w["path"] for w in out["repos"][repo]["workflows"] if w["id"] == wf_id), None)
        if got != path:
            problems.append(f"{repo}: main CI id {wf_id} has path {got}, expected {path}")
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT}, all checks passed")


if __name__ == "__main__":
    main()
