# Study log: decisions and unusual cases

This file records how I made the study's decisions, why, and every unusual case that came up while running it. It's written for readers and reviewers who want to check that nothing was hidden or tuned after the fact. The plan itself is in PRE_REGISTRATION.md and PRE_REGISTRATION_AMENDMENT_1.md. This file covers what happened around that plan.

All times are Pakistan time (PKT, UTC+5). New entries go at the bottom of each part. I don't rewrite old entries. If something changes, I add a new entry that says what it replaces.

## How I make decisions

These rules held for the whole study.

- Answer keys come from code that runs straight on the database. No model is ever asked for an answer. A second version was written independently from a written spec, and the two match.
- A choice that looks at data that could bias it gets said out loud, here and in the amendment.
- I never look at scores while runs are going. The first time I see any score is grading, after both tries are done.
- Outages on my side are rerun. Mistakes by the model stay in the data. When a case doesn't fit either rule cleanly, I write down which way I went and why.
- When a record has to be changed by hand, I keep the original, write the reason inside the record, and make a backup first.
- Each finished try is committed to git as a compressed snapshot with a checksum before the next step, so its timestamp shows it was locked in before any grading.
- The whole setup is fingerprinted in answer_keys/FREEZE.json. A run refuses to start if anything differs.

## Changes before the main run

Each of these was made before any main run, on practice questions, the data itself or the no-tool floor.

**Bot rule (keys-frozen-v3).** Scripted test agents failed two eslint questions. The cause was the key's bot rule: commits with no login counted as human, so eslint's release script and README automation (124 commits) were counted as people. In one case the release script came out as eslint's top contributor. I checked every person field in all six repos, and eslint was the only one affected. I fixed the rule for all repos. 3 of 65 answers changed and no verdict changed.

**R4 check (keys-frozen-v4).** The check asked for the share of unapproved PRs, but the question asks how many of them bots opened, so a model answering exactly what was asked would fail. Now it checks the unapproved count (within 10%) and the bot count (exact). To choose "exact", I tried a tolerance on the no-tool floor, so this choice looked at floor data. Exact is also the sensible choice with no data at all, because the bot counts are only 0 to 4 and a tolerance of 1 would accept most guesses. No floor drop depends on it.

**Level 2 uses query tools.** Plain listing tools can't work at this data size. One question would need 11,653 rows read inside 25 turns. So level 2 got one generic query tool per table, modeled on the API Supabase puts on every table. The tools never apply a question's definition. Scripted agents proved every question is answerable within the budget at levels 0, 1 and 2.

**R7 stays in every level.** R7 asks about the longest stretch of failing CI. I first suggested leaving it out of levels 1 and 2, because plain filters can't express a sequence. A prototype showed a standard database operation solves it, so I added it to every query tool, as generic as the rest.

**Prompt v3.** In the smoke test, minimax hit the 25-turn limit in 4 of 6 runs because nothing told it when to stop. Version 3 added a neutral stop rule. A recheck cut budget hits from 6 to 3, and the 3 left were real work. I froze it there, since more rounds would tune the prompt to these five models on 12 practice questions.

**Failure and provider rules.** In practice runs gemini returned empty replies. That's when I wrote the rule: outages and provider errors are rerun, model output failures are not. OpenRouter also served one model from 6 providers at very different prices and precisions. So every model is pinned to one provider with no fallback, and every run records whether the pin held.

**Sandbox toolkit and no internet.** In practice, 10 of 30 sandbox runs crashed because the image lacked SQLAlchemy and psycopg2, which models commonly use. I gave the sandbox a standard pinned toolkit. Before this, containers also had full internet. Now their only way out is a relay to the database. 16 checks prove what it can and can't reach.

**Outage check (keys-frozen-v4.1).** I found that if the database went down mid-run, the agent saw an ordinary tool error and often answered "the data isn't available". That would charge my outage to the model. Now, when a tool fails, the harness checks right then whether the database, Docker and the relay can be reached. If they can't, the run is marked an infrastructure failure and rerun. A real test with the relay switched off mid-run confirmed it works.

**Tries.** Three tries were planned at first. Before the main run I fixed it at two, so a result can be checked against luck within the budget. I fixed the number before any run, because choosing it after seeing results would be optional stopping.

## The main run, try 1

Try 1 ran on 2026-11-14, from 10:41 to 22:30: 1575 main runs plus the 126-run side check. Every planned run is present exactly once. All runs used one prompt and one code commit, and every provider pin held. It cost $35.43 by the run records and $35.51 by the account. Runs ended like this: 1480 answered, 180 hit the turn limit, 41 model output failures.

**A pause to check for waste (11:10).** About half an hour in, level 2 runs looked expensive, and I stopped the run to check the engineering before spending more. I didn't look at any scores. I found nothing worth changing:
- every provider was already caching prompts;
- compact JSON would have saved about 5%;
- the cost came from agents asking for large pages of raw rows, which is their own behavior and part of what level 2 measures.

I resumed the run unchanged.

**Connection limit (17:38).** The outage check stopped the run. The Supabase session pooler allowed only 15 connections for the study user, and sandbox scripts can open several each. I raised the pool to 50 and cut the parallel runs from 8 to 5. Neither changes anything a model sees. The run that hit it (minimax, R7-junit-framework, sandbox) was marked an infrastructure failure and rerun.

**A run that saw the limit undetected.** After that I scanned the tool results of every finished run for the limit error. One run had it: deepseek, R5-tokio, sandbox. Its tool result showed the limit error, but by the time the check ran a connection had freed up, so the check passed and the run was saved as normal. Under the failure rule that's my outage, not the model's mistake. I marked it by hand as an infrastructure failure, wrote the reason into the record, and reran it. The original is kept in the file and backed up.

**Two provider timeouts.** Two ministral runs (R3-tokio at level 2, R10-sqlalchemy at level 3) failed because Mistral's servers kept timing out. Under the failure rule they were rerun.

So try 1 has 4 redone runs: 2 of my outages and 2 provider timeouts. The old records stay in the file, and the grader skips them.

**Errors that look like outages but aren't.** Some runs still show "connection refused" or name lookup errors. I checked every one. They come from the models' own code: gemini and ministral sometimes connected to made-up addresses like localhost or "host" instead of the one they were given. That's a model mistake, so those runs stay as they are.

**Snapshot.** Before try 2 finished and before any grading, I committed try 1 as study_runs/main/try1_runs.jsonl.gz. The live file grows past GitHub's 100 MB limit, so it isn't committed itself. The checksum of the uncompressed lines is in study_runs/main/README.md.

## The main run, try 2

Try 2 started on 2026-11-14 at 22:51. The larger pool allowed 8 parallel runs for levels 0 to 3 and the side check, and 5 for the sandbox. The commands are in study_runs/main/try2.sh.

**Internet outage (2026-11-15, 04:05).** My internet connection dropped. Every address failed to resolve, not just the database, and the computer didn't sleep. It happened near the end of the level runs, during ministral at level 3:
- 29 runs crashed before they were saved, so they never reached the data;
- 7 were saved as provider failures;
- the sandbox part then failed at its first database check, and the run stopped.

Both kinds of affected run are rerun under the failure rule. I scanned every finished try 2 run for outage errors in its tool results and found none.

**Restart (09:30).** Before restarting, I backed up the full run file and took a checksum of its 2,936 lines. The restart skipped every finished run and did only the 36 affected ones. After new runs were added, the old 2,936 lines still had the same checksum.

**R6-prometheus, ministral, level 3.** The rerun timed out at Mistral again. That's a provider failure, so it gets rerun again, the same as the two timeouts in try 1.

**R7-junit-framework, ministral, level 3: a context limit.** The rerun failed in a way not seen before. By turn 21 the conversation was 272,747 tokens, over ministral's maximum of 262,144, and Mistral rejected the request. It got that long because the model kept pulling large tool results into its history. That's the model's own doing, not an outage. The harness code files it as a provider failure, which would mean a rerun. But a context limit isn't on the pre-registered list of reasons to rerun (network errors, server errors, rate limits, timeouts). Rerunning would give the model another chance after its own mistake.

I chose to keep it as the model's result. I mark it by hand as a model output failure, with the reason written into the record. It isn't rerun, and it's graded as no answer. I don't change the frozen code. It's the only context limit case in about 3,000 runs. The hand mark is made after the side check finishes, so the file isn't edited while runs are still being added.

**The sandbox password shows up in some run records.** The sandbox code gets the database address, password included, as an environment variable, because it needs it to connect. Some agents printed that variable while finding their way around, so the password is saved in their tool results. The level setups never show it, because their tools run on my side. The study user can only read the 7 tables of public GitHub data, and the repo was private while the runs went on. I leave the records as they are, so their checksums still hold, and I change that password before the repo is made public, which makes every saved copy useless. A cleaner design would have the relay log in to the database itself, so the sandbox never holds a password. I list this as a limitation.

**The code commit in the records changes partway through try 2.** Each run records the git commit it ran on. The first 81 try 2 runs say 9c2abf3, the same as try 1, and the rest say 7e26a14. 7e26a14 is the commit that added the try 1 snapshot, its README, the two run scripts and one .gitignore line. It changed no code, prompt or tool, and the freeze check passed before each part of try 2. Every run in both tries has the same prompt hash.

**Model settings are the provider defaults.** Each request sends only the model, the messages, the tools and the provider pin. I don't set temperature or reasoning effort, so every model runs at its provider's default, the same in every setup. The saved token counts show what that means: deepseek, glm and minimax think before answering in every run, ministral is not a thinking model, and gemini-2.5-flash-lite has thinking off by default (2 of 693 runs so far show any). The comparison is between setups for the same model, so this is fair, but more effort might change the results, and I leave that for future work.

**Some runs make dozens or hundreds of tool calls in one turn.** The budget counts turns, and one turn may make several calls, so nothing stops a model from making very many. While watching try 2 I saw gemini make 389 calls in 9 turns on R4-eslint in the side check: one query per pull request, 50 at a time, instead of one combined query. The 50 matches the default page size of its first query. The first three turns asked the same 50 questions again with a different filter spelling each time. A quick count of runs with 20 or more calls in a single turn gives 12 so far: 9 from gemini, 2 from ministral and 1 from minimax. The largest is 801 calls in one turn (gemini, R8-junit-framework, level 3, try 1). I looked only at the calls, not at the answers. This is an exploratory finding and will be reported as one.

**The last run stopped while it seemed stuck (15:43).** The final side check run, glm on R1-junit-framework, made no progress for about 40 minutes: its last database query was around 15:04 and no reply came back from the model. The client gives up after 120 seconds of silence, but OpenRouter keeps slow requests open with small keep-alive bytes, so a call can wait far longer. I stopped it. It hadn't been saved, so nothing was written to the file. I can't be sure it was truly stuck rather than very slow: glm takes 25 to 58 minutes on this question in other runs. Either way the wait was on the provider, so it was redone from the start like any other provider problem.

**Finishing try 2 (15:44 to 16:15).** I backed up the run file, then marked the R7-junit-framework record as described above. Only that one line changed. A short pass (study_runs/main/try2_cleanup.sh) then redid R6-prometheus and the glm run. It skipped R7-junit-framework, as intended.

**Try 2 check.** Every planned run is present exactly once: 1575 main runs and 126 side check runs. 8 older records of redone runs are kept and skipped by the grader: 7 from the internet outage and the second R6-prometheus timeout. Runs ended like this: 1472 answered, 203 hit the turn limit, 26 model output failures (including R7-junit-framework). All runs have the same prompt hash, every provider pin held, and no finished run shows outage errors in its tool results. Try 2 cost $32.78 by the run records. The try 1 lines are unchanged and still match their snapshot. I snapshotted try 2 as study_runs/main/try2_runs.jsonl.gz before any grading, and its checksum is in study_runs/main/README.md.

## Grading

**The grading run (2026-11-15, 17:13).** After both tries were snapshotted, the two judges read all 3402 answers: 3150 main runs and 252 side check runs. The 12 older records of redone runs were skipped, as planned. No judge call failed. The two judges differed on at least one value or flag in 73 answers, and the third judge read those. Grading cost $4.18. This was the first time I saw any score.

**The tiebreaker review.** I reviewed all 73 tiebreaker answers by hand, as the amendment says. The sheet showed the question, the answer and the three readings, with no model, setup or try. For each value I either accepted the majority reading or wrote my own. I changed 35 values in 29 answers:
- 20 values were stand-ins the judges had read as real values, so I marked them as stand-ins;
- 5 values were not given for what was asked (for example, an answer gave H1 and H2 but the field asks for the whole window), so I marked them not available;
- 10 were a different value or verdict. Where the RESULTS block and the text above it disagreed, the RESULTS block won, and where it was mixed I wrote unclear.

This moved 18 answers to the stand-in label (17 from gives values, 1 from no values) and changed 3 pass results: 2 failures became passes and 1 pass became a failure. Overall passes went from 1692 to 1693. The blank sheet and my filled sheet are both kept in grading_results/main/.

**The blind sample (2026-11-16).** As the amendment says, I copied values from 20 more main run answers myself and compared them with the grader. The script draws the sample with a fixed seed from every graded answer with text, minus the 73 I had already seen. It takes one answer from each of the 12 templates, then 8 more, balancing models and then setups. That gave 4 answers per model and 3 or 4 per setup. The sheet showed only the question and the answer.

On my first pass the grader matched me on 60 of 61 items, 19 of 20 pass results and 20 of 20 labels. The one difference was my slip. On S17 the RESULTS block gave only the H1 and H2 shares, and I wrote not available for the window share. The text above it does state the window share (60.1%), and the rule is that text fills values the RESULTS block leaves out. I fixed it on a second look, and then the grader matched me on all 61 items. My first pass is kept as sample_sheet.first_pass.md.

**The stand-in check (2026-11-16).** The amendment says a stand-in counts as a correct workaround only if it is clearly labeled and reasonable, and that I judge this blind. All 35 stand-in answers went on one sheet in a shuffled order, with the question, the answer and the values taken as stand-ins, and no model, setup, try, key or grade. For each I decided whether it was clearly labeled and whether it was a sensible substitute that a careful analyst could defend. I judged the choice of stand-in, not whether its number was right.

All 35 were clearly labeled. 25 were reasonable, all of them at level 3 (25 of 32). The 2 sandbox stand-ins and the 1 at level 2 were not. The reasonable ones mostly used PR authors in place of commit authors, or grouped commits by the area named at the start of their message in place of the folder they changed. The 10 I judged not reasonable:
- answered with the parent folder instead of a folder inside it (1);
- gave numbers with no data behind them: simulated data, a guess from what repos usually look like, or module counts without seeing which files a commit changed (3);
- measured a different thing: PR authors or committers counted as reviewers, or all PRs counted as bug reports (4);
- gave a value that is true by construction, a 100% merge share from data that only shows merged PRs (1);
- assumed every bot PR lacked an approval without checking (1).

A stand-in never passes, so this check changes no pass result. It only splits the stand-in label for RQ3. The sheet and results are in grading_results/main/hand/.

**Snapshot of the grades.** Before any of the planned statistics, I committed the grades as grading_results/main/graded.jsonl.gz (the judges' output) and final.jsonl.gz (with my review applied), with their checksums in grading_results/main/README.md.

## Analysis

**Fixing the open details before the analysis (2026-11-16).** The amendment fixes the unit, the comparisons, the template bootstrap and Holm's method, but not every detail. Before running anything on the real grades, I fixed the rest in scripts/analysis/study_stats.py and committed it:
- 10,000 resamples of whole templates, with a fixed seed;
- the 95% interval is the middle 95% of the resampled differences;
- the p-value is two-sided: the resampled differences are centered on zero, and p is the share at least as far from zero as the real difference, so the smallest is 1 in 10,000;
- the RQ3 shares use the same template bootstrap.

I tested the script on grades with the setups shuffled within each question, so no real difference was left. It found no difference. Over 200 such shuffles it wrongly found one 5.5% of the time at the 0.05 level, close to the expected 5%. The test output is analysis_results/main/stats_shuffled_test.json.

## Exploratory analysis

Everything in this section was done after I saw the results, so it is exploratory and not part of the planned analysis.

**What I looked at (2026-11-16 and 17).** scripts/exploratory/explore.py counts how Level 2 runs failed, the habits of each model, and what agents did in the sandbox. scripts/exploratory/definitions/ checks every wrong Level 2 answer against the definitions its question uses. scripts/exploratory/small_checks.py covers smaller questions. All of them read only committed files, and their outputs are in analysis_results/exploratory/.

**How the definition checks work.** For each of the 154 Level 2 runs that gave wrong values, each definition the question uses gets one verdict: applied, missed, another reasonable reading, or unclear. The evidence is of two kinds. First, alternative keys: the same answer with one definition left out or read another way, such as keeping merge commits or dropping the last day of the window. An answer that equals an alternative key exactly shows which definition went wrong. Second, the filters the agent actually sent to the query tools. I checked a random sample of 20 runs by hand (seed 20261117, up to two per template), and all 20 verdicts held.

**What they found.** 125 of the 154 runs missed at least one definition, 15 follow a reading of the question that the key does not accept, and 14 I could not explain. Almost all misses came from ministral (74) and gemini (39).

**Problems in the frozen keys.** The checks showed a few questions that allow two reasonable readings where the key takes one. R10's test-file rule follows the written definition but also counts junit documentation folders like writing-tests/; 24 runs would pass under the narrower reading, at most 1.4 points at Level 2 and 1.9 in the sandbox. R3's key counts dismissed reviews (6 runs). One R6 run counted merge commits toward the floor of 20 commits, a reading the question may allow (1 run). I also found one grading slip: an R5 answer (prometheus, glm, Level 2, try 1) gave the right median, but both judges flagged it as a stand-in because the agent wrote placeholder times for open bugs, as the prompt tells it to. Scoring every failed answer that has a stand-in value as if the value were real shows this is the only such case. As the plan requires, I kept the frozen keys and grades unchanged. None of these moves a setup by more than 2 points, against differences of 13 to 48 points between setups, so no conclusion changes. They are reported as limitations.

**Smaller checks.** The one Level 3 run that passed (R8-tokio, ministral, try 1) asked for a tool Level 3 does not have, was refused, then counted pull requests per author and reported them as commit shares without saying so; the shares fell within the tolerance by chance. In the sandbox, no agent installed packages, ran shell commands, reached for the internet or tried to write to the database. Some printed the read-only database password (minimax in 52 runs, deepseek in 7); that password has since been changed and the old one no longer works.

**Figures and tables.** scripts/paper/make_paper_outputs.py builds every figure, table and appendix file in paper_outputs/ from committed results, so nothing in the paper is typed in by hand. The diagrams are Graphviz files in scripts/paper/diagrams/.

**The bootstrap is not exactly repeatable (found 2026-11-17).** While checking that the replication package reproduces the analysis, I found that scripts/analysis/study_stats.py gives slightly different intervals and p-values on each run, even with its fixed seed. The cause is one line that loops over a set of question IDs. Python orders sets differently in each process, so the bootstrap assigns the same random draws to templates in a different order. I reran the analysis under 20 different settings of PYTHONHASHSEED. The estimates never changed. The RQ1 and RQ2 intervals moved by at most 0.5 points and their p-values by at most 0.015; the RQ3 comparison of Level 3 and the sandbox by at most 0.023 in p; the side check by at most 0.076 in p; the intervals for single models by at most 1.5 points. No Holm-adjusted p-value crossed 0.05. I kept the committed stats.json, which is the planned run and the source of every number in the paper, and did not change the script. Setting PYTHONHASHSEED makes a rerun exact.
