# Curated Tools or Open Code? Replication package

This is the replication package for the paper "Curated Tools or Open Code? How Tool Coverage Shapes LLM Agents' Answers About Software Repository Data" by Muhammad Moiz (School of Electrical Engineering and Computer Science, National University of Sciences and Technology, Islamabad).

The study asks whether AI agents answer questions about software project data better when they are guided by curated tools that apply the project's definitions, or when they are free to write their own code. Five cost-efficient models answered 63 questions about six GitHub repositories in six setups that differ only in their tools: four coverage levels, from one tool that returns the needed values (Level 0) down to tools that cannot reach the needed data (Level 3), a padded Level 2 as a side check, and an open Python sandbox. Every condition ran twice, giving 3,402 runs.

## What is here

| Folder | Contents |
|---|---|
| docs/ | The pre-registration (PRE_REGISTRATION.md) and its amendment (PRE_REGISTRATION_AMENDMENT_1.md), the study log for reviewers (study_log.md), the design of the coverage levels, the question templates, the specification for the independent key check, the spot checks against GitHub, and the repository screening |
| questions/ | All 63 questions as the agents saw them (questions.json) |
| answer_keys/ | The answer keys, the accepted alternatives, the bot audit and FREEZE.json, the fingerprints of everything frozen before the main run |
| independent_check/ | The second, independent implementation of the keys and its notes |
| prompts/ | The study system prompt (study_v3.md is the frozen one) and earlier versions |
| src/ | The study code: the tools for every coverage level, the sandbox runner, the study harness and the grading code |
| scripts/ | Every step, from data collection to the paper's figures (see below) |
| sandbox/ | The Dockerfiles for the sandbox and the database relay |
| study_config/ | The provider pin for each model |
| tool_data/ | The CI workflow list the tools and the sandbox read |
| floor_results/, levels_results/, screening_results/ | The no-tool floor, the scripted agents that proved every question answerable, and the model screening |
| study_runs/main/ | The run records of both tries, without the transcripts (see below) |
| grading_results/main/ | The final grades of all 3,402 runs, the tiebreak review, the blind hand-check sample and the stand-in check |
| analysis_results/ | The pre-registered results (main/stats.json) and the exploratory results |
| paper_outputs/ | Every figure, table and appendix file in the paper |
| tests/ | Unit tests |

LEFT_OUT.md lists every file of the development repository that is not here, with the reason.

## What is not here, and why

- **Full run transcripts.** The agents' tool results contain the email addresses of contributors to the six projects. GitHub's Acceptable Use Policy allows research use of public, non-personal information only, so the transcripts are not published. The run records here keep every number (outcome, turns, tool calls, tokens, cost, tool menu, provider) but not the transcripts or the final answer text. Transcripts with emails masked are available on request.
- **Contributor emails** in the grade files and the hand-check sheets are replaced with `<email>`. Grades and labels are unchanged.
- **The database.** The 7 tables of GitHub data also contain contributor emails. scripts/ingest_repos.py and scripts/ingest_commit_files.py download the same fixed window (2025-09-28 to 2026-09-24), and the table fingerprints in answer_keys/FREEZE.json show whether a rebuilt database matches the one used.
- **The pilot study.** The pilot's results, web demo and pilot-only scripts are not part of this study and are left out. The pilot pre-registration (docs/PRE_REGISTRATION.md) is kept unchanged as a frozen record. Its description of Data Interpreter as evidence that open code beats curated tools was later found to be wrong, and the paper does not make that claim.
- **Development history.** This package was assembled from the private development repository. That repository's history, including the commits and tags (keys-frozen-v4 and keys-frozen-v4.1) that froze the plan, keys and analysis before the main run, is available to reviewers on request.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --all-groups
```

## What you can rerun without a database or API keys

**Check the frozen files.** Every file listed in answer_keys/FREEZE.json is here byte for byte:

```
python3 -c "
import json, hashlib, pathlib
f = json.loads(pathlib.Path('answer_keys/FREEZE.json').read_text())
files = {**f['files'], **f['setup_files']}
ok = sum(hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest() == h for n, h in files.items())
print(ok, 'of', len(files), 'frozen files match')"
```

**The pre-registered analysis.**

```
uv run python scripts/analysis/study_stats.py
```

This rewrites analysis_results/main/stats.json. The estimates are reproduced exactly. The bootstrap intervals and p-values can differ slightly between runs, because the script visits the questions in an order that depends on Python's hash seed. Over 20 seeds, the estimates never changed, the intervals in the paper moved by at most 0.5 points, and no adjusted p-value crossed 0.05 (details in docs/study_log.md). The committed stats.json is the planned run and the source of every number in the paper. Set PYTHONHASHSEED for a fixed result on your machine.

**The paper's figures, tables and appendix files.**

```
uv run python scripts/paper/make_paper_outputs.py
```

This rebuilds paper_outputs/ from the committed results. The diagrams need Graphviz.

**The tests.**

```
uv run python -m pytest
```

Tests that need a database or Docker are skipped.

## What needs a database and API keys

Copy .env.example to .env and fill it in. The main study also reads STUDY_SANDBOX_DATABASE_URL, a read-only account created with scripts/create_study_sandbox_role.sql.

| Step | Scripts |
|---|---|
| Collect and clean the data | scripts/ingest_repos.py, scripts/ingest_commit_files.py, scripts/stage_raw_data.py, scripts/run_cleaning.py, scripts/verify_ingestion.py |
| Screen repositories | scripts/screen_repo_candidates.py |
| Compute, check and freeze the keys | scripts/answer_keys/compute_keys.py, compare_keys.py, freeze_keys.py |
| No-tool floor | scripts/floor/run_floor.py, grade_floor.py |
| Prove each question answerable | scripts/levels/check_level0.py, perfect_agents_level1.py, perfect_agents_level2.py |
| Screen models | scripts/screening/screen_models.py |
| Build and check the sandbox | scripts/study/build_sandbox.sh, check_sandbox.py |
| Run the study | scripts/study/run_study.py |
| Grade | scripts/grading/grade_study.py, then the hand checks in main_sample.py and stand_in_check.py |
| Exploratory analysis | scripts/exploratory/ (needs the full transcripts) |

The study log (docs/study_log.md) records every step in order, with every decision and unusual case.

## License

MIT. See LICENSE.

## Citation

To be added when the paper is published.
