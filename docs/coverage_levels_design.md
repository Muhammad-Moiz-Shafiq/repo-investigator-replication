# Coverage levels: design draft

Draft 3, 2026-10-23. The level 2 tools are built and tested; the rest is not built yet. Early notes called these "rungs" (steps on a ladder). I switched to "coverage levels" because it says what it means. This file explains what the levels are, how each template gets its tools, and how I test that the levels are fair before any agent sees them.

## What a coverage level is

The main question of the study (RQ2) is how an agent's accuracy changes as its tools cover less of the question. To measure that, I ask the same question several times and change only the tools.

An everyday comparison: you ask a new team member "did CI get worse this year?"

- Level 0. You hand them a dashboard that shows exactly that number. They only have to read it correctly.
- Level 1. You hand them reports that each show part of it, for example the failure count for one half of the year. They have to pull the parts together and compare.
- Level 2. You hand them the raw run log. They have to filter, count and compare everything themselves.
- Level 3. You hand them logs for other things (PRs, issues) but no CI data at all. The honest answer is "I can't tell from what I have." I want to see whether they say that, find a fair workaround, or make something up (RQ3).

The question, the model, the system prompt and the budget stay the same at every level. Only the tools change. So if accuracy drops from level 0 to level 2, the drop comes from coverage, not from a harder question or a weaker model.

## The general recipe

Every template uses the same recipe, so the levels mean the same thing across all twelve.

Level 0, direct tool. One tool takes the repo and the dates and returns every must-have value of the question, including the verdict. The agent has to pick the right tool, pass the right arguments, and report the output faithfully.

Level 1, part tools. Tools that each return one correctly defined part: the landing runs of one period, the fix commits of one window, the review times of one half. They return counts, and lists as a result id the calculators accept, never a finished statistic like a verdict, a median or an overall share. The shared definitions (landing run, bot, fix, test file) are built in. The agent combines the parts: it calls them for each period, runs the calculators, applies the question's thresholds and does small arithmetic. No single call gives the whole answer.

So each step down removes one kind of help. Level 0 does the combining and the definitions. Level 1 does the definitions but leaves the combining. Level 2 leaves both. Level 3 takes the data away.

What is an argument and what is built in. Anything the question states that differs between repos or questions is an argument at levels 0 and 1: the dates, the workflow (by path or file name, as GitHub's API allows), the bug label, the module folder, the bot names in R11 and the 20 commit threshold in R6. The rules that every question of a template repeats are built in, and each tool's description states them so the agent can check them against the question. Dates are inclusive, as the questions write them.

Level 2, generic query tools. One tool per table. They know the table's columns but nothing about any question. They can filter, group, count and sort, like a standard data API. The agent has to turn every definition in the question into these operations itself: which runs count, who is a bot, what a fix is, what a module is.

Level 3, no coverage. The query tools, minus every tool that reads the data the question needs. The right answer is to say the data isn't available, or to give a clearly labeled partial workaround.

The levels are nested. Level 2 is the query tools. Level 1 adds the part tools. Level 0 adds the direct tool. Level 3 removes tools from level 2. So moving down a level only ever takes coverage away. Nothing else changes.

## What stays the same at every level

The question text. It comes from questions/questions.json, which is frozen.

The system prompt. It holds the shared definitions, including how "did it change" is decided (the Fisher test, the bootstrap rule with the 20% floor, the binomial test). The questions don't state these rules. Putting them in the system prompt gives every level and both variants the same rules without touching the frozen questions.

The calculators. Every level has the same four calculators: median and summary, Fisher test, binomial test, and the median comparison rule. They take either a short list of numbers or a result id from an earlier query (see below), so the agent never has to copy hundreds of numbers into a call. They read no table themselves, so they don't change coverage. They let level 2 test whether the agent can get the right numbers out of the data, not whether it can run a Fisher test in its head.

The budget. Every run gets at most 25 steps, the same as the pilot. A step is one model turn, as in the pilot: the model answers once, and that answer can ask for one or more tool calls. I also record the number of tool calls in every run, so it can be reported. When the 25 steps are used up, the run stops and its answer is graded as it stands. The limit is the same at every level and in Variant B, so no setup gets more chances to fix its mistakes. It is fixed and won't be raised.

## The menu at each level

Menus are set per template, not per question. All questions of one template (for example R1 on all six repos) get the same menu, and the repo is just an argument. Every menu is built by the same rule:

- Level 2: the 7 query tools below plus the 4 calculators. This is the same 11 tools for every template.
- Level 1: level 2 plus that template's part tools (one or two).
- Level 0: level 1 plus that template's direct tool.
- Level 3: level 2 minus the query tools that read the tables the key needs.

So the menu gets shorter as coverage drops. For R1 it goes 13, 12, 11, 9. I don't pad menus with filler tools. Removing tools is the ablation, and a shorter menu is part of what removing them means. Fillers would also differ from template to template and add a new difference I'd have to control.

A shorter menu is, if anything, easier to choose from. So the shrinking menu can only make the lower levels look a little better than they would otherwise. That makes any drop I measure a slight underestimate (a conservative bias). It can't create a drop that isn't there. The catch is the other direction: if a level shows no drop, a shorter menu could be hiding a small one. So I say "no detectable drop" in that case, never "no drop".

To measure this instead of assuming it, I add one side check, decided before any runs. On level 2, I run the same questions twice: once with the normal 11 tools, and once padded to exactly that template's level 0 size (13 or 14 tools) with 2 or 3 filler tools. Nothing else changes. The fillers are list_releases, repo_languages and repo_info. They work and show true data, saved once from the GitHub API (scripts/tools/snapshot_repo_extras.py, tool_data/repo_extras.json), but releases, code languages and basic repo facts can't help with any study question. A broken or fake filler would bias the check, so they are real. They never appear in a main menu, and a test checks that.

How big the gap is. Level 0 has 2 or 3 more tools than level 2. In the text the model reads, it is only about 8% longer (about 7,900 against 7,200 tokens of tool descriptions), because the query tools carry most of the text. Work on tool selection reports trouble mainly with dozens or hundreds of tools, so I expect a small effect, but I measure it.

Why not one shared toolbox. I considered giving every question all 39 tools, so menu size would barely change. I rejected it. At level 2 for R1, R2's run_durations would still be there with the landing run rule built in, which is the help level 2 removes, and at level 3 it would still read the CI data. Fixing that means removing tools per template again. It would also double the tool text in every turn (about 14,800 tokens), and that cost is paid on every call. The size is about 1 or 2 models, all study questions, 3 tries each. The final numbers are set after the smoke test, before the main runs.

The side check never changes the main results or the main analysis. I report it whatever it shows, in a short section or the appendix. If the two scores are close, the menu size effect is shown to be small. If they differ, I report the size of the difference next to the main results and word the level comparisons with that in mind. Reporting it only if it turned out useful would be cherry picking, so it is always reported.

I log the menu size in every run.

## The generic query tools (level 2)

Why not plain listing tools. My first plan was tools that only list raw rows, 200 per page. Before building them I counted how many rows a perfect agent would need to read. On prometheus, R6 needs 11,653 file rows (59 pages), R2 needs 5,612 runs and R3 needs 5,177 PRs and reviews. That doesn't fit in 25 steps. Even where it fits, no model can take the median of 2,483 numbers or count thousands of file paths by reading them. Level 2 would score near zero for reasons that have nothing to do with coverage, and it would look the same as level 3. So level 2 gets generic query tools instead.

What they are. Each tool reads one table and takes the same kind of arguments. The design follows PostgREST, the standard REST API that Supabase puts on every Postgres table: filters, column choice, ordering, paging, exact counts, reading linked rows, and basic aggregates. I add a few things PostgREST doesn't have. Each one is a standard SQL feature, and none knows anything about a question: comparing two columns, keeping the first row per group (DISTINCT ON), a condition on a single aggregate (FILTER), consecutive stretches of rows, computed columns, and result ids. All of them are in every query tool.

- Filters on any column: equals, not equals, in a list, not in a list, less or greater than, a case-insensitive pattern match, its opposite, empty, not empty, and "list contains" for labels. A filter can compare two columns, such as reviewer is not the PR author. "Any of" joins groups of filters with or, like PostgREST's or filter.
- First row per group: for example the earliest run for each commit.
- Group by one or more columns, with count, distinct count, min, max, sum and average. Each aggregate can have its own condition, such as counting only the failing runs.
- Stretches: split the rows, in order, into runs of consecutive rows where a condition holds or doesn't. Each stretch comes back as one row with its first and last row and the first row after it. This is the "gaps and islands" pattern, done in SQL with window functions (LAG and LEAD) and in pandas with shift and cumsum. It is how streaks and outages are usually measured, for example DORA's time to restore service.
- Computed columns: hours between two time columns, or the sum of two number columns, which can then be filtered and sorted. The calculators already accept the same two.
- Order by any column or aggregate, 200 rows per page, and the total number of matching rows or groups.
- A result id for every query. It stands for the full result, not just the page shown, and the calculators accept it. So "the median of these 2,483 commit sizes" is one call. A calculator can also work on the difference between two time columns (hours from opening to merge) or the sum of two columns.

The tools and their columns. They show timestamp and identity columns only, never current-state fields like approval_count or state, following the timestamps rule in question_templates_draft.md. Linked fields work like PostgREST's embedded reads, and each tool declares every table it reads.

- query_workflows(repo): id, name and file path of each workflow. Names aren't unique (eslint has two workflows named CI, junit has five), so the path is needed to find the workflow a question names. The CI table stores each run's workflow id and name but not its path. So I fetched the workflow list once per repo from the GitHub API and saved it (scripts/tools/snapshot_workflows.py, tool_data/workflows.json). Runs read that file, never the live API. It is covered by the freeze check.
- query_ci_runs: run id, workflow id, commit, event, result, attempt, start, finish, duration, and whether the commit is on the default branch (like GitHub's own branch filter). Reads ci_runs and commits.
- query_commits: sha, author (the GitHub login) and author email, time, first line of the message, lines added, deleted and their total (GitHub's stats.total), merge or not. Default branch only. Reads commits.
- query_commit_files: commit, file name, its first, second and third folder, lines added and deleted, plus the commit's time, author, author email, first line and merge flag. Reads commit_files and commits.
- query_pull_requests: number, title, author, opened, merged and closed times. Reads pull_requests.
- query_pr_reviews: PR number, reviewer, review state, time, plus the PR's author and its opened and merged times. Reads pr_reviews and pull_requests.
- query_issues: number, title, labels, opened and closed times. Reads issues.

Why these additions, and the line I hold. Every addition so far was made because a template needed it: first row per group for the landing run rule, the share aggregate for rates, stretches for R7. That is how level 2 is defined: the smallest set of generic operations that can answer all 12 templates. If a question can't be answered at level 2, every model fails it there, and that measures my API, not the models. The line is that no addition may do a question's thinking. Each one must be a standard SQL or pandas operation, must have no question-specific names, values or thresholds, and must be listed here with the template that needed it.

What stays the agent's job. The tools never apply a definition from a question. The agent has to pick the right workflow, notice that some commits have more than one run, exclude bots, write the fix pattern, choose the module depth, leave out test and doc files, and decide which numbers go into which test. That is the gap between level 2 and level 1, where the part tools do this for it.

The difference from Variant B. Variant B writes free SQL and Python. Level 2 can only use this fixed set of typed operations. That is the same contrast as typed tools against bash in the papers I build on.

## Per template

Level 0 is always one direct tool, so the table names it and lists the other levels.

| Template | Level 0 tool | Level 1 part tools | Level 3 removes |
|---|---|---|---|
| R1 CI stability | ci_failure_trend | landing_run_counts(period): counted, failing, passed after a re-run | CI runs and workflows |
| R2 CI speed | ci_duration_trend | run_durations(event, period): successful run durations as a result id | CI runs and workflows |
| R3 PR time | pr_review_timing_trend | first_review_times(merge period): counts, and wait and after-review hours as a result id | reviews |
| R4 Unreviewed merges | unapproved_merges | merged_pr_count(period, author kind), approved_pr_count(period, author kind) | reviews |
| R5 Bug intake | bug_backlog_report | issue_counts(label, opened or closed, period), time_to_close(label, opened period, as of) | issues |
| R6 Fix hotspots | fix_hotspots | module_commit_counts(module folder, period): per module commits, fix commits and fix share | commit files |
| R7 Broken build | longest_red_streak | red_stretches(period), commit_details(sha) | CI runs and workflows |
| R8 Commit concentration | commit_concentration_trend | commits_by_person(period) | commits, commit files, CI runs |
| R9 Review load | review_load | review_pairs_by_reviewer(period) | reviews |
| R10 Tests with fixes | fix_test_coverage | fix_commit_count(period, changed a test file or not) | commit files |
| R11 Dependency updates | dependency_pr_report | bot_pr_counts(authors, opened period), merge_times(authors, merge period) | PRs and reviews |
| R12 Change size | commit_size_trend | commit_sizes(period, all, fix or other) | commits, commit files, CI runs |

Level 3 follows one strict rule: no tool that is left may read a table the answer needs, even just to check that a row exists. The CI run tool checks the commits table to say whether a run's commit is on the default branch, so it goes for R8 and R12 as well. Menu sizes from level 0 to level 3 are 13 or 14, 12 or 13, 11, and 8 to 10.

Some level 3 cases leave a possible workaround. R8 without commits still has PR authors. R11 without PRs still has the commits that bots merged. That's intended. RQ3 labels a workaround as correct only if it's clearly labeled as a proxy and is reasonable.

Variant B (open code execution) has no levels. It gets the same question, system prompt and budget, with read-only SQL and Python on the full database. It's the reference arm for RQ1. For RQ3, its silent errors come from these same runs: answers that are wrong but don't say anything is missing or uncertain. Variant B gets no level 3 version with tables removed. RQ3 doesn't ask for one, and it would add cost and scope.

## The tests that make the levels fair

Before any agent runs, every one of the 63 questions has to pass these five tests at every level. They're code, and they run again before each batch of runs, like the freeze check.

1. Level 0 is exact. The direct tool's output, called with the question's own dates, equals the frozen key on every must-have field. If it doesn't, the tool has a bug, and the key is never touched.

2. Levels 1 and 2 are reachable. I write a scripted "perfect agent" for each template. It can only call that level's tools, through the same code path the real agent uses, and then compute on what they return. It must pass every must-have check against the frozen key (the same checks the grader uses), within the step budget. At level 2 it may only do small arithmetic itself, on at most 20 numbers it read from tool outputs. Everything bigger has to go through a tool or a calculator, because that is all a model can do reliably in its head. This proves a correct answer is possible at every level. A drop in accuracy then means the agent didn't find the path, not that there was no path. If level 2 can't fit in 25 steps for a big repo, I add a general operation to the query tools, one that any data API might offer. I never raise the budget, and never change the question or a key to make a recipe pass. If a recipe fails because the key itself is wrong, the key is fixed with a written reason and frozen again. That happened once, before any agent run: the bot rule (see docs/decisions.md and answer_keys/bot_audit.txt).

3. No shortcuts. At level 1, no part tool output holds every must-have value of its question as top-level fields, and none holds a finished statistic (a verdict, a median, an overall percentage or share) at the top level. Per-row values, like each module's fix share, are parts: the agent still has to choose among them by the question's rules. I checked that this test catches a shortcut: it flags all 12 direct tools. At level 2, no tool applies a definition from any question. Every operation is one a generic data API offers, and the test checks the tool code has no question-specific filters, names or thresholds.

4. Level 3 is really empty. Each tool declares the tables it reads, and the test checks that no level 3 tool reads a table the key needs. The no-tool floor already showed the answers can't be guessed.

5. Same everything else. A test compares the system prompt, budget and question text across the four levels of each question, and fails if anything other than the tools differs. It also checks the nesting: each level's menu is exactly the one above it minus the removed tools.

## Settled choices

- Menus shrink as coverage drops, with a side check on menu size (see "The menu at each level").
- Level 2 uses generic query tools, not plain listing tools (see "The generic query tools").
- Level 0 tools take dates as arguments, like a real metrics API, rather than having them built in. That keeps one small step (passing the right dates) at level 0.
- The step budget is 25 model turns everywhere, as in the pilot, and is not raised.
- Level 2 gets the generic stretches operation and computed columns, so R7 stays in every level.
- Variant B has no level 3 version.
