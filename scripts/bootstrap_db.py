import os
from pathlib import Path

import psycopg


def main():
    schema_path = Path(__file__).parent.parent / "src" / "repo_investigator" / "db" / "schema.sql"
    schema_sql = schema_path.read_text()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    print("Schema applied successfully.")


if __name__ == "__main__":
    main()
