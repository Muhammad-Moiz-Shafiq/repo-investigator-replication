-- Repo Investigator: Postgres schema (Supabase)
-- Detail tables mirror raw ingested data (one row per real GitHub object).
-- Derived tables are computed by the PySpark cleaning job and queried
-- directly by the agent tools — see PROJECT_PLAN.md Section 2.2/2.3.

CREATE TABLE IF NOT EXISTS repos (
    id BIGSERIAL PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    github_node_id TEXT,
    first_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner, name)
);

CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    author_login TEXT,
    author_email TEXT,
    committed_at TIMESTAMPTZ NOT NULL,
    message TEXT NOT NULL,
    additions INT NOT NULL DEFAULT 0,
    deletions INT NOT NULL DEFAULT 0,
    changed_files INT NOT NULL DEFAULT 0,
    is_merge BOOLEAN NOT NULL DEFAULT false,
    is_bugfix BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_date ON commits (repo_id, committed_at);
CREATE INDEX IF NOT EXISTS idx_commits_author ON commits (repo_id, author_login);

CREATE TABLE IF NOT EXISTS commit_files (
    id BIGSERIAL PRIMARY KEY,
    commit_sha TEXT NOT NULL REFERENCES commits(sha),
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    additions INT NOT NULL DEFAULT 0,
    deletions INT NOT NULL DEFAULT 0,
    patch TEXT  -- nullable: GitHub omits this for very large diffs (~0.5% of files)
);
CREATE INDEX IF NOT EXISTS idx_commit_files_sha ON commit_files (commit_sha);
CREATE INDEX IF NOT EXISTS idx_commit_files_filename ON commit_files (filename);

CREATE TABLE IF NOT EXISTS pull_requests (
    id BIGSERIAL PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    number INT NOT NULL,
    title TEXT NOT NULL,
    author_login TEXT,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    merged_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    review_comment_count INT NOT NULL DEFAULT 0,
    approval_count INT NOT NULL DEFAULT 0,
    time_to_merge_seconds BIGINT,
    UNIQUE (repo_id, number)
);
CREATE INDEX IF NOT EXISTS idx_prs_repo_date ON pull_requests (repo_id, created_at);

-- References pull_requests by (repo_id, number), not a surrogate id: the
-- cleaning job produces reviews keyed this way naturally (it never needs
-- Postgres's auto-generated pull_requests.id), and pull_requests already
-- has a UNIQUE(repo_id, number) constraint to reference.
CREATE TABLE IF NOT EXISTS pr_reviews (
    id BIGSERIAL PRIMARY KEY,
    repo_id BIGINT NOT NULL,
    pr_number INT NOT NULL,
    reviewer_login TEXT,
    state TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (repo_id, pr_number) REFERENCES pull_requests (repo_id, number)
);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_pr ON pr_reviews (repo_id, pr_number);

CREATE TABLE IF NOT EXISTS issues (
    id BIGSERIAL PRIMARY KEY,
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    number INT NOT NULL,
    title TEXT NOT NULL,
    author_login TEXT,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    labels TEXT[] NOT NULL DEFAULT '{}',
    comment_count INT NOT NULL DEFAULT 0,
    is_bug BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (repo_id, number)
);
CREATE INDEX IF NOT EXISTS idx_issues_repo_date ON issues (repo_id, created_at);
CREATE INDEX IF NOT EXISTS idx_issues_labels ON issues USING GIN (labels);

-- commit_sha is NOT a foreign key: a CI run's head_sha can reference a
-- commit outside our ingestion window (e.g. a fork PR's commit), which
-- would otherwise reject an otherwise-valid CI run row.
CREATE TABLE IF NOT EXISTS ci_runs (
    id BIGINT PRIMARY KEY,  -- GitHub's own run id; globally unique, no need to invent one
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    commit_sha TEXT,
    workflow_id BIGINT,
    workflow_name TEXT,
    status TEXT NOT NULL,
    conclusion TEXT,
    event TEXT,
    run_attempt INT NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds INT
);
CREATE INDEX IF NOT EXISTS idx_ci_runs_repo_date ON ci_runs (repo_id, started_at);
CREATE INDEX IF NOT EXISTS idx_ci_runs_commit_sha ON ci_runs (commit_sha);
CREATE INDEX IF NOT EXISTS idx_ci_runs_workflow ON ci_runs (repo_id, workflow_name);

-- Derived tables: computed by the PySpark cleaning job, queried directly
-- by the agent tools (Section 2.3). Grouped by workflow_name, not just
-- date, so a flaky non-core workflow doesn't get conflated with real CI.
CREATE TABLE IF NOT EXISTS daily_ci_failure_rate (
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    date DATE NOT NULL,
    workflow_name TEXT NOT NULL,
    total_runs INT NOT NULL,
    failed_runs INT NOT NULL,
    failure_rate NUMERIC(5, 4) NOT NULL,
    PRIMARY KEY (repo_id, date, workflow_name)
);

CREATE TABLE IF NOT EXISTS review_turnaround (
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    pr_number INT NOT NULL,
    hours_to_first_review NUMERIC(10, 2),
    hours_to_merge NUMERIC(10, 2),
    PRIMARY KEY (repo_id, pr_number)
);

-- implicated_commit_count: how many of this contributor's OWN commits touch
-- a file some later bug-fix commit also touches (each of their commits
-- counted at most once). association_rate = implicated / total, genuinely
-- bounded [0,1] by construction -- see derived_metrics.py's docstring for
-- why an earlier version (counting linked bug-fixes instead) was not.
CREATE TABLE IF NOT EXISTS contributor_bugfix_association (
    repo_id BIGINT NOT NULL REFERENCES repos(id),
    author_login TEXT NOT NULL,
    commit_count INT NOT NULL,
    implicated_commit_count INT NOT NULL,
    association_rate NUMERIC(5, 4) NOT NULL,
    PRIMARY KEY (repo_id, author_login)
);
