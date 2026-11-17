"""One look for every figure in the paper.

IEEE two-column sizes, Times, a few colors. Each model keeps the same color and
marker in every figure. The five model colors are the Okabe-Ito set, checked
with a colorblind simulator on a white page: every pair is told apart, but the
closest pair (pink and green) only just, so models also get a marker shape and
a label, never color alone. Everything that is not a model is black or gray.
"""

import matplotlib as mpl

ONE_COLUMN = 3.5  # inches, IEEE column width
TWO_COLUMNS = 7.16

INK = "#000000"  # all text is black, like the body text and tables
GRID = "#e3e3e3"
AXIS = "#9a9a9a"

MODELS = [
    # (id in the run records, name in the paper, color, marker)
    ("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "#0072B2", "o"),
    ("google/gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "#D55E00", "s"),
    ("z-ai/glm-5.3-flash", "GLM 5.3 Flash", "#009E73", "^"),
    ("minimax/minimax-m3.1-flash", "MiniMax M3.1 Flash", "#E69F00", "D"),
    ("mistralai/ministral-14b-2512", "Ministral 14B", "#CC79A7", "v"),
]
MODEL_NAME = {m: n for m, n, _, _ in MODELS}
MODEL_COLOR = {m: c for m, _, c, _ in MODELS}
MODEL_MARKER = {m: k for m, _, _, k in MODELS}

SETUPS = ["L0", "L1", "L2", "L3", "sandbox"]
SETUP_NAME = {
    "L0": "Level 0",
    "L1": "Level 1",
    "L2": "Level 2",
    "L3": "Level 3",
    "sandbox": "Sandbox",
    "L2_padded": "Level 2 padded",
}

# Grays for answer types, darkest for the one that matters most.
GRAYS = ["#2b2b2b", "#5e5e5e", "#8c8c8c", "#b9b9b9", "#dedede"]


def use():
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "TeX Gyre Termes", "Nimbus Roman", "DejaVu Serif"],
            "mathtext.fontset": "stix",
            "font.size": 8,
            "axes.titlesize": 8,
            "axes.labelsize": 8,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "legend.fontsize": 7.5,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.6,
            "xtick.color": AXIS,
            "ytick.color": AXIS,
            "xtick.labelcolor": INK,
            "ytick.labelcolor": INK,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.5,
            "ytick.major.size": 2.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "axes.axisbelow": True,
            "legend.frameon": False,
            "lines.linewidth": 1.2,
            "lines.markersize": 4.5,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
            "pdf.fonttype": 42,  # embed fonts as TrueType, which IEEE asks for
            "ps.fonttype": 42,
        }
    )


def save(fig, path):
    """Write a PDF for the paper and a PNG for quick viewing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".pdf"), metadata={"CreationDate": None})  # no timestamp, so rebuilds match
    fig.savefig(path.with_suffix(".png"))
