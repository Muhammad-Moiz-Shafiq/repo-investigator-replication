from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# A workflow name must appear at least this many times in the whole window
# to be included in daily_ci_failure_rate -- otherwise one-off, uniquely
# named automated runs (e.g. dependency-bot workflows, each named after the
# specific update it makes) each produce a meaningless single-run "rate".
# See data_engineering_log.md for the real tokio example that surfaced this.
MIN_WORKFLOW_RUN_COUNT = 5


def compute_daily_ci_failure_rate(ci_runs: DataFrame) -> DataFrame:
    """failure_rate excludes cancelled/skipped runs from the denominator --
    they didn't actually finish testing anything, so counting them as
    either a pass or a fail would distort the real signal.
    """
    frequent_workflows = (
        ci_runs.groupBy("repo_id", "workflow_name")
        .count()
        .filter(F.col("count") >= MIN_WORKFLOW_RUN_COUNT)
        .select("repo_id", "workflow_name")
    )

    countable = (
        ci_runs.join(frequent_workflows, on=["repo_id", "workflow_name"], how="inner")
        .filter(F.col("conclusion").isin("success", "failure"))
        .withColumn("date", F.to_date(F.col("started_at")))
    )

    return (
        countable.groupBy("repo_id", "date", "workflow_name")
        .agg(
            F.count("*").alias("total_runs"),
            F.sum(F.when(F.col("conclusion") == "failure", 1).otherwise(0)).alias("failed_runs"),
        )
        .withColumn("failure_rate", (F.col("failed_runs") / F.col("total_runs")).cast("decimal(5,4)"))
    )


def compute_review_turnaround(pull_requests: DataFrame, pr_reviews: DataFrame) -> DataFrame:
    """hours_to_first_review uses the earliest review submission per PR;
    hours_to_merge is null for PRs that never merged (closed-without-merge
    or still open) -- both are legitimate, distinct outcomes worth keeping
    separate rather than defaulting to 0 or dropping the row.
    """
    first_review = pr_reviews.groupBy("repo_id", "pr_number").agg(
        F.min("submitted_at").alias("first_review_at")
    )

    joined = pull_requests.join(
        first_review,
        (pull_requests.repo_id == first_review.repo_id) & (pull_requests.number == first_review.pr_number),
        how="left",
    ).select(
        pull_requests.repo_id,
        pull_requests.number.alias("pr_number"),
        pull_requests.created_at,
        pull_requests.merged_at,
        first_review.first_review_at,
    )

    seconds_per_hour = 3600.0
    return joined.select(
        F.col("repo_id"),
        F.col("pr_number"),
        ((F.col("first_review_at").cast("long") - F.col("created_at").cast("long")) / seconds_per_hour)
        .cast("decimal(10,2)")
        .alias("hours_to_first_review"),
        ((F.col("merged_at").cast("long") - F.col("created_at").cast("long")) / seconds_per_hour)
        .cast("decimal(10,2)")
        .alias("hours_to_merge"),
    )


def compute_contributor_bugfix_association(commits: DataFrame, commit_files: DataFrame) -> DataFrame:
    """For each contributor, what fraction of THEIR OWN commits are ever
    "implicated" -- touch a file that some later bug-fix commit also
    touches (bug-fix committed strictly after theirs).

    Important: this counts distinct IMPLICATED COMMITS of the contributor's
    own, not distinct bug-fixes they're linked to. Counting bug-fixes
    instead (an earlier version of this function did) is unbounded -- one
    commit touching a frequently-modified file can link to many separate
    later bug-fixes, producing a "rate" like 17.0 for a contributor with a
    single commit, which is not a rate at all. Counting the contributor's
    own implicated commits (each counted at most once) is bounded to
    [0, 1] by construction, matching what "association_rate" should mean.

    This is a scoped file-overlap heuristic, not full SZZ (which traces
    exact changed lines via blame) -- see data_engineering_log.md.
    """
    commit_file_pairs = commits.join(commit_files, commits.sha == commit_files.commit_sha).select(
        commits.repo_id,
        commits.sha,
        commits.author_login,
        commits.committed_at,
        commit_files.filename,
    )

    bugfix_files = (
        commits.filter(F.col("is_bugfix"))
        .join(commit_files, commits.sha == commit_files.commit_sha)
        .select(
            commits.repo_id.alias("bf_repo_id"),
            commits.committed_at.alias("bugfix_committed_at"),
            commit_files.filename.alias("bf_filename"),
        )
    )

    implicated_commits = (
        commit_file_pairs.join(
            bugfix_files,
            (commit_file_pairs.repo_id == bugfix_files.bf_repo_id)
            & (commit_file_pairs.filename == bugfix_files.bf_filename)
            & (commit_file_pairs.committed_at < bugfix_files.bugfix_committed_at),
        )
        .select(commit_file_pairs.repo_id, commit_file_pairs.author_login, commit_file_pairs.sha)
        .distinct()  # one commit can match several later bugfixes/files -- count that commit once
    )

    implicated_counts = implicated_commits.groupBy("repo_id", "author_login").agg(
        F.count("sha").alias("implicated_commit_count")
    )

    # Commits with no resolvable GitHub login (author_login is null -- e.g.
    # a commit email not linked to any account) are excluded here: we can't
    # meaningfully attribute a "contributor" we can't identify. They remain
    # visible in the `commits` table itself; only this per-contributor
    # aggregation drops them, rather than lumping distinct unknown authors
    # into one misleading bucket.
    total_commits = (
        commits.filter(F.col("author_login").isNotNull())
        .groupBy("repo_id", "author_login")
        .agg(F.count("*").alias("commit_count"))
    )

    return (
        total_commits.join(implicated_counts, on=["repo_id", "author_login"], how="left")
        .withColumn("implicated_commit_count", F.coalesce(F.col("implicated_commit_count"), F.lit(0)))
        .withColumn(
            "association_rate",
            (F.col("implicated_commit_count") / F.col("commit_count")).cast("decimal(5,4)"),
        )
    )
