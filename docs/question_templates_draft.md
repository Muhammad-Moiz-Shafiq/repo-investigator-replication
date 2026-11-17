# Question templates, draft 3

Updated 2026-10-22. These are the questions for the scaled study. I apply each template to every repo it fits. The five pilot questions are my dev set and are not in here.

I tested every definition on the real data before writing it down. My exploration scripts are in scripts/key_exploration/. The result tables come from scripts/answer_keys/compute_keys.py, my primary key script in SQL, which follows docs/key_spec_for_independent_check.md exactly. The keys are frozen (answer_keys/FREEZE.json, tag keys-frozen-v1). The rest of this file can still change, for example when I add the coverage level setups.

## Shared rules

Windows. The full window is 2025-10-01 to 2026-09-20. H1 is 2025-10-01 to 2026-03-31. H2 is 2026-04-01 to 2026-09-20. Both halves sit inside the span every repo fully covers. They are not the same length, so comparisons use rates, shares and medians, never raw counts.

Timestamps only. I compute everything from timestamps, never from current state fields, because I ingested the repos on different days. One exception I can't avoid is issue labels. GitHub doesn't give label history, so labels are as of the ingestion date.

Bots. GitHub's GraphQL API gives bot logins without the [bot] suffix for PRs and reviews, while commits have it. A "login contains bot" rule would also drop real people, like codeboten and subotac. So bots are a fixed list: renovate, dependabot, github-actions, eslintbot, copilot-pull-request-reviewer, copilot-swe-agent, Copilot, plus any login ending in [bot]. I built the list by reading every login in the data that contains "bot" or "copilot". A looser rule (the list plus anything containing "bot") gave identical results everywhere I tried it.

People. A person is their GitHub login. If a commit has no login, I use its author email. One person with two emails counts as two, which is a known limit.

Missing authors. A deleted GitHub account shows up with no login. A review on such a PR counts as a review by someone other than the author. This happens once in the data (tokio PR 7984).

Merge commits are left out of commit counts. In repos that use merge commits, the merger would otherwise get credit for everyone's work.

Gerrit. sqlalchemy does its reviews and merges on Gerrit. GitHub has no true answer for its review questions, so R3, R4 and R9 skip it. I decided this before any runs. Every condition still gets exactly the same question set.

Wording. Each question opens with one neutral line about who is asking and why. It never hints at the answer. Each question names the exact workflow, label and rule it uses, so the agent doesn't have to guess what I mean.

## How "did it change" is decided

For rates (R1, R8): "up" or "down" only if a two-sided Fisher exact test gives p below 0.05. For shares of work (R8) the share must also move by at least 5 points. Otherwise the verdict is "no clear change".

For medians (R2, R3): "up" or "down" only if the 95% bootstrap interval for the ratio of medians excludes 1, and the change is at least 20%. Durations have long tails. With hundreds of PRs, a 5% shift can be statistically clear and still mean nothing to a maintainer, hence the size floor.

For bug intake (R5): "growing" or "shrinking" only if an exact binomial test on opened vs closed gives p below 0.05. Otherwise "balanced".

I use tests instead of fixed cutoffs because the repos are very different sizes. A 2 point change means a lot in a repo with 600 commits and nothing in one with 170.

## Per-repo settings

| Repo | {main_ci} | {bug_label} | Module = |
|---|---|---|---|
| tokio | CI, .github/workflows/ci.yml | C-bug | top folder |
| eslint | CI, .github/workflows/ci.yml | bug | folder under lib/ |
| sqlalchemy | Run tests, .github/workflows/run-test.yaml | bug | folder under lib/sqlalchemy/ |
| vite | CI, .github/workflows/ci.yml | p3-minor-bug | folder under packages/ |
| junit-framework | CI, main.yml until 2026-05-15, then ci.yml | type: bug | top folder |
| prometheus | CI, .github/workflows/ci.yml | kind/bug | top folder |

{main_ci} is the main test workflow, picked as the workflow with the most push runs on the main branch. The question names it by its file. In the data it is matched by workflow id, not by name, because names are not unique. In eslint, two other workflows (docs-ci.yml and types-integration.yml) logged runs named "CI" until January 2026, starting in the same second as the real one. I caught this by computing the keys twice. My SQL and my earlier pandas exploration broke the tie between same-second runs differently, so they disagreed on eslint. junit renamed main.yml to ci.yml in May 2026, which gave the same workflow a new id, so it has two.

For vite I use p3-minor-bug and not "bug: upstream", which marks bugs in other projects.

## Rules for CI questions (R1, R2, R7)

Main branch only. "Main branch" means the default branch, which is called master in tokio. The CI data has no branch field. A run counts only if its commit is in the main-branch commit history. In prometheus this removes 882 of 2,382 push runs, mostly from release branches.

The landing run. A commit can get push runs again later, for example when it is pushed to a release branch or tagged. I only use the run from when it landed on main, which is its earliest push run, with its final result after any re-runs. I found this the hard way: without it, a prometheus commit that passed on May 19 picked up a failing release-branch run from May 28.

Failing means failure, timed_out or startup_failure. Cancelled and skipped runs are left out. Cancelled usually means CI stopped an old run because a newer push came in.

Edge cases, which I wrote down after the independent check. If two push runs of one commit start in the same second, the lower run id is the landing run. A run with no start time can't be a landing run. A counted result that is neither failing nor success breaks a streak. None of these happen in the main CI data, where push results are only success, failure, cancelled and one startup_failure.

A push with several commits only runs CI on the last one, so "consecutive commits" really means consecutive pushes.

## Rules for fix commits (R6, R10)

The pilot's bug-fix flag only counts a commit if its message closes a bug-labeled issue. In a full year that catches 2 commits in vite, 5 in eslint and 6 in tokio, because these repos squash-merge and reference the PR number, not the issue. It can't carry a question.

So the question states its own rule: a fix commit is a non-merge, non-bot commit whose first line contains the word fix, fixes, fixed, fixing or bugfix. I read 8 random matches per repo by hand. Nearly all eslint matches were real code fixes (it uses a strict "fix:" convention), about 6 in 8 for vite, 5 in 8 for prometheus, 4 in 8 for tokio, and only 1 or 2 in 8 for junit and sqlalchemy (things like "Fix formatting"). The agent and the key follow the same stated rule, so grading is fair. But "fix" in a subject line is only a proxy for a bug fix, and I will say so in the paper.

Sensitivity alternative: a strict rule that also drops subjects mentioning docs, typo, lint, CI, tests, formatting and similar.

Test files. A file is a test file if any folder in its path is test, tests, __tests__, testdata, testing, fixtures, playground (vite's end-to-end tests) or ends in -test or -tests, or if its name looks like a test (_test.go, test_*.py, *_test.py, *Test.java, *Tests.java, *.test.ts, *.spec.js and similar). Go keeps tests next to the code, so a folders-only rule would miss most of prometheus's tests (60% drops to 12%). That's why both folders and file names are needed.

## The ten templates

R1. CI stability. A maintainer deciding whether to spend time on CI. Did the share of commits that fail {main_ci} on the main branch change between H1 and H2? How often did a failing run pass just by re-running it? Sources: B&Z testing practices, DORA change failure rate (loose). All six repos.

R2. CI speed. A contributor tired of waiting for feedback. Did successful {main_ci} runs on the main branch get slower or faster between H1 and H2? Is the change the same for pull request runs of {main_ci}? Source: B&Z productivity. All six repos. sqlalchemy has no pull request runs, so its answer to the second part is that there are none.

R3. Where PR time goes. A maintainer whose PRs sit too long. For PRs merged in H1 and in H2, what is the median time from opening to first review, and from first review to merge? Did either change? Sources: CHAOSS Time to First Response and Change Request Duration. Not for sqlalchemy.

R4. Unreviewed merges. A security reviewer. Of the PRs merged in H2, how many had no approval from someone other than the author before they were merged, and how many of those were opened by bots? Sources: OpenSSF Scorecard Code-Review check, CHAOSS Change Request Reviews. Not for sqlalchemy.

R5. Bug intake vs closing. A triager. How many {bug_label} issues were opened and how many were closed in the window? Is the bug backlog growing, shrinking or balanced? For bugs opened in H1, what was the median time to close? Sources: CHAOSS Issue Resolution Duration, Issues New, Issues Closed. All six repos.

R6. Fix hotspots. A new reviewer. Counting a commit as a fix by the stated rule, which module had the most fix commits in the window? Among modules with at least 20 commits, which had the highest share of fix commits? Source: B&Z bug measurements. Only eslint, prometheus, sqlalchemy and vite (see results).

R7. Broken build. Whoever is on build duty. Find the longest stretch in H2 where {main_ci} stayed red on the main branch. Which commit did it first fail on, what did that commit change, which commit did it next pass on, and how long was it red? Source: B&Z development practices. All six repos.

R8. Commit concentration. A project lead thinking about risk. What share of non-merge, non-bot commits came from the two most active people in H1, and in H2? Did work become more or less concentrated? Source: CHAOSS Bus Factor. All six repos.

R9. Review load. A maintainer worried about reviewer burnout. In H2, how many people reviewed PRs, and what share of review work did the two busiest reviewers do? Source: B&Z teams and collaboration. Not for sqlalchemy.

R10. Tests with fixes. A code reviewer. Counting a commit as a fix by the stated rule, what share of fix commits in the window also changed a test file? Source: B&Z testing practices. All six repos.

R11. Dependency updates. A maintainer checking whether dependency updates keep up. For PRs opened by renovate and dependabot in the window, how many were opened, what share was merged, and what share was closed without merging? Why were the closed ones not merged? For bot PRs merged in H1 and in H2, what was the median time to merge, and did it change? Source: OpenSSF Scorecard Dependency-Update-Tool check. Only eslint, vite, junit-framework and prometheus (see R11 results).

R12. Change size. A code reviewer. Measuring a human non-merge commit by lines added plus lines deleted, did the median commit size change between H1 and H2? What is the median size of fix commits and of other commits in the window? Source: B&Z code churn questions. All six repos.

That made 55 questions from R1 to R10. Each template runs on six repos, minus R3, R4 and R9 on sqlalchemy (Gerrit) and R6 on tokio and junit-framework (see R6 results). The no-tool floor then dropped R6-eslint and R6-vite, which left 53. I then added R11 (4 repos) and R12 (6 repos), which the floor didn't catch, so the study has 63 questions (see Adding R11 and R12 below).

## What testing on the data changed

R9 started as "how many people do half of all reviews, and did that change". In three repos that count sat right on the 50% line. eslint's margin was 0.0%, so a few reviews either way flip the answer. Moving to the share done by the top two reviewers fixed the level, but the trend still flipped for tokio and prometheus under reasonable counting choices. So R9 asks for the H2 level only.

R8 had the same 50% line problem with "how many people make half the commits" (margins of 0.0% in tokio and 0.4% in prometheus). The top-two share fixed it, and here the trend held under every alternative, so R8 keeps the trend.

R10 started with a trend and a "which module has untested fixes" part. The trend flipped for eslint under the strict fix rule, and the module part was based on 1 to 4 commits in most repos. So R10 asks for the level only.

R6 dropped tokio, because the highest-share module changed under the strict rule (tokio-util or tokio). It dropped junit-framework because its top module has only 6 fix commits. Rule: an R6 instance needs at least 10 fix commits in its top module and a stable answer under the strict rule.

R4 asks for counts of bot PRs instead of a share. In most repos only a handful of PRs were unapproved, and a share of 6 is not worth grading.

## Definitions and results

My first exploration scripts counted reviews from deleted accounts in R3, and only reviews on merged PRs in R9. The primary script follows the spec on both, which is why a few numbers differ from earlier drafts.

### R1

Unit: main-branch commits with a counted landing run, each counted once, so a commit with several runs can't count twice.

Half: decided by when the landing run started. Failure rate: failing commits over counted commits, per half. Verdict: Fisher test as above.

Re-run part: the share of counted commits whose landing run needed more than one attempt and ended in success. GitHub only keeps the final attempt's result, so this means "passed after someone re-ran it", not flakiness in general. Prometheus flips between fail and pass within an hour, which looks flaky, but its team rarely re-runs. They push again, so it barely shows up here. That's why the question asks about re-runs and not flakiness.

Key. Must have: both failure rates within 1.5 points, and the verdict. Should have: both re-run shares roughly right, and a sensible reading of what changed. Known wrong: a clear change where the verdict is "no clear change", counting runs instead of commits, counting release-branch runs.

Alternatives tried: cancelled counted as failing, half by commit time, counting runs. No verdict changed.

| Repo | H1 failing | H2 failing | Verdict | Passed after re-run, H1 then H2 |
|---|---|---|---|---|
| eslint | 2.5% | 1.2% | no clear change | 2.8%, 1.8% |
| junit-framework | 8.7% | 10.8% | no clear change | 2.3%, 3.0% |
| prometheus | 38.5% | 29.8% | down | 1.6%, 0.3% |
| sqlalchemy | 21.4% | 7.5% | down | 1.5%, 0.0% |
| tokio | 3.5% | 2.0% | no clear change | 6.9%, 13.9% |
| vite | 13.1% | 34.3% | up | 6.6%, 1.4% |

I checked four random vite runs on GitHub. They matched exactly, including that the failures are real test jobs.

### R2

Runs: successful landing runs of {main_ci} on the main branch. Duration is run start to finish, so queue time is not included. Half by start time. Verdict: median rule above. Second part: the same for successful pull_request runs of {main_ci}.

Key. Must have: both medians within 10%, and the verdict. Should have: the pull request comparison, and what it suggests. If main got slower but PR runs didn't, the extra time is on main-branch-only jobs.

Alternative tried: first attempts only. No verdict changed.

| Repo | Main, H1 to H2 (minutes) | Verdict | PR runs, H1 to H2 | Verdict |
|---|---|---|---|---|
| eslint | 5.6 to 5.1 | no clear change | 5.5 to 5.1 | no clear change |
| junit-framework | 7.7 to 8.5 | no clear change | 10.0 to 11.8 | no clear change |
| prometheus | 26.9 to 44.7 | up | 21.3 to 23.8 | no clear change |
| sqlalchemy | 43.3 to 42.6 | no clear change | none | |
| tokio | 18.2 to 21.0 | no clear change | 18.3 to 20.7 | no clear change |
| vite | 5.2 to 5.4 | no clear change | 5.3 to 5.5 | no clear change |

### R3

PRs: merged, author not a bot, split by merge date. First review: the earliest review of any kind (approved, commented, changes requested or dismissed) by someone other than the author, not a bot and not a deleted account, submitted before the merge. PRs with no such review are left out of the medians and reported as a share. Verdict: median rule above, separately for each part.

Key. Must have: the four medians within 15%, and both verdicts. Should have: which part is bigger, and the share merged with no review.

Alternatives tried: split by opening date instead of merge date, looser bot rule. Opening date flipped prometheus's wait verdict (up to no clear change) and the after-review verdict (no clear change to down). The question names the merge date, so the opening date is not a fair reading of it. I keep prometheus but note it as the least stable R3 instance.

| Repo | Wait for first review, H1 to H2 (hours) | Verdict | First review to merge | Verdict | H2 merged with no review |
|---|---|---|---|---|---|
| eslint | 6.8 to 6.0 | no clear change | 4.3 to 0.2 | no clear change | 1.3% |
| junit-framework | 18.8 to 12.5 | no clear change | 25.4 to 12.8 | no clear change | 29.6% |
| prometheus | 8.9 to 17.7 | up | 2.3 to 1.5 | no clear change | 0.8% |
| tokio | 4.1 to 9.4 | up | 3.7 to 1.7 | no clear change | 0.0% |
| vite | 11.7 to 22.9 | up | 1.5 to 0.7 | no clear change | 19.3% |

In junit, 81% of PRs merged in H2 came from renovate. Among the human PRs, the lead maintainer merged 18 of their 34 with no one else reviewing.

### R4

PRs: merged in H2, bots included. Unapproved means no APPROVED review from someone other than the author, not a bot, submitted at or before the merge.

Key. Must have: the unapproved count within 10% (at least 1), and how many of them are bot PRs, exact. Should have: the unapproved share.

I changed this on 2026-10-24, before any study run. The old must-have checked the share, which the question never asks for, and skipped the bot count, which it does ask for. The judge trial on practice answers showed it. The bot count is exact because the counts are 0 to 4, so a tolerance of 1 would accept almost any small guess. The floor agrees: with a tolerance of 1, one floor try passes R4-tokio by luck, and exact gives none. No drop depends on this choice.

Alternatives tried: approval at any time, any review counting as approval, looser bot rule. Shares moved by at most 6 points (vite, 23.8% to 17.6% when any review counts). The question says "approval", so the main rule stands.

| Repo | Merged in H2 | Unapproved | Of those, bot PRs |
|---|---|---|---|
| eslint | 288 | 1.4% (4) | 0 |
| junit-framework | 424 | 6.8% (29) | 1 |
| prometheus | 687 | 0.9% (6) | 2 |
| tokio | 252 | 1.2% (3) | 0 |
| vite | 547 | 23.8% (130) | 4 |

### R5

Issues with {bug_label}. Opened means created in the window. Closed means closed in the window, whenever it was opened. Verdict: binomial rule above. Time to close is for bugs opened in H1. Bugs still open on 2026-09-20 count as "not closed yet", so the median is right even when many are still open.

Key. Must have: opened and closed counts within 2, the verdict, and the median days within 10%. Should have: share of H1 bugs still open.

Alternative tried: any label containing "bug". Only vite changed, because it would add "bug: upstream". The question names the label. Verdicts all stayed balanced.

| Repo | Opened | Closed | Verdict | Median days to close, H1 bugs | Still open |
|---|---|---|---|---|---|
| eslint | 89 | 88 | balanced | 2.4 | 9.3% |
| junit-framework | 41 | 40 | balanced | 5.9 | 3.8% |
| prometheus | 32 | 46 | balanced | 46.7 | 29.2% |
| sqlalchemy | 103 | 115 | balanced | 2.0 | 5.1% |
| tokio | 57 | 66 | balanced | 2.3 | 22.7% |
| vite | 61 | 62 | balanced | 87.7 | 23.5% |

Every verdict is "balanced", so an agent could guess that part. The counts and medians vary a lot (2 days to 88 days), and those are must-haves too, so the question still separates good answers from guesses.

### R6

Fix commits by the stated rule. Files that are tests or docs, and files at the repo root, are left out. Each commit counts once per module it touches.

Key. Must have: the module with the most fix commits, and the module with the highest fix share among modules with at least 20 commits. Should have: the counts.

| Repo | Most fix commits | Highest fix share (20+ commits) |
|---|---|---|
| eslint | lib/rules (59 of 112) | lib/linter (67%) |
| prometheus | promql (60 of 202) | model (32%) |
| sqlalchemy | lib/sqlalchemy/dialects (18 of 109) | lib/sqlalchemy/orm (20%) |
| vite | packages/vite (246 of 555) | packages/vite (44%) |

Both answers stayed the same under the strict rule for these four, with one caveat. For sqlalchemy under the strict rule, dialects and orm tie at 12 fix commits each, and dialects only wins on the tie-break (more commits overall). Under the stated rule it's a clear 18 to 15, so I keep it, but it's the weakest R6 instance.

### R7

Uses the CI rules above, one landing-run status per commit, in order of when the landing run started. A streak is a run of failing commits with a passing commit right before and right after. Streaks that start in H1, or are still failing at the end, don't count. Longest means the most time red, from when the first failing run finished to when the next passing run finished. Ties go to the streak with more commits. If the second-longest streak is within 1% of the longest, both are accepted, since no sensible reader would call one longer. This happens once: junit's streak from ad922b18 to 05b4ea07 (3 failing commits, 33.10 h) against d2dd0bca to f05dd1b2 (33.14 h). The next closest pair is vite at 87.6 h and 81.6 h, 7% apart. Time red includes quiet periods: if nobody pushes for a week while main is red, main really was red that week.

The data shows where CI first failed and where it next passed. It can't prove the first commit caused the failure or that the other fixed it. In prometheus, the next passing commit is an unrelated merge. So the question asks which commit it first failed on and next passed on.

Key. Must have: the first failing commit, the next passing commit, and time red within 10%. Should have: at least one file or folder the first failing commit changed, and a careful view on whether it caused the failure. Known wrong: starting at a cancelled run, a branch run, or a later re-push of an old commit.

Alternatives tried: cancelled counted as failing, any failed run instead of the final result, ordering by commit time. No streak changed.

| Repo | First failed on | Next passed on | Failing commits | Time red |
|---|---|---|---|---|
| eslint | 9ac7eb60 | 92086c87 | 1 | 17.1 h |
| junit-framework | d2dd0bca | f05dd1b2 | 4 | 33.1 h |
| prometheus | e48be9d7 | 9c235097 | 3 | 169.4 h |
| sqlalchemy | aa1a5575 | 2dd1451c | 1 | 119.9 h |
| tokio | 9c880b08 | 6858348a | 1 | 171.8 h |
| vite | a07a4bd0 | dfc8aa50 | 2 | 87.6 h |

I checked prometheus by hand: after the third failing push on April 27, nothing was pushed to main until May 4. The commits dated in between came in through the May 4 merge.

### R8

Non-merge, non-bot commits, grouped by person. The top two are picked separately in each half. Verdict: Fisher test plus the 5 point rule.

Key. Must have: both shares within 3 points, and the verdict.

Alternative tried: including merge commits. No verdict changed, though prometheus's shares rise because maintainers get credit for merges.

| Repo | Top two share, H1 | H2 | Verdict |
|---|---|---|---|
| eslint | 31.1% | 24.4% | no clear change |
| junit-framework | 82.3% | 85.5% | no clear change |
| prometheus | 20.1% | 28.0% | more concentrated |
| sqlalchemy | 76.5% | 71.9% | no clear change |
| tokio | 27.9% | 29.3% | no clear change |
| vite | 63.0% | 49.0% | less concentrated |

### R9

Reviews submitted in H2, on any PR (merged or not, since reviewing a PR that gets closed is still work), by someone other than the PR author, not bots, not deleted accounts. Unit: one reviewer on one PR, so ten comments on the same PR count once. Answer: number of distinct reviewers, and the share of review work done by the two busiest.

Key. Must have: the share within 3 points. Should have: the number of reviewers within 2.

Alternatives tried: counting every review submission, looser bot rule, top three. Shares moved by up to 4 points with raw submissions.

| Repo | Reviewers in H2 | Top two share |
|---|---|---|
| eslint | 23 | 53.9% |
| junit-framework | 7 | 95.9% |
| prometheus | 57 | 38.3% |
| tokio | 26 | 58.5% |
| vite | 29 | 81.2% |

### R10

Fix commits by the stated rule over the full window. Answer: the share that also changed at least one test file.

Key. Must have: the share within 3 points. Should have: the number of fix commits within 5%.

| Repo | Fix commits | Also changed a test |
|---|---|---|
| eslint | 127 | 78.0% |
| junit-framework | 42 | 31.0% |
| prometheus | 351 | 60.1% |
| sqlalchemy | 72 | 55.6% |
| tokio | 53 | 39.6% |
| vite | 322 | 48.4% |

The strict rule moves these a lot (tokio goes to 68%, eslint to 91%), because it removes docs and CI fixes that never touch tests. The question states the rule, so the key follows it. The spread is a reminder that this number depends on what you call a fix, and I will say so in the paper.

### R11

Dependency bot PRs: PRs opened by renovate or dependabot. Other bots (eslintbot, github-actions) don't update dependencies, so they're left out. Opened means created in the window. Merged and closed unmerged are decided by the end of the window. Merge time is for bot PRs merged in H1 and in H2, split by merge date like R3, so a PR opened late in H2 that isn't merged yet can't pull the H2 median down. Verdict: median rule above.

Repos: an R11 instance needs at least 20 dependency bot PRs opened in the window. tokio has 6 and sqlalchemy 11 (and it merges on Gerrit), so they're out.

Why were they closed without merging? Renovate adds "autoclosed" to the title when a newer update replaces a PR. Dependabot closes replaced PRs without changing the title, so the autoclosed share is a lower bound on how many were replaced. That part is a should-have, not a must-have.

Key. Must have: opened within 5% (at least 2), merged share within 3 points, both merge medians within 15%, and the verdict. Should have: the closed unmerged share, and that many closed ones were replaced by newer updates.

Alternatives tried: split by opening date, renovate only, all bot PRs. Only one verdict moved: prometheus goes from down to no clear change with renovate only. Its slow H1 merges were mostly dependabot PRs. The question names both bots, so leaving one out is not a fair reading of it. I keep prometheus but note it as the least stable R11 instance, as with R3. I also tried a "[security]" split, since renovate marks security updates. There are too few to use (eslint 3, vite 8, junit none).

| Repo | Opened | Merged | Closed unmerged | Of those, autoclosed | Merge time, H1 to H2 (hours) | Verdict |
|---|---|---|---|---|---|---|
| eslint | 79 | 82.3% | 17.7% | 50% | 3.5 to 7.7 | no clear change |
| junit-framework | 625 | 97.1% | 2.9% | 50% | 7.7 to 10.2 | no clear change |
| prometheus | 339 | 72.3% | 27.4% | 47% | 53.8 to 20.2 | down |
| vite | 167 | 83.2% | 16.2% | 19% | 3.5 to 6.5 | no clear change |

### R12

Human non-merge commits in the window. Size is lines added plus lines deleted, from the commit. I checked that this equals the sum over the commit's files in 99.8% of commits. Verdict for H1 to H2: median rule above. The fix part asks for two medians and no verdict.

Key. Must have: both half medians within 10% (at least 1 line), the verdict, and the fix and other medians within 10% (at least 1 line).

Alternatives tried: leaving out lock files, snapshots and dist/, the strict fix rule, files changed instead of lines, and bots included. The H1 to H2 verdict held under all of them. "Are fixes smaller than other commits" flipped in three repos under the strict fix rule (tokio, sqlalchemy, prometheus), so, as with R10, that part asks for levels only.

| Repo | Median lines, H1 to H2 | Verdict | Fix commits | Other commits |
|---|---|---|---|---|
| eslint | 15 to 20 | no clear change | 41 | 13 |
| junit-framework | 10 to 10 | no clear change | 5 | 11 |
| prometheus | 35 to 33 | no clear change | 24 | 36 |
| sqlalchemy | 35 to 58.5 | no clear change | 22 | 59 |
| tokio | 21 to 34 | up | 12 | 30 |
| vite | 20 to 23 | no clear change | 18.5 | 23 |

sqlalchemy's median grew by two thirds and still isn't a clear change, because its bootstrap interval is wide. That is the rule doing its job, not a bug.

## How the keys were checked

1. I wrote the primary keys in SQL (scripts/answer_keys/).
2. A separate coding agent (OpenAI Codex) wrote a second version in pandas from the written spec alone, without seeing my code or results. Its log shows it never opened those files. The two versions matched on all 265 fields (answer_keys/comparison.md). The only difference was a label for an empty case, and I fixed the spec wording.
3. I checked 17 rows by hand on github.com (docs/spot_checks.md), and 6 more for R11 and R12. All matched. The pages show dates but not exact times, so I also compared the exact times of all 17 rows with the GitHub API. All matched to the second.
4. I froze the keys. scripts/answer_keys/freeze_keys.py records a hash of each key file and a fingerprint of every table, and its check must pass before any run or grading.

## No-tool floor

The exact question texts are in questions/questions.json, written by scripts/questions/render_questions.py. Every condition reads that one file. I checked that no question contains its own answer. My first draft gave packages/vite, lib/rules and lib/sqlalchemy/orm as examples of a module, and those are R6 answers, so the examples are now placeholders like packages/<name>.

The floor asks every question to three models with no tools and no data: openai/gpt-5-mini, deepseek/deepseek-v4-flash and google/gemini-3.6-flash. The first two are the models I plan to carry over from the pilot. The third is newer and stronger, so it knows more about these projects and makes the floor stricter. Each model answers each question 3 times and gives its best guess for every must-have field as JSON. scripts/floor/grade_floor.py grades the guesses against the frozen keys with the must-have items in scripts/floor/must_haves.py, which follow the "Key. Must have" lines above.

Rule, written before the first run: a question is dropped if any of the three models meets every must-have item in at least 2 of its 3 tries. One lucky hit in 3 is reported but not dropped. I don't tighten a question after seeing floor results, I only drop it, so the floor can't be used to tune questions. The report also lists how often guessing gets each single item right. Items that guessing often gets right (for example a verdict that is "balanced" everywhere) shouldn't carry much weight in the main grading.

Result (floor_results/floor_report.md). 495 replies, all parsed, total cost about $0.76. Five deepseek replies came back empty or cut off, so I asked those five again before grading. That didn't change the result.

Dropped: R6-eslint and R6-vite. gpt-5-mini named both eslint modules (lib/rules and lib/linter) in all 3 tries, and gemini named packages/vite for both vite parts in all 3. These answers follow from knowing the project layout. vite's code nearly all lives in packages/vite, and eslint is mostly rules, so no data is needed. That leaves 53 questions, and R6 now runs only on prometheus and sqlalchemy.

Met every must-have once, by luck, and kept under the rule: R1-eslint, R9-prometheus, R9-tokio. Each was one try out of three, from deepseek, plus one gemini try for R9-tokio. R4-tokio was on this list until the R4 must-have was fixed (see R4 above). R9 has only one must-have number, which makes a lucky hit easier.

Single items. Guessing never got a commit sha right, and almost never a count or a median. Verdicts were guessed right 13% to 39% of the time, close to chance with three options. Even R5, where every key is "balanced", was only guessed right 31% of the time, because the models mostly guessed a growing backlog. The main grader shouldn't pass an answer on a verdict alone, and with these checklists it doesn't.

## Adding R11 and R12

After the first floor, I checked whether 53 questions are enough with a power simulation. For a 20-point accuracy drop between coverage levels, 53 questions gave 94% power when each question is one data point, and 84% when each template is one data point. New templates helped the strict analysis more than new repos did. So I added two templates that ask about different parts of the process: dependency updates (R11) and change size (R12). I left out two other candidates (newcomer PRs and declined PRs) to keep the set focused.

R11 and R12 went through the same steps as the others: tested on the data with alternatives, keys in SQL, the floor (no drops), spot checks (docs/spot_checks.md, round 2), and the independent check (Round 2 in docs/key_spec_for_independent_check.md). Adding them to the key script didn't change any R1 to R10 key. I checked that the output is identical to the keys-frozen-v1 tag. Once the round 2 checks pass, I freeze all twelve as keys-frozen-v2.

Round 2 result. Codex's pandas version matched on all 323 fields, and its R1 to R10 output didn't change. I checked spot checks 18 to 23 on github.com and against the API, plus 30 random commit sizes. All matched. I froze all twelve templates as keys-frozen-v2. The freeze now also covers the question texts (questions/questions.json) and the floor result.

## Still to do

1. Build coverage levels 0 to 3 for each template (docs/coverage_levels_design.md).
