from pyspark.sql import SparkSession

# The Postgres JDBC driver isn't a Python package — it's a Java library that
# Spark's JVM loads at runtime. spark.jars.packages tells Spark to fetch it
# (and its dependencies) from Maven Central automatically on first run, so
# nothing needs to be manually downloaded or committed to the repo.
POSTGRES_JDBC_PACKAGE = "org.postgresql:postgresql:42.7.4"


def make_spark_session(app_name: str = "repo-investigator-cleaning") -> SparkSession:
    return (
        SparkSession.builder.master("local[*]")
        .appName(app_name)
        .config("spark.jars.packages", POSTGRES_JDBC_PACKAGE)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
