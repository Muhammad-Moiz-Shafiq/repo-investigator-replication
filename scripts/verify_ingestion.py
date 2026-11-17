import json
import os
import sys

from repo_investigator.storage.s3_client import make_storage_client


def list_all(client, bucket, prefix):
    all_files = []
    offset = 0
    while True:
        batch = client.storage.from_(bucket).list(prefix, {"limit": 1000, "offset": offset})
        if not batch:
            break
        all_files.extend(batch)
        offset += len(batch)
    return all_files


def load_all(client, bucket, owner, repo, data_type, date):
    files = list_all(client, bucket, f"raw/{owner}/{repo}/{data_type}/{date}")
    items = []
    for f in files:
        raw = client.storage.from_(bucket).download(f"raw/{owner}/{repo}/{data_type}/{date}/{f['name']}")
        items.extend(json.loads(raw))
    return items, len(files)


def main():
    client = make_storage_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    bucket = os.environ["SUPABASE_STORAGE_BUCKET"]

    repos = [
        ("tokio-rs", "tokio", "2026-09-23"),
        ("eslint", "eslint", "2026-09-24"),
        ("sqlalchemy", "sqlalchemy", "2026-09-24"),
    ]

    results = {}
    for owner, repo, date in repos:
        results[f"{owner}/{repo}"] = {}
        for data_type in ["commits", "issues", "pull_requests", "ci_runs"]:
            items, file_count = load_all(client, bucket, owner, repo, data_type, date)
            results[f"{owner}/{repo}"][data_type] = {"records": len(items), "files": file_count}
            print(
                f"{owner}/{repo} {data_type}: {len(items)} records across {file_count} files",
                file=sys.stderr,
            )

    with open("/tmp/verification_summary.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
