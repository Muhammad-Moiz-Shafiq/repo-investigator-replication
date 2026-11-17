import os
from pathlib import Path

from repo_investigator.storage.s3_client import make_storage_client

# Where Spark reads its input from. Not committed (see .gitignore's data/ rule) --
# this is a local materialization of the bronze layer already durably stored
# in Supabase, safe to delete and re-download at any time.
STAGING_DIR = Path(__file__).parent.parent / "data" / "raw"

# Each repo's base 4 types (commits/issues/pull_requests/ci_runs) were
# written under the date their own ingest() run started; commit_files was
# a separate later pass. See data_engineering_log.md for why these dates
# differ per repo/type. Tuples are (owner, repo, base date, commit_files date).
REPOS = [
    ("tokio-rs", "tokio", "2026-09-23", "2026-09-24"),
    ("eslint", "eslint", "2026-09-24", "2026-09-24"),
    ("sqlalchemy", "sqlalchemy", "2026-09-24", "2026-09-24"),
    ("vitejs", "vite", "2026-10-21", "2026-10-22"),
    ("junit-team", "junit-framework", "2026-10-21", "2026-10-22"),
    ("prometheus", "prometheus", "2026-10-21", "2026-10-22"),
]
DATA_TYPES = ["commits", "issues", "pull_requests", "ci_runs", "commit_files"]


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


def main():
    client = make_storage_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    bucket = os.environ["SUPABASE_STORAGE_BUCKET"]

    for owner, repo, base_ingestion_date, commit_files_date in REPOS:
        for data_type in DATA_TYPES:
            date_str = commit_files_date if data_type == "commit_files" else base_ingestion_date
            prefix = f"raw/{owner}/{repo}/{data_type}/{date_str}"
            files = list_all(client, bucket, prefix)
            local_dir = STAGING_DIR / owner / repo / data_type
            local_dir.mkdir(parents=True, exist_ok=True)
            files = [f for f in files if f["name"].endswith(".json.gz")]
            for f in files:
                content = client.storage.from_(bucket).download(f"{prefix}/{f['name']}")
                (local_dir / f["name"]).write_bytes(content)
            print(f"{owner}/{repo}/{data_type}: staged {len(files)} file(s)")


if __name__ == "__main__":
    main()
