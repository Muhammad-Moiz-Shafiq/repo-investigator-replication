# Independent answer key check: task for a second coding agent

This is the brief I gave to a separate coding agent (OpenAI Codex) on 2026-10-22, so it could write a second version of my answer keys without seeing the first. Its output is in independent_check/. Since then I've changed the wording to first person, added one note to R2, added Round 2 at the end for two new questions (R11 and R12), and added Round 3 for a corrected bot rule.

## What this project is

This is a research study about LLM agents that answer questions about software repositories: things like "did CI get flakier this year?" or "where does the time go on pull requests?". I compare agents that get purpose-built tools with agents that write their own code, and I change how well the tools cover each question.

To grade the agents, every question needs a reference answer, called an answer key. I compute the keys with code, straight from a Postgres database of real GitHub data for six repositories.

## Why you are being asked to do this

I already have one implementation of the keys. One author tends to misread a definition the same way every time, so I want a second implementation, written by someone who has never seen the first one. You work only from this file and the database.

If your numbers match the first implementation, I can trust the keys. If they don't, either one of the two has a bug, or the definition below is ambiguous. Both are useful to find. If you find a definition that can honestly be read two ways, don't guess. Pick the reading you think is most natural, and write down the ambiguity in your notes (see Output).

## Rules

Do not open these files or folders. They contain the other implementation or its results:

- docs/question_templates_draft.md
- docs/spot_checks.md
- docs/ground_truth_answers.md
- answer_keys/
- scripts/answer_keys/
- scripts/key_exploration/
- evaluation_results/
- src/repo_investigator/levels/
- scripts/levels/
- levels_results/

Also don't use git log or git show to read past versions of those files.

Do not change anything outside the folder independent_check/. Do not write to the database. Use the read-only connection described below.

Write your code in Python with pandas. Keep it plain and readable: someone will read it to find where the two implementations differ.

## Environment

Repo root: /Users/mac/MS/Project/repo-investigator (run commands from here).

Python is managed with uv. pandas, numpy and psycopg are available through `uv run`. scipy is not a project dependency. If you want it, use `uv run --with scipy python ...`, which doesn't change the project. You can also write the tests yourself, they are small.

Database: the file .env in the repo root has SANDBOX_DATABASE_URL, a Postgres login that can only read. Load it with `uv run --env-file .env python independent_check/keys_pandas.py`. Do not use DATABASE_URL. It can write.

The table definitions are in src/repo_investigator/db/schema.sql. You can read that file.

## The data

Six repositories, in the `repos` table: tokio-rs/tokio, eslint/eslint, sqlalchemy/sqlalchemy, vitejs/vite, junit-team/junit-framework, prometheus/prometheus. Below, a repo is called by its `name` column (tokio, eslint, sqlalchemy, vite, junit-framework, prometheus).

Tables you need: commits, commit_files, pull_requests, pr_reviews, issues, ci_runs. Ignore the derived tables (daily_ci_failure_rate, review_turnaround, contributor_bugfix_association). Compute everything from the base tables.

All timestamps are UTC. Treat them as UTC throughout.

Things about this data that will trip you up:

1. The commits table only has commits on each repo's default branch history (called main, or master in tokio). ci_runs has no branch field.
2. Bot accounts appear without the [bot] suffix in pull_requests.author_login and pr_reviews.reviewer_login (for example "renovate"), but with it in commits.author_login (for example "renovate[bot]").
3. Some logins are null. That happens when an account was deleted, or when a commit's email isn't linked to any GitHub account.
4. sqlalchemy does code review on Gerrit, not GitHub, so its GitHub PRs and reviews don't reflect its real process.
5. The same commit can have several CI runs, including push runs that happened days later (when the commit was pushed to a release branch or tagged).

## Shared definitions

Windows. Full window W: from 2025-10-01 00:00 up to but not including 2026-09-21 00:00. H1: from 2025-10-01 up to but not including 2026-04-01. H2: from 2026-04-01 up to but not including 2026-09-21. "In H1" always means the timestamp is in that range.

Bots. A login is a bot if it is one of: renovate, dependabot, github-actions, junit-builds, copilot-pull-request-reviewer, copilot-swe-agent, Copilot, or it ends with "[bot]", or it ends with "bot" ignoring case. Null logins are not bots.

Person. A commit's person is commits.author_login. If that is null, use commits.author_email.

Human commit. A commit that is not a merge (is_merge is false), whose author_login is not a bot, and which is not an automation commit. An automation commit has a null author_login and an author_email of jenkins@eslint-03 or eslint@googlegroups.com.

Per-repo settings:

| Repo | main_ci workflow_id | bug_label | Module |
|---|---|---|---|
| tokio | 1972898 | C-bug | first folder of the path |
| eslint | 27292 | bug | first two folders (lib/...) |
| sqlalchemy | 971063 | bug | first three folders (lib/sqlalchemy/...) |
| vite | 6990137 | p3-minor-bug | first two folders (packages/...) |
| junit-framework | 24797 or 277287548 | type: bug | first folder of the path |
| prometheus | 34174364 | kind/bug | first folder of the path |

main_ci is identified by ci_runs.workflow_id, not by workflow_name. Names are not unique: in eslint, other workflows also logged runs named "CI". junit renamed its workflow file in May 2026, which gave it a new id, so both ids count.

Module of a file path: join the first N folder names with "/", where N is 1, 2 or 3 as in the table. If the path has fewer than N folders before the file name, the file is a "root file" and has no module.

### CI rules (R1, R2, R7)

Main CI run: a row in ci_runs whose workflow_id is the repo's main_ci id, event equal to "push", and commit_sha present in the commits table for that repo.

Landing run: for each commit, its main CI run with the earliest started_at. Use only the landing run. Ignore later runs of the same commit.

Counted landing run: a landing run whose conclusion is not null, not "cancelled" and not "skipped".

Failing: conclusion is "failure", "timed_out" or "startup_failure". Passing: conclusion is "success".

### Fix commits (R6, R10)

Fix commit: a human commit, committed in W, whose first line of message contains the word fix, fixes, fixed, fixing or bugfix, matched as a whole word and ignoring case. "prefix" does not match, "Fix:" does.

Test file: a file path where any folder in the path (not the file name) is named test, tests, __tests__, testdata, testing, fixtures or playground, or ends with "-test", "-tests", "_test" or "_tests" (ignoring case). A file is also a test file if its name ends with _test.go or _test.py, starts with test_ and ends with .py, ends with Test.java, Tests.java, Test.kt or Tests.kt, or matches *.test.js, *.spec.js and the same for .jsx, .ts, .tsx, .mjs, .cjs, .mts and .cts.

Doc file: a path where any folder is named doc, docs, documentation, .github or changelog.d (ignoring case), or whose name ends with .md, .rst, .txt or .adoc.

### Tests for "did it change"

Fisher: two-sided Fisher exact test on a 2 by 2 table.

Rate verdict (R1): "up" or "down" if Fisher p < 0.05 comparing the H1 and H2 counts, else "no clear change".

Share-of-work verdict (R8): "more concentrated" or "less concentrated" if Fisher p < 0.05 and the share moved by at least 0.05, else "no clear change". The 2 by 2 table is: (work by the top two, work by everyone else) in H1 vs in H2.

Median verdict (R2, R3): bootstrap the ratio median(H2) / median(H1) with 4000 resamples of each half, with replacement. Take the 2.5th and 97.5th percentiles. "up" if the lower bound is above 1 and the observed ratio is at least 1.2. "down" if the upper bound is below 1 and the observed ratio is at most 1/1.2. Otherwise "no clear change". If either half has fewer than 10 values, "too few". The other implementation used numpy with seed 7, but don't try to copy its random numbers. A verdict that differs only because of bootstrap noise near the edge is something I want to know about.

Binomial verdict (R5): exact two-sided binomial test of closed out of (opened + closed) against 0.5. "growing" if p < 0.05 and opened > closed, "shrinking" if p < 0.05 and closed > opened, else "balanced".

## The ten questions

R1 (all six repos). Take commits with a counted landing run. Put each commit in H1 or H2 by its landing run's started_at, and drop commits outside both halves. For each half: failing commits, counted commits, failure rate. Verdict by the rate rule. Also for each half: the share of counted commits whose landing run has run_attempt greater than 1 and conclusion "success".

R2 (all six repos). Main part: landing runs with conclusion "success" and a non-null duration_seconds, by half of started_at. Median duration in minutes for H1 and H2, and the median verdict. Second part: all ci_runs rows with the repo's main_ci workflow_id, event "pull_request", conclusion "success" and non-null duration_seconds, by half of started_at. Same medians and verdict. If there are no such runs at all in either half, the medians are null and the verdict is "none". (I added this after the check. The first version only said "say so", and the independent version reasonably used "too few".)

R3 (all repos except sqlalchemy). Merged PRs (merged_at not null) whose author is not a bot, put in H1 or H2 by merged_at. First review: the earliest pr_reviews row for that PR (same repo, pr_number equal to the PR number) with any state, where reviewer_login is not null, is not the PR author, is not a bot, and submitted_at is at or before merged_at. For PRs with a first review: wait = first review minus created_at, and after = merged_at minus first review, both in hours. For each half: the median wait and median after, and a median verdict for each part. Also, among H2 PRs, the share with no first review.

R4 (all repos except sqlalchemy). PRs merged in H2, bots included. A PR is approved if it has a pr_reviews row with state "APPROVED", reviewer_login not null, not the PR author, not a bot, and submitted_at at or before merged_at. Report: number of PRs merged in H2, number and share not approved, and how many of the not-approved PRs have a bot author.

R5 (all six repos). Issues whose labels array contains the repo's bug_label exactly. Opened = created_at in W. Closed = closed_at in W, regardless of when the issue was opened. Binomial verdict. Then, for bug issues created in H1: days to close = closed_at minus created_at in days, but if closed_at is null or not before 2026-09-21, treat it as not closed (infinitely long). Report the median of these days (it can be infinite if more than half are not closed), and the share not closed.

R6 (eslint, prometheus, sqlalchemy, vite). Take the files of human commits committed in W, leaving out test files, doc files and root files. A commit touches a module if any of its remaining files is in that module. Count each commit once per module. For each module: commits touching it, and fix commits touching it. Report the module with the most fix commits (break ties by more commits), and, among modules with at least 20 commits, the module with the highest share of fix commits.

R7 (all six repos). Sort commits with a counted landing run by their landing run's started_at. A streak is a maximal run of consecutive failing commits, with a passing commit just before it and just after it. Keep streaks whose first failing commit's landing run started in H2, and which end with a passing commit (whose landing run may finish after H2). Time red = completed_at of the first failing commit's landing run to completed_at of the next passing commit's landing run. Report the streak with the longest time red (ties: more failing commits): the first failing commit's sha, the next passing commit's sha, the number of failing commits, and the time red in hours.

R8 (all six repos). Human commits in H1 and in H2, grouped by person. In each half, the two people with the most commits (picked separately per half), and their share of that half's human commits. Share-of-work verdict.

R9 (all repos except sqlalchemy). pr_reviews rows submitted in H2 on PRs from that repo, where reviewer_login is not null, not the PR author and not a bot. Count each (PR, reviewer) pair once. Report the number of distinct reviewers, and the share of (PR, reviewer) pairs belonging to the two reviewers with the most pairs.

R10 (all six repos). Fix commits. A fix commit changed a test if any of its commit_files rows is a test file. Report the number of fix commits and the share that changed a test.

## Output

Write everything into the folder independent_check/ at the repo root:

1. independent_check/keys_pandas.py, a single script that computes all of the above.
2. independent_check/keys_pandas.json, written by the script, shaped like this:

```json
{
  "R1": {"tokio": {"h1_failing": 0, "h1_counted": 0, "h1_rate": 0.0, "h2_failing": 0, "h2_counted": 0, "h2_rate": 0.0, "verdict": "", "h1_rerun_pass_share": 0.0, "h2_rerun_pass_share": 0.0}},
  "R2": {"tokio": {"main_h1_min": 0.0, "main_h2_min": 0.0, "main_verdict": "", "pr_h1_min": null, "pr_h2_min": null, "pr_verdict": ""}},
  "R3": {"tokio": {"wait_h1_h": 0.0, "wait_h2_h": 0.0, "wait_verdict": "", "after_h1_h": 0.0, "after_h2_h": 0.0, "after_verdict": "", "h2_no_review_share": 0.0}},
  "R4": {"tokio": {"merged_h2": 0, "unapproved": 0, "unapproved_share": 0.0, "unapproved_bot_prs": 0}},
  "R5": {"tokio": {"opened": 0, "closed": 0, "verdict": "", "h1_bugs": 0, "median_days_to_close": 0.0, "share_not_closed": 0.0}},
  "R6": {"eslint": {"most_fixes_module": "", "most_fixes_count": 0, "most_fixes_module_commits": 0, "top_share_module": "", "top_share": 0.0}},
  "R7": {"tokio": {"first_failing_sha": "", "next_passing_sha": "", "failing_commits": 0, "hours_red": 0.0}},
  "R8": {"tokio": {"h1_top2_share": 0.0, "h2_top2_share": 0.0, "verdict": ""}},
  "R9": {"tokio": {"reviewers": 0, "top2_share": 0.0}},
  "R10": {"tokio": {"fix_commits": 0, "share_changed_test": 0.0}}
}
```

Use full 40-character shas in R7. Use null for an infinite median in R5. Shares and rates are fractions between 0 and 1, not percentages.

3. independent_check/NOTES.md, short and plain. List every place where a definition could be read more than one way, and which reading you chose. Also list anything in the data that surprised you.

When you're done, don't compare against anything. I do the comparison separately.

## Round 2: R11 and R12

I added two questions later. If you are reading this for Round 2, your earlier work is already in independent_check/. Extend keys_pandas.py with R11 and R12, rerun it, and add a short "Round 2" section to NOTES.md. The rules above still apply: don't open the forbidden files, don't use git to read them, and don't compare against anything. Don't change how R1 to R10 are computed. Their output must stay exactly the same.

R11 (eslint, vite, junit-framework, prometheus). Dependency bot PRs are pull_requests whose author_login is "renovate" or "dependabot". Opened: dependency bot PRs with created_at in W. Of those, merged share = merged_at before 2026-09-21, divided by opened. Closed unmerged share = merged_at null and closed_at before 2026-09-21, divided by opened. Autoclosed share = among the closed unmerged ones, the share whose title contains "autoclosed" (ignoring case), or null if there are none. Merge time: dependency bot PRs whose merged_at is in H1 or H2 (whenever they were opened), hours from created_at to merged_at, split by the half of merged_at. Report the median for each half and the median verdict.

R12 (all six repos). Human commits committed in W. Size = commits.additions + commits.deletions. Median size for commits in H1 and in H2 (by committed_at) and the median verdict. Over the whole window, the median size of fix commits and the median size of the other human commits, with no verdict. Fix commit is defined above.

Add these to keys_pandas.json:

```json
{
  "R11": {"eslint": {"opened": 0, "merged_share": 0.0, "closed_unmerged_share": 0.0, "closed_autoclosed_share": 0.0, "merge_h1_h": 0.0, "merge_h2_h": 0.0, "merge_verdict": ""}},
  "R12": {"tokio": {"h1_median_lines": 0.0, "h2_median_lines": 0.0, "verdict": "", "fix_median_lines": 0.0, "other_median_lines": 0.0}}
}
```


## Round 3: the bot rule

A test found that the old bot rule missed automation in eslint. Commits with no login counted as human, and 124 of them were made by eslint's release server (jenkins@eslint-03) and its daily README job (eslint@googlegroups.com). I changed the Bots and Human commit definitions above. The changes are:

1. junit-builds is added to the list of bot logins.
2. A login that ends with "bot", ignoring case, is a bot. This replaces eslintbot in the list, which it already covers.
3. A commit with a null author_login and an author_email of jenkins@eslint-03 or eslint@googlegroups.com is not a human commit.

If you are reading this for Round 3, your earlier work is in independent_check/. Change keys_pandas.py to use the new definitions everywhere a bot or a human commit is used, rerun it, and add a short "Round 3" section to NOTES.md that says which outputs changed. The rules above still apply: don't open the forbidden files, don't use git to read them, and don't compare against anything. Don't change anything else.
