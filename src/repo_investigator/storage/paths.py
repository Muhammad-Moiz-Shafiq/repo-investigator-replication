from datetime import date


def raw_data_path(owner: str, repo: str, data_type: str, ingestion_date: date, page: int) -> str:
    """Key layout for raw ingested data in Supabase Storage.

    data_type is one of: commits, pull_requests, issues, ci_runs.
    Partitioned by ingestion_date so re-ingesting a repo never overwrites
    or loses a prior run's raw data. Files are gzipped JSON (see upload_json);
    the original 2026-09 pilot uploads were plain .json and were converted
    by scripts/compress_raw_storage.py.
    """
    return f"raw/{owner}/{repo}/{data_type}/{ingestion_date.isoformat()}/{page:05d}.json.gz"
