#!/usr/bin/env python3
"""Build the rename-aware, author-attributed CBS change ledger.

Unlike ``compare-cbs-branches.py`` — which diffs two worktrees as plain file
trees and therefore reports a renamed analysis as *deleted on the left, added on
the right* — this script asks Git directly.  It uses Git's own rename detection
(``-M``) so the ~75 ``Analysis_<EXPERIMENT>_<TeV>_<channel>_<lumi>`` →
``Analysis_<EXPERIMENT>_<REPORT_NUMBER>`` migrations show up as one moved file
each, and it attributes every changed path to the authors who actually touched
it, so upstream ``master`` merges are not miscounted as local work.

Output: ``dependences/cbs-change-ledger.json``, consumed by
``dependences/cbs-change-ledger.html``.

Usage:
    scripts/build-change-ledger.py --gambit-root ~/Gambit-Workshop/gambit
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys

# Commit authors that count as the presenter's own work.  Everything else is
# treated as upstream (merged from master) or collaborator work.
OWN_AUTHORS = ("Pengxuan", "Buding")
# Agent-assisted commits authored under the presenter's direction; they do not
# make a file "collaborator work", but they are not evidence of authorship on
# their own either.
ASSISTED_AUTHORS = ("Claude",)

THEMES = (
    ("cbs-runner", "CBS standalone runner", (
        r"ColliderBit/examples/solo",
    )),
    ("results", "Result framework", (
        r"analyses/Histogram\.hpp", r"analyses/Cutflow\.hpp", r"AnalysisMacros",
        r"analyses/AnalysisData\.hpp", r"analyses/Analysis\.(hpp|cpp)",
        r"Utils/json\.hpp", r"plot_cbs_histograms", r"SignalRegionData",
        r"LHC_likelihoods",
    )),
    ("event-pipeline", "Event / jet pipeline", (
        r"ColliderBit/Utils\.hpp", r"src/Utils\.cpp", r"Py8EventConversions",
        r"BuckFast", r"getHepMCEvent", r"getLHEvent", r"getPy8Collider",
        r"HEPUtils/Event\.h", r"lhef2heputils", r"EventConversionUtils",
        r"ColliderBit_eventloop", r"warppertopness",
    )),
    ("analyses", "Analyses", (r"src/analyses/",)),
    ("build", "Build / backends / config", (
        r"^cmake/", r"^config/", r"^contrib/", r"^Backends/", r"^CMakeLists",
    )),
    ("yaml", "YAML & scripts", (r"^yaml_files/", r"\.py$")),
)

# Completion status asserted in the analysis sources themselves; each entry is
# verified against a quotable marker in the tree rather than assumed.
ANALYSIS_STATUS = {
    "Analysis_ATLAS_EXOT_2018_60": (
        "skeleton",
        "run() carries a TODO; collect_results() is empty. Registered only.",
    ),
    "Analysis_CMS_B2G_18_003": (
        "partial",
        "3M histogram SRs digitised; 3T/2M1L obs/bkg pending; high-mass is a "
        "cut-and-count approximation, not the CMS shape fit.",
    ),
}


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def classify_theme(path: str) -> tuple[str, str]:
    for key, label, patterns in THEMES:
        if any(re.search(p, path) for p in patterns):
            return key, label
    return "other", "Other"


def classify_author(authors: list[str]) -> str:
    own = any(any(a in name for a in OWN_AUTHORS) for name in authors)
    other = any(
        not any(a in name for a in OWN_AUTHORS + ASSISTED_AUTHORS)
        for name in authors
    )
    if own and not other:
        return "own"
    if own and other:
        return "mixed"
    if other:
        return "upstream"
    return "assisted"


def collect(root: Path, base: str, head: str) -> dict:
    raw = git(root, "diff", "--numstat", "-M", f"{base}", f"{head}")
    status = git(root, "diff", "--name-status", "-M", f"{base}", f"{head}")

    # name-status gives us rename pairs; numstat gives churn.
    renames: list[dict] = []
    kinds: dict[str, str] = {}
    for line in status.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        code = parts[0]
        if code.startswith("R") and len(parts) == 3:
            similarity = int(code[1:]) if code[1:].isdigit() else None
            renames.append({
                "from": parts[1], "to": parts[2], "similarity": similarity,
            })
            kinds[parts[2]] = "renamed"
        elif len(parts) >= 2:
            kinds[parts[1]] = {
                "A": "added", "D": "deleted", "M": "modified",
            }.get(code[0], code[0])

    churn: dict[str, tuple[int, int]] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if "=>" in path:
            # numstat renders renames as "old => new"; normalise to the new name.
            path = re.sub(r"\{.*? => (.*?)\}", r"\1", path)
            path = path.split(" => ")[-1]
        churn[path] = (
            int(added) if added.isdigit() else 0,
            int(deleted) if deleted.isdigit() else 0,
        )

    files: list[dict] = []
    for path, kind in kinds.items():
        authors = sorted(set(
            git(root, "log", "--format=%an", f"{base}..{head}", "--follow",
                "--", path).split("\n")
        ) - {""})
        commits = len([
            l for l in git(root, "log", "--oneline", f"{base}..{head}",
                           "--follow", "--", path).splitlines() if l
        ])
        added, deleted = churn.get(path, (0, 0))
        theme_key, theme_label = classify_theme(path)
        files.append({
            "path": path,
            "kind": kind,
            "added": added,
            "deleted": deleted,
            "commits": commits,
            "authors": authors,
            "attribution": classify_author(authors),
            "theme": theme_key,
            "theme_label": theme_label,
        })

    files.sort(key=lambda f: (-f["added"], f["path"]))
    return {"files": files, "renames": renames}


def summarise(files: list[dict]) -> dict:
    by_theme: dict[str, dict] = defaultdict(
        lambda: {"own": 0, "mixed": 0, "upstream": 0, "assisted": 0,
                 "added": 0, "deleted": 0, "label": ""}
    )
    for f in files:
        bucket = by_theme[f["theme"]]
        bucket["label"] = f["theme_label"]
        bucket[f["attribution"]] += 1
        if f["attribution"] in ("own", "mixed", "assisted"):
            bucket["added"] += f["added"]
            bucket["deleted"] += f["deleted"]
    return dict(by_theme)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path, required=True)
    parser.add_argument("--head", default="ColliderBit_solo_development")
    parser.add_argument("--source-branch", default="private-SUSYRun2")
    parser.add_argument("--master-ref", default="gambit/master")
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dependences" / "cbs-change-ledger.json",
    )
    args = parser.parse_args()

    root = args.gambit_root.expanduser().resolve()
    if not (root / ".git").exists():
        print(f"error: {root} is not a Git worktree", file=sys.stderr)
        return 1

    head_sha = git(root, "rev-parse", "--short", args.head).strip()
    source_sha = git(root, "rev-parse", "--short", args.source_branch).strip()
    master_sha = git(root, "rev-parse", "--short", args.master_ref).strip()
    merge_base = git(root, "merge-base", args.source_branch, args.head).strip()

    ledger = collect(root, merge_base, args.head)
    files = ledger["files"]

    # Commit-level author tallies, for the "whose work is this" slide.
    def author_tally(base: str) -> dict[str, int]:
        names = [n for n in git(root, "log", "--format=%an",
                                f"{base}..{args.head}").splitlines() if n]
        tally: dict[str, int] = defaultdict(int)
        for n in names:
            tally[n] += 1
        return dict(sorted(tally.items(), key=lambda kv: -kv[1]))

    payload = {
        "generated_by": "scripts/build-change-ledger.py",
        "refs": {
            "head": {"name": args.head, "sha": head_sha},
            "source_branch": {"name": args.source_branch, "sha": source_sha},
            "master": {"name": args.master_ref, "sha": master_sha},
            "merge_base": merge_base[:9],
        },
        "totals": {
            "files_changed": len(files),
            "renames": len(ledger["renames"]),
            "own_files": sum(1 for f in files if f["attribution"] == "own"),
            "mixed_files": sum(1 for f in files if f["attribution"] == "mixed"),
            "upstream_files": sum(
                1 for f in files if f["attribution"] == "upstream"),
            "commits_vs_master": len(git(
                root, "log", "--oneline",
                f"{args.master_ref}..{args.head}").splitlines()),
            "commits_vs_source": len(git(
                root, "log", "--oneline",
                f"{args.source_branch}..{args.head}").splitlines()),
        },
        "authors_vs_master": author_tally(args.master_ref),
        "authors_vs_source": author_tally(args.source_branch),
        "by_theme": summarise(files),
        "renames": ledger["renames"],
        "files": files,
        "analysis_status": {
            name: {"status": s, "note": n}
            for name, (s, n) in ANALYSIS_STATUS.items()
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    t = payload["totals"]
    print(f"Wrote {args.output}")
    print(f"  {t['files_changed']} files changed, {t['renames']} renamed")
    print(f"  attribution: own={t['own_files']} mixed={t['mixed_files']} "
          f"upstream={t['upstream_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
