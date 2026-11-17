# No-tool floor

Models: deepseek/deepseek-v4-flash, google/gemini-3.6-flash, openai/gpt-5-mini. Each answered each of the 65 questions 3 times with no tools and no data. Replies: 585, unparsed: 0, cost: $0.89.

Rule, written before the first run: a question is dropped if any model meets every must-have item in at least 2 of its 3 tries.

## Dropped

- R6-eslint ({'deepseek/deepseek-v4-flash': 1, 'openai/gpt-5-mini': 3})
- R6-vite ({'deepseek/deepseek-v4-flash': 2, 'google/gemini-3.6-flash': 3})

## Met every must-have at least once, but not dropped

- R1-eslint ({'deepseek/deepseek-v4-flash': 1})
- R9-prometheus ({'deepseek/deepseek-v4-flash': 1})
- R9-tokio ({'deepseek/deepseek-v4-flash': 1, 'google/gemini-3.6-flash': 1})

## How often guessing gets each must-have item

| Template | Item | Hit rate |
|---|---|---|
| R1 | h1 rate within 1.5 points | 8/54 (15%) |
| R1 | h2 rate within 1.5 points | 8/54 (15%) |
| R1 | verdict | 21/54 (39%) |
| R2 | main h1 median within 10% | 1/54 (2%) |
| R2 | main h2 median within 10% | 3/54 (6%) |
| R2 | main verdict | 15/54 (28%) |
| R3 | after h1 within 15% | 0/45 (0%) |
| R3 | after h2 within 15% | 1/45 (2%) |
| R3 | after verdict | 6/45 (13%) |
| R3 | wait h1 within 15% | 0/45 (0%) |
| R3 | wait h2 within 15% | 3/45 (7%) |
| R3 | wait verdict | 18/45 (40%) |
| R4 | bot PRs among them exact | 3/45 (7%) |
| R4 | unapproved count within 10% (at least 1) | 2/45 (4%) |
| R5 | closed within 2 | 3/54 (6%) |
| R5 | median days within 10% | 2/54 (4%) |
| R5 | opened within 2 | 1/54 (2%) |
| R5 | verdict | 18/54 (33%) |
| R6 | most fixes module | 18/36 (50%) |
| R6 | top share module | 10/36 (28%) |
| R7 | first failing commit | 0/54 (0%) |
| R7 | next passing commit | 0/54 (0%) |
| R7 | time red within 10% | 2/54 (4%) |
| R8 | h1 share within 3 points | 3/54 (6%) |
| R8 | h2 share within 3 points | 12/54 (22%) |
| R8 | verdict | 8/54 (15%) |
| R9 | top two share within 3 points | 3/45 (7%) |
| R10 | share within 3 points | 0/54 (0%) |
| R11 | merge h1 median within 15% | 1/36 (3%) |
| R11 | merge h2 median within 15% | 5/36 (14%) |
| R11 | merge verdict | 10/36 (28%) |
| R11 | merged share within 3 points | 9/36 (25%) |
| R11 | opened within 5% (at least 2) | 0/36 (0%) |
| R12 | fix median within 10% (at least 1 line) | 7/54 (13%) |
| R12 | h1 median within 10% (at least 1 line) | 13/54 (24%) |
| R12 | h2 median within 10% (at least 1 line) | 7/54 (13%) |
| R12 | other median within 10% (at least 1 line) | 9/54 (17%) |
| R12 | verdict | 29/54 (54%) |
