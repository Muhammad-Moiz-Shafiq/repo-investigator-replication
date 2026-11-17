# ruff: noqa: E501
"""Check the study sandbox: it can do real analysis work, and it can reach the
database's 7 tables and nothing else. Every probe goes through the same tool
the agents call. Exits non-zero if any check fails.

Usage:
  uv run --env-file .env python scripts/study/check_sandbox.py
"""

import json
import sys

from repo_investigator.study import harness as h

PROBES = {
    # Must work
    "pandas.read_sql with the URL (SQLAlchemy)": (
        True,
        "import os, pandas as pd\nprint(pd.read_sql('select count(*) n from repos', os.environ['DATABASE_URL']).n[0])",
    ),
    "psycopg 3": (
        True,
        "import os, psycopg\nprint(psycopg.connect(os.environ['DATABASE_URL']).execute('select count(*) from commits').fetchone()[0])",
    ),
    "psycopg2": (
        True,
        "import os, psycopg2\nc = psycopg2.connect(os.environ['DATABASE_URL']).cursor(); c.execute('select count(*) from pull_requests'); print(c.fetchone()[0])",
    ),
    "all 7 tables readable": (
        True,
        "import os, psycopg\nc = psycopg.connect(os.environ['DATABASE_URL'])\nfor t in ['repos','commits','commit_files','pull_requests','pr_reviews','issues','ci_runs']: c.execute(f'select 1 from {t} limit 1')\nprint('ok')",
    ),
    "scipy Fisher test": (
        True,
        "from scipy.stats import fisher_exact\nprint(round(fisher_exact([[3, 7], [9, 1]]).pvalue, 4))",
    ),
    "pandas 2 code (12H, a common spelling pandas 3 rejects)": (
        True,
        "import pandas as pd\nprint(pd.Series([1, 2], index=pd.to_datetime(['2026-01-01', '2026-01-02'])).resample('12H').sum().size)",
    ),
    "temp tables allowed": (
        True,
        "import os, psycopg\nc = psycopg.connect(os.environ['DATABASE_URL'])\nc.execute('create temp table t as select 1 x'); print(c.execute('select x from t').fetchone()[0])",
    ),
    "workflow list readable": (
        True,
        "import json\nprint(len(json.load(open('/data/workflows.json'))['repos']))",
    ),
    # Must fail
    "precomputed pilot table": (
        False,
        "import os, psycopg\nprint(psycopg.connect(os.environ['DATABASE_URL']).execute('select 1 from review_turnaround limit 1').fetchone())",
    ),
    "write to a data table": (
        False,
        "import os, psycopg\nc = psycopg.connect(os.environ['DATABASE_URL'])\nc.execute(\"update repos set name = name where false\"); c.commit(); print('wrote')",
    ),
    "GitHub API over HTTPS": (
        False,
        "import urllib.request\nprint(urllib.request.urlopen('https://api.github.com', timeout=5).status)",
    ),
    "a public IP directly": (
        False,
        "import socket\nsocket.create_connection(('1.1.1.1', 443), timeout=5); print('connected')",
    ),
    "DNS lookup of github.com": (False, "import socket\nprint(socket.gethostbyname('github.com'))"),
    "the host machine": (
        False,
        "import socket\nsocket.create_connection(('host.docker.internal', 8080), timeout=5); print('connected')",
    ),
    "another port on the relay": (
        False,
        "import socket\nsocket.create_connection(('repo-investigator-db-relay', 80), timeout=5); print('connected')",
    ),
    "pip install": (
        False,
        "import subprocess, sys\nr = subprocess.run([sys.executable, '-m', 'pip', 'install', '--timeout', '5', 'requests'], capture_output=True)\nassert r.returncode == 0, 'pip failed'\nprint('installed')",
    ),
}


def main():
    url = h.env("STUDY_SANDBOX_DATABASE_URL")
    _, dispatch, _ = h.tools_for("R1", "sandbox", url)
    failed = 0
    for name, (should_work, code) in PROBES.items():
        out = dispatch(None, "execute_python", {"code": code})
        worked = out["exit_code"] == 0
        ok = worked == should_work
        failed += not ok
        detail = (
            out["stdout"].strip() if worked else (out["stderr"].strip().splitlines() or ["timed out"])[-1]
        )
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {'works' if worked else 'blocked'} ({detail[:110]})")
    print(json.dumps({"checks": len(PROBES), "failed": failed}))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
