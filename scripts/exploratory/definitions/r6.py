"""R6: which module had the most fix commits, and among modules with at least 20
commits, which had the highest share of fix commits.

Definitions the question uses:
- window: commits from 2025-10-01 to 2026-09-20, both inclusive
- merges: merge commits are left out
- bots: commits by bots are left out (and eslint's two automation emails)
- fix_rule: the first line has fix, fixes, fixed, fixing or bugfix as a whole word
- module: the folder at the depth the question names (top-level folder, or lib/sqlalchemy/<name>)
- test_files: test files are left out (test folders and test-style names)
- doc_files: documentation files are left out
- root_files: files at the repo root are left out
- denominator: a module's commits are the human non-merge commits touching it
- ranking: the answer is the highest share among modules with at least 20 commits

The answers are module names, so a match with an alternative key is weaker
evidence than in R8 or R12: several readings can give the same module. The main
evidence is the queries: the agent's file filters are tried on the repo's real
test and doc paths, and its own module table (if it shows commits and fixes per
module) is ranked again to see if it picked the top share.
"""

from collections import defaultdict

from common import (
    APPLIED,
    MISSED,
    OTHER_READING,
    UNCLEAR,
    Verdict,
    bot_filter,
    ck,
    fetch,
    fix_filter,
    merge_filter,
    window_check,
)
from r8 import kept, merge_row, ok_calls, person_row

TEMPLATE = "R6"
DEFINITIONS = [
    "window",
    "merges",
    "bots",
    "fix_rule",
    "module",
    "test_files",
    "doc_files",
    "root_files",
    "denominator",
    "ranking",
]
DEPTH = {"eslint": 2, "vite": 2, "sqlalchemy": 3, "prometheus": 1}
PARENT = {"eslint": "lib/", "vite": "packages/", "sqlalchemy": "lib/sqlalchemy/", "prometheus": ""}
DOC_BY_EXTENSION = r"lower(f.filename) ~ '\.(md|rst|txt|adoc)$'"
TEST_FOLDER_ONLY = (
    r"f.filename ~* '(^|/)(tests?|__tests__|testdata|testing|fixtures|playground|[^/]*[-_]tests?)/'"
)

# Each alternative switches off or changes one definition: (name, definition).
ALTERNATIVES = [
    ("merges kept", "merges"),
    ("bots kept", "bots"),
    ("test files kept", "test_files"),
    ("only test folders left out", "test_files"),
    ("doc files kept", "doc_files"),
    ("docs by extension only", "doc_files"),
    ("module commits include merges and bots", "denominator"),
    ("20-commit floor ignored", "ranking"),
    ("last day left out", "window"),
]


def _modules(rows, depth, sw):
    """(most fixes module, top share module) with one switch on."""
    commits, fixes = defaultdict(set), defaultdict(set)
    for r in rows:
        if sw == "last day left out" and r["at"] >= "2026-09-20":
            continue
        if r["test"] and sw != "test files kept" and (sw != "only test folders left out" or r["test_folder"]):
            continue
        if sw == "doc files kept":
            pass
        elif sw == "docs by extension only":
            if r["doc_ext"]:
                continue
        elif r["doc"]:
            continue
        parts = r["filename"].split("/")
        if len(parts) - 1 < depth:
            continue
        module = "/".join(parts[:depth])
        human = (sw == "merges kept" or not r["merge"]) and (sw == "bots kept" or not (r["bot"] or r["auto"]))
        if human or sw == "module commits include merges and bots":
            commits[module].add(r["sha"])
        if human and r["fix"]:
            fixes[module].add(r["sha"])
    if not commits:
        return None, None
    most = sorted(commits, key=lambda m: (-len(fixes[m]), -len(commits[m]), m))[0]
    floor = 0 if sw == "20-commit floor ignored" else 20
    busy = [m for m in commits if len(commits[m]) >= floor]
    top = sorted(busy, key=lambda m: (-len(fixes[m]) / len(commits[m]), m))[0] if busy else None
    return most, top


def _spread(paths, n=400):
    """Up to n paths, spread evenly over the sorted list."""
    paths = sorted(paths)
    step = max(1, len(paths) // n)
    return paths[::step][:n]


def prepare(conn, repos):
    rows = fetch(
        conn,
        f"""
        select r.name repo, c.sha, f.filename,
          to_char(c.committed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') at, c.is_merge merge,
          coalesce({ck.bot("c.author_login")}, false) bot,
          (c.author_login is null and coalesce(c.author_email, '') in {ck.AUTOMATION_EMAILS}) auto,
          {ck.FIX_SUBJECT} fix, {ck.TEST_FILE} test, {TEST_FOLDER_ONLY} test_folder,
          {ck.DOC_FILE} doc, {DOC_BY_EXTENSION} doc_ext
        from commits c join repos r on r.id = c.repo_id join commit_files f on f.commit_sha = c.sha
        where c.committed_at >= '{ck.W0}' and c.committed_at < '{ck.W1}'
          and r.name in ({", ".join(f"'{x}'" for x in repos)})""",
    )
    alt = {}
    for repo in repos:
        rs = [r for r in rows if r["repo"] == repo]
        depth = DEPTH[repo]
        in_module = [
            r
            for r in rs
            if len(r["filename"].split("/")) - 1 >= depth and r["filename"].startswith(PARENT[repo])
        ]
        alt[repo] = {
            "key": _modules(rs, depth, None),
            "alts": {name: _modules(rs, depth, name) for name, _ in ALTERNATIVES},
            # Real paths inside modules, to try the agent's file filters on.
            "test_paths": _spread({r["filename"] for r in in_module if r["test"]}),
            "doc_paths": _spread({r["filename"] for r in in_module if r["doc"] and not r["test"]}),
            "code_paths": _spread({r["filename"] for r in in_module if not r["doc"] and not r["test"]}),
        }
    return alt


def _file_row(path):
    parts = path.split("/")
    row = {"filename": path}
    for n in (1, 2, 3):
        row[f"folder{n}"] = "/".join(parts[:n]) if len(parts) > n else None
    return row


def module_calls(t):
    """Successful file queries grouped by a folder column: the module tables."""
    return [
        (a, r)
        for _, a, r in ok_calls(t, ("query_commit_files",))
        if any(str(g).startswith("folder") for g in (a.get("group_by") or []))
    ]


def file_filter_check(t, paths, code, what):
    """Share of the repo's real test (or doc) paths the agent's module queries leave
    out, taking the best of the queries that count fixes per module. Also says if it
    dropped ordinary code files."""
    calls = [
        (a, r) for a, r in module_calls(t) if any("fix" in c.lower() for c in r["columns"])
    ] or module_calls(t)
    if not calls:
        return Verdict(UNCLEAR, "no module query grouped by folder")
    if not paths:
        return Verdict(UNCLEAR, f"no {what} files inside modules in this repo")
    calls = [(a, r) for a, r in calls if r["rows"]]
    if not calls:
        return Verdict(UNCLEAR, "its module queries returned no rows")

    def dropped(c, ps):
        return sum(not kept(c[0], _file_row(p)) for p in ps) / len(ps) if ps else 0

    best = max(calls, key=lambda c: dropped(c, paths) - dropped(c, code))
    out, code_out = dropped(best, paths), dropped(best, code)
    note = f"; it also drops {code_out:.0%} of ordinary code files" if code_out > 0.2 else ""
    if code_out > 0.5:
        return Verdict(
            MISSED, f"its file filters are too broad: they drop {code_out:.0%} of ordinary code files"
        )
    if out >= 0.9:
        return Verdict(APPLIED, f"its module query leaves out {out:.0%} of the {what} files{note}")
    left = [p for p in paths if kept(best[0], _file_row(p))]
    if what == "doc" and all(_key_only_doc(p) for p in left):
        # The question names no doc rule; these are docs only by the key's wider rule.
        return Verdict(
            UNCLEAR,
            f"it kept {len(left)} files under .github/, changelog.d/ or .txt, "
            f"which only the key's doc rule counts{note}",
        )
    if out <= 0.1:
        return Verdict(MISSED, f"its module queries keep {1 - out:.0%} of the {what} files{note}")
    return Verdict(MISSED, f"its best module query leaves out only {out:.0%} of the {what} files{note}")


def _counts_humans(args, agg_name):
    """Does this count leave out merges and bots, by the query's filters or the
    aggregate's own where clause?"""
    agg = next((x for x in args.get("aggregates") or [] if x.get("name") == agg_name), {})
    where = agg.get("where") or []
    fs = [*(args.get("filters") or []), *(where if isinstance(where, list) else [where])]
    return (
        kept({"filters": fs}, merge_row(True)) is False
        and kept({"filters": fs}, person_row("dependabot[bot]")) is False
    )


def _key_only_doc(path):
    """Doc files by the key's rule that a plain reading of "documentation" may not cover."""
    return path.startswith(".github/") or "changelog.d/" in path or path.lower().endswith(".txt")


def own_tables(t):
    """Module tables from its own results that show commits and fix commits per module:
    a list of ({module: (commits, fixes)}, whether the commit count is human only), one
    per denominator column. A table of only fixes and a table of only commits are joined
    on the module."""
    tables, fix_only, count_only = [], [], []
    for a, r in module_calls(t):
        cols = r["columns"]
        if len(cols) == 2 and r["total"] <= len(r["rows"]) and cols[0].startswith("folder"):
            tab = {row[0]: row[1] for row in r["rows"] if row[0]}
            if "fix" in cols[1].lower():
                fix_only.append(tab)
            else:
                count_only.append((tab, _counts_humans(a, cols[1])))
    for f in fix_only:
        for c, human in count_only:
            joined = {m: (c[m], f.get(m, 0)) for m in c if isinstance(c[m], int)}
            if joined:
                tables.append((joined, human))
    for a, r in module_calls(t):
        cols = r["columns"]
        mod = next((i for i, c in enumerate(cols) if c.startswith("folder")), None)
        fix = [i for i, c in enumerate(cols) if "fix" in c.lower()]
        dens = [i for i, c in enumerate(cols) if i != mod and i not in fix and "file" not in c.lower()]
        if mod is None or len(fix) != 1 or r["total"] > len(r["rows"]):
            continue
        for d in dens:
            rows = [row for row in r["rows"] if isinstance(row[d], int) and row[mod]]
            if rows:
                tables.append(({row[mod]: (row[d], row[fix[0]]) for row in rows}, _counts_humans(a, cols[d])))
    return tables


def denominator_check(t):
    """Do the module queries that count commits leave out merges and bots before counting?"""
    calls = [
        a
        for a, r in module_calls(t)
        if any("fix" not in str(x.get("name", "")).lower() for x in a.get("aggregates") or [])
    ]
    if not calls:
        return Verdict(UNCLEAR, "no module query counting commits")
    clean = [a for a in calls if not kept(a, merge_row(True)) and not kept(a, person_row("dependabot[bot]"))]
    if len(clean) == len(calls):
        return Verdict(APPLIED, "its module commit counts leave out merges and bots")
    if not clean:
        return Verdict(MISSED, "its module commit counts keep merges or bots")
    return Verdict(UNCLEAR, "some module commit counts keep merges or bots")


def check(t, alt):
    a = alt[t.repo]
    out = {}
    most, top = t.value("most_fixes_module"), t.value("top_share_module")
    key_most, key_top = t.key["most_fixes_module"], t.key["top_share_module"]
    tools = ("query_commit_files", "query_commits")

    # Plain query checks, as in r10.py.
    out["window"] = window_check(t, tools, "committed_at")
    out["merges"] = merge_filter(t, tools, "(commit_)?is_merge")
    out["bots"] = bot_filter(t, tools, "(commit_)?author")
    out["fix_rule"] = fix_filter(t, tools, "(commit_)?subject")
    if most == key_most:
        for d in ("window", "merges", "bots", "fix_rule"):
            if out[d].verdict == UNCLEAR:
                out[d] = Verdict(APPLIED, f"most-fixes module {most} equals the key; {out[d].evidence}")

    # Module depth and root files: from the folder column it grouped by and its answers.
    depth = DEPTH[t.repo]
    groups = {g for a_, _ in module_calls(t) for g in a_.get("group_by") or [] if str(g).startswith("folder")}
    names = [x for x in (most, top) if isinstance(x, str)]
    if f"folder{depth}" in groups and all(x.count("/") == depth - 1 for x in names):
        out["module"] = Verdict(APPLIED, f"grouped by folder{depth}, answers at that depth")
    elif names and any(x.count("/") != depth - 1 for x in names):
        out["module"] = Verdict(MISSED, f"answer {names} is not a folder at depth {depth}")
    else:
        out["module"] = Verdict(UNCLEAR, f"grouped by {sorted(groups)}")
    out["root_files"] = (
        Verdict(APPLIED, f"grouped by folder{depth}, so root files have no module")
        if f"folder{depth}" in groups and all(names)
        else Verdict(UNCLEAR, "no grouping by a folder column")
    )

    # Test and doc files: its filters tried on the repo's real paths.
    out["test_files"] = file_filter_check(t, a["test_paths"], a["code_paths"], "test")
    out["doc_files"] = file_filter_check(t, a["doc_paths"], a["code_paths"], "doc")

    # The share answer: alternatives that give its module, and its own tables.
    hits = [n for n, (_, x) in a["alts"].items() if x == top and x != key_top]
    tables = own_tables(t)
    picks, picked_human = [], {}
    for tab, human in tables:
        busy = {m: v for m, v in tab.items() if v[0] >= 20}
        if busy:
            pick = max(busy, key=lambda m: busy[m][1] / busy[m][0])
            picks.append(pick)
            picked_human.setdefault(pick, human)
    if top == key_top:
        out["denominator"] = Verdict(APPLIED, f"top-share module {top} equals the key")
        out["ranking"] = Verdict(APPLIED, f"top-share module {top} equals the key")
    else:
        den_hits = [n for n in hits if dict(ALTERNATIVES)[n] == "denominator"]
        den = denominator_check(t)
        if top in picked_human:
            # Judge the count it ranked by, not every query.
            den = (
                Verdict(APPLIED, "the commit count it ranked by leaves out merges and bots")
                if picked_human[top]
                else Verdict(MISSED, "the commit count it ranked by keeps merges or bots")
            )
        if den_hits and top in picks and den.verdict == MISSED:
            # Counting every commit that touched a module is a literal reading of "at least 20 commits".
            out["denominator"] = Verdict(
                OTHER_READING,
                f"{top} is the top share when a module's commits include merges and bots "
                "(the question says 'at least 20 commits', not human commits); "
                f"its own table agrees; {den.evidence}",
            )
        elif den.verdict == APPLIED:
            out["denominator"] = den
        elif den_hits:
            out["denominator"] = Verdict(
                UNCLEAR, f"{top} equals the key with '{den_hits[0]}'; {den.evidence}"
            )
        else:
            out["denominator"] = Verdict(
                den.verdict, f"top-share module {top}, key {key_top}; {den.evidence}"
            )
        seen = [(len(r["rows"]), r["total"]) for _, r in module_calls(t) if len(r["columns"]) > 2]
        if not picks and seen and all(n < total for n, total in seen):
            n, total = seen[-1]
            out["ranking"] = Verdict(MISSED, f"it saw only {n} of {total} modules in its share table")
        elif picks and top not in picks:
            out["ranking"] = Verdict(
                MISSED,
                f"its own module table gives {picks[0]} the highest share at 20+ commits, it said {top}",
            )
        elif picks:
            out["ranking"] = Verdict(APPLIED, f"{top} is the top share in its own module table")
        elif "20-commit floor ignored" in hits:
            out["ranking"] = Verdict(MISSED, f"{top} equals the key with the 20-commit floor ignored")
        elif top == most:
            out["ranking"] = Verdict(
                UNCLEAR, f"it gave the most-fixes module {top} for the share too; no table to rank again"
            )
        else:
            out["ranking"] = Verdict(
                UNCLEAR, f"top-share module {top}, key {key_top}; no table to rank again"
            )
    return out
