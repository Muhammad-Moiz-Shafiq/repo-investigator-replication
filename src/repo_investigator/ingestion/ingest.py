from datetime import date, datetime

from repo_investigator.ingestion.github_graphql import make_github_client
from repo_investigator.ingestion.github_rest import fetch_workflow_runs, fetch_workflow_runs_by_day
from repo_investigator.ingestion.pagination import paginate, stop_before_cutoff
from repo_investigator.ingestion.queries import COMMITS_QUERY, ISSUES_QUERY, PULL_REQUESTS_QUERY
from repo_investigator.storage.paths import raw_data_path
from repo_investigator.storage.s3_client import make_storage_client, upload_json

PAGE_WRITE_SIZE = 100


def _write_in_pages(client, bucket, owner, repo, data_type, ingestion_date, items):
    batch: list[dict] = []
    page = 0
    total = 0
    for item in items:
        batch.append(item)
        if len(batch) >= PAGE_WRITE_SIZE:
            upload_json(client, bucket, raw_data_path(owner, repo, data_type, ingestion_date, page), batch)
            total += len(batch)
            page += 1
            batch = []
    if batch:
        upload_json(client, bucket, raw_data_path(owner, repo, data_type, ingestion_date, page), batch)
        total += len(batch)
    return total


def ingest(
    owner: str,
    repo: str,
    since_dt: datetime,
    until_dt: datetime | None,
    github_pat: str,
    supabase_url: str,
    supabase_service_role_key: str,
    supabase_bucket: str,
    data_types: tuple[str, ...] = ("commits", "issues", "pull_requests", "ci_runs"),
    ingestion_date: date | None = None,
) -> dict[str, int]:
    """Pulls commits, pull requests, issues, and CI runs for one repo between
    since_dt and until_dt, and writes each as raw JSON pages into Supabase
    Storage. Parameterized by repo, per FR1.

    The pilot repos were ingested with a rolling "last 360 days" window, so
    their window ends on the day they were ingested. until_dt lets repos
    ingested later be cut to that same end point (None means up to now).
    Issues keep the pilot's semantics (updated since since_dt) and are only
    trimmed by creation date, since GitHub's issue filter has no upper bound.
    """
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if until_dt else None
    ingestion_date = ingestion_date or date.today()

    gh_client = make_github_client(github_pat)
    storage_client = make_storage_client(supabase_url, supabase_service_role_key)

    counts: dict[str, int] = {}

    if "commits" in data_types:

        def extract_commits(result):
            h = result["repository"]["defaultBranchRef"]["target"]["history"]
            return h["nodes"], h["pageInfo"]

        commits = paginate(
            gh_client,
            COMMITS_QUERY,
            {"owner": owner, "name": repo, "since": since_iso, "until": until_iso},
            extract_commits,
        )
        counts["commits"] = _write_in_pages(
            storage_client, supabase_bucket, owner, repo, "commits", ingestion_date, commits
        )

    if "issues" in data_types:

        def extract_issues(result):
            i = result["repository"]["issues"]
            return i["nodes"], i["pageInfo"]

        issues = paginate(
            gh_client, ISSUES_QUERY, {"owner": owner, "name": repo, "since": since_iso}, extract_issues
        )
        if until_iso:
            issues = (i for i in issues if i["createdAt"] < until_iso)
        counts["issues"] = _write_in_pages(
            storage_client, supabase_bucket, owner, repo, "issues", ingestion_date, issues
        )

    if "pull_requests" in data_types:

        def extract_prs(result):
            p = result["repository"]["pullRequests"]
            return p["nodes"], p["pageInfo"]

        prs = paginate(gh_client, PULL_REQUESTS_QUERY, {"owner": owner, "name": repo}, extract_prs)
        bounded_prs = stop_before_cutoff(prs, "createdAt", since_dt)
        if until_iso:
            bounded_prs = (p for p in bounded_prs if p["createdAt"] < until_iso)
        counts["pull_requests"] = _write_in_pages(
            storage_client, supabase_bucket, owner, repo, "pull_requests", ingestion_date, bounded_prs
        )

    if "ci_runs" in data_types:
        # with a fixed end date, fetch day by day: paging back from the newest
        # run stops at 40,000 results, which prometheus exceeds
        if until_dt:
            ci_runs = fetch_workflow_runs_by_day(github_pat, owner, repo, since_dt, until_dt)
        else:
            ci_runs = fetch_workflow_runs(github_pat, owner, repo, since_iso)
        counts["ci_runs"] = _write_in_pages(
            storage_client, supabase_bucket, owner, repo, "ci_runs", ingestion_date, ci_runs
        )

    return counts
