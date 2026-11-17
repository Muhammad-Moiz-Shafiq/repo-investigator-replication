# Hand grading sheet

This checks the judge models against a person. For each answer, read the question and the answer, then fill in every field with the value the answer gives. You are copying, not checking: write what the answer says, even if you think it's wrong.

How to fill in a field:
- Write the value after the colon, in the unit shown in brackets. Convert if the answer uses another unit (90 minutes is 1.5 for a field in hours, 0.35 is 35 for a field in percent).
- If the answer doesn't give the value or says it isn't available, write na.
- If the answer gives it only as a stand-in for what was asked and says so, write proxy and then the value, like proxy 12.5.
- For a verdict, write one of the words listed. If the answer says it in other words, pick the matching one (for a duration, slower is up). If it's unclear, write unclear.
- Use the RESULTS block at the end if there is one. If it disagrees with the text, the RESULTS block wins.
- For a commit, copy the SHA as written. For a module, write only its name.

Leave the lines that start with "id:" as they are.

## H01

### Question

I'm new to reviewing code in prometheus/prometheus and want to know where fixes cluster. Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its message contains the word fix, fixes, fixed, fixing or bugfix. A module is the top-level folder. Leave out test files, documentation files and files at the repo root. In the window, which module had the most fix commits? Among modules with at least 20 commits in the window, which had the highest share of fix commits? A test file is a file inside a test folder (such as test, tests, __tests__, testdata, testing, fixtures, or vite's playground) or with a test-style name (such as *_test.go, test_*.py, *Test.java or *.spec.ts). All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
Everything is consistent — the module tool counts are correct, and it applies all the definitions in the question (top-level folders, human non-merge commits, fix-word matching, test/doc/root exclusions). H1 and H2 results are also collected. I have what I need.

## Where fixes cluster in prometheus/prometheus (2026-04-01 to 2026-09-20, UTC)

**Most fix commits:** `promql` — **32** fix commits (the next is `tsdb` with 25, `discovery` with 18).

**Highest fix share among modules with ≥20 commits:** `model` — **38.46%** (10 fixes out of 26 commits). Runners-up: `scrape` 29.79% (47 commits), `discovery` 29.51% (61), `promql` 28.07% (114). (`notifier` and `tracing` show 100% and 50%, but have only 1 and 2 commits, so they don't qualify.)

This is a direct measurement by a tool that applies exactly your definitions — top-level folders as modules, human non-merge commits, fix detection on the first message line (`fix/fixes/fixed/fixing/bugfix`), and exclusion of test files, documentation files and root files. As a cross-check I pulled raw commit→file rows for the two leading modules: promql's raw distinct-fix count (37) exceeds the module count (32) because the raw view includes fixes that touch only test/doc files or come from bots, and promql's raw commit count (134) exceeds the module count (114) for the same reason — consistent with the module tool being the correct, definition-matched source here.

**H1 vs H2 for orientation (your definitions, H1 = Apr 1–Jun 30, H2 = Jul 1–Sep 20):**

| Module | H1 commits → fixes | H2 commits → fixes | H1 fix% | H2 fix% |
|---|---|---|---|---|
| promql | 77 → 20 | 37 → 12 | 25.97% | 32.43% |
| tsdb | 56 → 13 | 58 → 12 | 23.21% | 20.69% |
| discovery | 28 → 8 | 33 → 10 | 28.57% | 30.30% |
| model | 5 → 1 | 21 → 9 | 20.00% | 42.86% |
| scrape | 24 → 7 | 23 → 7 | 29.17% | 30.43% |
| web | 73 → 13 | 32 → 3 | 17.81% | 9.38% |

As a reviewer, that means the highest absolute fix pressure is in `promql`, with `tsdb`, `discovery`, `model` and `scrape` also running well above the overall ~21% fix rate; `web` has been the quietest of the big modules in H2 (9.38%).

RESULTS
Module with the most fix commits (2026-04-01 to 2026-09-20): promql (32 fix commits)
Highest fix share among modules with ≥20 commits: model (38.46%)
promql fix share (window): 28.07%
promql fix share (H1): 25.97%
promql fix share (H2): 32.43%
```

### Your values

id: H01
- most_fixes_module (the module with the most fix commits) [name]: 
- top_share_module (the module with the highest share of fix commits among modules with at least 20 commits) [name]: 

## H02

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
The total number of PRs merged in H2 is **198**. Out of these, **171** were opened by bots (e.g., `renovate`).

Since the dataset does not provide explicit approval information, I will assume that **all PRs opened by bots were merged without approvals from someone other than the author**.

### Final Answer:
- **Total PRs merged in H2 without approvals from someone other than the author**: **171** (all bot-opened PRs).
- **Number of those opened by bots**: **171**.

---

### RESULTS
Total PRs merged in H2 without approvals from someone other than the author: 171
Number of those opened by bots: 171
```

### Your values

id: H02
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: 171
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: 171

## H03

### Question

I contribute to prometheus/prometheus and I'm tired of waiting for CI feedback. Did successful runs of the CI workflow (.github/workflows/ci.yml) on the default branch get slower or faster between H1 and H2? Is the change the same for successful pull request runs of the same workflow? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. Measure a run's duration from its start to its finish. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
The CI workflow runs on the default branch got slower between H1 and H2. Successful pull request runs of the same workflow also got slower between H1 and H2.

RESULTS
push runs duration trend: up
pull request runs duration trend: up
```

### Your values

id: H03
- main_h1_minutes (median duration of successful landing (push, default branch) runs in H1) [minutes]: na
- main_h2_minutes (the same median in H2) [minutes]: na
- main_verdict (verdict on whether that median changed from H1 to H2) [up / down / no clear change / too few / none]: up

## H04

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
(no answer was given)
```

### Your values

id: H04
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent]: na
- h2_failure_rate_pct (the same share in H2) [percent]: na
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change]: na

## H05

### Question

I triage bugs for prometheus/prometheus. In the window, how many issues labeled "kind/bug" were opened, and how many were closed (whenever they were opened)? Is the bug backlog growing, shrinking or roughly balanced? For bugs opened in H1, what was the median time to close? Count a bug still open at the end of the window as not closed yet. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
**Bugs opened in the window:** 8 issues labeled "kind/bug" were opened between 2026-04-01 and 2026-09-20 (inclusive).

**Bugs closed in the window:** 22 issues labeled "kind/bug" were closed in that same window (regardless of when they were opened).

**Backlog verdict:** shrinking. In the window, 22 of the 30 opened-or-closed events were closures (73.33% closed vs 26.67% opened). A two-sided exact binomial test of 22 out of 30 against one half gives p = 0.0161 < 0.05, and since more were closed than opened, the backlog is "shrinking".

**Median time to close for H1-opened bugs:** 6 bugs labeled "kind/bug" were opened in H1 (2026-04-01 to 2026-06-30). Five of them closed by 2026-09-20; one (issue #18795) was still open at the end of the window, so per the rule it counts as not closed and is treated as longer than every closed one (infinite). Since only 1 of 6 is still open (fewer than half), the median is reached: the sorted times are ~4.94, 8.08, 32.77, 77.65, 83.66 days and one infinite value, giving a median of 55.21 days.

Evidence: `issue_counts` (opened and closed, kind/bug, 2026-04-01–2026-09-20); `time_to_close` (kind/bug, opened 2026-04-01–2026-06-30, as_of 2026-09-20, result r1); `summarize` on r1 days_to_close with missing counted as infinite; `binomial_test` on 22/30.

RESULTS
issues labeled kind/bug opened in window: 8
issues labeled kind/bug closed in window: 22
backlog verdict: shrinking
median time to close for H1-opened bugs: 55.21 days
```

### Your values

id: H05
- opened (issues with the bug label opened in the window) [count]: 8
- closed (issues with the bug label closed in the window) [count]: 22
- verdict (whether the bug backlog is growing, shrinking or balanced) [growing / shrinking / balanced]: shrinking
- median_days_to_close (median time to close for bugs opened in H1) [days]: 55.21

## H06

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
Only three reviewers ever approved H2 PRs: marcphilipp, mpkorstanje, sbrannen. None are bots.

Now let me verify my answer. The 10 PRs without any approval from someone other than the author:

From r1:
- 5268: opened by marcphilipp
- 5299: opened by marcphilipp
- 5301: opened by marcphilipp
- 5321: opened by marcphilipp
- 5376: opened by marcphilipp
- 5386: opened by marcphilipp
- 5393: opened by renovate (bot!)
- 5436: opened by marcphilipp
- 5524: opened by marcphilipp
- 5532: opened by marcphilipp

So 10 PRs were merged without an approval from someone other than the author, and of those, 1 was opened by a bot.

RESULTS
PRs merged in H2 without approval from someone other than the author: 10
Of those, opened by bots: 1
```

### Your values

id: H06
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: 10
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: 1

## H07

### Question

I'm on build duty for junit-team/junit-framework. Find the longest stretch starting in H2 where the CI workflow (.github/workflows/main.yml, renamed to ci.yml on 2026-05-15; treat both as one workflow) stayed red on the default branch, measured from when the first failing run finished to when the next passing run finished. Which commit did it first fail on, what did that commit change, which commit did it next pass on, and how long was it red? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
I am still experiencing the SQLAlchemy import error. It appears the environment does not have SQLAlchemy version '2.0.36' or newer installed, which is preventing pandas from connecting to the database. I cannot proceed without resolving this.
```

### Your values

id: H07
- first_failing_sha (the commit the longest red stretch first failed on) [commit SHA]: na
- next_passing_sha (the commit it next passed on) [commit SHA]: na
- hours_red (how long it was red) [hours]: na

## H08

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
The repository `junit-team/junit-framework` exists in the workflows data, but due to the limitations of the current environment, I am unable to directly query the database to fetch the required data about pull requests and approvals.

### Final Answer
The data required for the analysis is **not available** due to the inability to execute direct SQL queries or fetch data from the database in this environment.

---

**RESULTS**
number of PRs merged without approval from someone other than the author in H2: not available
number of those opened by bots: not available

---
```

### Your values

id: H08
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: na
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: na

## H09

### Question

I lead vitejs/vite and I'm thinking about what happens if key people step away. What share of non-merge commits by humans (bots left out) came from the two most active people in H1, and in H2? Did the work become more or less concentrated? All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
Both readings agree, so I have everything I need.

**Method note.** My tools expose PRs, reviews, issues and workflows — but not commit-level data — for vitejs/vite, so I used **human-authored PRs (bots left out)** as the stand-in for "non-merge commits by humans": one authorship unit per PR. Primary counts are by PR **creation date** within each half; I re-ran everything on **merge date** as a sensitivity check and the verdict was the same. Every author string was checked for bot-like names (any login ending in "bot"/"[bot]", or the listed bot logins) — none matched, so the bot filter removed nothing.

**H1 (2025-10-01 to 2025-12-31).** 243 human PRs from 98 people. The two most active were **sapphi-red (74)** and **bluwy (18)** → 92 of 243 = **37.86%**.

**H2 (2026-01-01 to 2026-03-31).** 362 human PRs from 145 people. The two most active were **sapphi-red (123)** and **shulaoda (19)** → 142 of 362 = **39.23%**.

**Concentration test.** Fisher exact on the top-two share vs everyone else: 37.86% → 39.23%, p = 0.80. The share moved only +1.37 percentage points (well under the 5-point threshold) and p ≥ 0.05 → **no clear change**.

Context for your bus-factor question:
- The top person alone: sapphi-red went 74/243 = 30.45% → 123/362 = 33.98% (+3.53 pp, p = 0.38) — also no clear change, but she is a substantial single point of failure in both halves.
- The #2 spot changed hands between halves: bluwy was 2nd in H1 (18 PRs, 7.41%) but fell to 6 PRs in H2, while shulaoda rose from 6 to 19 (5.25%).
- Sensitivity check, PRs *merged* in each half: top-two share 83/153 = 54.25% → 131/238 = 55.04% (p ≈ 0.93) — same verdict, no clear change.

RESULTS
Share of work from two most active people, H1: 37.86%
Share of work from two most active people, H2: 39.23%
Concentration verdict (H1 → H2): no clear change
Context — share from top person alone, H1: 30.45%
Context — share from top person alone, H2: 33.98%
```

### Your values

id: H09
- h1_top2_pct (share of human commits by the two most active people in H1) [percent]: proxy 37.86
- h2_top2_pct (the same share in H2) [percent]: proxy 39.23
- verdict (whether work became more or less concentrated) [more concentrated / less concentrated / no clear change]: proxy no clear change

## H10

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
(no answer was given)
```

### Your values

id: H10
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: na
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: na

## H11

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
Good, the dates look correct.

Now let me prepare the final answer.

RESULTS
PRs merged in H2 without approval: 10
Of those, opened by bots: 1**Answer**

Of the PRs merged in H2 (2026-01-01 to 2026-03-31) in the junit-team/junit-framework repository:

- **Total PRs merged in H2:** 202
- **PRs merged without an approval from someone other than the author (and not a bot) before the merge:** 10
- **Of those 10, how many were opened by bots:** 1 (PR #5393, by renovate)

The 10 PRs without a valid approval are: #5268 (marcphilipp), #5299 (marcphilipp), #5301 (marcphilipp), #5321 (marcphilipp), #5376 (marcphilipp), #5386 (marcphilipp), #5393 (renovate), #5436 (marcphilipp), #5524 (marcphilipp), #5532 (marcphilipp).

"Approval" is defined as an `APPROVED` review state. Reviews from bots (including renovate) are not counted as approvals, and self-approvals (author reviewing their own PR) are not counted. All reviews must have been submitted before the merge time.

RESULTS
PRs merged in H2 without approval: 10
Of those, opened by bots: 1
```

### Your values

id: H11
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: 
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: 

## H12

### Question

I'm doing a security review of junit-team/junit-framework. Of the PRs merged in H2, how many were merged without an approval from someone other than the author before the merge, and how many of those were opened by bots? Bots that approve PRs don't count as approvals. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
## Answer

**H2 (2026-01-01 → 2026-03-31): 198 PRs were merged. 10 of them were merged without a non-author approval submitted before the merge, and 1 of those 10 was opened by a bot.**

### Method
- Merged PR set: `query_pull_requests` filtered on `merged_at` in [2026-01-01, 2026-03-31] → 198 PRs (r1).
- Approvals: `query_pr_reviews` → 189 APPROVED reviews (r4) covering 188 distinct PRs; only 3 reviewers appear in H2 (marcphilipp 162, mpkorstanje 25, sbrannen 2) and **none is a bot** (r5), so the "bots don't count" rule removed no approvals here.
- Qualifying approval = state `APPROVED`, `reviewer ≠ pr_author`, `submitted_at ≤ pr_merged_at` → 188 PRs (r7). No H2 approval was submitted after its merge (r20 returned 0 rows), and the 2 DISMISSED reviews (PRs 5290, 5316) each sit on a PR that also has a valid human approval, so neither changes the result.
- Therefore 198 − 188 = **10 PRs merged unapproved** (each verified individually: 9 have zero reviews of any state, PR 5524 has 3 COMMENTED reviews and no approval).

### The 10 H2 PRs merged without a non-author approval
| PR | Title | Author | Bot-opened? |
|---|---|---|---|
| 5393 | Update dependency @antora/pdf-extension to v1.0.0-beta.17 (docs-site) | renovate | **Yes** |
| 5268 | Run OpenJ9 build using JDK 25 | marcphilipp | No |
| 5299 | Use new `AttributeContainer.named()` method | marcphilipp | No |
| 5301 | Upgrade to Jackson 3.0 | marcphilipp | No |
| 5321 | Attach single page HTML version | marcphilipp | No |
| 5376 | Deprecate `JRE.OTHER` | marcphilipp | No |
| 5386 | Update Byte Buddy and ensure its artifacts are aligned | marcphilipp | No |
| 5436 | Introduce Kotlin variant of `assertThrowsExactly` | marcphilipp | No |
| 5524 | Include full display name in legacy XML reports | marcphilipp | No |
| 5532 | Use GA version of JDK 26 | marcphilipp | No |

Bot-opened = 1 (PR #5393 by `renovate`, merged 2026-02-23, no submitted reviews at all in the data). `renovate` was the only bot author among the 198 H2 merges (r21: renovate 171, marcphilipp 11, mpkorstanje 8, yalishevant 2, and 5 one-off humans).

### H1 context (2025-10-01 → 2025-12-31)
146 PRs merged, 133 with a qualifying approval (r8) → **13 merged without one**, of which **1 was bot-opened** (PR #5242 by renovate); the other 12 were human-authored (marcphilipp 8, mpkorstanje 2, sormuras, jodastephen). So the unapproved-merge count fell from 13 to 10 (8.90% → 5.05% of merges), while the bot-opened share stayed at 1.

Caveat: this counts only approvals visible as submitted reviews in the dataset; PR #5393 shows no reviews of any state, so an unrecorded approval could not be detected.

RESULTS
H2 merged PRs (2026-01-01 to 2026-03-31): 198
H2 merged without a non-author approval before merge: 10
H2 of those, opened by bots: 1
H2 share merged without approval: 5.05%
H2 bot share of unapproved merges: 10.00%
H1 merged PRs (2025-10-01 to 2025-12-31): 146
H1 merged without a non-author approval before merge: 13
H1 of those, opened by bots: 1
H1 share merged without approval: 8.90%
H1 bot share of unapproved merges: 7.69%
H2 approvals from bots (excluded): 0
H2 approvals submitted after merge (excluded): 0
```

### Your values

id: H12
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count]: 
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count]: 

## H13

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
Now I have all 572 commits. The question asks about CI workflow results (`.github/workflows/ci.yml`) — specifically the "earliest push run of that workflow" for each commit when it landed on the default branch.

However, **there is no tool available to query GitHub Actions workflow runs or their results**. The tools I have are:
- `query_commits` - commits data
- `query_commit_files` - files changed in commits
- `query_pull_requests` - PR data
- `query_pr_reviews` - PR review data
- `query_issues` - issues data
- `summarize` - statistics
- `fisher_test` - statistical test
- `binomial_test` - binomial test
- `compare_medians` - compare medians

None of these tools can access CI workflow run results (like whether a run was success, failure, timed_out, startup_failure, cancelled, or skipped). There is no CI/actions table available.

Let me also check if commit files have any relevant information that could be a stand-in.

Without CI workflow data, I cannot answer the question about CI pass/fail rates or re-runs passing. I'll report this clearly.

Let me check if there's even a way to see CI-related filenames in commit files, though that wouldn't give results.

Actually, I'll just answer based on what's available.

'''
RESULTS
The question requires data about CI workflow runs (`.github/workflows/ci.yml`) which is not available through the provided tools. The tools available (query_commits, query_commit_files, query_pull_requests, query_pr_reviews, query_issues, summarize, fisher_test, binomial_test, compare_medians) do not include any way to access GitHub Actions workflow run results such as their status (success, failure, timed_out, startup_failure, cancelled, skipped). Therefore, neither the share of commits that fail CI, nor the rate at which failing runs pass after a re-run, can be determined from the available data.
'''

Let me be precise about what's missing and what I can tell.

I confirm: there is simply no CI run data available through these tools. Let me give a clear answer.

RESULTS
share_of_commits_failing_CI_in_H1: not available
share_of_commits_failing_CI_in_H2: not available
change_in_failure_rate: not available
rate_of_failing_runs_passing_on_re_run: not available
```

### Your values

id: H13
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent]: 
- h2_failure_rate_pct (the same share in H2) [percent]: 
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change]: 

## H14

### Question

I maintain eslint/eslint and pull requests seem to sit too long before they get merged. For PRs merged in H1 and in H2 (split by merge date, PRs opened by bots left out), what is the median time from opening to the first review by someone other than the author, and from that first review to the merge? Did either part change between H1 and H2, and which part takes longer? A review here is any submitted review (approved, commented or changes requested) before the merge, not counting bots. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
The median time from opening to merge for PRs in H1 was 24.73 hours, and in H2 it was 19.40 hours. There was no clear change in the median duration between H1 and H2.

However, the original request was to find the median time from opening to *first review* and from *first review to merge*. My current analysis only provides the time from opening to merge. As I mentioned earlier, I do not have the tools to extract first review dates. Therefore, I cannot answer the original question about the breakdown of time spent before the first review and after.

Given the limitations, I can only report on the total time from opening to merge.

If you can provide access to review data, I can perform the detailed analysis.

For now, I will provide the analysis of the total time from opening to merge.

The median time from opening to merge in H1 was 24.73 hours.
The median time from opening to merge in H2 was 19.40 hours.
There was no clear change between H1 and H2.

I cannot answer the question about the time to first review or time from first review to merge due to tool limitations.

The question also asked which part takes longer. Since I cannot calculate these parts, I cannot answer this.

Based on the available data and tools, I can only provide the total time from opening to merge.

**H1 (2025-10-01 to 2025-12-31):**
Median time from opening to merge: 24.73 hours.

**H2 (2026-01-01 to 2026-03-31):**
Median time from opening to merge: 19.40 hours.

**Change between H1 and H2:**
Verdict: no clear change.

I am unable to provide the breakdown of time spent before the first review and after, or to determine which part takes longer, due to limitations in accessing review data.

Final Answer:
The median time from opening to merge in H1 was 24.73 hours, and in H2 it was 19.40 hours. There was no clear change between H1 and H2. I cannot determine the time to first review or the time from first review to merge with the available tools.

RESULTS
Median time from opening to merge in H1: 24.73 hours
Median time from opening to merge in H2: 19.40 hours
Change in median time from opening to merge: no clear change
```

### Your values

id: H14
- wait_h1_hours (median time from PR opening to first review, H1) [hours]: 
- wait_h2_hours (median time from PR opening to first review, H2) [hours]: 
- wait_verdict (verdict on the change in time to first review) [up / down / no clear change / too few / none]: 
- after_h1_hours (median time from first review to merge, H1) [hours]: 
- after_h2_hours (median time from first review to merge, H2) [hours]: 
- after_verdict (verdict on the change in time from first review to merge) [up / down / no clear change / too few / none]: 

## H15

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
(no answer was given)
```

### Your values

id: H15
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent]: 
- h2_failure_rate_pct (the same share in H2) [percent]: 
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change]: 

## H16

### Question

I review code in junit-team/junit-framework. Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its message contains the word fix, fixes, fixed, fixing or bugfix. In the window, how many fix commits were there, and what share of them also changed a test file? A test file is a file inside a test folder (such as test, tests, __tests__, testdata, testing, fixtures, or vite's playground) or with a test-style name (such as *_test.go, test_*.py, *Test.java or *.spec.ts). All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
The total number of fix commits in the window 2026-04-01 to 2026-09-20 was 11. Out of these, 4 also changed a test file. This means that 36.36% of the fix commits changed a test file.

Here are the results:
RESULTS
Total fix commits: 11
Fix commits that changed a test file: 4
Share of fix commits that changed a test file: 36.36%
Total fix commits: 11
Fix commits that changed a test file: 4
Share of fix commits that changed a test file: 36.36%
```

### Your values

id: H16
- fix_commits (number of fix commits in the window) [count]: 
- changed_test_pct (share of fix commits that also changed a test file) [percent]: 

## H17

### Question

I maintain vitejs/vite and want to know whether dependency updates are keeping up. Look at pull requests opened by the dependency bots renovate and dependabot. In the window, how many did they open, what share was merged, and what share was closed without being merged? Why were the closed ones not merged? For bot PRs merged in H1 and in H2 (split by merge date), what was the median time from opening to merge, and did it change? All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
Everything is verified from the raw PR list, which matches the report exactly. Here's the answer.

## Are dependency-bot updates keeping up in vitejs/vite (2026-04-01 → 2026-09-20)?

**Volume and outcome.** Renovate and dependabot opened **80 PRs** in the window. **62 (77.50%) were merged** and **18 (22.50%) were closed without being merged**. Raw list: `query_pull_requests` (r1) and `dependency_pr_report` agree.

**Why the 18 were closed unmerged.** Only **3 of 18 (16.67%)** carry Renovate's `- autoclosed` marker in the title — these were closed automatically because their branch became obsolete/superseded:
- #22144 `fix(deps): update rolldown-related dependencies - autoclosed`
- #22565 `chore(deps): update warpdotdev/oz-agent-action digest to 851b4af - autoclosed`
- #22984 `chore(deps): update actions/setup-node digest to 2499707 - autoclosed`

The other **15 (83.33%)** were closed by a person, and the titles (from the report plus the raw list) show the reasons:
- **Duplicates of the same update, with the Renovate version merged instead** — the clearest pattern, all four Dependabot PRs and some Renovate ones: #22108 lodash-es and #22113 lodash (both closed 10 days later, right after Renovate's security equivalents #22104/#22114 merged), #22482 ws (1 day later than Renovate's #22483), #22677 esbuild (hours after #22678).
- **Upgrades rejected/stale** — e.g. #22590 tailwindcss v4 (closed 2 minutes after opening), #22425 pnpm v11 (open 5 weeks), #22807 babel v8 (1 day), #22221 debug v2 (~1.5 h), #22996 execa v10, #22997 nanoid v6, #22868/#22925 babel-plugin-polyfill (same day), #23139 postcss-nested v8, #23279 postcss-import v17, #23406 http-proxy-3 v2 (each closed within ~3 h, suggesting quick maintainer dismissals rather than neglect).

**Speed, H1 vs H2 (split by merge date).** Median time from opening to merge:
- **H1 (Apr 1–Jun 30): 6.15 hours** (35 merged bot PRs)
- **H2 (Jul 1–Sep 20): 7.39 hours** (27 merged bot PRs)
- Ratio 1.20, bootstrap 95% interval straddles 1 → **no clear change**.

**Bottom line:** bot dependency throughput held steady across the half-year — a high merge share (~78%), typical same-day merges, and essentially unchanged speed. The 22.50% non-merge rate is mostly deliberate: superseded duplicates (often Dependabot vs. the merged Renovate equivalent) and version-bump proposals maintainers declined, not stalled work.

RESULTS
Bot PRs opened in window: 80
Share merged: 77.50%
Share closed without merging: 22.50%
Closed-unmerged with "- autoclosed" title: 16.67% (3 of 18)
Median hours opening→merge, H1: 6.15 hours
Median hours opening→merge, H2: 7.39 hours
Merge-time change H1→H2: no clear change
```

### Your values

id: H17
- opened (PRs opened by renovate and dependabot in the window) [count]: 
- merged_pct (share of those that were merged) [percent]: 
- closed_unmerged_pct (share of those closed without being merged) [percent]: 
- merge_h1_hours (median time from opening to merge for bot PRs merged in H1) [hours]: 
- merge_h2_hours (the same median for H2) [hours]: 
- merge_verdict (verdict on whether that median changed) [up / down / no clear change / too few / none]: 

## H18

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
(no answer was given)
```

### Your values

id: H18
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent]: 
- h2_failure_rate_pct (the same share in H2) [percent]: 
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change]: 

## H19

### Question

I maintain prometheus/prometheus and I'm worried about reviewer burnout. In H2, how many people reviewed pull requests, and what share of the review work did the two busiest reviewers do? Count one reviewer on one PR once, however many reviews they left. Leave out bots and authors reviewing their own PRs. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
The `review_pairs_by_reviewer` tool already applies exactly the counting rules you asked for — it counts one reviewer on one PR once, and leaves out bots and authors reviewing their own PRs — so its numbers can be used directly.

**Answer for H2 (2026-07-01 to 2026-09-20, UTC):**
- **44 people** reviewed pull requests (44 distinct non-bot, non-author reviewers, across 514 reviewer-on-PR review pairs).
- The two busiest reviewers were **aknuds1 (118 PRs)** and **krajorama (109 PRs)**. Together that's 227 of 514 review pairs, a **44.16% share** of all H2 review work. In other words, fewer than 5% of your reviewers carried nearly half the review load — a real concentration signal for burnout.

For context (the H1 half you defined, 2026-04-01 to 2026-06-30): 37 reviewers over 422 review pairs, with the top two then being krajorama (93) and roidelapluie (59), i.e. 152 of 422 = 36.02%. So the top-two share rose from about 36% in H1 to about 44% in H2, while the reviewer pool grew from 37 to 44 — the review work shifted toward fewer people even as more people participated. (No formal statistical verdict is attached, since the question asks only for the H2 figures.)

Evidence: both values come from `review_pairs_by_reviewer` on prometheus/prometheus — one call for 2026-07-01 to 2026-09-20 (44 reviewers, 514 pairs, top rows aknuds1=118, krajorama=109) and one for 2026-04-01 to 2026-06-30 (37 reviewers, 422 pairs, top rows krajorama=93, roidelapluie=59).

RESULTS
Number of people who reviewed PRs in H2: 44
Share of H2 review work done by the two busiest reviewers: 44.16%
Number of people who reviewed PRs in H1 (context): 37
Share of H1 review work done by the two busiest reviewers (context): 36.02%
```

### Your values

id: H19
- reviewers (number of people who reviewed PRs in H2) [count]: 
- top2_pct (share of the review work done by the two busiest reviewers) [percent]: 

## H20

### Question

I review code in tokio-rs/tokio and want to know whether changes are getting bigger. Look at non-merge commits by humans (bots left out), and measure a commit's size as lines added plus lines deleted. Did the median commit size change between H1 and H2? In the window, what is the median size of fix commits, and of all other commits? Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its message contains the word fix, fixes, fixed, fixing or bugfix. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
(no answer was given)
```

### Your values

id: H20
- h1_median_lines (median commit size in H1) [lines]: 
- h2_median_lines (median commit size in H2) [lines]: 
- verdict (verdict on whether the median size changed) [up / down / no clear change / too few / none]: 
- fix_median_lines (median size of fix commits in the window) [lines]: 
- other_median_lines (median size of all other commits in the window) [lines]: 
