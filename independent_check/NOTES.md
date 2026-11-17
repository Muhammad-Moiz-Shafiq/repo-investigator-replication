# Independent check notes

These notes were written by the coding agent that did the independent check (OpenAI Codex), working only from docs/key_spec_for_independent_check.md. I kept them exactly as it wrote them, so "I" below means that agent. My review of its edge cases is in docs/question_templates_draft.md (Edge cases, Missing authors, and the R7 near tie rule).

The calculations use only the six base tables named in the specification and the read-only
`SANDBOX_DATABASE_URL`. I did not inspect or compare against the other answer-key implementation,
its outputs, the exploration scripts, or the prohibited documents.

## Interpretive choices

- A CI row with a null `started_at` cannot be ordered as an "earliest" run, so I exclude it from
  landing-run candidates. When two candidates have the same `started_at`, I choose the lower CI
  run ID to make the result deterministic.
- A counted CI conclusion other than a specified failure or `success` is neither failing nor
  passing. It interrupts an R7 streak and cannot serve as the passing boundary of one.
- For R7, I use the full ordered landing-run history, not just W. Only the first failure must start
  in H2; the following passing run may start after W as well as complete after W.
- If a PR author is null, a non-null human reviewer is treated as someone other than the author.
- If both commit login and email are null in R8, the missing identity is retained as one grouped
  person instead of silently dropping those commits.
- For R2, a dataset with fewer than ten values in either half gets the specified `"too few"`
  verdict. Thus a workflow with no qualifying rows has null medians and `"too few"`, rather than a
  separate undocumented verdict string.
- The bootstrap uses 4,000 resamples and an independent deterministic seed derived from the
  repo/metric name. It does not reuse the other implementation's seed.
- The specification gives only partial tie-breakers. After applying those stated tie-breakers, I
  use module name alphabetically in R6 and first failing SHA alphabetically in R7. For R6's highest
  fix share, an otherwise tied module is ordered by more fixes, then more total commits, then name.
- Test and documentation folders are matched as complete slash-delimited path components. The
  filename itself is evaluated only by the filename rules. Paths with fewer than the required
  number of parent folders are treated as root files for module analysis.
- An issue that is created and closed in W contributes once to `opened` and once to `closed` in
  R5, so the binomial trial count is `opened + closed`, as stated, rather than a count of distinct
  issues.
- Empty shares/rates are represented as JSON null. No requested rate or share in this dataset was
  empty; the rule is only a guard for reproducibility on changed data.

## Data observations

- SQLAlchemy has no qualifying successful pull-request main-CI runs in either half, so both R2 PR
  medians are null.
- Vite stands out in H2: 19.3% of human merged PRs have no qualifying first review, and 23.8% of
  all merged PRs have no qualifying approval. Its landing-run failure rate also rises from 13.1%
  to 34.3%.
- Some long R7 red periods contain only one failing landing commit: about 171.8 hours for Tokio and
  119.9 hours for SQLAlchemy. Time red therefore captures elapsed recovery time, not just streak
  length.
- All six R5 backlog tests are `balanced`, and none of the H1 bug-closure medians is infinite,
  although the not-closed share reaches 29.2% for Prometheus.
- The highest-share eligible ESLint module (`lib/linter`) has a fix-commit share of two thirds,
  while the module with the most fixes is `lib/rules`; the two R6 rankings can identify different
  areas as intended.

## Round 2

- Added R11 and R12 using the same read-only connection and base tables. No other implementation
  or answer keys were inspected. R1–R10 calculations were retained, and their regenerated output
  exactly matches the output saved before this round. The later R2 `"none"` wording was therefore
  not applied to the earlier calculation.
- R11 uses exact logins `renovate` and `dependabot`. Its merged and closed-unmerged shares use
  only PRs opened in W; merge-time medians use PRs merged in each half, even if opened before W.
  All cutoff comparisons exclude 2026-09-21 00:00 UTC. Following the literal `merged_at null`
  definition, a PR with a later non-null merge timestamp is not counted as closed unmerged.
- `autoclosed` is a case-insensitive substring anywhere in the title. Its denominator is the
  closed-unmerged subset, not all opened dependency PRs. Empty denominators yield null, and fewer
  than ten merge times in either half yield `"too few"`, using the existing helpers.
- R12 includes zero-line human commits and all changed file types. Size is the commit-level sum
  of additions and deletions; fix and other medians partition human commits in W using the existing
  first-line fix rule. Both new verdicts use the existing bootstrap with separate metric seeds.
- Data observations: Prometheus dependency-PR median merge time falls from 53.85 to 20.16 hours
  (`"down"`); the other three R11 repos have `"no clear change"`. JUnit merges 97.12% of dependency
  PRs opened in W. Tokio's human-commit median size rises from 21 to 34 lines (`"up"`); all other
  R12 verdicts are `"no clear change"`. ESLint fix commits have a median of 41 lines versus 13 for
  its other human commits, whereas fix commits are smaller by the median in the other five repos.
- Validation: synthetic checks covered window boundaries, the two PR cohorts, exact bot logins,
  case-insensitive titles, null denominators, human-commit exclusion, and fix/other medians.
  Ruff and output shape/range checks passed. SHA-256 of canonical R1–R10 JSON before and after:
  `eb899c0f60f43e2500c8ebd89d25a0e1f6d44260ddd19a78c2bcc7b065d2d30b`.

## Round 3

- Updated the shared bot rule to include `junit-builds` and logins ending in `bot` ignoring case.
  Human commits now also exclude null-login commits with either specified automation email.
  Email matching is exact, and the email exclusion applies only when the login is null.
- R8 ESLint top-two shares changed from 0.31086142322097376 to 0.3448275862068966 in H1 and
  from 0.24381625441696114 to 0.25892857142857145 in H2. JUnit's H1 share changed from
  0.8231884057971014 to 0.8255813953488372; its H2 share stayed the same.
- R12 ESLint median lines changed from 15 to 30 in H1, from 20 to 27 in H2, and from 13 to 22.5
  for other human commits over W. Its fix-commit median stayed the same.
- These are the only six changed output values relative to this script's saved Round 2 output.
  All verdicts, all other R8/R12 values, and all R1–R7 and R9–R11 outputs stayed the same.
  Earlier observations above describe the outputs at the time of those rounds.
- Reran against the read-only database. Bot suffix, null-login, automation-email, merge, fix,
  PR-author and reviewer checks passed, as did Ruff checks. Verified that only the three requested
  definition changes were made to the script. No other implementation or results were inspected.
