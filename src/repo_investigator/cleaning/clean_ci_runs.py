from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

# Raw REST workflow-run objects carry far more fields than we use (see
# data_engineering_log.md) -- only declaring the ones we keep; PySpark's
# JSON reader silently ignores any raw field not in the schema, so this
# is a safe, deliberate projection, not a risk of a parse error.
_CI_RUN_RAW_SCHEMA = StructType(
    [
        StructField("id", LongType()),
        StructField("head_sha", StringType()),
        StructField("workflow_id", LongType()),
        StructField("name", StringType()),
        StructField("status", StringType()),
        StructField("conclusion", StringType()),
        StructField("event", StringType()),
        StructField("run_attempt", IntegerType()),
        StructField("run_started_at", StringType()),
        StructField("updated_at", StringType()),
    ]
)


def read_raw_ci_runs(spark: SparkSession, path: str) -> DataFrame:
    return spark.read.schema(_CI_RUN_RAW_SCHEMA).option("multiLine", True).json(path)


def clean_ci_runs(raw: DataFrame, repo_id: int) -> DataFrame:
    """Flattens raw CI run JSON into the `ci_runs` table shape.

    duration_seconds is only computed for completed runs (status ==
    "completed"); an in-progress run's updated_at is not a meaningful end
    time. run_started_at is used as the run's actual start (not
    created_at, which can include queue time before the job began).

    The same run can appear twice in raw data: paging back from the newest
    run shifts when new runs land mid-fetch (junit's 2026-10-21 ingest had 3
    such repeats). Keep one row per run id, the most recently updated copy.
    """
    latest_first = Window.partitionBy("id").orderBy(F.col("updated_at").desc())
    raw = raw.withColumn("_copy", F.row_number().over(latest_first)).filter(F.col("_copy") == 1)
    started = F.to_timestamp(F.col("run_started_at"))
    completed = F.to_timestamp(F.col("updated_at"))
    return raw.select(
        F.col("id"),
        F.lit(repo_id).alias("repo_id"),
        F.col("head_sha").alias("commit_sha"),
        F.col("workflow_id"),
        F.col("name").alias("workflow_name"),
        F.col("status"),
        F.col("conclusion"),
        F.col("event"),
        F.coalesce(F.col("run_attempt"), F.lit(1)).alias("run_attempt"),
        started.alias("started_at"),
        F.when(F.col("status") == "completed", completed).alias("completed_at"),
        F.when(F.col("status") == "completed", completed.cast("long") - started.cast("long")).alias(
            "duration_seconds"
        ),
    )
