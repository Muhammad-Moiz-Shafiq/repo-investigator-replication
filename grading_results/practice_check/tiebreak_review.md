# Tiebreaker calls to review

In each answer below, the two main judges (A and B) read something differently, and the tiebreaker (C) decided.
Read the answer. Then after "your call:" write ok if the decision is what the answer says, or else the right value,
written as on the hand sheet: a number in the unit in brackets, na, proxy and a value, or unclear.

## T001

### Question

I review code in junit-team/junit-framework. Count a commit as a fix if it is not a merge commit, is not from a bot, and the first line of its message contains the word fix, fixes, fixed, fixing or bugfix. In the window, how many fix commits were there, and what share of them also changed a test file? A test file is a file inside a test folder (such as test, tests, __tests__, testdata, testing, fixtures, or vite's playground) or with a test-style name (such as *_test.go, test_*.py, *Test.java or *.spec.ts). All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
I have retrieved commits for both H1 and H2. Now I will process these commits to count the "fix commits" according to your definition. I will exclude merge commits and commits from bots. I will also check the subject line for keywords "fix", "fixes", "fixed", "fixing", or "bugfix".

**Bot identification:**
I will consider the following logins as bots:
- renovate
- dependabot
- github-actions
- junit-builds
- copilot-pull-request-reviewer
- copilot-swe-agent
- Copilot
- Any login ending in "[bot]" or "bot" (case-insensitive).

I will iterate through the commits from H1 and H2, apply the filters, and count the fix commits. As previously noted, I cannot determine if test files were changed with the current tools.

**Processing H1 commits (2026-04-01 to 2026-06-30):**
Total commits: 217
- Merge commits: 0
- Bot commits:
    - renovate[bot]: 17
- Fix commits:
    - "Fix some NullAway wildcard warnings (#5602)" by msridhar on 2026-04-14.

**Processing H2 commits (2026-07-01 to 2026-09-20):**
Total commits: 224
- Merge commits: 0
- Bot commits:
    - renovate[bot]: 33
    - sbt/setup-sbt action: 2 (these are from renovate)
    - nmcp-settings: 1 (this is from renovate)
- Fix commits:
    - "Fix NoTestsDiscoveredException for suites containing only dynamic tests (#5839)" by mpkorstanje on 2026-07-04.
    - "Fix CI badge" by mpkorstanje on 2026-07-12.

Here's the count of fix commits for each period:

H1 (2026-04-01 to 2026-06-30): 1 fix commit.
H2 (2026-07-01 to 2026-09-20): 2 fix commits.

Since I cannot determine the share of fix commits that also changed a test file, I can only provide the counts of fix commits.
I will now output the results.

RESULTS
fix commits in H1: 1
fix commits in H2: 2
share of fix commits that changed a test file in H1: not available
share of fix commits that changed a test file in H2: not available

```

### Readings

- fix_commits (number of fix commits in the window) [count] A: na | B: 3 | C: na | decision: na | your call: 
- changed_test_pct (share of fix commits that also changed a test file) [percent] A: na | B: na | C: na | decision: na | your call: 

## T002

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

### Readings

- h1_top2_pct (share of human commits by the two most active people in H1) [percent] A: proxy 37.86 | B: proxy 37.86 | C: proxy 37.86 | decision: proxy 37.86 | your call: 
- h2_top2_pct (the same share in H2) [percent] A: proxy 39.23 | B: proxy 39.23 | C: proxy 39.23 | decision: proxy 39.23 | your call: 
- verdict (whether work became more or less concentrated) [more concentrated / less concentrated / no clear change] A: proxy no clear change | B: no clear change | C: proxy no clear change | decision: proxy no clear change | your call: 

## T003

### Question

I triage bugs for prometheus/prometheus. In the window, how many issues labeled "kind/bug" were opened, and how many were closed (whenever they were opened)? Is the bug backlog growing, shrinking or roughly balanced? For bugs opened in H1, what was the median time to close? Count a bug still open at the end of the window as not closed yet. All dates are in UTC. The window is 2026-04-01 to 2026-09-20. H1 is 2026-04-01 to 2026-06-30 and H2 is 2026-07-01 to 2026-09-20, both inclusive.

### Answer

```text
All parts of the answer are in. Note on method: the tools expose no issue/label data, so I used bug-fix PRs as a stand-in for "issues labeled kind/bug" (title matching `fix|bug`, bots left out). Caveats that don't change the conclusion: a handful of bot look-alike authors (login literally "bot") and one off-topic PR (#18423 "stress test") slip into the broad counts; rerunning with the stricter `^fix:` prefix only gives 10 opened / 12 closed — the same verdict either way. Also, the "closed" count is one higher than "opened" because it includes a bug opened before the window and closed inside it, which the question explicitly asks to include.

**Backlog:** 148 bug fixes/bugs opened in the window, 164 closed in the window (whenever opened). Binomial test of 164 closed against the 148 opened + 164 closed = 312 closed-or-opened units: share closed 52.56%, p = 0.3958 ≥ 0.05 → **balanced**, not growing or shrinking (strict prefix-only counts, 10 vs 12, agree).

**Median time to close, H1-opened bugs:** all 72 H1 bugs were closed by 2026-09-20 (72 closed by end of window, 0 closed after, 0 never closed), so none counted as "not closed yet". Median time to close = **20.33 hours** (from 72 values; p25 2.73 h, p75 105.88 h).

RESULTS
Issues labeled kind/bug opened 2026-04-01 to 2026-09-20: 148 (stand-in: bug/fix PRs; exact issue-label counts not available)
Issues labeled kind/bug closed in window (whenever opened): 164 (stand-in: bug/fix PRs; exact issue-label counts not available)
Backlog verdict: balanced
Median time to close for H1-opened bugs: 20.33 hours
```

### Readings

- opened (issues with the bug label opened in the window) [count] A: proxy 148 | B: proxy 148 | C: proxy 148 | decision: proxy 148 | your call: 
- closed (issues with the bug label closed in the window) [count] A: proxy 164 | B: proxy 164 | C: proxy 164 | decision: proxy 164 | your call: 
- verdict (whether the bug backlog is growing, shrinking or balanced) [growing / shrinking / balanced] A: proxy balanced | B: balanced | C: balanced | decision: balanced | your call: 
- median_days_to_close (median time to close for bugs opened in H1) [days] A: proxy 0.847083 | B: 0.847083 | C: proxy 0.847083 | decision: proxy 0.847083 | your call: 

## T004

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

### Readings

- unapproved (number of PRs merged in H2 without an approval from someone other than the author) [count] A: 171 | B: proxy 171 | C: proxy 171 | decision: proxy 171 | your call: 
- unapproved_bot_prs (how many of those unapproved PRs were opened by bots) [count] A: 171 | B: proxy 171 | C: proxy 171 | decision: proxy 171 | your call: 
