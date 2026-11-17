# ruff: noqa: E501
"""Write docs/spot_checks.md, a short list of rows to check by hand on github.com.

These checks test our data against GitHub itself, which nothing else does: the
two key implementations both read the same database. Rows are picked in a fixed
order (by md5 of an id), so rerunning gives the same list.

Usage:
  uv run --env-file .env python scripts/answer_keys/make_spot_checks.py
"""

import json
import os
from datetime import timedelta
from pathlib import Path

import psycopg

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "docs" / "spot_checks.md"
KEYS = ROOT / "answer_keys" / "keys_primary.json"
PKT = timedelta(hours=5)


def t(ts):
    if ts is None:
        return "no time"
    return f"{ts:%Y-%m-%d %H:%M} UTC ({ts + PKT:%Y-%m-%d %H:%M} PKT)"


def one(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def main():
    keys = json.loads(KEYS.read_text())
    checks = []
    with psycopg.connect(os.environ["SANDBOX_DATABASE_URL"]) as conn:
        repo = {
            r["name"]: f"https://github.com/{r['owner']}/{r['name']}"
            for r in one(conn, "select owner, name from repos")
        }

        # R7 / R1: the vite streak runs
        r7 = keys["R7"]["vite"]
        for label, sha in [
            ("first failing", r7["first_failing_sha"]),
            ("next passing", r7["next_passing_sha"]),
        ]:
            run = one(
                conn,
                """
                select id, conclusion, run_attempt, started_at from ci_runs
                where commit_sha = %s and workflow_id = 6990137 and event = 'push' order by started_at, id limit 1
            """,
                (sha,),
            )[0]
            checks.append(
                (
                    f"R7, vite, the {label} run of the longest red streak",
                    f"{repo['vite']}/actions/runs/{run['id']}",
                    "The run is on the main branch, the workflow is CI (ci.yml), and the result and start time match.",
                    f"result {run['conclusion']}, attempt {run['run_attempt']}, started {t(run['started_at'])}, commit {sha[:8]}",
                )
            )

        # R1: a landing run that passed after a re-run
        run = one(
            conn,
            """
            select ci.id, ci.conclusion, ci.run_attempt, ci.started_at from ci_runs ci
            where ci.workflow_id = 1972898 and ci.event = 'push' and ci.run_attempt > 1 and ci.conclusion = 'success'
              and ci.started_at >= '2026-04-01' and ci.started_at < '2026-09-21'
            order by md5(ci.id::text) limit 1
        """,
        )[0]
        checks.append(
            (
                "R1, tokio, a run that passed after a re-run",
                f"{repo['tokio']}/actions/runs/{run['id']}",
                "GitHub shows more than one attempt (an attempt picker near the top), and the latest attempt passed.",
                f"result {run['conclusion']}, attempt {run['run_attempt']}",
            )
        )

        # R2: one successful prometheus landing run duration
        run = one(
            conn,
            """
            select id, duration_seconds, started_at from ci_runs
            where workflow_id = 34174364 and event = 'push' and conclusion = 'success'
              and started_at >= '2026-04-01' and started_at < '2026-09-21'
            order by md5(id::text) limit 1
        """,
        )[0]
        checks.append(
            (
                "R2, prometheus, how long one successful run took",
                f"{repo['prometheus']}/actions/runs/{run['id']}",
                "The total duration shown by GitHub is within about 2 minutes of ours.",
                f"{run['duration_seconds'] / 60:.1f} minutes",
            )
        )

        # R3: PRs with their first review
        for name in ["vite", "tokio", "junit-framework"]:
            pr = one(
                conn,
                """
                select p.number, p.author_login, p.created_at, p.merged_at,
                  (select min(v.submitted_at) from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
                     and v.reviewer_login is not null and v.reviewer_login <> p.author_login
                     and v.reviewer_login not in ('copilot-pull-request-reviewer', 'copilot-swe-agent', 'Copilot')
                     and v.submitted_at <= p.merged_at) first_review,
                  (select v.reviewer_login from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
                     and v.reviewer_login is not null and v.reviewer_login <> p.author_login
                     and v.reviewer_login not in ('copilot-pull-request-reviewer', 'copilot-swe-agent', 'Copilot')
                     and v.submitted_at <= p.merged_at order by v.submitted_at limit 1) first_reviewer
                from pull_requests p join repos r on r.id = p.repo_id
                where r.name = %s and p.merged_at >= '2026-04-01' and p.merged_at < '2026-09-21'
                  and p.author_login not in ('renovate', 'dependabot', 'github-actions')
                order by md5(p.number::text) limit 1
            """,
                (name,),
            )[0]
            checks.append(
                (
                    f"R3, {name}, one merged PR",
                    f"{repo[name]}/pull/{pr['number']}",
                    "Opened time, the first review by someone other than the author (reviews show as 'approved', "
                    "'reviewed' or 'requested changes' in the timeline), and the merge time all match.",
                    (
                        f"opened {t(pr['created_at'])}; "
                        + (
                            f"first review by {pr['first_reviewer']} at {t(pr['first_review'])}; "
                            if pr["first_reviewer"]
                            else "no review by anyone else; "
                        )
                        + f"merged {t(pr['merged_at'])}"
                    ),
                )
            )

        # R4: vite PRs merged with no approval from someone else
        prs = one(
            conn,
            """
            select p.number, p.author_login, p.merged_at from pull_requests p join repos r on r.id = p.repo_id
            where r.name = 'vite' and p.merged_at >= '2026-04-01' and p.merged_at < '2026-09-21'
              and not exists (select 1 from pr_reviews v where v.repo_id = p.repo_id and v.pr_number = p.number
                and v.state = 'APPROVED' and v.reviewer_login is not null and v.reviewer_login <> p.author_login
                and v.submitted_at <= p.merged_at)
            order by md5(p.number::text) limit 3
        """,
        )
        for pr in prs:
            checks.append(
                (
                    "R4, vite, a PR merged with no approval from someone else",
                    f"{repo['vite']}/pull/{pr['number']}",
                    "The timeline shows no 'approved these changes' from anyone except the author before the merge.",
                    f"author {pr['author_login']}, merged {t(pr['merged_at'])}",
                )
            )

        # R5: bug issues
        for name, label in [("prometheus", "kind/bug"), ("vite", "p3-minor-bug"), ("sqlalchemy", "bug")]:
            iss = one(
                conn,
                """
                select i.number, i.created_at, i.closed_at from issues i join repos r on r.id = i.repo_id
                where r.name = %s and %s = any(i.labels) and i.created_at >= '2025-10-01' and i.created_at < '2026-04-01'
                order by md5(i.number::text) limit 1
            """,
                (name, label),
            )[0]
            checks.append(
                (
                    f"R5, {name}, one bug issue opened in H1",
                    f"{repo[name]}/issues/{iss['number']}",
                    f"It has the label {label}, and the opened and closed times match.",
                    f"opened {t(iss['created_at'])}, closed {t(iss['closed_at'])}",
                )
            )

        # R6 / R10: fix commits and whether they touched tests
        for name in ["eslint", "prometheus", "vite"]:
            c = one(
                conn,
                r"""
                select c.sha, split_part(c.message, E'\n', 1) subject,
                  (select string_agg(f.filename, ', ' order by f.filename) from commit_files f where f.commit_sha = c.sha) files
                from commits c join repos r on r.id = c.repo_id
                where r.name = %s and not c.is_merge and c.committed_at >= '2025-10-01' and c.committed_at < '2026-09-21'
                  and split_part(c.message, E'\n', 1) ~* '\m(fix|fixes|fixed|fixing|bugfix)\M'
                order by md5(c.sha) limit 1
            """,
                (name,),
            )[0]
            files = c["files"] or ""
            shown = files if len(files) < 300 else files[:300] + "..."
            checks.append(
                (
                    f"R6 and R10, {name}, one fix commit",
                    f"{repo[name]}/commit/{c['sha']}",
                    "The first line uses the word fix, and the list of changed files matches.",
                    f"subject: {c['subject']}; files: {shown}",
                )
            )

        # R9: reviewers on one prometheus PR
        pr = one(
            conn,
            """
            select p.number, p.author_login,
              (select string_agg(distinct v.reviewer_login, ', ') from pr_reviews v
                 where v.repo_id = p.repo_id and v.pr_number = p.number and v.reviewer_login <> p.author_login) reviewers
            from pull_requests p join repos r on r.id = p.repo_id
            where r.name = 'prometheus' and exists (select 1 from pr_reviews v where v.repo_id = p.repo_id
              and v.pr_number = p.number and v.submitted_at >= '2026-04-01' and v.submitted_at < '2026-09-21'
              and v.reviewer_login <> p.author_login)
            order by md5(p.number::text) limit 1
        """,
        )[0]
        checks.append(
            (
                "R9, prometheus, who reviewed one PR",
                f"{repo['prometheus']}/pull/{pr['number']}",
                "The people who left reviews (other than the author) match the list below.",
                f"author {pr['author_login']}; reviewers {pr['reviewers']}",
            )
        )

        # R11: dependency bot PRs, two merged and one closed without merging
        for name in ["vite", "prometheus"]:
            pr = one(
                conn,
                """
                select p.number, p.author_login, p.created_at, p.merged_at from pull_requests p
                join repos r on r.id = p.repo_id
                where r.name = %s and p.author_login in ('renovate', 'dependabot')
                  and p.merged_at >= '2025-10-01' and p.merged_at < '2026-09-21'
                order by md5(p.number::text) limit 1
            """,
                (name,),
            )[0]
            checks.append(
                (
                    f"R11, {name}, one merged dependency bot PR",
                    f"{repo[name]}/pull/{pr['number']}",
                    "It was opened by the bot named, and the opened and merged times match.",
                    f"author {pr['author_login']}, opened {t(pr['created_at'])}, merged {t(pr['merged_at'])}",
                )
            )
        pr = one(
            conn,
            """
            select p.number, p.title, p.created_at, p.closed_at from pull_requests p join repos r on r.id = p.repo_id
            where r.name = 'prometheus' and p.author_login = 'renovate' and p.merged_at is null
              and p.closed_at >= '2025-10-01' and p.closed_at < '2026-09-21' and p.title ilike '%%autoclosed%%'
            order by md5(p.number::text) limit 1
        """,
        )[0]
        checks.append(
            (
                "R11, prometheus, one bot PR closed without merging",
                f"{repo['prometheus']}/pull/{pr['number']}",
                "It shows as closed, not merged, and the title says autoclosed (renovate closed it because a newer update replaced it).",
                f"title: {pr['title']}; closed {t(pr['closed_at'])}",
            )
        )

        # R12: commit size, lines added plus deleted
        for name in ["tokio", "sqlalchemy", "junit-framework"]:
            c = one(
                conn,
                """
                select c.sha, c.additions, c.deletions from commits c join repos r on r.id = c.repo_id
                where r.name = %s and not c.is_merge and c.committed_at >= '2025-10-01' and c.committed_at < '2026-09-21'
                  and c.author_login not like '%%[bot]'
                order by md5(c.sha || 'r12') limit 1
            """,
                (name,),
            )[0]
            checks.append(
                (
                    f"R12, {name}, size of one commit",
                    f"{repo[name]}/commit/{c['sha']}",
                    "The commit page shows the same number of lines added and deleted (near the top of the file list).",
                    f"{c['additions']} added, {c['deletions']} deleted",
                )
            )

    lines = [
        "# Spot checks on github.com",
        "",
        "My other checks compare code with the database. These compare the database with GitHub itself.",
        "For each row I open the link, look at the one thing listed, and write ok or what differs. Times are in UTC and in PKT (UTC+5), my local time.",
        "",
        "Generated by scripts/answer_keys/make_spot_checks.py. Small time differences of a few seconds are fine.",
        "",
        "Round 1 (checks 1 to 17, R1 to R10). I checked all 17 rows on github.com on 2026-10-22. All matched. "
        "The pages show dates but not exact times, so I also compared the exact times of every row with the "
        "GitHub API: CI run start, result and attempt; PR opened, merged and every review; issue opened and "
        "closed; commit time. All matched to the second.",
        "",
        "Round 2 (checks 18 to 23, R11 and R12, added when I added those two templates). I checked all 6 on "
        "github.com on 2026-10-22. All matched. I also compared them with the GitHub API (PR author, opened, "
        "merged and closed times, titles, lines added and deleted). All matched. Because these three commits "
        "were small, I also compared the size of 30 random commits (2 to 1,741 lines) with the API. All matched.",
        "",
    ]
    for i, (what, link, look, ours) in enumerate(checks, 1):
        lines += [
            f"## {i}. {what}",
            "",
            f"Link: {link}",
            "",
            f"Check: {look}",
            "",
            f"In my data: {ours}",
            "",
            "Result: ok" if i <= 23 else "Result: ",
            "",
        ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} with {len(checks)} checks")


if __name__ == "__main__":
    main()
