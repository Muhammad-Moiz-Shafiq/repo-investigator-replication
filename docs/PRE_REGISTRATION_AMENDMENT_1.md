# Pre-registration amendment 1

Author: Muhammad Moiz
Date: 2026-11-13
Status: frozen before the main run

The first pre-registration (PRE_REGISTRATION.md, 2026-09-23) described a small pilot. Since then the study grew into a larger design. This amendment records that design before the main run. No main run has happened yet. Every change below was made on practice questions, the data itself or the no-tool floor, never on main run results. Where a choice looked at data that could bias it, I say so.

The full reasoning for each choice is in the repo history and the design docs. This file is the short version that the main run is held to.

## Research questions

The questions changed after the pilot. The main question is now about tool coverage.

RQ1. With cost-efficient models, do curated tools give more accurate answers than open code execution on diagnostic questions about repository process data?

RQ2 (main). How does accuracy change as tool coverage drops?

RQ3. When the tools don't cover a question, what does the agent do? It can say the data is missing, use a clearly labeled stand-in, give a wrong answer without saying anything is missing, or refuse. I compare this with how open code execution goes wrong.

## What I expect

I expect accuracy to fall as tool coverage drops. The biggest fall should come between level 1 and level 2, because that is where the agent has to apply the definitions itself (who is a bot, what counts as a fix, which CI run counts), and in practice runs most mistakes were definition mistakes. At level 3 I expect many answers to be wrong without saying anything is missing, rather than saying the data isn't there. I expect the sandbox to land close to level 2, since it sees the same raw data and has to apply the same definitions, and below levels 0 and 1. I expect the weakest model to gain the most from curated tools.

These expectations are partly shaped by the practice runs, which used different questions. I hold them loosely and will report the results whichever way they go.

## Data

Six GitHub repos: tokio, eslint, sqlalchemy, vite, junit-framework and prometheus. Each was picked by written thresholds (repo-investigator/docs/repo_screening/). Every repo covers the same fixed window, 2025-09-28 to 2026-09-24. Questions stay inside 2025-10-01 to 2026-09-20. The data is fingerprinted in answer_keys/FREEZE.json, so any change to it is caught.

sqlalchemy reviews and merges happen on Gerrit, not GitHub. So review and merge questions skip it. This was decided before any run.

## Questions and answer keys

Twelve question templates (R1 to R12) asked on the six repos give 65 questions. The no-tool floor dropped 2 (R6-eslint and R6-vite) by a rule written before the floor ran. The main run uses the other 63. The texts are in questions/questions.json.

Every key is computed by code straight from the database, never by asking a model for an answer. A second version was written in pandas from a written spec, without seeing the SQL. Both match on every field. I made 23 spot checks by hand on github.com and the GitHub API, and all matched. Each key is a checklist of must-have items, and code scores them.

Two key changes were made after the first freeze. Both came before any main run.

1. The bot rule (keys-frozen-v3). Scripted test agents showed that eslint's release and README automation was counted as human. I fixed the rule for all repos. 3 of 65 answers changed and no verdict changed.
2. The R4 check (this freeze). The check asked for the share of unapproved PRs, but the question asks how many of them bots opened. Now the check asks for the unapproved count (within 10%, at least 1) and the bot count (exact). To choose "exact", I tried a tolerance on the no-tool floor. That means this choice looked at floor data. Exact is also the sensible choice without any data, because the bot counts are only 0 to 4, and no floor drop depends on it.

## The setups

Every question is asked of every model in six setups. Only the tools change. The question, system prompt, model settings and step budget are the same. A test checks this (tests/study/test_same_everything_else.py).

- Level 0. One direct tool returns every value the question needs.
- Level 1. Tools that each return one correctly defined part. The agent combines them.
- Level 2. One generic query tool per table, plus four calculators (summary, Fisher test, binomial test, median comparison). The agent applies every definition itself.
- Level 3. Level 2 minus every tool that reads the data the question needs.
- Level 2 padded. Level 2 with 2 or 3 real but unrelated tools added, so it has as many tools as level 0. This is a side check on menu size, run with two models: gemini-2.5-flash-lite (the weakest, so the most likely to be thrown by a longer menu) and glm-5.3-flash. It never changes the main analysis and is always reported.
- Sandbox. Open Python on the 7 data tables, read only. It has a standard toolkit: Python 3.12, pandas 2.3.3, numpy, scipy, SQLAlchemy, psycopg and psycopg2, all at pinned versions. It has no internet. Its only way out is a relay to the database. 16 checks prove what it can and can't reach (scripts/study/check_sandbox.py).

Before any agent ran, scripted agents proved that a correct answer is reachable at levels 0, 1 and 2 within the budget, on all 63 questions.

## Models and run rules

Five study models, each pinned to one provider with no fallback:

- deepseek/deepseek-v4-flash on Parasail (fp8)
- google/gemini-2.5-flash-lite on Google AI Studio
- z-ai/glm-5.3-flash on Z.ai (fp8)
- minimax/minimax-m3.1-flash on MiniMax
- mistralai/ministral-14b-2512 on Mistral

They were chosen by a screening rule on the 5 pilot questions, never on study questions. Every run records whether the pinned provider served it.

- Budget. 25 model turns per run in every setup. One turn can make several tool calls. The count of tool calls is recorded.
- Prompt. study_v3, frozen on 2026-10-24. Problems found during the main run are reported, not fixed.
- Failures. Infrastructure failures (network, server errors, rate limits, timeouts) are rerun. Model output failures (an empty reply, or a tool call the provider can't format, after 3 tries) end the run with no answer and are never rerun. Each model's rate is reported.
- Outages on my side. When a tool fails, the harness checks at that moment whether the database, Docker and the relay can be reached. If not, the run is an infrastructure failure and is rerun, because the model saw an outage, not its own mistake. Added on 2026-11-14, before the main run, so the code follows the failure rule above (tagged keys-frozen-v4.1).
- Tries. 2 tries per condition, so I can see whether a result holds or was luck. Try 1 for every condition finishes before try 2 starts. The spending cap is $100 for everything: $88 for the runs and the side check, the rest for grading. If the runs reach $88 during try 2, the analysis uses try 1 alone and says so. The stop depends on cost only, and I don't look at scores before try 2 is done. A third try is not planned.

## Grading

Two judges read every answer and copy out the values it gives: claude-haiku-5.5 and gpt-5-mini, at fixed settings. They don't score anything. Code compares the copied values with the keys. Neither judge is from a lab with a study model.

When the two judges read any value or flag differently, a third judge reads the answer, and each value takes the reading at least two of the three share. The third judge is deepseek-v4.1-flash, pinned to Parasail (fp8). It is from the same lab as one study model. I accept that because it only sees the rare answers where the two main judges differ, and I review every one of its calls by hand, without seeing the model or setup. My call is final. Before the main run, it agreed with the two judges on 364 of 364 practice items where they agreed.

I checked the judges by hand on 20 practice answers covering all 12 templates, all 5 models and every setup. I copied the values from 9 answers myself, without seeing the judges' output. For the other 11, I marked the judges' values right or wrong. Seeing a value first can pull a person toward agreeing, so I report the two parts apart. Both judges matched me on all 57 items: 24 of 24 copied and 33 of 33 marked. 20 answers is a small sample, so this supports using the judges but doesn't measure their exact error rate.

## RQ3 labels and grounding

The value checks can't show how an answer behaves when data is missing. The judges already flag each value the answer says isn't available, and each value it gives only as a stand-in. From those agreed flags, code gives every answer one label:

- no answer: the run ended without one,
- gives values: at least one value is given as the real thing; if the answer fails, it is wrong without saying anything is missing,
- stand-in: no real values, but at least one stand-in the answer labels as such,
- no values: the answer says the data is missing or declines.

A stand-in counts as a correct workaround only if it is clearly labeled and reasonable. Reasonableness is judged by me, blind, on the stand-in answers.

Grounding is a cheap check that numbers came from the data. For each value the judges copied, code checks whether it appears in the run's tool results, allowing rounding and a change between percent and fraction or between time units. It also records whether the run got any data at all. A value the agent worked out itself from tool output doesn't appear there, so grounding is a lower bound, and I report it as such.

I tested all of this on 139 practice answers before the main run. The new grader matched the judge trial on 340 of 341 items. The one difference is a stand-in verdict that the trial had counted as right, and my hand check had marked as a stand-in. Labels from the judges matched labels from my hand marks on 19 of 20 answers. The one miss was an answer that "assumed" its values, which the tiebreaker sent to my review. After the main run I label a blind sample of 20 more answers myself and report how often the grader matches me.

## Analysis plan

The main outcome is pass or fail: an answer passes when every must-have item is right. The share of items right is a secondary outcome.

The unit is one question. For each question and setup, its score is the share of passing runs over the 5 models and 2 tries. Only questions run in both setups being compared are used.

RQ2. I compare each step down: level 0 with level 1, level 1 with level 2, and level 2 with level 3. For each, I report the mean difference in score over the same questions, with a 95% interval and a p-value from a bootstrap that resamples whole templates, since questions from one template are alike. The p-values are adjusted with Holm's method.

RQ1. I compare the sandbox with each level the same way, with its own Holm adjustment. To see whether the answer depends on the model, I also report it for each model alone. Those per-model results are descriptive.

RQ3. For level 3 and the sandbox, I report the share of each label with 95% intervals, and compare how often each setup gives a wrong answer that doesn't say anything is missing. I report the grounding share per setup.

Also reported: the agreement between try 1 and try 2, the side check, cost, tool calls, turn budget hits and failure rates per model. Anything else I look at after the run is labeled as exploratory.

## What is frozen

Everything above is fixed in answer_keys/FREEZE.json and tagged keys-frozen-v4. It covers the keys and their scripts, the questions, the floor result, the workflow list, a fingerprint of every data table, the prompt, the provider pins, the harness, every tool, the sandbox files, the judges, the grading and review code, the locked package versions, and the IDs of the two sandbox images. A study run refuses to start if any of it differs.
