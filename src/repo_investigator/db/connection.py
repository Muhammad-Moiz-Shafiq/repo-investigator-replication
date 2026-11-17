from urllib.parse import urlsplit

import psycopg


def get_psycopg_connection(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def jdbc_url_and_properties(database_url: str) -> tuple[str, dict]:
    """Converts a postgresql:// URI (used by psycopg) into the jdbc:postgresql://
    URL + separate user/password properties Spark's JDBC writer expects.
    Parsed with urlsplit rather than string-slicing so special characters
    in the password are handled correctly regardless of content.
    """
    parts = urlsplit(database_url)
    jdbc_url = f"jdbc:postgresql://{parts.hostname}:{parts.port}{parts.path}"
    properties = {
        "user": parts.username,
        "password": parts.password,
        "driver": "org.postgresql.Driver",
    }
    return jdbc_url, properties
