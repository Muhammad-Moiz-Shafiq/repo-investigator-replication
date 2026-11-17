# ruff: noqa: E501
"""Save release, language and basic repo data for the three filler tools.

The filler tools are only for the menu size side check: level 2 padded to the
level 0 size of its template, with tools that work and show true data but
can't help with any study question. They read this file, never the live API,
so every run sees the same thing.

Releases are kept up to the end of the data window (2026-09-20), so nothing
after the window shows up.

Usage:
  uv run --env-file .env python scripts/tools/snapshot_repo_extras.py
"""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "tool_data" / "repo_extras.json"
API = "https://api.github.com"
WINDOW_END = "2026-09-21"


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
    repos = conn.execute("select owner, name from repos order by name").fetchall()
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_PAT']}", "Accept": "application/vnd.github+json"}
    out = {"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "repos": {}}
    with httpx.Client(headers=headers, timeout=30) as client:
        for owner, name in repos:
            info = get(client, f"{API}/repos/{owner}/{name}")
            languages = get(client, f"{API}/repos/{owner}/{name}/languages")
            releases, page = [], 1
            while page <= 5:
                batch = get(client, f"{API}/repos/{owner}/{name}/releases", {"per_page": 100, "page": page})
                releases += [
                    {"tag": r["tag_name"], "name": r["name"], "published_at": r["published_at"], "prerelease": r["prerelease"]}
                    for r in batch
                    if r["published_at"] and r["published_at"] < WINDOW_END and not r["draft"]
                ]
                if len(batch) < 100:
                    break
                page += 1
            out["repos"][name] = {
                "slug": f"{owner}/{name}",
                "info": {
                    "description": info["description"],
                    "license": (info.get("license") or {}).get("spdx_id"),
                    "topics": info.get("topics", []),
                    "created_at": info["created_at"],
                    "default_branch": info["default_branch"],
                    "homepage": info.get("homepage"),
                },
                "languages": languages,
                "releases": sorted(releases, key=lambda r: r["published_at"], reverse=True),
            }
            print(f"{name}: {len(releases)} releases, {len(languages)} languages")
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
