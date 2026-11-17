import re

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

# Matches GitHub's standard closing-keyword references, e.g. "fixes #123",
# "Closes: #45", "resolved #7" -- used to link a commit to the issue(s) it
# closes. Deliberately requires a closing verb, not just any "#123" mention,
# since a bare reference ("see #123") does not mean this commit fixes it.
_CLOSES_ISSUE_PATTERN = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)", re.IGNORECASE
)

_COMMIT_RAW_SCHEMA = StructType(
    [
        StructField("oid", StringType()),
        StructField("committedDate", StringType()),
        StructField("message", StringType()),
        StructField("additions", IntegerType()),
        StructField("deletions", IntegerType()),
        StructField("changedFiles", IntegerType()),
        StructField(
            "author",
            StructType(
                [
                    StructField("user", StructType([StructField("login", StringType())])),
                    StructField("email", StringType()),
                ]
            ),
        ),
        StructField("parents", StructType([StructField("totalCount", IntegerType())])),
    ]
)


def extract_closed_issue_numbers(message: str) -> list[int]:
    if not message:
        return []
    return [int(n) for n in _CLOSES_ISSUE_PATTERN.findall(message)]


_extract_closed_issue_numbers_udf = F.udf(extract_closed_issue_numbers, ArrayType(IntegerType()))


def read_raw_commits(spark: SparkSession, path: str) -> DataFrame:
    return spark.read.schema(_COMMIT_RAW_SCHEMA).option("multiLine", True).json(path)


def clean_commits(raw: DataFrame, repo_id: int, bug_issue_numbers: set[int]) -> DataFrame:
    """Flattens raw commit JSON into the `commits` table shape.

    is_bugfix is true only when the commit message closes an issue that is
    itself in bug_issue_numbers (computed from issue labels beforehand) --
    a plain "#123" mention or closing a non-bug issue does not count. This
    is the scoped heuristic described in data_engineering_log.md, not full
    SZZ.
    """
    bug_issues_col = F.array(*[F.lit(n) for n in bug_issue_numbers]) if bug_issue_numbers else F.array()

    return (
        raw.withColumn("closed_issue_numbers", _extract_closed_issue_numbers_udf(F.col("message")))
        .withColumn(
            "is_bugfix",
            F.size(F.array_intersect(F.col("closed_issue_numbers"), bug_issues_col)) > 0,
        )
        .select(
            F.col("oid").alias("sha"),
            F.lit(repo_id).alias("repo_id"),
            F.col("author.user.login").alias("author_login"),
            F.col("author.email").alias("author_email"),
            F.to_timestamp(F.col("committedDate")).alias("committed_at"),
            F.col("message"),
            F.coalesce(F.col("additions"), F.lit(0)).alias("additions"),
            F.coalesce(F.col("deletions"), F.lit(0)).alias("deletions"),
            F.coalesce(F.col("changedFiles"), F.lit(0)).alias("changed_files"),
            (F.col("parents.totalCount") > 1).alias("is_merge"),
            F.col("is_bugfix").cast(BooleanType()),
        )
    )
