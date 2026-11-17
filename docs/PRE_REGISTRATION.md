# Pre-registration

Author: Muhammad Moiz
Date: 2026-09-23
Status: draft v1

This document sets out the research question, the reasoning behind it, and the planned method, before any part of the study is run. The point of writing it now is simple. I want a record of what I expected and why, before I see any results, so I cannot later convince myself the results were obvious all along.

This is a living document. If the plan changes as the work progresses, I will add a dated note below explaining what changed and why, rather than rewriting history quietly.

## The problem

Teams generate a lot of process data while building software: commits, pull requests, issues, CI runs. Understanding what that data means, why a build started failing, whether review is actually catching bugs, usually takes a person sitting down and digging through it by hand.

Recent work has tried to automate this with LLMs. SWE-agent showed that giving an LLM a small set of well-designed tools works better than giving it raw, unstructured access, at least for the task of fixing code. It is not yet known whether the same holds for a different kind of task: investigating and explaining a repository's history, rather than editing its code.

There is also real reason to doubt that curated tools always win. MetaGPT's Data Interpreter found the opposite pattern on data analysis tasks: giving the agent open code execution beat giving it curated tools. And a paper posted in September 2026, days before I found it, showed that whether curated tools help at all seems to depend on how capable the underlying model is. Weaker models do better with curated tools. Stronger models do fine, sometimes better, with open access.

So this is a real open question, not one I already know the answer to.

## What already exists, and why this is still worth doing

The closest existing work is RepoChat (MSR 2025), a tool that lets you ask natural language questions about a GitHub repository. I read the full paper, not just a summary. RepoChat builds a knowledge graph from repository metadata, then answers each question with exactly one generated database query and one generated response. It does not look again, does not check its own answer, and does not investigate further if the first query turns out to be wrong. Across their evaluation (four participants, ten question types, one repository, forty question instances), it reached 90 percent accuracy. Every failure came from the same source: the model misread what the question was actually asking, and had no way to catch that mistake since it only gets one attempt. Their own paper says their planned next step is adding agents that can take actions like opening or closing issues, not agents that investigate more deeply.

Agentic Repository Mining (EASE 2026) is the other close paper. It compares an agent with open bash access against a plain LLM with no tools at all, on classification tasks like "is this commit a bugfix." It found the two are roughly tied on most tasks. But it never compares two different kinds of tool access against each other, and its tasks are closed-label classification, not open-ended questions with a real investigation behind them.

So the specific thing I want to test, curated tools against open code execution, for open-ended diagnostic questions about repository history, has not been done. Every close paper differs on the task, the comparison being made, or the domain.

## Research questions

These are written as a draft.

RQ1. When an LLM agent investigates open-ended questions about a repository's history, does giving it a small set of curated, purpose-built tools produce more reliable and better-grounded answers than giving it an open code execution environment, and does the answer to that depend on how capable the underlying model is?

RQ2. What do the two approaches actually get wrong, and are the mistakes different in kind? I plan to build the failure categories from two existing taxonomies, ToolFailBench and the disagreement categories used in Agentic Repository Mining, rather than inventing my own from scratch. I will also watch for the kind of mistake RepoChat made, misreading the question itself, since that is a different failure than a tool-use failure and neither existing taxonomy targets it directly.

RQ3. Does any gap between the two approaches depend on how complex the question is? CodeAct found open execution helps more on tasks that need combining several steps, and roughly ties on simple ones. I want to see if that pattern shows up here too.

## What I expect, stated honestly before I have data

I lean toward expecting curated tools to help more with a weaker or cheaper model, and that gap to shrink or disappear with a stronger model. I lean toward expecting compound questions, ones that need cross-referencing more than one kind of data, to show a bigger gap than simple trend questions. I hold both of these loosely. The MetaGPT result argues the opposite could easily be true, and I would rather be wrong here on record than quietly adjust the story after seeing results.

## Method, as currently planned

Two versions of the same agent will be built. Both use the same reasoning loop, reason, act, observe, reason again. What differs is what "act" means.

The first version gets five tools: one for checking CI history over a date range, one for pulling the actual code diff of a specific commit, one for querying issues and pull requests, one for comparing a metric across two time periods, and one for looking up which contributors' commits are most associated with later bug fixes. That last one was added after realizing the first four had no clean way to answer the question about contributors and bug fixes, since it needs a different kind of lookup than the other four cover. I chose to add a fifth narrow tool rather than make an existing one more general, since a more general tool starts to blur the line between the curated-tools condition and the open-access condition, which is the exact thing this study is trying to keep distinct.

The second version gets one capability instead: a sandboxed environment where it can write and run its own Python or SQL against the same data, with read-only database access and a timeout so it cannot run away with itself.

Both versions will run against the same set of test questions, over the same two or three repositories, and every step will be logged through Langfuse so the reasoning trace is fully visible afterward, not just the final answer.

I plan to test three models, not just one: two weaker/cheaper ones (from different providers, deepseek-v4-flash and gemini-2.5-flash-lite) and one stronger one (gemini-2.5-pro). Testing only a single cheap model would make RQ1's question about model capability impossible to actually answer, and testing only one weak model risks any finding being specific to that one model rather than a real pattern. One honest thing to flag now, before I have results: the strong model and one of the two weak models are both from Google, just different tiers, while the other weak model is from a different provider entirely. This means I get two different weak-versus-strong comparisons, one across providers and one within the same provider's family, which is useful, but I want to be upfront that I am not pretending all three sit on some perfectly neutral, unbiased footing relative to each other.

The test questions are deliberately picked so that none of them can be answered with a single lookup. If a question resolves in one query with no follow-up reasoning needed, it does not belong in the set, since the entire point is to see how each version behaves when it actually has to investigate.

## What counts as done, for this stage

A working pilot across two or three repositories, both agent versions actually built and run against the same questions, a written comparison of what each version got right, wrong, and how, and an honest account of the limitations, including the fact that a handful of questions across a few repositories is not enough to claim statistical significance. That last point is a real limitation, not something to hide. A study this size is a first, careful look, not a final answer.

## What I am aiming for beyond the pilot

The realistic goal is a public write-up, an article, and an arXiv preprint once results exist and an endorser is found. A full peer-reviewed paper would need real faculty involvement, a larger scale, and more rigor than a solo pilot can provide on its own, and I am treating that as a possible later step rather than something this stage depends on.

## Amendment log

2026-09-23. Initial version written, after two rounds of literature search and a direct reading of the RepoChat paper and source code.

2026-09-24. Ingestion complete for all three repos (tokio-rs/tokio, eslint/eslint, sqlalchemy/sqlalchemy), 12-month window each. Data engineering details, bugs found and fixed, and a real architecture change (Docker's role narrowed to the Variant B sandbox only, since GitHub's REST API turned out to already provide full commit diffs without cloning) are logged in `docs/data_engineering_log.md` in the parent research workspace. No change to the RQs themselves from this work, but the bug-fix detection approach (RQ2's failure taxonomy depends on being able to identify bug-fix commits) is now concretely scoped: a labeled heuristic, not full SZZ, chosen after checking that label vocabularies differ across the three repos (tokio: "C-bug", eslint/sqlalchemy: "bug").

2026-09-24 (later same day). Method section revised: the curated-tools version of the agent now has five tools, not four (added a tool for contributor/bug-fix association lookups, since none of the original four could answer that part of the test question set). Noted here rather than silently changed, per this document's own stated purpose.

2026-09-24 (later still). The two model-capability tiers mentioned in the method section are now specifically deepseek/deepseek-v4-flash (weaker/cheaper) and google/gemini-2.5-pro (stronger), chosen after real tool-calling reliability testing across many candidates, including free tiers, which proved broadly unreliable across every provider tried (details in docs/agent_methodology_log.md). Deliberately picked from two different providers, not two sizes of the same model, after realizing a same-family pairing would confound any capability finding with that one company's specific quirks.

2026-09-24 (later still again). Expanded from two models to three: added gemini-2.5-flash-lite as a second weak-tier model, so any weak-tier finding can be checked against more than one cheap model rather than trusting deepseek-v4-flash's behavior as representative on its own. Full reasoning and reliability numbers in docs/agent_methodology_log.md.

2026-11-14. The pilot grew into a larger study with a new main question about tool coverage. Its full design, frozen before the main run, is in docs/PRE_REGISTRATION_AMENDMENT_1.md.
