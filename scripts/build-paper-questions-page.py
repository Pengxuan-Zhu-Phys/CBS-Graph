#!/usr/bin/env python3
"""Render the open-questions page for the CBS paper.

Every other page in this project documents what CBS *does*. This one collects
what nobody has written down yet: the questions a reader of the paper would
ask, that the source cannot answer on its own.

The split matters, so it is stated on the page too:

  the questions   ours -- editorial judgement about what a paper owes a reader
  the evidence    read from the tree and from the other pages' generated JSON
                  at build time, never typed in

That means a question can outlive its evidence. If a number here disagrees
with the source, the source is right and this page is stale -- rerun it.

Nothing is built or run.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

MASTER = "gambit/master"
BASE = "9c955e3a78"
SR2 = "5989e2d27a"

NEW_ANALYSES = [
    "ATLAS_EXOT_2016_013", "ATLAS_EXOT_2016_017", "ATLAS_EXOT_2018_60",
    "ATLAS_EXOT_2019_04", "ATLAS_EXOT_2019_07", "ATLAS_EXOT_2021_35",
    "ATLAS_SUSY_2018_07", "ATLAS_SUSY_2018_12", "ATLAS_SUSY_2018_41",
    "ATLAS_SUSY_2019_09", "CMS_B2G_18_003", "CMS_SUS_16_039",
]

# Capabilities that exist in CBS and not in released GAMBIT. Checked across all
# four refs because *where* they entered decides whether the deck should have
# mentioned them -- see question 10.
FEATURES = ["ONNX", "BDT", "METSignificance", "FullLikes"]

CAVEAT_RE = re.compile(
    r"TODO|FIXME|not validated|still in progress|approximation|pending",
    re.IGNORECASE)

# A file usually carries several markers and they are not equally informative:
# a commented-out `#include` with a TODO on it says far less than the author
# writing "Not validated". Markers are ranked so the strongest one represents
# the file, rather than whichever happens to appear first.
STRONG_RE = re.compile(
    r"not validated|still in progress|approximation|are still TODO|"
    r"Implement the published", re.IGNORECASE)

SEVERITY = {
    "numbers": ("changes published numbers", "sev-num"),
    "rerun": ("blocks an independent rerun", "sev-run"),
    "decision": ("needs a decision, not text", "sev-dec"),
    "text": ("needs a paragraph", "sev-txt"),
}

GROUPS = [
    ("results", "What the numbers depend on",
     "Settings and modelling choices that move the yields. If the paper does "
     "not pin these down, two people running the same input file get two "
     "different likelihoods and neither is wrong."),
    ("reproducibility", "What a reader needs to rerun it",
     "A reader with the repository and the paper should be able to reproduce a "
     "run. Each of these is something they would need and cannot currently get "
     "from either."),
    ("compatibility", "What existing users walk into",
     "CBS is not a new tool for new users only. Anyone with a working GAMBIT "
     "ColliderBit setup has files that CBS will now reject, and the paper is "
     "where they will look first."),
    ("interface", "What downstream code may rely on",
     "The JSON output is already being consumed by scripts. The paper decides "
     "whether that is a promise or an accident."),
    ("distribution", "How anyone gets it at all",
     "Covered at length on slide 14. Restated here because a paper with no "
     "followable installation route is a paper nobody reproduces."),
    ("scope", "What the paper is even about",
     "The one question that has to be answered first, because it silently "
     "sets the answer to several of the others."),
]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def grep_files(root: Path, ref: str, term: str, path: str) -> int:
    out = git(root, "grep", "-il", term, ref, "--", path)
    return len([line for line in out.splitlines() if line.strip()])


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


# ---------------------------------------------------------------- evidence


def load_pages(out_dir: Path) -> dict:
    """The generated JSON behind each of the other pages.

    Reading these rather than re-deriving keeps one definition of every count:
    if the histogram page and this page ever disagree, it is a bug in one
    script, not a difference of opinion.
    """
    wanted = {
        "yaml": "cbs-yaml-config.json",
        "hist": "cbs-histograms.json",
        "rename": "cbs-rename-migration.json",
        "vr": "cbs-vr-jets.json",
        "pkg": "cbs-package-matrix.json",
        "json": "cbs-json-output.json",
        "ledger": "cbs-change-ledger.json",
    }
    pages = {}
    for key, name in wanted.items():
        path = out_dir / name
        if path.exists():
            pages[key] = json.loads(path.read_text())
    return pages


def analysis_caveats(root: Path) -> list[dict]:
    """Per-analysis validation signals, read from the analysis sources.

    Two signals, deliberately kept separate. `Cutflow` instrumentation is the
    machinery an author uses to compare against the published cutflow; its
    absence does not prove the analysis is unvalidated, only that the usual
    evidence is not in the file. The caveat markers are the author's own words.
    """
    directory = root / "ColliderBit" / "src" / "analyses"
    rows = []
    for name in NEW_ANALYSES:
        matches = sorted(directory.glob(f"Analysis_{name}*.cpp"))
        if not matches:
            rows.append({"name": name, "missing": True})
            continue
        path = matches[0]
        lines = path.read_text(errors="replace").splitlines()
        markers = []
        for index, line in enumerate(lines):
            if not CAVEAT_RE.search(line):
                continue
            # Quote the prose, not the code it hangs off: a trailing `// TODO`
            # on a 90-column table of numbers is unreadable otherwise.
            comment = line.split("//", 1)[1] if "//" in line else line
            markers.append({
                "line": index + 1,
                "text": comment.strip().lstrip("/*! ").strip(),
                "strong": bool(STRONG_RE.search(line)),
            })
        markers.sort(key=lambda m: (not m["strong"], m["line"]))
        rows.append({
            "name": name,
            "file": path.name,
            "lines": len(lines),
            "cutflow": sum(1 for line in lines if "Cutflow" in line),
            "markers": markers,
            "missing": False,
        })
    return rows


def feature_origins(root: Path) -> list[dict]:
    """Where each CBS-only capability entered, across the four refs.

    The deck is scoped to HEAD-vs-merge-base, so anything already present at
    the merge-base is correctly absent from it. The paper is scoped to
    CBS-vs-released-GAMBIT, which is a different set.
    """
    rows = []
    for term in FEATURES:
        counts = {
            "master": grep_files(root, MASTER, term, "ColliderBit"),
            "base": grep_files(root, BASE, term, "ColliderBit"),
            "sr2": grep_files(root, SR2, term, "ColliderBit"),
            "head": grep_files(root, "HEAD", term, "ColliderBit"),
        }
        if counts["master"] == 0 and counts["base"] > 0:
            where = "predates the branch point; absent from master"
        elif counts["head"] > counts["base"]:
            where = "grew on this branch"
        else:
            where = "inherited"
        rows.append({"term": term, **counts, "where": where})
    return rows


def distribution(root: Path) -> dict:
    """The install surface, counted rather than characterised."""
    backends = (root / "cmake" / "backends.cmake").read_text(errors="replace")
    standalones = (root / "cmake" / "standalones.cmake").read_text(errors="replace")

    cbs_line = next((i + 1 for i, line in enumerate(standalones.splitlines())
                     if "add_standalone(CBS" in line), None)
    call = standalones[standalones.find("add_standalone(CBS"):]
    modules = re.search(r"MODULES\s+(.+?)(?:\s+DEPENDENCIES|\))", call)
    deps = re.search(r"DEPENDENCIES\s+(.+?)\)", call)

    urls = re.findall(r'set\(dl\s+"([^"]+)"', backends)
    scripts = {name: (root / "cmake" / "scripts" / name).exists()
               for name in ("safe_dl.sh", "copy_tarballs.sh", "restore_tarballs.sh")}
    script_origin = {
        name: bool(git(root, "cat-file", "-e", f"{MASTER}:cmake/scripts/{name}")
                   or git(root, "log", "-1", "--format=%H", MASTER,
                          "--", f"cmake/scripts/{name}").strip())
        for name in scripts
    }
    return {
        "backends": len(re.findall(r"^set\(name ", backends, re.M)),
        "urls": len(urls),
        "hepforge": sum(1 for u in urls if "hepforge.org" in u),
        "cbs_line": cbs_line,
        "cbs_modules": modules.group(1).strip() if modules else "",
        "cbs_deps": deps.group(1).strip().split() if deps else [],
        "scripts": scripts,
        "script_from_master": script_origin,
        "lld_line": next((i + 1 for i, line in enumerate(standalones.splitlines())
                          if "GAMBIT_USE_LLD_FOR_CBS" in line), None),
    }


def gitignore_hit(root: Path, needle: str) -> int | None:
    path = root / ".gitignore"
    if not path.exists():
        return None
    for index, line in enumerate(path.read_text(errors="replace").splitlines()):
        if needle in line:
            return index + 1
    return None


def collect(root: Path, out_dir: Path) -> dict:
    pages = load_pages(out_dir)
    return {
        "generated_by": "scripts/build-paper-questions-page.py",
        "refs": {"master": MASTER, "base": BASE, "sr2": SR2,
                 "head": git(root, "rev-parse", "--short=10", "HEAD").strip()},
        "pages_read": sorted(pages),
        "analyses": analysis_caveats(root),
        "features": feature_origins(root),
        "distribution": distribution(root),
        "gitignore_cbs_yaml": gitignore_hit(root, "CBS_yaml"),
        "pages": pages,
        "caveat": "Static read of the worktree and of the other pages' JSON. "
                  "Nothing was built or run.",
    }


# ---------------------------------------------------------------- questions


def build_questions(data: dict) -> list[dict]:
    """The punch-list.

    Each entry pairs an editorial question with facts pulled out of `data`.
    Nothing here computes a number inline -- if a figure appears in the text of
    a question it is interpolated from the evidence, so the two cannot drift.
    """
    pages = data["pages"]
    hist = pages.get("hist", {})
    yaml_data = pages.get("yaml", {})
    rename = pages.get("rename", {})
    vr = pages.get("vr", {})
    pkg = pages.get("pkg", {})
    jsonp = pages.get("json", {})
    ledger = pages.get("ledger", {})
    dist = data["distribution"]

    questions: list[dict] = []

    # ---- 1. check_histogram -------------------------------------------
    consumers = hist.get("consumers", [])
    sr_users = [c for c in consumers if c.get("mode") == "signal region"]
    extra = sum(max(0, c.get("srs_with_flag", 0) - c.get("srs_without_flag", 0))
                for c in consumers)
    macros = hist.get("macros", [])
    gate = yaml_data.get("histogram_gate", {})
    guarded = [name for name, m in gate.get("macros", {}).items() if m.get("self_guarded")]
    switch_line = hist.get("switch", {}).get("read", {}).get("line")
    questions.append({
        "group": "results",
        "severity": "numbers",
        "title": "Which <code>check_histogram</code> setting produced the published numbers?",
        "ask": (
            f"<code>check_histogram</code> defaults to <strong>false</strong>. Turned on, the "
            f"{len(sr_users)} signal-region histogram analyses commit "
            f"<strong>{extra} additional signal regions</strong> that are simply absent "
            f"otherwise. That is not a verbosity flag &mdash; it changes the number of "
            f"likelihood terms in the output."),
        "evidence": [
            (f"read with <code>getValueOrDef</code>, default <code>false</code>",
             f"solo.cpp:{switch_line}"),
            (f"{len(sr_users)} of {len(consumers)} histogram analyses run in signal-region mode, "
             f"contributing {extra} extra signal regions when the flag is on",
             "cbs-histograms.json &middot; consumers"),
            (f"only {len(guarded)} of {len(macros)} histogram macros guard themselves "
             f"({', '.join(f'<code>{g}</code>' for g in guarded)}); the rest rely on the "
             f"caller checking",
             "AnalysisMacros.hpp"),
        ],
        "consequence": (
            "A reader who copies the example YAML gets fewer signal regions than the paper "
            "reports, with no warning and no error. The paper needs the setting stated next to "
            "the results, and ideally the flag&#8217;s value echoed into the output JSON."),
        "link": ("Histogram mechanism", "cbs-histograms.html"),
    })

    # ---- 2. VR smearing -----------------------------------------------
    optouts = vr.get("optouts", {})
    smear_sites = optouts.get("no_smear_sites", [])
    wire_sites = optouts.get("no_smear_wire", [])
    no_smear_line = optouts.get("no_smear_decl", {}).get("line")
    vr_users = [a for a in vr.get("analyses", []) if a.get("vr_collections")]
    questions.append({
        "group": "results",
        "severity": "numbers",
        "title": "Are variable-R jets smeared, and is that the intended physics?",
        "ask": (
            "Variable-R collections are named into a no-smear list and skipped by the "
            "detector simulation, so VR jets carry <strong>no jet energy resolution "
            "smearing</strong> while every fixed-R collection does. The code says what "
            "happens; nothing says whether it is right."),
        "evidence": [
            ("<code>jetcollections_no_smear</code> declared on the smearing object",
             f"BuckFast.hpp:{no_smear_line}"),
            (f"{len(smear_sites)} <code>continue</code> sites drop those collections out of the "
             f"smearing loop",
             ", ".join(f"BuckFast.cpp:{s['line']}" for s in smear_sites) or "BuckFast.cpp"),
            (f"the list is filled from the VR settings at {len(wire_sites)} wiring sites, so "
             f"membership is automatic &mdash; a collection is excluded by being variable-R, not "
             f"by anyone choosing to exclude it",
             ", ".join(f"getBuckFast.cpp:{s['line']}" for s in wire_sites) or "getBuckFast.cpp"),
            (f"{len(vr_users)} analyses consume VR jets and inherit the choice: "
             + ", ".join(f"<code>{a['name']}</code>" for a in vr_users),
             "ColliderBit/src/analyses/"),
        ],
        "consequence": (
            "Either it is deliberate &mdash; because the experimental VR calibration is applied "
            "upstream and smearing twice would be wrong &mdash; in which case say so in one "
            f"sentence and the objection dies. Or it is a gap, in which case it is an "
            f"unquantified systematic on every analysis that uses VR jets "
            f"({len(vr_users)} of them), and the paper is silent about it. Right now a referee "
            f"cannot tell which."),
        "link": ("Variable-R jets", "cbs-vr-jets.html"),
    })

    # ---- 3. per-analysis validation ------------------------------------
    rows = data["analyses"]
    no_cutflow = [r for r in rows if not r.get("missing") and r.get("cutflow", 0) == 0]
    # Only the ranked-strong markers are quoted. Every large analysis has a
    # stray TODO somewhere; the ones worth a referee's attention are the ones
    # where the author wrote down a limitation.
    flagged = [r for r in rows if any(m["strong"] for m in r.get("markers", []))]
    status = ledger.get("analysis_status", {})
    questions.append({
        "group": "results",
        "severity": "numbers",
        "title": "Which of the twelve new analyses are validated, and against what?",
        "ask": (
            f"The deck says twelve analyses were added. It does not say which of them "
            f"reproduce the published cutflows. {len(no_cutflow)} of {len(rows)} carry no "
            f"<code>Cutflow</code> instrumentation at all, and {len(flagged)} say in their own "
            f"source comments that they are not finished."),
        "evidence": [
            (f"no cutflow instrumentation: "
             + ", ".join(f"<code>{r['name']}</code>" for r in no_cutflow),
             "ColliderBit/src/analyses/"),
        ] + [
            (f"<code>{r['name']}</code> &mdash; &ldquo;{esc(r['markers'][0]['text'][:120])}&rdquo;",
             f"{r['file']}:{r['markers'][0]['line']}")
            for r in flagged
        ] + [
            (f"<code>{name.replace('Analysis_', '')}</code> is tracked as "
             f"<strong>{info['status']}</strong> &mdash; {esc(info['note'])}", "change ledger")
            for name, info in status.items()
        ],
        "consequence": (
            "A validation table is the single most-requested thing in a recast paper. Without "
            "one, every yield in the paper is taken on trust, and the two analyses already "
            "tracked as skeleton and partial will be read as finished."),
        "link": ("Change ledger", "cbs-change-ledger.html#8"),
    })

    # ---- 4. the defaults file ------------------------------------------
    defaults = yaml_data.get("defaults", {})
    questions.append({
        "group": "reproducibility",
        "severity": "rerun",
        "title": "Where does a reader get the default settings?",
        "ask": (
            f"The three-layer merge &mdash; global defaults, per-analysis card, user file &mdash; "
            f"is the headline simplification of the new configuration. The defaults file at the "
            f"bottom of it is <strong>not in the repository</strong>: the whole "
            f"<code>CBS_yaml/</code> directory is gitignored, and a missing defaults file is a "
            f"silent fallback rather than an error."),
        "evidence": [
            (f"<code>{esc(defaults.get('path', 'CBS_yaml/CBS_defaults.yaml'))}</code> exists in the "
             f"worktree, {defaults.get('lines', {}).get('code', '?')} lines of settings, "
             f"<strong>tracked: {defaults.get('tracked')}</strong>",
             "cbs-yaml-config.json &middot; defaults"),
            ("<code>CBS_yaml/*</code> ignored",
             f".gitignore:{data['gitignore_cbs_yaml']}"),
            ("absent defaults return silently rather than failing, so the run proceeds on "
             "whatever the compiled-in values happen to be", "solo_input.cpp"),
        ],
        "consequence": (
            "Every number in the paper was produced under a set of defaults that ships with "
            "nobody. Either commit the file and cite it, or print the resolved settings into the "
            "output JSON so a run is self-describing. The second is cheaper and also fixes the "
            "previous question."),
        "link": ("User YAML", "cbs-yaml-config.html"),
    })

    # ---- 5. forced and dead keys ---------------------------------------
    policy = yaml_data.get("policy", {})
    counts = yaml_data.get("counts", {})
    questions.append({
        "group": "reproducibility",
        "severity": "text",
        "title": "Which settings does CBS overrule, and which do nothing at all?",
        "ask": (
            f"{len(policy)} keys are overwritten in <code>solo.cpp</code> after the user file is "
            f"read, so setting them in YAML has no effect. A further "
            f"<strong>{counts.get('dead', 0)}</strong> keys are read by no source file at either "
            f"ref. Both kinds look exactly like working settings in an example file."),
        "evidence": [
            (f"<code>{key}</code> forced to <code>{esc(info['value'])}</code>"
             + (f" &mdash; {esc(info['why'])}" if info.get("why") else ""),
             f"solo.cpp:{info['line']}")
            for key, info in policy.items()
        ] + [
            (f"of the {sum(counts.values())} keys in the original example file, only "
             f"<strong>{counts.get('user', 0)}</strong> are still genuinely the "
             f"user&#8217;s to set &mdash; {counts.get('program', 0)} are defaulted by the "
             f"program, {counts.get('conditional', 0)} is conditional, and "
             f"{counts.get('dead', 0)} are read by nothing",
             "cbs-yaml-config.json &middot; counts"),
        ],
        "consequence": (
            "<code>run_convergence_checks</code> being forced to <code>false</code> makes the "
            "whole convergence block inert &mdash; a reader tuning those thresholds is tuning "
            "nothing. A configuration table in the paper that lists dead keys as options is "
            "worse than no table."),
        "link": ("User YAML", "cbs-yaml-config.html"),
    })

    # ---- 6. backend versions -------------------------------------------
    contur = pkg.get("contur_check", {})
    head_contur = contur.get("head", {})
    questions.append({
        "group": "reproducibility",
        "severity": "decision",
        "title": "Which backend versions is the paper claiming?",
        "ask": (
            "A software paper carries a version table. At HEAD the tree does not agree with "
            "itself about at least one entry: cmake and the frontend name different Contur "
            "versions, and the patch cmake points at does not exist."),
        "evidence": [
            (f"<code>{ref}</code>: cmake says <code>{info.get('cmake_version')}</code>; "
             + ("no patch line (deliberately absent)" if info.get("patch_referenced") is None
                else f"patch <code>{esc(Path(info['patch_referenced']).name)}</code> "
                     f"<strong>{'present' if info.get('patch_exists') else 'missing'}</strong>")
             + f"; self-consistent: <strong>{'yes' if info.get('consistent') else 'no'}</strong>",
             f"cmake/backends.cmake:{info.get('cmake_line')}")
            for ref, info in contur.items()
        ],
        "consequence": (
            f"HEAD is the only ref of the four that is internally inconsistent here. Fix it "
            f"before the version table is written, or the table records a configuration that "
            f"cannot be built."),
        "link": ("Package matrix", "cbs-change-ledger.html#12"),
    })

    # ---- 7. name migration ---------------------------------------------
    reg = rename.get("registered", {})
    files = rename.get("files", {})
    debt = rename.get("yaml_debt", [])
    questions.append({
        "group": "compatibility",
        "severity": "decision",
        "title": "What happens to an existing user&#8217;s YAML?",
        "ask": (
            f"<strong>{len(reg.get('retired', []))} registered analysis names were retired.</strong> "
            f"Any input file naming one of them now fails. The migration is documented in the "
            f"source as per-file comments, which is the one place a user with a broken YAML will "
            f"not look."),
        "evidence": [
            (f"{len(reg.get('retired', []))} names retired, "
             f"{len(reg.get('introduced', []))} introduced, "
             f"{reg.get('base')} &rarr; {reg.get('head')} registered overall",
             "cbs-rename-migration.json"),
            (f"{files.get('documented')} renames documented across "
             f"{files.get('git_renames')} git-detected file moves, including "
             f"{files.get('consolidations')} consolidations absorbing {files.get('absorbed')} files",
             "per-file provenance comments"),
        ] + [
            (f"<code>{esc(d['file'])}</code> in this tree still names "
             f"<strong>{d['count']}</strong> retired analyses", "yaml debt")
            for d in debt
        ],
        "consequence": (
            "Decide whether CBS accepts old names with a deprecation warning or breaks cleanly. "
            "Either is defensible; silence is not. If it breaks, the paper needs the mapping as "
            "an appendix or a cited machine-readable file &mdash; not a comment in a .cpp."),
        "link": ("Naming migration", "cbs-rename-migration.html"),
    })

    # ---- 8. the JSON contract -------------------------------------------
    questions.append({
        "group": "interface",
        "severity": "decision",
        "title": "Is the output JSON a specified interface, or an implementation detail?",
        "ask": (
            f"The output carries <code>schema_version</code> "
            f"(<code>{esc(jsonp.get('schema_version', '?'))}</code>), which is a promise. But the "
            f"field layout is defined only by the code that writes it, and the "
            f"<code>term_id</code> grammar &mdash; the thing every downstream consumer parses "
            f"&mdash; is documented nowhere."),
        "evidence": [
            (f"{len(jsonp.get('root_fields', []))} top-level keys, "
             f"{len(jsonp.get('objects', []))} nested object types",
             "cbs-json-output.json"),
            (f"<code>&lt;analysis&gt;::&lt;sr|combined&gt;::&lt;variant&gt;</code>, e.g. "
             f"<code>{esc(jsonp.get('sample_terms', [{}])[-1].get('term_id', ''))}</code>",
             "term_id grammar"),
            (f"{len(jsonp.get('consumers', []))} in-tree consumers already parse it, with their "
             f"own guards for fields they expect", "reader-side guards"),
        ],
        "consequence": (
            "If it is an interface, the paper should carry the schema and the grammar, and "
            "<code>schema_version</code> should have a documented bump policy. If it is not, say "
            "so, and downstream users know to pin a commit rather than trust the version string."),
        "link": ("JSON output", "cbs-json-output.html"),
    })

    # ---- 9. distribution -------------------------------------------------
    scripts_present = [n for n, ok in dist["scripts"].items() if ok]
    pct = round(100 * dist["hepforge"] / dist["urls"]) if dist["urls"] else 0
    questions.append({
        "group": "distribution",
        "severity": "decision",
        "title": "What installation route does the paper tell a reader to take?",
        "ask": (
            f"CBS declares one module and <strong>{len(dist['cbs_deps'])} dependencies</strong> "
            f"({', '.join(f'<code>{d}</code>' for d in dist['cbs_deps'])}). The build system in "
            f"front of it declares <strong>{dist['backends']}</strong> backends, and "
            f"<strong>{dist['hepforge']} of {dist['urls']}</strong> download URLs ({pct}%) point "
            f"at a single host. Nothing tells a reader which of the two numbers applies to them."),
        "evidence": [
            (f"<code>add_standalone(CBS &hellip; MODULES {esc(dist['cbs_modules'])} "
             f"DEPENDENCIES {esc(' '.join(dist['cbs_deps']))})</code>",
             f"cmake/standalones.cmake:{dist['cbs_line']}"),
            (f"{dist['backends']} backends declared; {dist['hepforge']}/{dist['urls']} downloads "
             f"on hepforge.org", "cmake/backends.cmake"),
            (f"mitigation already exists and is undocumented: "
             + ", ".join(f"<code>{n}</code>" for n in scripts_present),
             "cmake/scripts/"),
            (f"<code>GAMBIT_USE_LLD_FOR_CBS</code> exists because linking CBS was worth an option",
             f"cmake/standalones.cmake:{dist['lld_line']}"),
        ],
        "consequence": (
            "The cheapest fix is a paragraph: name the minimal dependency set, and point at the "
            "tarball-mirror scripts that are already in the tree. The real fix is a container or "
            "conda recipe, so that most readers never build at all."),
        "link": ("Build and distribution", "cbs-change-ledger.html#14"),
    })

    # ---- 10. scope --------------------------------------------------------
    feats = data["features"]
    cbs_only = [f for f in feats if f["master"] == 0 and f["head"] > 0]
    questions.append({
        "group": "scope",
        "severity": "decision",
        "title": "What does &ldquo;CBS&rdquo; name, and against which baseline?",
        "ask": (
            f"This whole project is scoped to <em>what changed on this branch</em>, so it is "
            f"baselined at the merge-base. A paper is scoped to <em>what CBS is</em>, which is "
            f"the delta against released GAMBIT. Those are different sets, and the gap is not "
            f"small: capabilities that predate the branch point are invisible here but are "
            f"squarely part of what the paper describes."),
        "evidence": [
            (f"<code>{f['term']}</code> &mdash; master {f['master']} files, merge-base "
             f"{f['base']}, HEAD {f['head']} &mdash; {f['where']}", "ColliderBit tree")
            for f in feats
        ] + [
            (f"{len(cbs_only)} of {len(feats)} probed capabilities are absent from master "
             f"entirely, and this deck mentions none of them",
             "scope gap"),
        ],
        "consequence": (
            "Answer this first. It decides whether the paper&#8217;s change list starts at the "
            "merge-base (in which case ONNX and MET-significance belong to somebody else&#8217;s "
            "paper) or at master (in which case they are CBS features that are currently "
            "undocumented in every artefact here)."),
        "link": ("What counts as my change", "cbs-change-ledger.html#2"),
    })

    return questions


# ---------------------------------------------------------------- render


def question_html(questions: list[dict]) -> str:
    out = []
    number = 0
    for group_id, group_title, group_blurb in GROUPS:
        members = [q for q in questions if q["group"] == group_id]
        if not members:
            continue
        out.append('<section class="qgroup">')
        out.append(f'<p class="kicker">{esc(group_id)}</p>')
        out.append(f"<h2>{group_title}</h2>")
        out.append(f'<p class="source">{group_blurb}</p>')
        out.append('<div class="q-list">')
        for q in members:
            number += 1
            label, css = SEVERITY[q["severity"]]
            evidence = "".join(
                f"<tr><td>{fact}</td><td><code>{src}</code></td></tr>"
                for fact, src in q["evidence"])
            link_text, link_href = q["link"]
            out.append(f'''
<article class="q" id="q{number}">
  <div class="q-head">
    <span class="unit-num">{number}</span>
    <span class="unit-title">{q["title"]}</span>
    <span class="q-sev {css}">{label}</span>
  </div>
  <p class="q-ask">{q["ask"]}</p>
  <table class="q-ev"><thead><tr><th>what the tree says</th><th>where</th></tr></thead>
  <tbody>{evidence}</tbody></table>
  <p class="q-cons"><span class="q-lbl">if it goes unanswered</span>{q["consequence"]}</p>
  <p class="q-link">Background: <a href="{link_href}">{link_text} &#8599;</a></p>
</article>'''.strip())
        out.append("</div></section>")
    return "\n".join(out)


PAGE_CSS = """
<style>
  .qgroup { border-top:1px solid var(--rule); margin-top:34px; padding-top:24px; }
  .q-list { display:grid; gap:16px; margin-top:18px; }
  .q { background:#fff; border:1px solid var(--rule); border-radius:8px; padding:18px 20px 16px;
       scroll-margin-top:20px; }
  .q:target { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
  .q-head { align-items:center; display:flex; flex-wrap:wrap; gap:11px; margin-bottom:11px; }
  .q-head .unit-title { flex:1 1 420px; }
  .q-sev { border:1px solid currentColor; border-radius:3px; font:10.5px var(--font-mono);
           letter-spacing:.8px; padding:3px 8px; text-transform:uppercase; white-space:nowrap; }
  .sev-num { color:#93513f; background:var(--red-tint); }
  .sev-run { color:var(--accent); background:var(--accent-tint); }
  .sev-dec { color:#4a6fa5; background:#eef3fb; }
  .sev-txt { color:var(--green); background:var(--green-tint); }
  .q-ask { color:var(--muted); font-size:15.5px; line-height:1.62; margin:0 0 13px; max-width:96ch; }
  .q-ask strong, .q-cons strong { color:var(--ink); font-weight:600; }
  .q-ev { margin:0 0 13px; }
  .q-ev th:last-child, .q-ev td:last-child { width:1%; white-space:nowrap; }
  .q-ev td { color:var(--muted); font-size:13.5px; line-height:1.55; }
  .q-ev td code { color:var(--soft); font-size:11.5px; }
  .q-ev td:first-child code { color:var(--ink); font-size:12.5px; }
  .q-cons { background:var(--paper-2); border-radius:5px; color:var(--muted); font-size:14px;
            line-height:1.6; margin:0 0 10px; padding:11px 13px; }
  .q-lbl { color:var(--soft); display:block; font:10.5px var(--font-mono); letter-spacing:.14em;
           margin-bottom:5px; text-transform:uppercase; }
  .q-link { font-size:13px; margin:0; }
  .q-link a { border-bottom:1px solid rgba(235,108,54,.42); color:var(--accent);
              font-weight:600; text-decoration:none; }
  .q-link a:hover { background:var(--accent-tint); }
  .legend { display:flex; flex-wrap:wrap; gap:9px; margin:16px 0 0; }
</style>
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open questions for the CBS paper</title>
__CSS__
__PAGE_CSS__
</head>
<body>
<div class="frame">
  <p class="eyebrow">ColliderBit Solo &middot; paper punch-list</p>
  <h1>What the paper still has to answer</h1>
  <p class="intro">
    Every other page in this project documents what CBS does. This one is the residue: the
    questions that came up while writing those pages and that the source cannot settle on its
    own. <strong>__N__ questions</strong> in __N_GROUPS__ groups, ordered by what they cost if
    they stay unanswered &mdash; from settings that change the published yields, down to a
    paragraph that is merely missing.
  </p>
  <div class="meta">
    <span>refs <strong>__BASE__</strong> &rarr; <strong>__HEAD__</strong>, master <strong>__MASTER__</strong></span>
    <span>evidence from <strong>__N_PAGES__</strong> generated data files</span>
    <span>__N_NUMBERS__ affect published numbers</span>
    <span>generated by <strong>__SCRIPT__</strong></span>
  </div>
  <div class="note">
    The questions are ours &mdash; editorial judgement about what a paper owes a reader. Every
    figure beside them is read out of the tree, or out of the JSON behind the other pages, at
    build time. If a number here disagrees with the source, the source is right and this page is
    stale; rerun the script rather than editing the HTML.
  </div>

  <div class="summary-grid">
    __CARDS__
  </div>

  __QUESTIONS__

  <section>
    <p class="kicker">not on this list</p>
    <h2>Things that are already settled</h2>
    <p class="source">
      Recorded so the list is not mistaken for a survey of everything uncertain.
    </p>
    <div class="claim-grid">
      <div class="claim">
        <p class="claim-h">The variable-R addition is minimal</p>
        <p>The fixed-R clustering path is __VR_RATIO__% token-identical to the baseline
        (__VR_TOKENS__ tokens each side), and the single difference traces to an unrelated commit.
        That claim is measured, not asserted, and needs no further work before it goes in the
        paper.</p>
      </div>
      <div class="claim">
        <p class="claim-h">The physics was not rewritten</p>
        <p>CBS changed how ColliderBit is invoked, not what it computes. The event pipeline,
        detector simulation and likelihood machinery are the inherited ones. This is a claim the
        paper can make plainly.</p>
      </div>
    </div>
  </section>

  <div class="backlink">
    <span class="lbl">deck</span>
    <span>These questions are drawn from across the
    <a href="cbs-change-ledger.html">CBS change ledger</a>; the slide that raises the most of them
    is <a href="cbs-change-ledger.html#13">what is not finished</a>.</span>
  </div>

  <footer>__CAVEAT__ &middot; generated by <code>__SCRIPT__</code>.</footer>
</div>
</body>
</html>
"""


def render_html(data: dict, questions: list[dict]) -> str:
    css_path = Path(__file__).with_name("_page_css.html")
    css = css_path.read_text() if css_path.exists() else "<style></style>"

    by_sev: dict[str, int] = {}
    for q in questions:
        by_sev[q["severity"]] = by_sev.get(q["severity"], 0) + 1

    cards = [f'<div class="card accent"><span class="n">{len(questions)}</span>'
             f'<span class="label">open questions</span></div>']
    for key, (label, _) in SEVERITY.items():
        cards.append(f'<div class="card"><span class="n">{by_sev.get(key, 0)}</span>'
                     f'<span class="label">{label}</span></div>')
    groups_used = len({q["group"] for q in questions})
    cards.append(f'<div class="card"><span class="n">{groups_used}</span>'
                 f'<span class="label">groups</span></div>')

    regression = (data["pages"].get("vr", {})
                  .get("parallel", {}).get("regression", {}))
    if "ratio" not in regression:
        raise SystemExit("cbs-vr-jets.json carries no regression ratio; "
                         "rerun build-vrjet-page.py first")
    replacements = {
        "__CSS__": css,
        "__PAGE_CSS__": PAGE_CSS,
        "__N__": str(len(questions)),
        "__N_GROUPS__": str(groups_used),
        "__N_PAGES__": str(len(data["pages_read"])),
        "__N_NUMBERS__": str(by_sev.get("numbers", 0)),
        "__BASE__": esc(data["refs"]["base"]),
        "__HEAD__": esc(data["refs"]["head"]),
        "__MASTER__": esc(data["refs"]["master"]),
        "__CARDS__": "\n    ".join(cards),
        "__QUESTIONS__": question_html(questions),
        "__VR_RATIO__": f"{regression['ratio'] * 100:.1f}",
        "__VR_TOKENS__": str(regression["base_tokens"]),
        "__CAVEAT__": esc(data["caveat"]),
        "__SCRIPT__": data["generated_by"],
    }
    page = TEMPLATE
    for token, value in replacements.items():
        page = page.replace(token, value)
    leftover = sorted(set(re.findall(r"__[A-Z_]+__", page)))
    if leftover:
        raise SystemExit(f"unreplaced tokens: {leftover}")
    return page


def plain(text: str) -> str:
    """HTML fragment to prose: drop the tags, then put the entities back."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def render_markdown(data: dict, questions: list[dict]) -> str:
    lines = [
        "# Open questions for the CBS paper",
        "",
        f"Refs: `{data['refs']['base']}` -> `{data['refs']['head']}`, "
        f"master `{data['refs']['master']}`.",
        "",
        "The questions are editorial. Every figure beside them is read from the tree "
        "or from the other pages' generated JSON at build time.",
        "",
    ]
    number = 0
    for group_id, group_title, group_blurb in GROUPS:
        members = [q for q in questions if q["group"] == group_id]
        if not members:
            continue
        lines += [f"## {group_title}", "", group_blurb, ""]
        for q in members:
            number += 1
            lines.append(f"### {number}. {plain(q['title'])}  "
                         f"_[{SEVERITY[q['severity']][0]}]_")
            lines.append("")
            lines.append(plain(q["ask"]))
            lines.append("")
            for fact, src in q["evidence"]:
                lines.append(f"- {plain(fact)} — `{plain(src)}`")
            lines.append("")
            lines.append(f"**If unanswered:** {plain(q['consequence'])}")
            lines.append("")
    lines.append(f"---\n\n{data['caveat']} Generated by `{data['generated_by']}`.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path,
                        default=Path.home() / "Gambit-Workshop" / "gambit")
    parser.add_argument("--out-dir", type=Path, default=Path("dependences"))
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    args = parser.parse_args()

    data = collect(args.gambit_root, args.out_dir)
    questions = build_questions(data)

    # The page's own data file drops the embedded copies of the other pages:
    # they are already on disk, and duplicating them invites the two to drift.
    record = {k: v for k, v in data.items() if k != "pages"}
    record["questions"] = [
        {"group": q["group"], "severity": q["severity"],
         "title": plain(q["title"]),
         "evidence": [{"fact": plain(f), "source": plain(s)} for f, s in q["evidence"]]}
        for q in questions
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "cbs-paper-questions.json").write_text(json.dumps(record, indent=2) + "\n")
    page = render_html(data, questions)
    (args.out_dir / "cbs-paper-questions.html").write_text(page)
    (args.out_dir / "CBS_PAPER_QUESTIONS.md").write_text(render_markdown(data, questions))
    if args.site_dir.exists():
        (args.site_dir / "cbs-paper-questions.html").write_text(page)

    print(json.dumps({
        "questions": len(questions),
        "by_severity": {k: sum(1 for q in questions if q["severity"] == k) for k in SEVERITY},
        "pages_read": data["pages_read"],
        "no_cutflow": [r["name"] for r in data["analyses"] if not r.get("cutflow")],
        "cbs_only_features": [f["term"] for f in data["features"] if f["master"] == 0],
    }, indent=2))
    for name in ("cbs-paper-questions.json", "cbs-paper-questions.html",
                 "CBS_PAPER_QUESTIONS.md"):
        print(f"Wrote {args.out_dir / name}")


if __name__ == "__main__":
    main()
