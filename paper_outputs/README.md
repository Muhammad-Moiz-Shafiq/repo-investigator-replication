# Paper outputs

Every figure and table for the paper. All of it is built by one script from committed results, so nothing here is edited by hand:

```
uv run --group analysis python scripts/paper/make_paper_outputs.py
```

It reads `grading_results/main/final.jsonl.gz`, `analysis_results/main/stats.json`, `analysis_results/exploratory/` and the hand check files in `grading_results/main/hand/`. It needs no database and no API key.

## Look

Times at 8 pt, sized for an IEEE column (3.5 in) or the full page (7.16 in). Fonts are embedded as TrueType. The five models use the Okabe-Ito colors, always the same color and marker shape. I checked them with a colorblind simulator. Everything else is black or gray. The look lives in `scripts/paper/style.py`.

The diagrams are Graphviz files in `scripts/paper/diagrams/`. On macOS they're drawn with the quartz renderer, because the default cairo renderer writes a Type 3 font, which IEEE's PDF check rejects.

## Figures (PDF for the paper, PNG for viewing)

- `pass_by_setup`: the share of runs that pass in each setup, with 95% intervals.
- `pass_by_model`: the same for each model.
- `rq3_answer_types`: how Level 3 and sandbox answers behave.
- `l2_failures`: why Level 2 runs failed, per model. Exploratory.
- `pipeline`: how the study runs, from data to analysis.
- `setups`: what each setup gives the agent.

## Tables (LaTeX for IEEEtran with booktabs, Markdown for reading)

- `models`, `setups`: the design.
- `scores`, `tests`, `rq3`: the pre-registered results.
- `hand_checks`: how well the grading matched my own reading.
- `sandbox`, `definition_kinds`, `definition_outcomes`: exploratory, and labeled as exploratory in their captions.
