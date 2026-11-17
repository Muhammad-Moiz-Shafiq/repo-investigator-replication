"""Build every figure and table for the paper from committed results.

Reads only files in the repo, so it needs no database and no API key:
- grading_results/main/final.jsonl.gz (one grade per run)
- analysis_results/main/stats.json (the pre-registered analysis)
- analysis_results/exploratory/ (exploratory, labeled as such in captions)
- grading_results/main/hand/ (my hand checks)

Writes PDF and PNG figures to paper_outputs/figures and LaTeX and Markdown
tables to paper_outputs/tables. The two diagrams are Graphviz files in
scripts/paper/diagrams, drawn with dot if it is installed.

Usage:
  uv run --group analysis python scripts/paper/make_paper_outputs.py
"""

import gzip
import json
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import style as s

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "paper_outputs"
FIG, TAB = OUT / "figures", OUT / "tables"
STATS = json.loads((ROOT / "analysis_results" / "main" / "stats.json").read_text())
EXPLORE = json.loads((ROOT / "analysis_results" / "exploratory" / "explore.json").read_text())
DEFS = json.loads((ROOT / "analysis_results" / "exploratory" / "definitions_summary.json").read_text())
RERUN = ("provider_failure", "infrastructure_failure")  # older records of runs that were redone
HAND = ROOT / "grading_results" / "main" / "hand"
PROVIDERS = json.loads((ROOT / "study_config" / "providers.json").read_text())

with gzip.open(ROOT / "grading_results" / "main" / "final.jsonl.gz", "rt") as f:
    GRADES = [json.loads(line) for line in f]


def short(model):
    return model.split("/")[-1]


def pct(x, digits=1):
    return f"{100 * x:.{digits}f}"


def ci(c, digits=1):
    return f"[{pct(c[0], digits)}, {pct(c[1], digits)}]"


def p_text(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def per_model_pass():
    """Share of runs passing, per model and setup. Every model has 126 runs
    (63 questions, 2 tries) in each setup it ran."""
    n, passed = Counter(), Counter()
    for g in GRADES:
        n[g["model"], g["setup"]] += 1
        passed[g["model"], g["setup"]] += g["passed"]
    return {k: passed[k] / n[k] for k in n}


# Tables


def write_table(name, header, rows, caption, align=None, wide=False):
    """The same table as LaTeX (booktabs, for IEEEtran) and as Markdown. A wide table spans
    both columns."""
    env = "table*" if wide else "table"
    align = align or "l" + "r" * (len(header) - 1)
    esc = lambda x: str(x).replace("%", r"\%").replace("&", r"\&").replace("_", r"\_")  # noqa: E731
    tex = [
        "% Built by scripts/paper/make_paper_outputs.py. Do not edit by hand.",
        rf"\begin{{{env}}}[t]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        rf"\caption{{{esc(caption)}}}",
        rf"\label{{tab:{name}}}",
        rf"\begin{{tabular}}{{{align}}}",
        r"\toprule",
        " & ".join(esc(h) for h in header) + r" \\",
        r"\midrule",
        *(" & ".join(esc(c) for c in r) + r" \\" for r in rows),
        r"\bottomrule",
        r"\end{tabular}",
        rf"\end{{{env}}}",
    ]
    md = [
        f"{caption}",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" if a == "l" else "---:" for a in align) + "|",
        *("| " + " | ".join(str(c) for c in r) + " |" for r in rows),
    ]
    TAB.mkdir(parents=True, exist_ok=True)
    (TAB / f"{name}.tex").write_text("\n".join(tex) + "\n")
    (TAB / f"{name}.md").write_text("\n".join(md) + "\n")


def table_models():
    lab = {"deepseek": "DeepSeek", "google": "Google", "z-ai": "Z.ai", "minimax": "MiniMax",
           "mistralai": "Mistral"}
    rows = [[name, lab[model.split("/")[0]], PROVIDERS[model]] for model, name, _, _ in s.MODELS]
    write_table(
        "models",
        ["Model", "Lab", "Provider pin"],
        rows,
        "The five models, each run through OpenRouter on one pinned provider. "
        "Exact model IDs are in the appendix.",
        "lll",
    )


def table_setups():
    rows = [
        ["Level 0", "One direct tool returns every value the question needs."],
        ["Level 1", "Tools that each return one correctly defined part. The agent combines them."],
        ["Level 2", "A query tool per table and four calculators. The agent applies every definition."],
        ["Level 3", "Level 2 without the tools that read the data the question needs."],
        ["Level 2 padded", "Level 2 plus 2 or 3 unrelated tools, as many tools as Level 0. Two models only."],
        ["Sandbox", "Python over the 7 data tables, read only, no internet."],
    ]
    write_table(
        "setups", ["Setup", "What the agent gets"], rows, "The six setups. Only the tools change.",
        "lp{2.4in}",
    )


def table_scores():
    rows = []
    for setup in s.SETUPS:
        sc = STATS["scores"][setup]
        rows.append([s.SETUP_NAME[setup], pct(sc["pass"]["estimate"]), ci(sc["pass"]["ci95"]),
                     pct(sc["items"]["estimate"]), ci(sc["items"]["ci95"])])
    write_table(
        "scores",
        ["Setup", "Pass %", "95% CI", "Items %", "95% CI"],
        rows,
        "Score per setup, the mean over 63 questions of the share of 10 runs that pass "
        "(5 models, 2 tries). Intervals from a bootstrap over templates.",
    )


def table_tests():
    rows = []
    for rq, key in (("RQ2", "rq2"), ("RQ1", "rq1")):
        for t in STATS[key]:
            a, b = t["setups"].split(" minus ")
            rows.append([rq, f"{s.SETUP_NAME[a]} vs {s.SETUP_NAME[b]}", pct(t["estimate"]), ci(t["ci95"]),
                         p_text(t["p_holm"])])
    write_table(
        "tests",
        ["RQ", "Comparison", "Points", "95% CI", "Holm p"],
        rows,
        "Pre-registered comparisons of pass scores over the same 63 questions. "
        "Points is the mean difference in pass rate. Holm adjustment within each RQ.",
        "llrrr",
    )


def table_rq3():
    names = [
        ("wrong_without_saying", "Wrong, says nothing is missing"),
        ("stand_in", "Uses a stand-in"),
        ("no_values", "Says the data is missing"),
        ("no_answer", "No answer"),
    ]
    rows = []
    for key, name in names:
        a, b = STATS["rq3"]["L3"][key], STATS["rq3"]["sandbox"][key]
        rows.append([name, pct(a["estimate"]), ci(a["ci95"]), pct(b["estimate"]), ci(b["ci95"])])
    d = STATS["rq3_wrong_without_saying_L3_minus_sandbox"]
    write_table(
        "rq3",
        ["Answer type", "Level 3 %", "95% CI", "Sandbox %", "95% CI"],
        rows,
        "How answers behave when data is missing (Level 3) or must be found (Sandbox). "
        f"Wrong without saying, Level 3 minus Sandbox: {pct(d['estimate'])} points, "
        f"95% CI {ci(d['ci95'])}, p = {d['p']:.2f}.",
    )


def table_sandbox():
    pat = EXPLORE["sandbox"]["patterns"]
    lines = [
        ("Printed the database password", EXPLORE["sandbox"]["password_in_tool_output"]),
        ("Made up a connection string", pat["made-up connection string"]),
        ("Called a tool API that does not exist", pat["calls a nonexistent default_api"]),
        ("Looked at the file system", pat["looks at the file system"]),
        ("Installed packages or used a shell", {**pat["pip install"], **pat["shell or subprocess"]}),
    ]
    rows = [[name, *(by.get(short(m), 0) for m, *_ in s.MODELS)] for name, by in lines]
    write_table(
        "sandbox",
        ["Behavior (runs of 126)", *(n for _, n, _, _ in s.MODELS)],
        rows,
        "Exploratory. Sandbox habits per model. No password reached a final answer.",
    )


def table_hand_checks():
    sample = json.loads((HAND / "sample_comparison.json").read_text())["totals"]
    stand = json.loads((HAND / "stand_in_results.json").read_text())
    rows = [
        # Before the main run, from docs/PRE_REGISTRATION_AMENDMENT_1.md.
        ["Before", "Judges against my reading, 20 practice answers", "57 / 57 items"],
        ["Before", "Grader against the judge trial, 139 practice answers", "340 / 341 items"],
        ["Before", "Labels against my hand marks", "19 / 20 answers"],
        ["After", "Grader against me, blind sample",
         f"{sample['grader scores the item the same as me']} / {sample['items']} items, "
         f"{sample['grader gives the same label as me']} / {sample['answers']} labels"],
        ["After", "Stand-ins I judged clearly labeled and reasonable",
         f"{sum(r['correct_workaround'] for r in stand)} / {len(stand)} answers"],
        # From docs/exploratory/level2_failures.md (local): 2 sampled runs per template, seed 20261117.
        ["Exploratory", "Definition-check verdicts I confirmed by hand", "20 / 20 runs"],
    ]
    write_table("hand_checks", ["When", "Check", "Agreement"], rows, "Hand checks of the grading.", "llr")


def table_definitions():
    kinds = DEFS["runs_missing_each_kind"]
    rows = [[k[0].upper() + k[1:], n] for k, n in kinds.items()]
    write_table(
        "definition_kinds",
        ["Kind of definition missed", "Runs"],
        rows,
        f"Exploratory. Definitions missed in the {DEFS['runs']} wrong Level 2 answers. A run can miss "
        "more than one kind. 57 of the 60 date cases are one habit: an end filter that drops the last day.",
    )
    outcomes = list(DEFS["outcome"])
    rows = [[n, *(DEFS["by_model"].get(short(m), {}).get(o, 0) for o in outcomes)] for m, n, _, _ in s.MODELS]
    rows.append(["All", *(DEFS["outcome"][o] for o in outcomes)])
    write_table(
        "definition_outcomes",
        ["Model", "Missed", "Other reading", "Unexplained"],
        rows,
        "Exploratory. Why each wrong Level 2 answer was wrong: it missed a definition, it followed "
        "a reasonable reading the key does not accept, or neither could be shown.",
    )


def main_runs():
    """The final record of every main run (not the side check), without older records of redone runs."""
    keep = {g["run_id"] for g in GRADES if g["setup"] in s.SETUPS}
    runs = {}
    for n in (1, 2):
        with gzip.open(ROOT / "study_runs" / "main" / f"try{n}_runs.jsonl.gz", "rt") as f:
            for line in f:
                r = json.loads(line)
                if r["run_id"] in keep and r["stop_reason"] not in RERUN:
                    runs[r["run_id"]] = r
    return runs


def table_per_model():
    """Over the five main setups only, so every model has the same 630 runs. stats.json also
    counts the side check runs for the two side check models."""
    runs = main_runs()
    rows = []
    for model, name, _, _ in s.MODELS:
        mine = [r for r in runs.values() if r["model"] == model]
        passed = sum(g["passed"] for g in GRADES if g["model"] == model and g["setup"] in s.SETUPS)
        rows.append([
            name,
            pct(passed / len(mine)),
            f"{statistics.median(r['tool_calls'] for r in mine):g}",
            sum(r["stop_reason"] == "budget" for r in mine),
            sum(r["stop_reason"] == "model_output_failure" for r in mine),
        ])
    write_table(
        "per_model",
        ["Model", "Pass %", "Calls", "Turn limits", "Failures"],
        rows,
        "Per model, over its 630 runs in the five main setups (63 questions, 2 tries each). "
        "Calls is the median number of tool calls per run, turn limits the runs that used all 25 "
        "turns, and failures the runs with no usable reply. The side check is left out.",
    )


def table_cost_by_setup():
    runs = main_runs()
    rows = []
    for setup in s.SETUPS:
        mine = [r for r in runs.values() if r["setup"] == setup]
        passed = sum(g["passed"] for g in GRADES if g["setup"] == setup)
        cost = sum(r["cost_usd"] or 0 for r in mine)
        rows.append([
            s.SETUP_NAME[setup],
            f"{cost:.2f}",
            f"{1000 * cost / len(mine):.1f}",
            f"{1000 * cost / passed:.0f}" if passed > 1 else "n/a",
            f"{statistics.median(r['tool_calls'] for r in mine):g}",
            sum(r["stop_reason"] == "budget" for r in mine),
        ])
    write_table(
        "cost_by_setup",
        ["Setup", "Cost (USD)", "USD per 1000 runs", "USD per 1000 passes", "Median tool calls",
         "Turn limit hits"],
        rows,
        "Cost and effort per setup, 630 runs each. Level 3 has one pass, so no cost per pass.",
    )


def table_grounding():
    rows = []
    for setup in (*s.SETUPS, "L2_padded"):
        g = STATS["grounding"][setup]
        rows.append([s.SETUP_NAME[setup], g["values_copied"], pct(g["share_found_in_tool_results"]),
                     pct(g["share_of_runs_that_got_data"])])
    write_table(
        "grounding",
        ["Setup", "Values given", "Found in tool results %", "Runs that got data %"],
        rows,
        "Grounding. A value the agent computed itself from tool output isn't found there, "
        "so the share found is a lower bound.",
    )


def table_pass_by_model():
    rows = []
    for model, name, _, _ in s.MODELS:
        p = STATS["per_model_setup_pass"][model]
        rows.append([name, *(pct(p[x]) if x in p else "" for x in (*s.SETUPS, "L2_padded"))])
    write_table(
        "pass_by_model",
        ["Model", *(s.SETUP_NAME[x] for x in (*s.SETUPS, "L2_padded"))],
        rows,
        "Share of runs that pass, per model and setup (%). 126 runs per cell. "
        "Only two models ran the padded side check.",
    )


def table_reliability():
    tr, sc = STATS["tries"], STATS["side_check"]
    rows = [
        ["Try 1 and try 2 give the same pass result",
         f"{pct(tr['same_result'])}% of {tr['conditions']} cases"],
        ["Pass rate, try 1 and try 2", f"{pct(tr['pass_try1'])}% and {pct(tr['pass_try2'])}%"],
        ["Level 2 padded minus Level 2 (2 models)",
         f"{pct(sc['estimate'])} points, 95% CI {ci(sc['ci95'])}, p = {sc['p']:.2f}"],
    ]
    write_table("reliability", ["Check", "Result"], rows, "Do the results hold?", "ll")


# Figures


def fig_pass_by_setup():
    xs = [0, 1, 2, 3, 4.4]  # the sandbox sits apart from the levels
    fig, ax = plt.subplots(figsize=(s.ONE_COLUMN, 1.9))
    ax.axvline(3.7, color=s.GRID, lw=0.8)
    for setup, x in zip(s.SETUPS, xs, strict=True):
        p = STATS["scores"][setup]["pass"]
        v = 100 * p["estimate"]
        lo, hi = (100 * c for c in p["ci95"])
        ax.bar(x, v, width=0.6, color=s.GRAYS[2])
        ax.errorbar(x, v, yerr=[[v - lo], [hi - v]], color=s.INK, lw=0.8, capsize=2, capthick=0.8)
        ax.text(x, hi + 3, f"{v:.1f}", ha="center", va="bottom", fontsize=7.5, color=s.INK)
    ax.set_xticks(xs, [s.SETUP_NAME[x] for x in s.SETUPS])
    ax.set_xlim(-0.5, 4.9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Runs that pass (%)")
    ax.grid(axis="x", visible=False)
    ax.tick_params(axis="x", length=0)
    s.save(fig, FIG / "pass_by_setup")
    plt.close(fig)


def fig_pass_by_model():
    rates = per_model_pass()
    xs = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "sandbox": 4.4}
    fig, ax = plt.subplots(figsize=(s.ONE_COLUMN, 2.3))
    ax.axvline(3.7, color=s.GRID, lw=0.8)
    for model, name, color, marker in s.MODELS:
        levels = ["L0", "L1", "L2", "L3"]
        ax.plot([xs[x] for x in levels], [100 * rates[model, x] for x in levels], color=color,
                marker=marker, mec="white", mew=0.6, label=name, zorder=3)
        ax.plot(xs["sandbox"], 100 * rates[model, "sandbox"], marker=marker, color=color, ls="none",
                mec="white", mew=0.6, zorder=3)
    ax.set_xticks(list(xs.values()), [s.SETUP_NAME[x] for x in xs])
    ax.set_xlim(-0.3, 4.7)
    ax.set_ylim(-3, 103)
    ax.set_ylabel("Runs that pass (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=3, handlelength=1.8, columnspacing=1.0)
    s.save(fig, FIG / "pass_by_model")
    plt.close(fig)


def fig_rq3():
    rows = [
        ("Correct", None),
        ("Wrong, says nothing\nis missing", "wrong_without_saying"),
        ("Labeled stand-in", "stand_in"),
        ("Says the data\nis missing", "no_values"),
        ("No answer", "no_answer"),
    ]
    series = [("L3", s.GRAYS[1]), ("sandbox", s.GRAYS[3])]
    h = 0.36
    fig, ax = plt.subplots(figsize=(s.ONE_COLUMN, 2.4))
    for i, (_, key) in enumerate(rows):
        y = len(rows) - 1 - i
        for j, (setup, color) in enumerate(series):
            est = STATS["scores"][setup]["pass"] if key is None else STATS["rq3"][setup][key]
            v = 100 * est["estimate"]
            lo, hi = (100 * c for c in est["ci95"])
            yy = y + h / 2 if j == 0 else y - h / 2
            ax.barh(yy, v, height=h * 0.88, color=color, label=s.SETUP_NAME[setup] if i == 0 else None)
            ax.errorbar(v, yy, xerr=[[v - lo], [hi - v]], color=s.INK, lw=0.7, capsize=1.5, capthick=0.7)
            ax.text(hi + 1.5, yy, f"{v:.0f}", va="center", fontsize=7, color=s.INK)
    ax.set_yticks(range(len(rows))[::-1], [name for name, _ in rows])
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("Share of answers (%)")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower right", handlelength=1.2)
    s.save(fig, FIG / "rq3_answer_types")
    plt.close(fig)


def fig_l2_failures():
    kinds = [
        ("Wrong value", lambda g: g["label"] == "gives_values"),
        ("Ran out of turns", lambda g: g["stop_reason"] == "budget"),
        ("Said data is missing", lambda g: g["label"] == "no_values"),
        ("Other", lambda g: g["label"] == "stand_in" or g["stop_reason"] == "model_output_failure"),
    ]
    failed = [g for g in GRADES if g["setup"] == "L2" and not g["passed"]]
    counts = {(name, g["model"]): 0 for name, _ in kinds for g in failed}
    for g in failed:
        name = next(n for n, test in kinds if test(g))  # every failure falls in exactly one kind
        counts[name, g["model"]] += 1
    fig, axes = plt.subplots(1, 4, figsize=(s.TWO_COLUMNS, 1.45), sharey=True)
    ys = list(range(len(s.MODELS)))[::-1]
    for ax, (name, _) in zip(axes, kinds, strict=True):
        total = sum(counts.get((name, m), 0) for m, *_ in s.MODELS)
        for y, (model, _, color, _) in zip(ys, s.MODELS, strict=True):
            n = counts.get((name, model), 0)
            ax.barh(y, n, height=0.62, color=color)
            ax.text(n + 2, y, str(n), va="center", fontsize=7, color=s.INK)
        ax.set_title(f"{name} ({total})", loc="left", color=s.INK)
        ax.set_xlim(0, 90)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(ys, [n for _, n, _, _ in s.MODELS])
    fig.supxlabel("Failed Level 2 runs (of 126 per model)", fontsize=8, color=s.INK, y=-0.16)
    fig.subplots_adjust(wspace=0.12)
    s.save(fig, FIG / "l2_failures")
    plt.close(fig)


def tex_text(text):
    """Plain text to LaTeX: escape special characters and turn straight double quotes into
    LaTeX quotes."""
    for a, b in (("\\", r"\textbackslash{}"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#"),
                 ("_", r"\_"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}")):
        text = text.replace(a, b)
    return re.sub(r'"([^"]*)"', r"``\1''", text)


def appendix():
    """Files for the paper's appendix, taken from the frozen study files so the appendix
    shows exactly what the agents and judges saw."""
    out = OUT / "appendix"
    out.mkdir(parents=True, exist_ok=True)

    prompt = (ROOT / "prompts" / "study_v3.md").read_text()
    prompt = re.sub(r"<!--.*?-->\s*", "", prompt, flags=re.S)  # drop the version header
    (out / "system_prompt.txt").write_text(prompt.strip() + "\n")

    sys.path.insert(0, str(ROOT / "src"))
    from repo_investigator.grading.extract import SYSTEM  # noqa: PLC0415

    (out / "judge_prompt.txt").write_text(SYSTEM.strip() + "\n")

    questions = [q for q in json.loads((ROOT / "questions" / "questions.json").read_text()) if q["in_study"]]
    first = {}
    for q in questions:
        first.setdefault(q["template"], q)
    lines = ["% Built by scripts/paper/make_paper_outputs.py. Do not edit by hand."]
    for n in range(1, 13):
        q = first[f"R{n}"]
        lines += [rf"\paragraph{{R{n} ({q['repo']})}} {tex_text(q['question'])}", ""]
    (out / "questions.tex").write_text("\n".join(lines))

    menus = {}
    for r in main_runs().values():
        if r["question_id"] == "R1-tokio":
            menus.setdefault(r["setup"], r["menu"])
    rows = [[s.SETUP_NAME[x], str(len(menus[x])), ", ".join(menus[x])] for x in s.SETUPS]
    body = [
        "% Built by scripts/paper/make_paper_outputs.py. Do not edit by hand.",
        r"\begin{table}[h]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Tool menus for R1 on tokio. Level 0 adds ci\_failure\_trend, which returns the answer's "
        r"values. Level 1 has landing\_run\_counts, which counts the CI runs that count for one period. "
        r"Level 3 drops the CI tables.}",
        r"\label{tab:menus}",
        r"\begin{tabular}{lrp{2.2in}}",
        r"\toprule",
        r"Setup & Tools & Names \\",
        r"\midrule",
        *(rf"{a} & {b} & \raggedright\texttt{{\footnotesize {tex_text(c)}}} \tabularnewline"
          for a, b, c in rows),
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    (out / "menus.tex").write_text("\n".join(body) + "\n")


def diagrams():
    dot = shutil.which("dot")
    if not dot:
        print("dot not found, skipping the diagrams")
        return
    # Graphviz's cairo renderer writes the space glyph as a Type 3 font, which
    # IEEE's PDF check rejects. The macOS quartz renderer embeds plain TrueType.
    formats = subprocess.run([dot, "-Tpdf:"], capture_output=True, text=True).stderr
    pdf = "pdf:quartz" if "pdf:quartz" in formats else "pdf"
    if pdf == "pdf":
        print("no quartz renderer: diagram PDFs will contain a Type 3 font")
    for src in sorted((Path(__file__).parent / "diagrams").glob("*.dot")):
        for fmt in (pdf, "png"):
            args = [dot, f"-T{fmt}", str(src), "-o", str(FIG / f"{src.stem}.{fmt.split(':')[0]}")]
            if fmt == "png":
                args.insert(2, "-Gdpi=300")
            subprocess.run(args, check=True)


def main():
    s.use()
    FIG.mkdir(parents=True, exist_ok=True)
    for build in (table_models, table_setups, table_scores, table_tests, table_rq3, table_sandbox,
                  table_hand_checks, table_definitions, table_per_model, table_reliability,
                  table_cost_by_setup, table_grounding, table_pass_by_model,
                  appendix, fig_pass_by_setup, fig_pass_by_model, fig_rq3,
                  fig_l2_failures, diagrams):
        build()
        print("built", build.__name__)


if __name__ == "__main__":
    main()
