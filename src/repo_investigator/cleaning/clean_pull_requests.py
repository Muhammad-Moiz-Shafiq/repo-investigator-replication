from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

_PR_RAW_SCHEMA = StructType(
    [
        StructField("number", IntegerType()),
        StructField("title", StringType()),
        StructField("state", StringType()),
        StructField("createdAt", StringType()),
        StructField("mergedAt", StringType()),
        StructField("closedAt", StringType()),
        StructField("author", StructType([StructField("login", StringType())])),
        StructField(
            "reviews",
            StructType(
                [
                    StructField(
                        "nodes",
                        ArrayType(
                            StructType(
                                [
                                    StructField("state", StringType()),
                                    StructField("submittedAt", StringType()),
                                    StructField("author", StructType([StructField("login", StringType())])),
                                ]
                            )
                        ),
                    )
                ]
            ),
        ),
        StructField("comments", StructType([StructField("totalCount", IntegerType())])),
    ]
)


def read_raw_pull_requests(spark: SparkSession, path: str) -> DataFrame:
    return spark.read.schema(_PR_RAW_SCHEMA).option("multiLine", True).json(path)


def clean_pull_requests(raw: DataFrame, repo_id: int) -> DataFrame:
    return raw.select(
        F.col("number"),
        F.lit(repo_id).alias("repo_id"),
        F.col("title"),
        F.col("author.login").alias("author_login"),
        F.col("state"),
        F.to_timestamp(F.col("createdAt")).alias("created_at"),
        F.to_timestamp(F.col("mergedAt")).alias("merged_at"),
        F.to_timestamp(F.col("closedAt")).alias("closed_at"),
        # comments.totalCount is the PR's general conversation thread (GitHub's
        # IssueComment type) -- not a count of review events. approval_count
        # below is the actual review-outcome count.
        F.coalesce(F.col("comments.totalCount"), F.lit(0)).alias("review_comment_count"),
        F.size(F.filter(F.col("reviews.nodes"), lambda r: r["state"] == "APPROVED")).alias("approval_count"),
        F.when(
            F.col("mergedAt").isNotNull(),
            F.to_timestamp(F.col("mergedAt")).cast("long") - F.to_timestamp(F.col("createdAt")).cast("long"),
        ).alias("time_to_merge_seconds"),
    )


def clean_pr_reviews(raw: DataFrame, repo_id: int) -> DataFrame:
    """Flattens each PR's nested reviews into one row per review, keyed by
    (repo_id, pr_number) since Postgres pr_reviews.pr_id is assigned only
    after pull_requests rows exist -- the write step resolves this join.
    """
    return raw.select(F.col("number").alias("pr_number"), F.explode("reviews.nodes").alias("review")).select(
        F.lit(repo_id).alias("repo_id"),
        F.col("pr_number"),
        F.col("review.author.login").alias("reviewer_login"),
        F.col("review.state").alias("state"),
        F.to_timestamp(F.col("review.submittedAt")).alias("submitted_at"),
    )
