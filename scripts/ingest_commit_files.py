import gzip
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from repo_investigator.ingestion.github_rest import fetch_commit_files
from repo_investigator.storage.paths import raw_data_path
from repo_investigator.storage.s3_client import make_storage_client, upload_json

PAGE_WRITE_SIZE = 100
# GitHub's abuse-prevention guidance asks clients to avoid high concurrency
# against a single endpoint; a handful of in-flight requests is a safe,
# well-documented middle ground that still gives a large speedup.
CONCURRENT_REQUESTS = 6


def load_all_commit_shas(client, bucket, owner, repo, date_str):
    files = client.storage.from_(bucket).list(f"raw/{owner}/{repo}/commits/{date_str}", {"limit": 1000})
    shas = []
    for f in files:
        if not f["name"].endswith(".json.gz"):
            continue
        raw = client.storage.from_(bucket).download(f"raw/{owner}/{repo}/commits/{date_str}/{f['name']}")
        shas.extend(c["oid"] for c in json.loads(gzip.decompress(raw)))
    return shas


def main():
    client = make_storage_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    bucket = os.environ["SUPABASE_STORAGE_BUCKET"]
    github_pat = os.environ["GITHUB_PAT"]
    ingestion_date = date.today()

    # args are owner/repo@date, where date is the folder the commits were
    # ingested under, e.g. vitejs/vite@2026-10-21. The pilot ran this for
    # tokio-rs/tokio@2026-09-23, eslint/eslint@2026-09-24 and
    # sqlalchemy/sqlalchemy@2026-09-24.
    repos_with_dates = []
    for arg in sys.argv[1:]:
        slug, commit_date = arg.split("@")
        owner, repo = slug.split("/")
        repos_with_dates.append((owner, repo, commit_date))

    for owner, repo, commit_date in repos_with_dates:
        shas = load_all_commit_shas(client, bucket, owner, repo, commit_date)
        print(f"{owner}/{repo}: fetching file-level data for {len(shas)} commits", flush=True)

        start = time.time()
        batch = []
        page = 0
        total = 0
        done = 0
        with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as pool:
            for result in pool.map(
                lambda sha, owner=owner, repo=repo: fetch_commit_files(github_pat, owner, repo, sha), shas
            ):
                batch.append(result)
                done += 1
                if len(batch) >= PAGE_WRITE_SIZE:
                    upload_json(
                        client,
                        bucket,
                        raw_data_path(owner, repo, "commit_files", ingestion_date, page),
                        batch,
                    )
                    total += len(batch)
                    page += 1
                    batch = []
                if done % 100 == 0:
                    elapsed = time.time() - start
                    print(f"  {done}/{len(shas)} done ({elapsed:.0f}s elapsed)", flush=True)
        if batch:
            upload_json(
                client,
                bucket,
                raw_data_path(owner, repo, "commit_files", ingestion_date, page),
                batch,
            )
            total += len(batch)

        print(f"{owner}/{repo}: wrote {total} commit_files records in {time.time() - start:.0f}s", flush=True)


if __name__ == "__main__":
    main()
