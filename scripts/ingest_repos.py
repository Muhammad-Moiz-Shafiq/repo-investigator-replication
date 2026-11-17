"""Ingests the scaled-study repos into raw storage with a fixed window.

The pilot repos (tokio, eslint, sqlalchemy) were ingested on 2026-09-23/24
with a rolling 360-day window, so their data runs from about 2025-09-28 up
to the moment of ingestion. New repos get the same window pinned explicitly,
so it doesn't matter what day this script is run.

Questions should use analysis windows inside the span every repo fully
covers (2025-10-01 to 2026-09-20), not the ragged edges.

Usage:
  uv run python scripts/ingest_repos.py vitejs/vite junit-team/junit-framework prometheus/prometheus
  # redo one data type into an existing ingestion folder (prometheus CI hit
  # GitHub's 40,000 result paging limit on the first run, 2026-10-21)
  uv run python scripts/ingest_repos.py prometheus/prometheus --only ci_runs --ingestion-date 2026-10-21
"""

import argparse
import os
from datetime import UTC, date, datetime

from dotenv import load_dotenv

from repo_investigator.ingestion.ingest import ingest

WINDOW_START = datetime(2025, 9, 28, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 24, tzinfo=UTC)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repos", nargs="+")
    parser.add_argument("--only", nargs="+", help="data types to ingest, default all four")
    parser.add_argument("--ingestion-date", type=date.fromisoformat, help="storage folder, default today")
    args = parser.parse_args()

    load_dotenv()
    for slug in args.repos:
        owner, repo = slug.split("/")
        print(f"{slug}: ingesting {WINDOW_START.date()} to {WINDOW_END.date()}", flush=True)
        counts = ingest(
            owner,
            repo,
            WINDOW_START,
            WINDOW_END,
            os.environ["GITHUB_PAT"],
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            os.environ["SUPABASE_STORAGE_BUCKET"],
            **({"data_types": tuple(args.only)} if args.only else {}),
            ingestion_date=args.ingestion_date,
        )
        print(f"{slug}: {counts}", flush=True)


if __name__ == "__main__":
    main()
