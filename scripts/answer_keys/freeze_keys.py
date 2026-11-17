"""Freeze the answer keys and the study setup, or check that nothing has changed.

A key is only as fixed as the data it was computed from. So the freeze records
a SHA-256 of each key file and script, and a fingerprint of every table the
keys read (row count plus an md5 over all rows, independent of row order).

Since keys-frozen-v4 it also covers everything the main run depends on: the
prompt, the tools, the harness, the provider pins, the sandbox, the judges and
the scoring code, the locked package versions, and the IDs of the two Docker
images. The images are built locally, so their IDs are recorded rather than
their Dockerfiles alone.

Run with --check before any agent run or grading. It exits with 1 if anything
differs from the freeze.

Usage:
  uv run --env-file .env python scripts/answer_keys/freeze_keys.py           # write the freeze
  uv run --env-file .env python scripts/answer_keys/freeze_keys.py --check   # verify it
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
FREEZE = ROOT / "answer_keys" / "FREEZE.json"
FILES = [
    "answer_keys/keys_primary.json",
    "answer_keys/accepted_alternatives.json",
    "answer_keys/comparison.md",
    "scripts/answer_keys/compute_keys.py",
    "independent_check/keys_pandas.json",
    "independent_check/keys_pandas.py",
    "docs/key_spec_for_independent_check.md",
    "docs/spot_checks.md",
    "questions/questions.json",
    "floor_results/floor_summary.json",
    "tool_data/workflows.json",
]
# What the agents see and run on, and how their answers are scored.
SETUP_FILES = [
    "prompts/study_v3.md",
    "study_config/providers.json",
    "src/repo_investigator/study/harness.py",
    "scripts/study/run_study.py",
    "src/repo_investigator/agent/react_loop.py",
    "src/repo_investigator/agent/db.py",
    "src/repo_investigator/agent/schemas.py",
    "src/repo_investigator/levels/calculators.py",
    "src/repo_investigator/levels/definitions.py",
    "src/repo_investigator/levels/domain.py",
    "src/repo_investigator/levels/fillers.py",
    "src/repo_investigator/levels/menus.py",
    "src/repo_investigator/levels/query.py",
    "src/repo_investigator/levels/tools.py",
    "src/repo_investigator/sandbox/docker_runner.py",
    "sandbox/study.Dockerfile",
    "sandbox/relay.Dockerfile",
    "src/repo_investigator/grading/extract.py",
    "scripts/grading/try_judges.py",
    "scripts/grading/grade_study.py",
    "scripts/grading/hand_sheet.py",
    "scripts/floor/must_haves.py",
    "uv.lock",
]
IMAGES = ["repo-investigator-study-sandbox:v2", "repo-investigator-db-relay:v1"]
TABLES = ["repos", "commits", "commit_files", "pull_requests", "pr_reviews", "issues", "ci_runs"]


KINDS = ("files", "tables", "setup_files", "images")


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def fingerprint(conn, table):
    count, digest = conn.execute(
        f"select count(*), md5(string_agg(h, '' order by h)) from (select md5(t::text) h from {table} t) x"
    ).fetchone()
    return {"rows": count, "md5": digest}


def image_id(image):
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True
    )
    return out.stdout.strip() or None


def current():
    with psycopg.connect(os.environ["SANDBOX_DATABASE_URL"]) as conn:
        conn.read_only = True
        tables = {t: fingerprint(conn, t) for t in TABLES}
    return {
        "files": {f: sha256(f) for f in FILES},
        "tables": tables,
        "setup_files": {f: sha256(f) for f in SETUP_FILES},
        "images": {i: image_id(i) for i in IMAGES},
    }


def main():
    now = current()
    if "--check" not in sys.argv:
        missing = [i for i, v in now["images"].items() if not v]
        if missing:
            sys.exit(f"Not freezing: missing images {missing}. Run scripts/study/build_sandbox.sh.")
        FREEZE.write_text(json.dumps({"frozen_at": datetime.now(UTC).isoformat(), **now}, indent=2) + "\n")
        print(f"wrote {FREEZE}")
        return
    frozen = json.loads(FREEZE.read_text())
    diffs = [
        f"{kind} {name}"
        for kind in KINDS
        for name in frozen.get(kind, {})
        if frozen[kind][name] != now[kind].get(name)
    ]
    print("\n".join(f"changed: {d}" for d in diffs) or f"all match the freeze from {frozen['frozen_at']}")
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
