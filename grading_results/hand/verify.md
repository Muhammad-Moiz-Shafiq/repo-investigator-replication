# Check the judges' values

For each answer, read it, then look at what the judges copied from it. After "your mark:" write:
- ok, if the value is what the answer says (even if the answer itself is wrong),
- a or b, if the judges differ (A and B) and one of them is right,
- otherwise the right value, written as on the main sheet (a number in the unit in brackets, na, proxy and a value, or unclear).

na means the answer doesn't give that value. Use the RESULTS block at the end if there is one.

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

### Check these

id: H01
- most_fixes_module (the module with the most fix commits) [name] judges say: promql | your mark: ok
- top_share_module (the module with the highest share of fix commits among modules with at least 20 commits) [name] judges say: model | your mark: ok

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

### Check these

id: H11
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count] judges say: 10 | your mark: ok
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count] judges say: 1 | your mark: ok

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

### Check these

id: H12
- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count] judges say: 10 | your mark: ok
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count] judges say: 1 | your mark: ok

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

### Check these

id: H13
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent] judges say: na | your mark: ok
- h2_failure_rate_pct (the same share in H2) [percent] judges say: na | your mark: ok
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change] judges say: na | your mark: ok

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

### Check these

id: H14
- wait_h1_hours (median time from PR opening to first review, H1) [hours] judges say: na | your mark: ok
- wait_h2_hours (median time from PR opening to first review, H2) [hours] judges say: na | your mark: ok
- wait_verdict (verdict on the change in time to first review) [up / down / no clear change / too few / none] judges say: na | your mark: ok
- after_h1_hours (median time from first review to merge, H1) [hours] judges say: na | your mark: ok
- after_h2_hours (median time from first review to merge, H2) [hours] judges say: na | your mark: ok
- after_verdict (verdict on the change in time from first review to merge) [up / down / no clear change / too few / none] judges say: na | your mark: ok

## H15

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
(no answer was given)
```

### Check these

id: H15
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent] judges say: na | your mark: ok
- h2_failure_rate_pct (the same share in H2) [percent] judges say: na | your mark: ok
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change] judges say: na | your mark: ok

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

### Check these

id: H16
- fix_commits (number of fix commits in the window) [count] judges say: 11 | your mark: ok
- changed_test_pct (share of fix commits that also changed a test file) [percent] judges say: 36.36 | your mark: ok

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

### Check these

id: H17
- opened (PRs opened by renovate and dependabot in the window) [count] judges say: 80 | your mark: ok
- merged_pct (share of those that were merged) [percent] judges say: 77.5 | your mark: ok
- closed_unmerged_pct (share of those closed without being merged) [percent] judges say: 22.5 | your mark: ok
- merge_h1_hours (median time from opening to merge for bot PRs merged in H1) [hours] judges say: 6.15 | your mark: ok
- merge_h2_hours (the same median for H2) [hours] judges say: 7.39 | your mark: ok
- merge_verdict (verdict on whether that median changed) [up / down / no clear change / too few / none] judges say: no clear change | your mark: ok

## H18

### Question

I maintain vitejs/vite and I'm deciding whether to spend time on CI. Did the share of commits on the default branch that fail the CI workflow (.github/workflows/ci.yml) change between H1 and H2? How often did a failing run pass just because someone re-ran it? For each commit, use the run from when it landed on the default branch (its earliest push run of that workflow), with its final result. Count each commit once, and leave out cancelled and skipped runs. A failing run means a result of failure, timed_out or startup_failure. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
(no answer was given)
```

### Check these

id: H18
- h1_failure_rate_pct (share of counted commits whose landing run failed, in H1) [percent] judges say: na | your mark: ok
- h2_failure_rate_pct (the same share in H2) [percent] judges say: na | your mark: ok
- verdict (verdict on whether that share changed from H1 to H2) [up / down / no clear change] judges say: na | your mark: ok

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

### Check these

id: H19
- reviewers (number of people who reviewed PRs in H2) [count] judges say: 44 | your mark: ok
- top2_pct (share of the review work done by the two busiest reviewers) [percent] judges say: 44.16 | your mark: ok

## H20

### Question

I review code in tokio-rs/tokio and want to know whether changes are getting bigger. Look at non-merge commits by humans (bots left out), and measure a commit's size as lines added plus lines deleted. Did the median commit size change between H1 and H2? In the window, what is the median size of fix commits, and of all other commits? Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its message contains the word fix, fixes, fixed, fixing or bugfix. All dates are in UTC. The window is 2025-10-01 to 2026-03-31. H1 is 2025-10-01 to 2025-12-31 and H2 is 2026-01-01 to 2026-03-31, both inclusive.

### Answer

```text
(no answer was given)
```

### Check these

id: H20
- h1_median_lines (median commit size in H1) [lines] judges say: na | your mark: ok
- h2_median_lines (median commit size in H2) [lines] judges say: na | your mark: ok
- verdict (verdict on whether the median size changed) [up / down / no clear change / too few / none] judges say: na | your mark: ok
- fix_median_lines (median size of fix commits in the window) [lines] judges say: na | your mark: ok
- other_median_lines (median size of all other commits in the window) [lines] judges say: na | your mark: ok