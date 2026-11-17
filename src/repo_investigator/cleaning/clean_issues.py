from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

_ISSUE_RAW_SCHEMA = StructType(
    [
        StructField("number", IntegerType()),
        StructField("title", StringType()),
        StructField("state", StringType()),
        StructField("createdAt", StringType()),
        StructField("closedAt", StringType()),
        StructField("author", StructType([StructField("login", StringType())])),
        StructField(
            "labels",
            StructType([StructField("nodes", ArrayType(StructType([StructField("name", StringType())])))]),
        ),
        StructField("comments", StructType([StructField("totalCount", IntegerType())])),
    ]
)


def read_raw_issues(spark: SparkSession, path: str) -> DataFrame:
    return spark.read.schema(_ISSUE_RAW_SCHEMA).option("multiLine", True).json(path)


def clean_issues(raw: DataFrame, repo_id: int) -> DataFrame:
    """Flattens raw issue JSON into the `issues` table shape.

    is_bug uses a case-insensitive substring match for "bug" against label
    names, chosen after checking real label vocabularies across all three
    repos: tokio uses "C-bug", eslint/sqlalchemy use plain "bug" -- an exact
    match would miss tokio's convention, a substring match correctly covers
    all three (see data_engineering_log.md).
    """
    return raw.withColumn("label_names", F.col("labels.nodes.name")).select(
        F.col("number"),
        F.lit(repo_id).alias("repo_id"),
        F.col("title"),
        F.col("author.login").alias("author_login"),
        F.col("state"),
        F.to_timestamp(F.col("createdAt")).alias("created_at"),
        F.to_timestamp(F.col("closedAt")).alias("closed_at"),
        F.col("label_names").alias("labels"),
        F.coalesce(F.col("comments.totalCount"), F.lit(0)).alias("comment_count"),
        F.exists(F.col("label_names"), lambda label: F.lower(label).contains("bug")).alias("is_bug"),
    )


def bug_issue_numbers(cleaned_issues: DataFrame) -> set[int]:
    """The set of issue numbers flagged as bugs, for linking bugfix commits."""
    rows = cleaned_issues.filter(F.col("is_bug")).select("number").distinct().collect()
    return {row["number"] for row in rows}
