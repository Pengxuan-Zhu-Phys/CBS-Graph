#!/usr/bin/env python3
"""Render the FastJet / fjcontrib build-integration page.

This one is a three-way comparison, because two-way would misrepresent it:

  gambit/master          fjcore only, always, no FastJet anywhere in contrib.cmake
  private-SUSYRun2       FastJet + fjcontrib downloaded and built by CMake; fjcore
                         commented out entirely
  ColliderBit_solo_dev   FastJet + fjcontrib detected if already built, fjcore kept
                         as the fallback, with FJNS selecting the namespace

Reading only the source branch against the dev branch would hide that the dev
branch re-unifies two upstream paths that had diverged.

Line numbers, link flags, gate conditions, consumer sites, the region diff and
the commit history are all extracted from the two worktrees at generation time.
No build was run: this page describes what the build system is configured to do,
not what a compiler did.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

CONTRIB = "cmake/contrib.cmake"
UTILITIES = "cmake/utilities.cmake"
EXECUTABLES = "cmake/executables.cmake"
BACKENDS = "cmake/backends.cmake"
FASTJET_H = "contrib/heputils/include/HEPUtils/FastJet.h"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def git_show(root: Path, ref: str, path: str) -> list[str]:
    return git(root, "show", f"{ref}:{path}").splitlines()


def find(lines: list[str], pattern: str, start: int = 0) -> int:
    """First 0-based index at or after ``start`` matching ``pattern``."""
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    raise SystemExit(f"pattern not found: {pattern!r}")


def find_all(lines: list[str], pattern: str) -> list[int]:
    rx = re.compile(pattern)
    return [i for i in range(len(lines)) if rx.search(lines[i])]


def region(lines: list[str], start_pat: str, end_pat: str) -> tuple[int, int]:
    """Inclusive 0-based span between two anchor patterns."""
    lo = find(lines, start_pat)
    hi = find(lines, end_pat, lo + 1)
    return lo, hi


def ldflags(line: str) -> list[str]:
    """The -l entries of a set(..._LDFLAGS ...) line, in order."""
    return re.findall(r'-l([A-Za-z0-9_]+)', line)


def libdirs(line: str) -> list[str]:
    return re.findall(r'-L([^"\s]+)', line)


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def collect(gambit: Path, baseline_ref: str, master_ref: str) -> dict:
    head = (gambit / CONTRIB).read_text().splitlines()
    base = git_show(gambit, baseline_ref, CONTRIB)
    master = git_show(gambit, master_ref, CONTRIB)

    # ---- the jet-clustering region on each side --------------------------
    head_lo, head_hi = region(head, r"^#contrib/fastjet-3\.4\.2 and fjcontrib", r"^#contrib/multimin")
    base_lo, base_hi = region(base, r"^#contrib/fjcore-3\.2\.0", r"^#contrib/multimin")
    master_lo, master_hi = region(master, r"^#contrib/fjcore-3\.2\.0", r"^#contrib/multimin")

    # ---- link surfaces ----------------------------------------------------
    head_fj = head[find(head, r"set\(fastjet_LDFLAGS")]
    head_fjc = head[find(head, r"set\(fjcontrib_LDFLAGS")]
    base_fj = base[find(base, r"set\(fastjet_LDFLAGS")]
    base_fjc = base[find(base, r"set\(fjcontrib_LDFLAGS")]

    # ---- gates ------------------------------------------------------------
    head_gate_idx = find(head, r"^if\(EXISTS .*ClusterSequence\.hh")
    base_fj_gate_idx = find(base, r'MATCHES ";ColliderBit;"', base_lo)
    base_fjc_gate_idx = find(base, r'MATCHES ";ColliderBit;"', base_fj_gate_idx + 1)

    # ---- Nsubjettiness object library -------------------------------------
    nsub_idx = find(head, r"add_gambit_library\(fjcontrib_nsubjettiness")
    nsub_sources = []
    for i in range(nsub_idx, min(nsub_idx + 14, len(head))):
        match = re.search(r"\$\{fjcontrib_nsubjettiness_dir\}/([A-Za-z0-9_]+\.cc)", head[i])
        if match:
            nsub_sources.append({"file": match.group(1), "line": i + 1})
        if head[i].rstrip().endswith(")") and nsub_sources:
            break

    # ---- FJNS switch ------------------------------------------------------
    fjns_true = find(head, r"add_definitions\(-DFJNS=fastjet\)")
    fjcore_def = find(head, r"add_definitions\(-DFJCORE\)")
    fjns_false = find(head, r"add_definitions\(-DFJNS=gambit::fjcore\)")
    fjcore_lib = find(head, r"add_gambit_library\(fjcore")

    # ---- who consumes the flags ------------------------------------------
    consumers = []
    for path in (UTILITIES, EXECUTABLES, BACKENDS):
        lines = (gambit / path).read_text().splitlines()
        for i in find_all(lines, r"EXCLUDE_FASTJET|EXCLUDE_FJCONTRIB|fastjet_LDFLAGS|fjcontrib_LDFLAGS"):
            consumers.append({"path": path, "line": i + 1, "text": lines[i].strip()})

    # ---- HEPUtils namespace plumbing -------------------------------------
    fastjet_h = (gambit / FASTJET_H).read_text().splitlines()
    fjns_sites = []
    for path in (
        "contrib/heputils/include/HEPUtils/FastJet.h",
        "contrib/heputils/include/HEPUtils/Event.h",
        "contrib/heputils/include/HEPUtils/Jet.h",
    ):
        lines = (gambit / path).read_text().splitlines()
        hits = find_all(lines, r"\bFJNS\b")
        fjns_sites.append({"path": path, "count": len(hits), "first": hits[0] + 1 if hits else None})

    # ---- ColliderBit consumers -------------------------------------------
    symbols = {}
    for symbol in ("VariableR", "Nsubjettiness", "EnergyCorrelator", "SoftDrop"):
        out = git(gambit, "grep", "-l", symbol, "--", "ColliderBit/").splitlines()
        includes = git(gambit, "grep", "-n", f'#include.*{symbol}', "--", "ColliderBit/").splitlines()
        symbols[symbol] = {
            "files": sorted(out),
            "includes": [line.strip() for line in includes],
        }

    # ---- guard coverage in the analyses ----------------------------------
    guarded, unguarded = [], []
    analysis_files = sorted({f for s in symbols.values() for f in s["files"] if "/analyses/" in f})
    for path in analysis_files:
        text = (gambit / path).read_text()
        (guarded if "#ifndef FJCORE" in text else unguarded).append(path)

    # ---- history ----------------------------------------------------------
    # -G (regex appears in the diff text) rather than -S (occurrence count
    # changed): a commit that rewrites a fastjet line without changing how many
    # times the word appears is still a commit about fastjet.
    log = git(
        gambit, "log", "--format=%h|%an|%ad|%s", "--date=short",
        "-G", "fastjet|fjcontrib|fjcore|FJNS", f"{baseline_ref}..HEAD",
        "--", "cmake/", "contrib/heputils/",
    ).splitlines()
    commits = []
    for entry in log:
        sha, author, date, subject = entry.split("|", 3)
        commits.append({
            "sha": sha, "author": author, "date": date,
            "subject": subject.split(" - ")[0].strip(),
        })

    # ---- why fjcore survives ---------------------------------------------
    # The question "who still needs fjcore?" is answerable: count the files
    # that name a jet type at all, per top-level directory.
    jet_users: dict[str, int] = {}
    for path in git(gambit, "grep", "-l", "PseudoJet\\|ClusterSequence\\|FJNS").splitlines():
        top = path.split("/", 1)[0]
        jet_users[top] = jet_users.get(top, 0) + 1

    fjcore_hh = (gambit / "contrib/fjcore-3.2.0/fjcore.hh").read_text().splitlines()
    ns_idx = find(fjcore_hh, r"#define FJCORE_BEGIN_NAMESPACE")
    common_idx = find(head, r"TARGET_OBJECTS:fjcore")

    # Every analysis that mentions fjcore, and whether its fallback branch is
    # self-consistent: a body that hard-codes ``fastjet::`` cannot compile once
    # FJNS becomes gambit::fjcore.
    fallbacks = []
    for path in sorted(git(gambit, "grep", "-l", "fjcore", "--", "ColliderBit/").splitlines()):
        src = (gambit / path).read_text().splitlines()
        guard_start = next((i for i, l in enumerate(src) if "#ifndef FJCORE" in l), None)
        body_start = 0
        if guard_start is not None:
            # Walk the preprocessor nesting to the #endif that closes the guard;
            # a fastjet:: inside the guard's own #ifndef branch is legitimate,
            # only one after it is unconditional.
            depth = 0
            for i in range(guard_start, len(src)):
                stripped = src[i].strip()
                if stripped.startswith(("#if", "#ifdef", "#ifndef")):
                    depth += 1
                elif stripped.startswith("#endif"):
                    depth -= 1
                    if depth == 0:
                        body_start = i + 1
                        break
        body = "\n".join(src[body_start:])
        hits = [
            {"line": body_start + offset + 1, "text": line.strip()}
            for offset, line in enumerate(src[body_start:])
            if re.search(r"\bfastjet::", line)
        ]
        fallbacks.append({
            "path": path,
            "guard": guard_start is not None,
            "guard_ends": body_start,
            "literal_fastjet": len(re.findall(r"\bfastjet::", body)),
            "first_hit": hits[0] if hits else None,
            "consistent": not hits,
        })

    # ---- provisioning reality --------------------------------------------
    ignore = (gambit / ".gitignore").read_text().splitlines()
    ignore_hits = [
        {"line": i + 1, "text": ignore[i].strip()}
        for i in find_all(ignore, r"^contrib/(fastjet|fjcontrib)-")
    ]
    tracked_fastjet = len(git(gambit, "ls-files", "contrib/fastjet-3.4.2").splitlines())
    tracked_fjcontrib = len(git(gambit, "ls-files", "contrib/fjcontrib-1.049").splitlines())
    tracked_fjcore = len(git(gambit, "ls-files", "contrib/fjcore-3.2.0").splitlines())

    lib_dir = gambit / "contrib/fastjet-3.4.2/local/lib"
    present_libs = sorted(p.name for p in lib_dir.glob("lib*")) if lib_dir.is_dir() else []

    return {
        "generated_by": "scripts/build-fastjet-cmake-page.py",
        "refs": {
            "baseline": baseline_ref,
            "master": master_ref,
            "head": git(gambit, "rev-parse", "--short", "HEAD").strip(),
        },
        "region": {
            "head": {"lo": head_lo + 1, "hi": head_hi, "lines": head[head_lo:head_hi]},
            "base": {"lo": base_lo + 1, "hi": base_hi, "lines": base[base_lo:base_hi]},
            "master": {"lo": master_lo + 1, "hi": master_hi, "lines": master[master_lo:master_hi]},
        },
        "links": {
            "head_fastjet": {"line": head_fj.strip(), "libs": ldflags(head_fj), "dirs": libdirs(head_fj)},
            "head_fjcontrib": {"line": head_fjc.strip(), "libs": ldflags(head_fjc), "dirs": libdirs(head_fjc)},
            "base_fastjet": {"line": base_fj.strip(), "libs": ldflags(base_fj), "dirs": libdirs(base_fj)},
            "base_fjcontrib": {"line": base_fjc.strip(), "libs": ldflags(base_fjc), "dirs": libdirs(base_fjc)},
        },
        "gates": {
            "head": {"line": head_gate_idx + 1, "text": head[head_gate_idx].strip()},
            "base_fastjet": {"line": base_fj_gate_idx + 1, "text": base[base_fj_gate_idx].strip()},
            "base_fjcontrib": {"line": base_fjc_gate_idx + 1, "text": base[base_fjc_gate_idx].strip()},
        },
        "nsubjettiness": {"line": nsub_idx + 1, "sources": nsub_sources},
        "fjns": {
            "with_fastjet": {"line": fjns_true + 1, "text": head[fjns_true].strip()},
            "fjcore_flag": {"line": fjcore_def + 1, "text": head[fjcore_def].strip()},
            "fjcore_ns": {"line": fjns_false + 1, "text": head[fjns_false].strip()},
            "fjcore_lib": {"line": fjcore_lib + 1, "text": head[fjcore_lib].strip()},
            "sites": fjns_sites,
        },
        "fjcore_rationale": {
            "jet_users": jet_users,
            "namespace": {"line": ns_idx + 1, "text": fjcore_hh[ns_idx].strip()},
            "always_linked": {"line": common_idx + 1, "text": head[common_idx].strip()},
            "fallbacks": fallbacks,
        },
        "consumers": consumers,
        "symbols": symbols,
        "guards": {"guarded": guarded, "unguarded": unguarded},
        "commits": commits,
        "provisioning": {
            "gitignore": ignore_hits,
            "tracked": {
                "fastjet": tracked_fastjet,
                "fjcontrib": tracked_fjcontrib,
                "fjcore": tracked_fjcore,
            },
            "present_libs": present_libs,
        },
    }


# --------------------------------------------------------------------------
# numbered change units
# --------------------------------------------------------------------------

def change_units(data: dict) -> list[dict]:
    links = data["links"]
    gates = data["gates"]
    base_fj = links["base_fastjet"]["libs"]
    head_fj = links["head_fastjet"]["libs"]
    base_fjc = links["base_fjcontrib"]["libs"]
    head_fjc = links["head_fjcontrib"]["libs"]

    return [
        {
            "id": 1,
            "kind": "replaced",
            "title": "The gate",
            "target": "cmake/contrib.cmake",
            "old": f'{gates["base_fastjet"]["text"]} — a declaration: "ColliderBit is in the build, so FastJet is wanted"',
            "new": f'{gates["head"]["text"]} — a probe: "a built FastJet is actually here"',
            "why": "The old gate asked what the user requested. It could not tell a "
                   "requested FastJet from a present one, which is the question that "
                   "matters once CMake stops building FastJet itself.",
            "impact": "Configuration now depends on the state of the working tree, not "
                      "only on the cache variables. The same <code>cmake</code> command "
                      "produces a different build on a machine that has not provisioned "
                      "FastJet.",
            "evidence": f'Both conditions read from source: baseline <code>contrib.cmake:{gates["base_fastjet"]["line"]}</code>, '
                        f'current <code>contrib.cmake:{gates["head"]["line"]}</code>.',
            "tokens": ["EXISTS", "ClusterSequence.hh", "MATCHES \";ColliderBit;\""],
        },
        {
            "id": 2,
            "kind": "removed",
            "title": "Download and build",
            "target": "ExternalProject_Add(fastjet) / (fjcontrib)",
            "old": "Two <code>ExternalProject_Add</code> blocks fetched the tarballs "
                   "(<code>fastjet.fr</code>, <code>fastjet.hepforge.org</code>), verified "
                   "MD5s, ran <code>./configure --enable-shared</code> and "
                   "<code>fragile-shared-install</code>, and registered clean/nuke targets.",
            "new": "Both blocks are gone. Nothing in CMake obtains FastJet any more.",
            "why": "Rebuilding FastJet on every fresh configure is slow, needs network, "
                   "and the in-tree build had repeatedly needed compiler-flag patches "
                   "(<code>-Xclang -fopenmp</code> stripping, four warning suppressions).",
            "impact": "Fastest possible reconfigure, and the FastJet build can be tuned "
                      "once by hand. The cost is that provisioning moved out of the build "
                      "system without moving into anything else in this repository — see "
                      "section 06.",
            "evidence": "The removed blocks are visible in the region diff below.",
            "tokens": ["ExternalProject_Add", "DOWNLOAD_COMMAND", "fastjet_dl", "fjcontrib_dl",
                       "add_contrib_clean_and_nuke", "CONFIGURE_COMMAND"],
        },
        {
            "id": 3,
            "kind": "expanded",
            "title": "FastJet link surface",
            "target": "fastjet_LDFLAGS",
            "old": " ".join(f"-l{lib}" for lib in base_fj),
            "new": " ".join(f"-l{lib}" for lib in head_fj),
            "why": "VariableR is a FastJet <em>plugin</em>, so it needs "
                   "<code>fastjetplugins</code>; the plugin set in turn pulls in both "
                   "SISCone libraries. Neither was linked before because nothing used a "
                   "plugin.",
            "impact": f'{len(head_fj) - len(base_fj)} additional libraries. Note the order '
                      "differs between the two consumption sites — see section 04.",
            "evidence": f'<code>{html.escape(links["head_fastjet"]["line"])}</code>',
            "tokens": ["fastjet_LDFLAGS", "lfastjetplugins", "lsiscone"],
        },
        {
            "id": 4,
            "kind": "expanded",
            "title": "fjcontrib link surface",
            "target": "fjcontrib_LDFLAGS",
            "old": " ".join(f"-l{lib}" for lib in base_fjc),
            "new": " ".join(f"-l{lib}" for lib in head_fjc),
            "why": "The branch added analyses that use variable-R jets and energy "
                   "correlators, neither of which lives in RecursiveTools.",
            "impact": "Adds the two algorithm libraries plus the combined "
                      "<code>fastjetcontribfragile</code> shared object. The three named "
                      "algorithm libraries are static archives on this machine while "
                      "<code>fastjetcontribfragile</code> is shared, so they are not "
                      "interchangeable at link time.",
            "evidence": f'<code>{html.escape(links["head_fjcontrib"]["line"])}</code>',
            "tokens": ["fjcontrib_LDFLAGS", "lVariableR", "lEnergyCorrelator", "lfastjetcontribfragile"],
        },
        {
            "id": 5,
            "kind": "revived",
            "title": "fjcore as fallback",
            "target": "FJNS / FJCORE",
            "old": "The whole fjcore block was commented out, under a TODO citing class-"
                   "name clashes with FastJet. The branch had exactly one jet backend.",
            "new": "fjcore is compiled unconditionally, and the preprocessor picks the "
                   "namespace: <code>-DFJNS=fastjet</code> when FastJet was found, "
                   "<code>-DFJCORE -DFJNS=gambit::fjcore</code> when it was not.",
            "why": "It restores upstream <code>master</code>'s behaviour as the floor. "
                   "master has no FastJet in <code>contrib.cmake</code> at all and always "
                   "uses fjcore; the source branch had replaced that rather than layered "
                   "on it.",
            "impact": "GAMBIT keeps configuring and building without FastJet. This is a "
                      "build-system fallback, not an analysis-level one — section 06 has "
                      "the limits.",
            "evidence": f'<code>contrib.cmake:{data["fjns"]["with_fastjet"]["line"]}</code> and '
                        f'<code>:{data["fjns"]["fjcore_ns"]["line"]}</code>; the macro is consumed by HEPUtils.',
            "tokens": ["FJNS", "FJCORE", "fjcore_INCLUDE_DIR", "add_gambit_library(fjcore"],
        },
        {
            "id": 6,
            "kind": "added",
            "title": "Nsubjettiness compiled in-tree",
            "target": "add_gambit_library(fjcontrib_nsubjettiness)",
            "old": "Not present. Nsubjettiness was neither built nor linked.",
            "new": f'{len(data["nsubjettiness"]["sources"])} fjcontrib source files are compiled '
                   "into a GAMBIT object library and folded into "
                   "<code>GAMBIT_BASIC_COMMON_OBJECTS</code>.",
            "why": "Unlike VariableR and EnergyCorrelator, Nsubjettiness is taken as "
                   "source rather than as a library.",
            "impact": "It is the one fjcontrib component whose compiler flags come from "
                      "GAMBIT rather than from fjcontrib's own configure, and the only one "
                      "that needs the unpacked fjcontrib source tree — not just the "
                      "installed libraries — to be present.",
            "evidence": f'<code>contrib.cmake:{data["nsubjettiness"]["line"]}</code>',
            "tokens": ["fjcontrib_nsubjettiness", "Njettiness", "AxesDefinition"],
        },
        {
            "id": 7,
            "kind": "added",
            "title": "Contrib headers on the include path",
            "target": "include_directories",
            "old": 'Only <code>${fjcontrib_dir}/RecursiveTools</code> was added.',
            "new": 'Both <code>${fastjet_DIR}/include</code> and '
                   '<code>${fastjet_DIR}/include/fastjet/contrib</code> are added.',
            "why": "The analyses are inconsistent about how they include contrib headers: "
                   "some write <code>#include \"fastjet/contrib/Nsubjettiness.hh\"</code>, "
                   "others write a bare <code>#include \"SoftDrop.hh\"</code>. Adding both "
                   "roots makes each spelling resolve.",
            "impact": "A line that looks redundant is load-bearing. Removing the second "
                      "<code>include_directories</code> breaks every bare-name include.",
            "evidence": "Both spellings appear in the analysis include list in section 05.",
            "tokens": ["include_directories", "include/fastjet/contrib"],
        },
        {
            "id": 8,
            "kind": "replaced",
            "title": "LDFLAGS as list elements",
            "target": "quoting, across every contrib",
            "old": 'One string: <code>set(fastjet_LDFLAGS "-L${dir} -lfastjet -lfastjettools")</code>.',
            "new": 'Separate elements: <code>set(fastjet_LDFLAGS "-L${dir}" "-lfastjet" ...)</code>.',
            "why": "CMake treats a single string as one item, so the same flags could be "
                   "appended more than once without CMake recognising the duplicate. The "
                   "commit that made the change says so directly: <em>\"split LDFLAGS into "
                   "list elements to kill duplicate-library warnings\"</em>.",
            "impact": "Applied consistently to <code>gambit_preload</code>, RestFrames, "
                      "HepMC, YODA and FastJet, so it is a house rule now rather than a "
                      "FastJet-specific fix. Cosmetic in effect, but it is the reason "
                      "those unrelated one-line changes appear in the same diff.",
            "evidence": "Commit <code>bb641a5d1e</code> in the history table below.",
            "tokens": ['"-L${fastjet_DIR}/lib"', '-L${fastjet_dir}/local/lib -lfastjet'],
        },
    ]


# --------------------------------------------------------------------------
# diff of the region
# --------------------------------------------------------------------------

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def region_diff(data: dict) -> str:
    import difflib
    old = data["region"]["base"]["lines"]
    new = data["region"]["head"]["lines"]
    return "\n".join(difflib.unified_diff(
        old, new,
        fromfile=f'private-SUSYRun2 {CONTRIB}',
        tofile=f'ColliderBit_solo_development {CONTRIB}',
        lineterm="", n=2,
    ))


def split_hunks(diff: str) -> list[dict]:
    hunks: list[dict] = []
    current: dict | None = None
    for line in diff.splitlines():
        if HUNK_HEADER_RE.match(line):
            current = {"header": line, "lines": []}
            hunks.append(current)
        elif current is not None:
            current["lines"].append(line)
    return hunks


def excerpt(lines: list[str], tokens: list[str], limit: int = 14) -> list[dict]:
    """Lines carrying any of the unit's tokens, with their 1-based numbers.

    The region is a rewrite rather than a set of edits, so a unified diff of it
    collapses into a single hunk and cannot separate one change from another.
    Quoting the lines each change actually owns, from each side, does separate
    them.
    """
    hits = []
    for offset, line in enumerate(lines):
        if any(token in line for token in tokens):
            hits.append({"line": offset + 1, "text": line})
        if len(hits) >= limit:
            break
    return hits


def attach_excerpts(units: list[dict], data: dict) -> None:
    base = data["region"]["base"]
    head = data["region"]["head"]
    for unit in units:
        unit["before_lines"] = [
            dict(hit, line=hit["line"] + base["lo"] - 1)
            for hit in excerpt(base["lines"], unit["tokens"])
        ]
        unit["after_lines"] = [
            dict(hit, line=hit["line"] + head["lo"] - 1)
            for hit in excerpt(head["lines"], unit["tokens"])
        ]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def three_way_svg(data: dict) -> str:
    width, height = 1160, 372
    lanes = [
        ("gambit/master", "upstream", "detail-data", [
            "fjcore only, unconditional",
            "-DFJCORE  -DFJNS=gambit::fjcore",
            "no FastJet in contrib.cmake",
        ]),
        ("private-SUSYRun2", "source branch", "detail-mod", [
            "FastJet 3.4.2 downloaded + built",
            "fjcontrib 1.049, -lRecursiveTools",
            "fjcore block commented out",
        ]),
        ("ColliderBit_solo_development", "this branch", "detail-focal", [
            "FastJet detected if already built",
            "5 FastJet + 4 fjcontrib libraries",
            "fjcore kept, FJNS picks namespace",
        ]),
    ]
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="tw-title tw-desc">',
        '<title id="tw-title">Three states of jet clustering</title>',
        '<desc id="tw-desc">Upstream master uses fjcore only; the SUSYRun2 source branch '
        'replaced it with a downloaded FastJet; the development branch keeps both and '
        'selects between them at configure time.</desc>',
        '<defs><marker id="tw-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]
    lane_w, gap = 348, 58
    for index, (title, kind, cls, rows) in enumerate(lanes):
        x = 20 + index * (lane_w + gap)
        out.append(f'<g class="node {cls}">')
        out.append(f'<rect x="{x}" y="40" width="{lane_w}" height="182" rx="8"/>')
        out.append(f'<text class="kind" x="{x + 18}" y="66">{esc(kind.upper())}</text>')
        out.append(f'<text class="title" x="{x + 18}" y="92">{esc(title)}</text>')
        for row_index, row in enumerate(rows):
            out.append(f'<text class="body" x="{x + 18}" y="{124 + row_index * 22}">{esc(row)}</text>')
        out.append("</g>")
        if index < len(lanes) - 1:
            x1 = x + lane_w
            out.append(f'<path class="detail-edge" d="M{x1 + 6} 131 H{x1 + gap - 10}" marker-end="url(#tw-arrow)"/>')

    out.append('<text class="legend-label" x="20" y="262">'
               'the middle state replaced fjcore; the right state layers on top of it instead, '
               'so master&#8217;s behaviour survives as the floor</text>')
    out.append('<text class="legend-label" x="20" y="282">'
               'that is why this page is a three-way comparison: against SUSYRun2 alone, '
               'reviving fjcore looks like a new feature rather than a restoration</text>')
    out.append(f'<rect class="zone" x="20" y="304" width="{width - 40}" height="50" rx="7"/>')
    out.append('<text class="zone-label" x="38" y="326">SELECTOR</text>')
    out.append('<text class="body" x="38" y="344" fill="#4f5d75">'
               'FJNS &#8212; a preprocessor macro CMake sets, consumed by HEPUtils Event.h / Jet.h / FastJet.h, '
               'so the choice reaches the event data model rather than stopping at link time</text>')
    out.append("</svg>")
    return "\n".join(out)


def gate_svg(data: dict) -> str:
    width, height = 1160, 300
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="gate-title gate-desc">',
        '<title id="gate-title">What the configure step decides</title>',
        '<desc id="gate-desc">A single EXISTS probe sets three variables that fan out to '
        'the link flags, the fjcore namespace and whether Rivet is built.</desc>',
        '<defs><marker id="gate-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]
    out.append('<g class="node detail-focal"><rect x="20" y="112" width="286" height="76" rx="8"/>')
    out.append('<text class="kind" x="38" y="138">CONFIGURE-TIME PROBE</text>')
    out.append('<text class="title" x="38" y="160">EXISTS ClusterSequence.hh</text>')
    out.append('<text class="body" x="38" y="178">contrib/fastjet-3.4.2/local</text></g>')

    branches = [
        (44, "FOUND", "detail-primary", [
            "WITH_FASTJET_CONTRIB = TRUE",
            "5 FastJet + 4 fjcontrib libs",
            "-DFJNS=fastjet",
        ]),
        (176, "NOT FOUND", "detail-optional", [
            "EXCLUDE_FASTJET / FJCONTRIB = TRUE",
            "no message printed",
            "-DFJCORE  -DFJNS=gambit::fjcore",
        ]),
    ]
    for y, label, cls, rows in branches:
        out.append(f'<g class="node {cls}"><rect x="386" y="{y}" width="330" height="92" rx="8"/>')
        out.append(f'<text class="kind" x="404" y="{y + 24}">{esc(label)}</text>')
        for row_index, row in enumerate(rows):
            out.append(f'<text class="body" x="404" y="{y + 46 + row_index * 18}">{esc(row)}</text>')
        out.append("</g>")
        out.append(f'<path class="detail-edge" d="M306 150 H346 V{y + 46} H378" marker-end="url(#gate-arrow)"/>')

    downstream = [
        (30, "utilities.cmake", "every GAMBIT library gets both flag sets"),
        (110, "executables.cmake", "gambit + standalones link fjcontrib before fastjet"),
        (190, "backends.cmake", "Rivet is ditched when FastJet is excluded"),
    ]
    for y, title, note in downstream:
        out.append(f'<g class="node detail-data"><rect x="796" y="{y}" width="344" height="62" rx="7"/>')
        out.append(f'<text class="title" x="814" y="{y + 26}">{esc(title)}</text>')
        out.append(f'<text class="body" x="814" y="{y + 46}">{esc(note)}</text></g>')
        out.append(f'<path class="detail-edge" d="M716 150 H756 V{y + 31} H788" marker-end="url(#gate-arrow)"/>')

    out.append('<text class="legend-label" x="20" y="286">'
               'the probe branch prints nothing; the first visible symptom is Rivet announcing its own exclusion</text>')
    out.append("</svg>")
    return "\n".join(out)


def unit_cards(units: list[dict]) -> str:
    kind_class = {
        "replaced": "in-place", "removed": "in-place", "expanded": "extracted",
        "revived": "extracted", "added": "extracted",
    }
    cards = []
    for unit in units:
        hunks = render_hunks(unit)
        cards.append(f"""
        <article class="unit" id="unit-{unit["id"]}">
          <header class="unit-head">
            <span class="unit-num">{unit["id"]}</span>
            <span class="unit-title">{esc(unit["title"])}</span>
            <span class="unit-kind {kind_class[unit["kind"]]}">{esc(unit["kind"])}</span>
            <span class="unit-delta">{esc(unit["target"])}</span>
          </header>
          <dl class="unit-grid">
            <div><dt>before</dt><dd>{unit["old"]}</dd></div>
            <div><dt>after</dt><dd>{unit["new"]}</dd></div>
            <div><dt>why</dt><dd>{unit["why"]}</dd></div>
            <div><dt>impact</dt><dd>{unit["impact"]}</dd></div>
          </dl>
          <p class="diagram-note"><strong>Evidence.</strong> {unit["evidence"]}</p>
          {hunks}
        </article>""")
    return "\n".join(cards)


def render_hunks(unit: dict) -> str:
    before, after = unit["before_lines"], unit["after_lines"]
    if not before and not after:
        return ('<p class="unit-nohunk">No line in either version carries this change on its own '
                '&mdash; it is visible only in the full region diff.</p>')
    body = []
    if before:
        body.append('<span class="dh">&#8722;&#8722;&#8722; private-SUSYRun2 &#183; cmake/contrib.cmake</span>')
        for hit in before:
            body.append(f'<span class="dr">{hit["line"]:>5}  {esc(hit["text"])}</span>')
    else:
        body.append('<span class="dh">&#8722;&#8722;&#8722; private-SUSYRun2 &#183; nothing to quote (did not exist)</span>')
    if after:
        body.append('<span class="dh">+++ ColliderBit_solo_development &#183; cmake/contrib.cmake</span>')
        for hit in after:
            body.append(f'<span class="da">{hit["line"]:>5}  {esc(hit["text"])}</span>')
    else:
        body.append('<span class="dh">+++ ColliderBit_solo_development &#183; nothing to quote (removed)</span>')
    total = len(before) + len(after)
    return (f'<details class="unit-diff"><summary>{total} source lines &#183; '
            f'{len(before)} before, {len(after)} after</summary>'
            f'<pre class="unit-hunks">{"".join(body)}</pre></details>')


def unit_rows(units: list[dict]) -> str:
    rows = []
    for unit in units:
        rows.append(
            f'<tr><td><code>{unit["id"]}</code></td>'
            f'<td>{esc(unit["title"])}</td>'
            f'<td><code>{esc(unit["target"])}</code></td>'
            f'<td>{unit["old"]}</td>'
            f'<td>{unit["new"]}</td>'
            f'<td>{unit["impact"]}</td></tr>'
        )
    return "".join(rows)


def lib_rows(data: dict) -> str:
    links = data["links"]
    base = set(links["base_fastjet"]["libs"]) | set(links["base_fjcontrib"]["libs"])
    rows = []
    for group, key in (("FastJet", "head_fastjet"), ("fjcontrib", "head_fjcontrib")):
        for lib in links[key]["libs"]:
            status = ("unchanged" if lib in base else "added-in-right")
            label = "also before" if lib in base else "new"
            present = f"lib{lib}"
            kind = "&mdash;"
            for name in data["provisioning"]["present_libs"]:
                if name.startswith(present + "."):
                    kind = "static archive" if name.endswith(".a") else "shared library"
                    break
            rows.append(
                f'<tr><td>{group}</td><td><code>-l{esc(lib)}</code></td>'
                f'<td><span class="status {status}">{label}</span></td>'
                f'<td>{kind}</td></tr>'
            )
    return "".join(rows)


def jet_user_rows(data: dict) -> str:
    readings = {
        "ColliderBit": "the only GAMBIT module that clusters jets",
        "contrib": "HEPUtils, fjcore and FastJet themselves",
        "cmake": "the build definitions on this page",
    }
    rows = []
    for top, count in sorted(data["fjcore_rationale"]["jet_users"].items(), key=lambda kv: -kv[1]):
        rows.append(
            f'<tr><td><code>{esc(top)}/</code></td><td>{count}</td>'
            f'<td>{readings.get(top, "&mdash;")}</td></tr>'
        )
    return "".join(rows)


def fallback_rows(data: dict) -> str:
    rows = []
    for entry in data["fjcore_rationale"]["fallbacks"]:
        name = Path(entry["path"]).name
        guard = ('<span class="status added-in-right">present</span>' if entry["guard"]
                 else '<span class="status unchanged">none</span>')
        if entry["consistent"]:
            verdict = '<span class="status added-in-right">yes &mdash; FJNS used throughout</span>'
        else:
            verdict = ('<span class="status unchanged">no &mdash; body names <code>fastjet::</code> '
                       'directly, which fjcore does not provide</span>')
        site = (f'<code>{entry["literal_fastjet"]}</code> after line {entry["guard_ends"]}'
                if entry["literal_fastjet"] else "<code>0</code>")
        rows.append(
            f'<tr><td><code>{esc(name)}</code></td><td>{guard}</td>'
            f'<td>{site}</td><td>{verdict}</td></tr>'
        )
    return "".join(rows)


def consumer_rows(data: dict) -> str:
    return "".join(
        f'<tr><td><code>{esc(c["path"])}:{c["line"]}</code></td>'
        f'<td><code>{esc(c["text"])}</code></td></tr>'
        for c in data["consumers"]
    )


def symbol_rows(data: dict) -> str:
    rows = []
    for symbol, info in data["symbols"].items():
        analyses = [f for f in info["files"] if "/analyses/" in f]
        others = [f for f in info["files"] if "/analyses/" not in f]
        includes = "<br>".join(f"<code>{esc(line)}</code>" for line in info["includes"]) or "&mdash;"
        rows.append(
            f'<tr><td><code>{esc(symbol)}</code></td>'
            f'<td>{len(analyses)}</td>'
            f'<td>{"<br>".join(f"<code>{esc(Path(f).name)}</code>" for f in others) or "&mdash;"}</td>'
            f'<td>{includes}</td></tr>'
        )
    return "".join(rows)


def commit_rows(data: dict) -> str:
    return "".join(
        f'<tr><td><code>{esc(c["sha"])}</code></td><td>{esc(c["date"])}</td>'
        f'<td>{esc(c["author"])}</td><td>{esc(c["subject"])}</td></tr>'
        for c in data["commits"]
    )


def render_markdown(data: dict, units: list[dict]) -> str:
    links = data["links"]
    lines = [
        "# FastJet and fjcontrib build integration",
        "",
        f'Refs: master `{data["refs"]["master"]}` &middot; baseline `{data["refs"]["baseline"]}` '
        f'&middot; head `{data["refs"]["head"]}`',
        "",
        "Three-way, because two-way hides that the development branch restores upstream",
        "`master`'s fjcore path rather than inventing a new one.",
        "",
        "| | master | SUSYRun2 | solo_development |",
        "|---|---|---|---|",
        "| FastJet | absent | downloaded + built | detected if present |",
        "| fjcontrib | absent | built, 1 library | detected, 4 libraries |",
        "| fjcore | always | commented out | always, namespace switched |",
        "",
        "## Why fjcore is still here",
        "",
        "Not because another module needs it. Counting every file that names a jet type",
        "(`PseudoJet`, `ClusterSequence` or `FJNS`):",
        "",
        "| Directory | Files |",
        "|---|---:|",
    ]
    for top, count in sorted(data["fjcore_rationale"]["jet_users"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{top}/` | {count} |")

    fallbacks = data["fjcore_rationale"]["fallbacks"]
    consistent = sum(1 for f in fallbacks if f["consistent"])
    lines += [
        "",
        "No GAMBIT module outside ColliderBit clusters jets at all. fjcore stays because",
        "it is upstream `master`'s only jet backend, because it is the floor when FastJet",
        "is not provisioned, and because it costs almost nothing to keep: `fjcore.hh:"
        f'{data["fjcore_rationale"]["namespace"]["line"]}` hard-codes `namespace gambit {{ namespace fjcore {{`,',
        "disjoint from `fastjet`, so both compile into one binary.",
        "",
        f"The remaining fjcore references are inside ColliderBit: {len(fallbacks)} analyses carry an",
        f"`#ifndef FJCORE` branch, of which {consistent} is self-consistent. The other",
        f"{len(fallbacks) - consistent} mix `FJNS::` with literal `fastjet::` in one jet-trimming idiom.",
        "",
        "## Numbered changes",
        "",
        "| # | Change | Target |",
        "|---:|---|---|",
    ]
    for unit in units:
        lines.append(f'| {unit["id"]} | {unit["title"]} | `{unit["target"]}` |')

    lines += [
        "",
        "## Link surfaces",
        "",
        f'FastJet before: `{" ".join("-l" + l for l in links["base_fastjet"]["libs"])}`',
        "",
        f'FastJet after: `{" ".join("-l" + l for l in links["head_fastjet"]["libs"])}`',
        "",
        f'fjcontrib before: `{" ".join("-l" + l for l in links["base_fjcontrib"]["libs"])}`',
        "",
        f'fjcontrib after: `{" ".join("-l" + l for l in links["head_fjcontrib"]["libs"])}`',
        "",
        "## Provisioning",
        "",
        f'Tracked files: fastjet {data["provisioning"]["tracked"]["fastjet"]}, '
        f'fjcontrib {data["provisioning"]["tracked"]["fjcontrib"]}, '
        f'fjcore {data["provisioning"]["tracked"]["fjcore"]}.',
        "",
        "Neither FastJet nor fjcontrib is tracked, and CMake no longer downloads them.",
        "On a fresh clone the probe fails, fjcore takes over silently and Rivet is ditched.",
        "",
        "No build was run to produce this document.",
        "",
    ]
    return "\n".join(lines)


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FastJet &amp; fjcontrib build integration</title>
  <style>
    :root { --paper:#f5f5f5; --paper-2:#ececec; --ink:#2d3142; --muted:#4f5d75; --soft:#7a8399; --rule:rgba(45,49,66,.12); --accent:#eb6c36; --accent-tint:rgba(235,108,54,.08); --green:#4f8a69; --green-tint:#eef8f1; --red:#93513f; --red-tint:#f3e9e5; --font-sans:'Geist',system-ui,sans-serif; --font-mono:'Geist Mono',ui-monospace,monospace; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 var(--font-sans); }
    .frame { max-width:1520px; margin:0 auto; padding:42px 42px 64px; }
    .eyebrow,.kicker,.meta,.source,.status,th,footer,.tag { font-family:var(--font-mono); }
    .eyebrow { color:var(--muted); font-size:12px; letter-spacing:.16em; text-transform:uppercase; margin:0 0 12px; }
    h1 { font-family:'Instrument Serif',Georgia,serif; font-size:clamp(42px,5vw,72px); font-weight:400; letter-spacing:-.04em; line-height:.98; margin:0 0 14px; }
    h2 { font-size:28px; font-weight:600; letter-spacing:-.03em; line-height:1.08; margin:0 0 8px; }
    p { color:var(--muted); }
    .intro { max-width:1080px; font-size:17px; line-height:1.65; margin:0 0 18px; }
    .meta { display:flex; flex-wrap:wrap; gap:8px 18px; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); padding:12px 0; color:var(--muted); font-size:12px; }
    .meta strong { color:var(--accent); font-weight:600; }
    .note { border-left:3px solid var(--accent); color:var(--muted); font-size:13px; line-height:1.6; margin:18px 0; max-width:1160px; padding:8px 12px; }
    .backlink { align-items:baseline; background:#fff; border:1px solid var(--rule); border-left:3px solid var(--accent);
      border-radius:0 6px 6px 0; color:var(--muted); display:flex; flex-wrap:wrap; font-size:14.5px; gap:4px 12px;
      line-height:1.6; margin:18px 0 0; max-width:1160px; padding:11px 14px; }
    .backlink .lbl { color:var(--soft); font-family:var(--font-mono); font-size:11.5px; letter-spacing:.14em; text-transform:uppercase; }
    .backlink span:last-child { flex:1 1 420px; }
    .backlink a { border-bottom:1px solid rgba(235,108,54,.42); color:var(--accent); font-weight:600; text-decoration:none; }
    .backlink a:hover { background:var(--accent-tint); }
    .summary-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:22px 0 32px; }
    .card { background:#fff; border:1px solid var(--rule); border-radius:6px; padding:14px 16px; }
    .card.accent { border-color:rgba(235,108,54,.45); background:var(--accent-tint); }
    .card .n { color:var(--ink); display:block; font-size:28px; font-weight:600; letter-spacing:-.04em; line-height:1; margin-bottom:8px; }
    .card .label { color:var(--soft); font-family:var(--font-mono); font-size:11px; letter-spacing:.1em; text-transform:uppercase; }
    section { border-top:1px solid var(--rule); margin-top:28px; padding:24px 0 0; }
    .kicker { color:var(--soft); font-size:11px; letter-spacing:.16em; margin:0 0 8px; text-transform:uppercase; }
    .source { color:var(--soft); font-size:12px; line-height:1.55; margin:0 0 14px; }
    .diagram-shell { overflow-x:auto; background:#fff; border:1px solid var(--rule); border-radius:8px; padding:8px; }
    svg { display:block; min-width:1080px; width:100%; height:auto; }
    svg .zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .zone-label { fill:var(--soft); font:500 12px var(--font-mono); letter-spacing:1.6px; }
    svg .node .kind { fill:var(--soft); font:500 11px var(--font-mono); letter-spacing:1.2px; }
    svg .node .title { fill:var(--ink); font:600 15px var(--font-mono); }
    svg .node .body { fill:var(--muted); font:11.5px var(--font-mono); }
    svg .legend-label { fill:var(--soft); font:11px var(--font-mono); letter-spacing:.6px; }
    svg .detail-edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
    svg .node.detail-primary rect { fill:#fff; stroke:var(--soft); stroke-width:1.2; }
    svg .node.detail-data rect { fill:rgba(79,93,117,.08); stroke:var(--soft); stroke-width:1.2; }
    svg .node.detail-mod rect { fill:#fff0e8; stroke:#b55c2d; stroke-width:1.2; }
    svg .node.detail-mod .kind { fill:#b55c2d; }
    svg .node.detail-optional rect { fill:#fff; stroke:var(--soft); stroke-width:1.2; stroke-dasharray:5 4; }
    svg .node.detail-focal rect { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    svg .node.detail-focal .kind { fill:var(--accent); }
    .unit-list { display:grid; gap:14px; margin-top:18px; }
    .unit { border:1px solid var(--rule); border-radius:8px; background:#fff; padding:16px 18px; scroll-margin-top:20px; }
    .unit:target { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
    .unit-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
    .unit-num { display:grid; place-items:center; width:26px; height:26px; border-radius:50%;
      border:1.2px solid var(--ink); font:600 15px var(--font-mono); }
    .unit-title { font-size:18px; font-weight:600; letter-spacing:-.01em; }
    .unit-kind { padding:2px 7px; border-radius:3px; border:1px solid currentColor;
      font:10px var(--font-mono); letter-spacing:.9px; text-transform:uppercase; }
    .unit-kind.extracted { color:#4f8a69; background:var(--green-tint); }
    .unit-kind.in-place { color:#b55c2d; background:#fff0e8; }
    .unit-delta { margin-left:auto; font:13px var(--font-mono); color:var(--soft); }
    .unit-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px 24px; margin:0; }
    .unit-grid > div { display:flex; gap:10px; border-bottom:1px solid var(--rule); padding-bottom:8px; }
    .unit-grid dt { flex:0 0 62px; margin:2px 0 0; color:var(--soft);
      font:11px var(--font-mono); letter-spacing:1px; text-transform:uppercase; }
    .unit-grid dd { margin:0; color:var(--muted); font-size:14.5px; line-height:1.6; }
    .unit-diff { margin-top:11px; border:1px solid var(--rule); border-radius:6px; background:#fff; }
    .unit-diff summary { cursor:pointer; padding:9px 13px; color:var(--accent);
      font:13px var(--font-mono); letter-spacing:.4px; list-style:none; }
    .unit-diff summary::-webkit-details-marker { display:none; }
    .unit-diff summary::before { content:"\25b8 "; display:inline-block; width:14px; }
    .unit-diff[open] summary::before { content:"\25be "; }
    .unit-diff[open] summary { border-bottom:1px solid var(--rule); }
    .unit-diff summary:hover { background:rgba(235,108,54,.05); }
    .unit-hunks { margin:0; padding:12px 0; overflow-x:auto; font:13px/1.65 var(--font-mono); background:#fff; border:0; }
    .unit-hunks span { display:block; padding:0 13px; white-space:pre; }
    .unit-hunks .dh { color:var(--accent); background:rgba(235,108,54,.06); margin:6px 0 4px; padding:3px 13px; }
    .unit-hunks .da { color:#2f6b4a; background:rgba(79,138,105,.09); }
    .unit-hunks .dr { color:#8c3a30; background:rgba(164,68,58,.08); }
    .unit-hunks .dc { color:var(--soft); }
    .unit-nohunk { margin:11px 0 0; padding:10px 13px; border-radius:6px;
      background:rgba(45,49,66,.035); color:var(--muted); font-size:14px; line-height:1.6; }
    .diagram-note { color:var(--muted); font-size:14px; line-height:1.6; margin:13px 0 0; max-width:1160px; }
    .mapping-table { overflow-x:auto; border:1px solid var(--rule); }
    .mapping-table table { min-width:960px; }
    table { border-collapse:collapse; font-size:13px; width:100%; }
    th,td { border-bottom:1px solid var(--rule); padding:8px 9px; text-align:left; vertical-align:top; }
    th { background:#ececec; color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }
    td code { color:var(--ink); font-family:var(--font-mono); font-size:12px; word-break:break-word; }
    .status { font-size:11px; font-weight:600; letter-spacing:.04em; white-space:nowrap; }
    .status.added-in-right { color:var(--green); } .status.unchanged { color:var(--soft); }
    details.full { border-top:1px solid var(--rule); margin-top:16px; }
    details.full summary { cursor:pointer; color:var(--ink); font:13px var(--font-mono); padding:12px 0; }
    pre.full { background:#fff; border:1px solid var(--rule); color:var(--ink); font:12px/1.45 var(--font-mono); margin:0; max-height:720px; overflow:auto; padding:16px; white-space:pre; }
    footer { border-top:1px solid var(--rule); color:var(--soft); font-size:12px; margin-top:32px; padding-top:14px; }
    @media (max-width:900px) { .frame { padding:30px 20px 48px; } .summary-grid { grid-template-columns:repeat(2,1fr); } .unit-grid { grid-template-columns:1fr; } }
    @media (max-width:560px) { h1 { font-size:44px; } }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit Solo &#183; contrib build integration</p>
  <h1>FastJet &amp; fjcontrib</h1>
  <p class="intro">What changed in how the build obtains, links and selects the jet-clustering stack &mdash; and why that is a three-way comparison rather than a two-way one. Upstream <code>master</code> ships fjcore only; the <code>private-SUSYRun2</code> source branch replaced it with a downloaded FastJet; this branch keeps both and decides at configure time.</p>
  <div class="meta"><span><strong>MASTER</strong> __MASTER_REF__</span><span><strong>BASELINE</strong> __BASELINE_REF__</span><span><strong>HEAD</strong> __HEAD_REF__</span><span><strong>FILE</strong> cmake/contrib.cmake</span><span><strong>STATIC EVIDENCE</strong> no build attempted</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page is the build-system half of <a href="cbs-change-ledger.html#11">slide 9 of the CBS change-ledger deck &#8599;</a> &mdash; <em>Variable-R jets, threaded end to end</em>. That slide follows a VR jet through the physics; this one explains what had to change in CMake before <code>-lVariableR</code> could exist.</span></p>
  <div class="summary-grid" aria-label="Change summary">
    <div class="card accent"><span class="n">__UNIT_COUNT__</span><span class="label">numbered changes</span></div>
    <div class="card"><span class="n">__FJ_BEFORE__ &#8594; __FJ_AFTER__</span><span class="label">FastJet libraries</span></div>
    <div class="card accent"><span class="n">__FJC_BEFORE__ &#8594; __FJC_AFTER__</span><span class="label">fjcontrib libraries</span></div>
    <div class="card"><span class="n">__CONSUMER_COUNT__</span><span class="label">flag consumption sites</span></div>
    <div class="card"><span class="n">__COMMIT_COUNT__</span><span class="label">commits on this file</span></div>
  </div>
  <div class="note">Every line number, link flag, gate condition and diff hunk below is extracted from the two worktrees when this page is generated. Nothing was compiled or linked to produce it: the page describes what the build system is configured to do, not what a compiler reported.</div>

  <section>
    <p class="kicker">01 &#183; three states</p>
    <h2>fjcore, then FastJet, then both</h2>
    <p class="source">Comparing only against the source branch would make the fjcore fallback look like an invention. It is a restoration &mdash; of exactly what upstream <code>master</code> still does.</p>
    <div class="diagram-shell">
      __THREE_WAY__
    </div>
    <p class="diagram-note">The source branch's own comment said why it had to choose: <em>"Temporarily comment while fastjet is a contrib, as there are class name clashes."</em> The two libraries could not coexist under one namespace, so one had to go. Routing every use through the <code>FJNS</code> macro is what makes keeping both possible.</p>
  </section>

  <section>
    <p class="kicker">02 &#183; the obvious question</p>
    <h2>Why fjcore is still here</h2>
    <p class="source">Keeping a second jet-clustering library costs compile time and one more thing to reason about. Three reasons it stays, and one common explanation that the tree does not support.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:22%">Reason</th><th style="width:34%">Evidence</th><th>What it buys</th></tr></thead>
      <tbody>
        <tr>
          <td><strong>It is upstream's only jet backend</strong></td>
          <td><code>gambit/master</code> has no FastJet in <code>cmake/contrib.cmake</code> at all &mdash; fjcore, unconditional, <code>-DFJCORE -DFJNS=gambit::fjcore</code>.</td>
          <td>A configuration that matches upstream still works here. Dropping fjcore would have made this branch unable to build the way master builds.</td>
        </tr>
        <tr>
          <td><strong>It is the no-FastJet floor</strong></td>
          <td>The <code>else()</code> branch of the probe, which is now reachable in normal use because CMake no longer downloads FastJet.</td>
          <td>GAMBIT still configures and compiles on a machine that has not provisioned FastJet. This matters <em>more</em> after change 2, not less.</td>
        </tr>
        <tr>
          <td><strong>Coexisting is nearly free</strong></td>
          <td><code>fjcore.hh:__FJCORE_NS_LINE__</code> &mdash; <code>__FJCORE_NS_TEXT__</code></td>
          <td>fjcore lives in <code>gambit::fjcore</code>, FastJet in <code>fastjet</code>. The namespaces are disjoint by construction, so both can be compiled into one binary.</td>
        </tr>
      </tbody>
    </table></div>
    <p class="diagram-note">That last row is what makes the whole arrangement possible, and it also explains the source branch's comment &mdash; <em>"Temporarily comment while fastjet is a contrib, as there are class name clashes"</em>. The clash was never between the definitions; it was between <em>unqualified uses</em> of <code>PseudoJet</code> and <code>ClusterSequence</code>, which exist in both namespaces. Routing every use through <code>FJNS</code> makes each one qualified, and the clash disappears.</p>
    <p class="diagram-note">fjcore is compiled and linked whether or not FastJet was found: <code>contrib.cmake:__FJCORE_LINK_LINE__</code> puts it in <code>GAMBIT_BASIC_COMMON_OBJECTS</code>, which every GAMBIT executable links. So the cost is paid on every build; only the namespace choice is conditional.</p>

    <p class="diagram-note" style="margin-top:20px"><strong>The explanation that does not hold up: "other modules still need fjcore".</strong> Counting every file that names a jet type at all &mdash; <code>PseudoJet</code>, <code>ClusterSequence</code> or <code>FJNS</code> &mdash; gives this:</p>
    <div class="mapping-table" style="margin-top:10px"><table>
      <thead><tr><th style="width:22%">Top-level directory</th><th style="width:14%">Files</th><th>Reading</th></tr></thead>
      <tbody>__JET_USER_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">No GAMBIT module outside ColliderBit touches jets. Nothing in <code>DarkBit</code>, <code>SpecBit</code>, <code>FlavBit</code>, <code>Elements</code>, <code>Backends</code> or <code>Printers</code> depends on fjcore, on FastJet, or on either through HEPUtils. fjcore does not survive because something else needs it.</p>

    <p class="diagram-note" style="margin-top:20px"><strong>And the direction of the migration is the reverse of what one would expect.</strong> The only non-contrib code in the tree that names fjcore is inside ColliderBit &mdash; __FALLBACK_COUNT__ analyses, each carrying an <code>#ifndef FJCORE</code> include branch. ColliderBit is where the fjcore references live, not where they were removed from.</p>
    <div class="mapping-table" style="margin-top:10px"><table>
      <thead><tr><th style="width:34%">Analysis</th><th style="width:12%">Guard</th><th style="width:22%">Literal <code>fastjet::</code> outside the guard</th><th>Would the fallback branch actually build?</th></tr></thead>
      <tbody>__FALLBACK_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>__CONSISTENT_COUNT__ of __FALLBACK_COUNT__ fallback branches are self-consistent.</strong> The count above excludes anything inside the guard's own <code>#ifndef</code> arm, where naming <code>fastjet::</code> is correct; it counts only unconditional uses after the guard closes.</p>
    <p class="diagram-note"><strong>All __INCONSISTENT_COUNT__ failures are the same copy-pasted line, not __INCONSISTENT_COUNT__ separate problems.</strong> Every one of them is a jet-trimming call that mixes the macro with the literal namespace in a single expression:</p>
    <pre class="unit-code">__TRIM_IDIOM__</pre>
    <p class="diagram-note">Under <code>-DFJCORE</code>, <code>FJNS</code> becomes <code>gambit::fjcore</code> while the three <code>fastjet::</code> qualifiers stay literal &mdash; and that namespace no longer exists in the translation unit. <code>Analysis_ATLAS_SUSY_2018_30.cpp</code> is the one written correctly, routing every type through <code>FJNS::</code> including <code>JetDefinition</code>, <code>antikt_algorithm</code> and <code>ClusterSequence</code>. It is the template worth copying: one idiom to fix in __INCONSISTENT_COUNT__ files, not a rewrite.</p>
    <p class="diagram-note">Read from source; no build was attempted. The claim here is about what the preprocessor would produce, not about a compiler diagnostic anyone has seen.</p>
  </section>

  <section>
    <p class="kicker">03 &#183; numbered changes</p>
    <h2>Eight changes, and what each one costs</h2>
    <p class="source">One row per change, then one card each with the before/after, the reason, the consequence and the diff hunks that carry it.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:3%">#</th><th style="width:12%">Change</th><th style="width:15%">Target</th><th style="width:22%">Before</th><th style="width:22%">After</th><th>Impact</th></tr></thead>
      <tbody>__UNIT_ROWS__</tbody>
    </table></div>
    <div class="unit-list">
      __UNIT_CARDS__
    </div>
    <p class="diagram-note">__HUNK_COVERAGE__</p>
  </section>

  <section>
    <p class="kicker">04 &#183; the decision</p>
    <h2>One probe, three consequences</h2>
    <p class="source">The <code>EXISTS</code> test sets three variables, and those fan out to the link flags, the fjcore namespace and whether Rivet is built at all.</p>
    <div class="diagram-shell">
      __GATE__
    </div>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:14%">Group</th><th style="width:24%">Flag</th><th style="width:14%">Status</th><th>Form on the machine that generated this page</th></tr></thead>
      <tbody>__LIB_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">Nine libraries where the source branch linked three. <code>fastjetplugins</code> and the two SISCone libraries are not optional extras: VariableR is implemented as a FastJet plugin, so the plugin machinery comes with it.</p>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:26%">Site</th><th>Source</th></tr></thead>
      <tbody>__CONSUMER_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>The two consumption sites disagree on link order.</strong> <code>executables.cmake</code> appends fjcontrib before FastJet; <code>utilities.cmake</code> appends FastJet before fjcontrib. With static archives &mdash; and <code>libRecursiveTools.a</code>, <code>libEnergyCorrelator.a</code> and <code>libVariableR.a</code> are static on this machine &mdash; a left-to-right resolver such as GNU <code>ld</code> wants the dependent archive first. It is not observed to fail here; macOS <code>ld64</code> does not require that order, and <code>libfastjetcontribfragile</code> is a shared object that may resolve the symbols anyway. Flagged because the two sites disagree, which is a difference no one chose.</p>
  </section>

  <section>
    <p class="kicker">05 &#183; who needs it</p>
    <h2>What actually uses the new libraries</h2>
    <p class="source">Extracted by searching ColliderBit for each algorithm. The include column shows the spellings that justify carrying two include roots.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:12%">Algorithm</th><th style="width:8%">Analyses</th><th style="width:20%">Also used in</th><th>Include lines found in ColliderBit</th></tr></thead>
      <tbody>__SYMBOL_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">Two spellings appear for the same kind of header: <code>#include "fastjet/contrib/Nsubjettiness.hh"</code> and a bare <code>#include "SoftDrop.hh"</code>. Change 7 adds both include roots so each resolves; that is the whole reason the second <code>include_directories</code> line exists.</p>
  </section>

  <section>
    <p class="kicker">06 &#183; the gap</p>
    <h2>Nothing in this repository provides FastJet any more</h2>
    <p class="source">The download step was removed. The ignore rules that made sense while CMake downloaded the tarballs are still in place.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:34%">Fact</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>Files tracked under <code>contrib/fastjet-3.4.2</code></td><td><code>__TRACKED_FASTJET__</code></td></tr>
        <tr><td>Files tracked under <code>contrib/fjcontrib-1.049</code></td><td><code>__TRACKED_FJCONTRIB__</code></td></tr>
        <tr><td>Files tracked under <code>contrib/fjcore-3.2.0</code></td><td><code>__TRACKED_FJCORE__</code></td></tr>
        <tr><td>Ignore rules still present</td><td>__IGNORE_RULES__</td></tr>
        <tr><td>Libraries present on the machine that generated this page</td><td>__PRESENT_LIBS__</td></tr>
      </tbody>
    </table></div>
    <p class="diagram-note"><strong>On a fresh clone the probe fails and the build keeps going.</strong> The <code>else()</code> branch sets the three exclusion variables and prints nothing &mdash; the old code printed a message on its exclusion path, this one does not. The first visible symptom is Rivet announcing <em>its</em> exclusion, which names FastJet but reads like a Rivet problem. A collaborator who wants what this branch does has to provision <code>contrib/fastjet-3.4.2/local</code> themselves; that step now lives in neither the build system nor the repository.</p>
    <p class="diagram-note"><strong>The fallback is a build fallback, not an analysis fallback.</strong> Of the analyses that use these algorithms, __GUARDED_COUNT__ carry an <code>#ifndef FJCORE</code> include guard and __UNGUARDED_COUNT__ carry none. Even the guarded ones only switch their <em>includes</em>: <code>Analysis_ATLAS_EXOT_2016_014.cpp</code> still writes <code>FJNS::contrib::EnergyCorrelator</code> in the body, and fjcore has no <code>contrib</code> namespace to provide it. Read from source, not from a compiler &mdash; no build was attempted &mdash; but the guard does not appear sufficient.</p>
    <p class="diagram-note">Adjacent work by another author points at the same problem from the other side: <code>cmake/scripts/copy_tarballs.sh</code> and <code>restore_tarballs.sh</code> (ChrisJChang, 2025-12) collect downloaded tarballs into one folder and put them back, and <code>safe_dl.sh</code> gained a project-source-directory argument to support it. That is a caching mechanism for things CMake still downloads &mdash; it does not cover FastJet, which CMake no longer downloads at all.</p>
  </section>

  <section>
    <p class="kicker">07 &#183; history</p>
    <h2>How it got here</h2>
    <p class="source">Commits that changed a FastJet-related line in <code>cmake/contrib.cmake</code> since the source branch diverged.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:10%">Commit</th><th style="width:10%">Date</th><th style="width:16%">Author</th><th>Subject</th></tr></thead>
      <tbody>__COMMIT_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The build-integration work in this file is local: the FastJet and fjcontrib restructuring is authored on this branch, not merged in from upstream. The tarball-caching scripts mentioned in section 05 are the opposite &mdash; upstream work by another author, included here only because it touches the same download machinery.</p>
  </section>

  <section>
    <p class="kicker">08 &#183; exact evidence</p>
    <h2>Region diff</h2>
    <p class="source">The jet-clustering region of <code>cmake/contrib.cmake</code>, source branch to this branch. Numbered cards above quote from this diff.</p>
    <details class="full" open><summary>__DIFF_SUMMARY__</summary><pre class="full">__DIFF__</pre></details>
    <p class="diagram-note"><strong>Boundary.</strong> This page reads CMake, shell and C++ source. It does not report a build: no <code>cmake</code> was run and no compiler or linker was invoked for it. Statements about what would happen on a fresh clone are read off the conditionals, and the link-order note is explicitly marked as unobserved.</p>
  </section>

  <p class="backlink"><span class="lbl">return</span><span>Back to <a href="cbs-change-ledger.html#11">the change-ledger deck &#183; slide 9 &#8599;</a>, or across to the <a href="cbs-json-output.html">JSON output contract &#8599;</a> and the <a href="cbs-solo-comparison.html">focused solo.cpp comparison &#8599;</a>.</span></p>

  <footer>Generated by <code>scripts/build-fastjet-cmake-page.py</code>. master <code>__MASTER_REF__</code> &#183; baseline <code>__BASELINE_REF__</code> &#183; head <code>__HEAD_REF__</code>.</footer>
</main>
</body>
</html>'''


def render_html(data: dict, units: list[dict], diff: str, coverage: str) -> str:
    links = data["links"]
    prov = data["provisioning"]
    page = TEMPLATE
    replacements = {
        "__MASTER_REF__": esc(data["refs"]["master"]),
        "__BASELINE_REF__": esc(data["refs"]["baseline"]),
        "__HEAD_REF__": esc(data["refs"]["head"]),
        "__UNIT_COUNT__": str(len(units)),
        "__FJ_BEFORE__": str(len(links["base_fastjet"]["libs"])),
        "__FJ_AFTER__": str(len(links["head_fastjet"]["libs"])),
        "__FJC_BEFORE__": str(len(links["base_fjcontrib"]["libs"])),
        "__FJC_AFTER__": str(len(links["head_fjcontrib"]["libs"])),
        "__CONSUMER_COUNT__": str(len(data["consumers"])),
        "__COMMIT_COUNT__": str(len(data["commits"])),
        "__THREE_WAY__": three_way_svg(data),
        "__GATE__": gate_svg(data),
        "__UNIT_ROWS__": unit_rows(units),
        "__UNIT_CARDS__": unit_cards(units),
        "__HUNK_COVERAGE__": coverage,
        "__CONSUMER_ROWS__": consumer_rows(data),
        "__JET_USER_ROWS__": jet_user_rows(data),
        "__FALLBACK_ROWS__": fallback_rows(data),
        "__FALLBACK_COUNT__": str(len(data["fjcore_rationale"]["fallbacks"])),
        "__CONSISTENT_COUNT__": str(sum(1 for f in data["fjcore_rationale"]["fallbacks"] if f["consistent"])),
        "__INCONSISTENT_COUNT__": str(sum(1 for f in data["fjcore_rationale"]["fallbacks"] if not f["consistent"])),
        "__TRIM_IDIOM__": esc("\n".join(
            f'{Path(f["path"]).name}:{f["first_hit"]["line"]}\n    {f["first_hit"]["text"]}'
            for f in data["fjcore_rationale"]["fallbacks"] if f["first_hit"]
        )),
        "__FJCORE_NS_LINE__": str(data["fjcore_rationale"]["namespace"]["line"]),
        "__FJCORE_NS_TEXT__": esc(data["fjcore_rationale"]["namespace"]["text"]),
        "__FJCORE_LINK_LINE__": str(data["fjcore_rationale"]["always_linked"]["line"]),
        "__COMMIT_ROWS__": commit_rows(data),
        "__SYMBOL_ROWS__": symbol_rows(data),
        "__LIB_ROWS__": lib_rows(data),
        "__TRACKED_FASTJET__": str(prov["tracked"]["fastjet"]),
        "__TRACKED_FJCONTRIB__": str(prov["tracked"]["fjcontrib"]),
        "__TRACKED_FJCORE__": str(prov["tracked"]["fjcore"]),
        "__IGNORE_RULES__": " &middot; ".join(
            f'<code>{esc(rule["text"])}</code> (.gitignore:{rule["line"]})'
            for rule in prov["gitignore"]
        ) or "&mdash;",
        "__PRESENT_LIBS__": (
            f'{len(prov["present_libs"])} files, including '
            + ", ".join(f"<code>{esc(n)}</code>" for n in prov["present_libs"][:4])
            + " &mdash; present because this machine built them, not because the repository carries them"
        ) if prov["present_libs"] else "none &mdash; FastJet is not provisioned here",
        "__GUARDED_COUNT__": str(len(data["guards"]["guarded"])),
        "__UNGUARDED_COUNT__": str(len(data["guards"]["unguarded"])),
        "__DIFF_SUMMARY__": esc(
            f'cmake/contrib.cmake jet-clustering region '
            f'({data["region"]["base"]["hi"] - data["region"]["base"]["lo"] + 1} lines before, '
            f'{data["region"]["head"]["hi"] - data["region"]["head"]["lo"] + 1} after)'
        ),
        "__DIFF__": esc(diff),
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path,
                        default=Path("/Users/p.zhu/Gambit-Workshop/gambit"))
    parser.add_argument("--baseline-ref", default="9c955e3a7",
                        help="merge base with private-SUSYRun2")
    parser.add_argument("--master-ref", default="gambit/master")
    parser.add_argument("--html", type=Path, default=Path("dependences/cbs-fastjet-cmake.html"))
    parser.add_argument("--json", type=Path, default=Path("dependences/cbs-fastjet-cmake.json"))
    parser.add_argument("--markdown", type=Path, default=Path("dependences/CBS_FASTJET_CMAKE.md"))
    parser.add_argument("--site-html", type=Path, default=Path("site/cbs-fastjet-cmake.html"))
    args = parser.parse_args()

    root = args.gambit_root.expanduser().resolve()
    data = collect(root, args.baseline_ref, args.master_ref)
    units = change_units(data)

    diff = region_diff(data)
    attach_excerpts(units, data)
    covered = sum(1 for u in units if u["before_lines"] or u["after_lines"])
    coverage = (
        f"<strong>{covered} of {len(units)} changes quote source lines directly.</strong> "
        "The expanders show before and after rather than a diff hunk, because this region "
        "was rewritten rather than edited: a unified diff of it is one hunk covering "
        "everything, which separates nothing. The whole-region diff is still in section 08."
    )

    page = render_html(data, units, diff, coverage)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(page)
    args.site_html.parent.mkdir(parents=True, exist_ok=True)
    args.site_html.write_text(page)
    serialisable = json.loads(json.dumps(data, default=str))
    serialisable["units"] = units
    serialisable["excerpt_coverage"] = {"covered": covered, "total": len(units)}
    args.json.write_text(json.dumps(serialisable, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(render_markdown(data, units))

    print(json.dumps({
        "units": len(units),
        "units_with_excerpts": covered,
        "fastjet_libs": f'{len(data["links"]["base_fastjet"]["libs"])} -> {len(data["links"]["head_fastjet"]["libs"])}',
        "fjcontrib_libs": f'{len(data["links"]["base_fjcontrib"]["libs"])} -> {len(data["links"]["head_fjcontrib"]["libs"])}',
        "consumers": len(data["consumers"]),
        "commits": len(data["commits"]),
    }, sort_keys=True))
    for path in (args.json, args.html, args.markdown, args.site_html):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
