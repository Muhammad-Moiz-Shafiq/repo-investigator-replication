# ruff: noqa: E501
"""Look for bot accounts that the bot rule in compute_keys.py misses.

The rule started as a hand list. This script checks every person field in the
data for accounts that look automated but are not caught: commit logins, commit
emails (when there is no login), PR authors, reviewers and issue authors.

An account is flagged if either signal fires:
- its name looks automated (bot, ci, jenkins, release, build, a machine email);
- half or more of its commit messages or titles are the same once numbers are removed.

Every flagged account must have a decision in REVIEWED, with the reason. The
script exits with 1 if a flagged account has none, so a new account can't slip by.
It also lists every login that the "ends in bot" part of the rule catches, so
anyone can check that none of them is a person.

Output goes to answer_keys/bot_audit.txt.

Usage:
  uv run --env-file .env python scripts/answer_keys/audit_bots.py
"""

import os
import re
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from compute_keys import AUTOMATION_EMAILS, bot  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "answer_keys" / "bot_audit.txt"
NAME = re.compile(
    r"bot|ci\b|action|release|automat|jenkins|deploy|build|service|noreply@github\.com$|^no-?reply|machine|@.*\.(local|lan)$|@[a-z0-9-]+$",
    re.I,
)

# Flagged accounts the rule does not catch, checked by hand.
REVIEWED = {
    "machine424": "person: a prometheus maintainer with varied code commits, PRs and reviews",
    "Menci": "person: 'ci' is part of the name",
    "pierluigilenoci": "person: 'ci' is part of the name",
    "codeboten": "person: 'bot' is inside the name, normal code changes",
    "edenbuilds": "person: 'builds' is part of the name, one normal PR",
    "subotac": "person: 'bot' is inside the name",
    "botirkhaltaev": "person: 'bot' is inside the name",
    "cbottomline": "person: 'bot' is inside the name",
    "tonyabbott": "person: 'bot' is inside the name",
    "rupert-madden-abbott": "person: 'bot' is inside the name",
    "JacobSobota": "person: 'bot' is inside the name",
    "NordicRealEstateServices": "person: 'services' is part of the name, one normal issue",
    "<email>": "person: a laptop email, normal code commits",
    "<email>": "person: a laptop email, normal code commit",
    "<email>": "person: a dev machine email, normal code commit",
}

SOURCES = {
    "commit login": "select r.name, c.author_login, split_part(c.message, E'\\n', 1) from commits c join repos r on r.id = c.repo_id where c.author_login is not null and not c.is_merge",
    "commit email (no login)": f"select r.name, c.author_email, split_part(c.message, E'\\n', 1) from commits c join repos r on r.id = c.repo_id where c.author_login is null and not c.is_merge and coalesce(c.author_email, '') not in {AUTOMATION_EMAILS}",
    "PR author": "select r.name, p.author_login, p.title from pull_requests p join repos r on r.id = p.repo_id where p.author_login is not null",
    "issue author": "select r.name, i.author_login, i.title from issues i join repos r on r.id = i.repo_id where i.author_login is not null",
    "reviewer": "select r.name, v.reviewer_login, v.state from pr_reviews v join repos r on r.id = v.repo_id where v.reviewer_login is not null",
}


def main():
    conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    conn.read_only = True
    lines, missing = [], []
    for src, q in SOURCES.items():
        actors = {}
        for repo, actor, text in conn.execute(q):
            actors.setdefault((repo, actor), []).append(re.sub(r"\d+", "#", text or ""))
        rule = bot("a").replace("%", "%%")
        caught = {
            a
            for (a,) in conn.execute(
                f"select a from unnest(%s::text[]) a where {rule}", ([a for _, a in actors],)
            )
        }
        lines.append(f"\n{src}: {len(actors)} accounts, {len(caught)} caught by the rule")
        for (repo, actor), texts in sorted(actors.items(), key=lambda x: (-len(x[1]), x[0])):
            if actor in caught:
                continue
            n, distinct = len(texts), len(set(texts))
            templated = src != "reviewer" and n >= 5 and distinct / n <= 0.5
            if not (NAME.search(actor) or templated):
                continue
            decision = REVIEWED.get(actor)
            if decision is None:
                missing.append(f"{src}: {repo} {actor}")
            top = max(set(texts), key=texts.count)
            lines.append(
                f"  {repo} | {actor} | {n} rows, {distinct} distinct | {decision or 'NOT REVIEWED'} | e.g. {top[:60]}"
            )

    lines.append("\nLogins caught only by the 'ends in bot' part of the rule (check that none is a person):")
    q = """
      select login, string_agg(distinct src || ' in ' || repo, ', ') from (
        select 'commits' src, r.name repo, author_login login from commits x join repos r on r.id = x.repo_id
        union all select 'PRs', r.name, author_login from pull_requests x join repos r on r.id = x.repo_id
        union all select 'reviews', r.name, reviewer_login from pr_reviews x join repos r on r.id = x.repo_id
        union all select 'issues', r.name, author_login from issues x join repos r on r.id = x.repo_id) t
      where login ~* 'bot$' and login not like '%%[bot]'
        and login not in ('renovate', 'dependabot', 'github-actions', 'junit-builds')
      group by 1 order by 1"""
    for login, where in conn.execute(q):
        lines.append(f"  {login} ({where})")

    text = "Bot audit, from scripts/answer_keys/audit_bots.py\n" + "\n".join(lines) + "\n"
    OUT.write_text(text)
    print(text)
    if missing:
        print("Flagged accounts with no decision in REVIEWED:\n" + "\n".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
