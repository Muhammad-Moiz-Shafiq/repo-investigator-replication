from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

_COMMIT_FILES_RAW_SCHEMA = StructType(
    [
        StructField("sha", StringType()),
        StructField(
            "files",
            ArrayType(
                StructType(
                    [
                        StructField("filename", StringType()),
                        StructField("status", StringType()),
                        StructField("additions", IntegerType()),
                        StructField("deletions", IntegerType()),
                        StructField("patch", StringType()),
                    ]
                )
            ),
        ),
    ]
)


def read_raw_commit_files(spark: SparkSession, path: str) -> DataFrame:
    return spark.read.schema(_COMMIT_FILES_RAW_SCHEMA).option("multiLine", True).json(path)


def clean_commit_files(raw: DataFrame) -> DataFrame:
    """One row per (commit, file) -- not scoped by repo_id since it joins
    to `commits` on sha, which is already globally unique and repo-scoped.
    """
    return raw.select(F.col("sha").alias("commit_sha"), F.explode("files").alias("file")).select(
        F.col("commit_sha"),
        F.col("file.filename").alias("filename"),
        F.col("file.status").alias("status"),
        F.coalesce(F.col("file.additions"), F.lit(0)).alias("additions"),
        F.coalesce(F.col("file.deletions"), F.lit(0)).alias("deletions"),
        F.col("file.patch").alias("patch"),
    )
