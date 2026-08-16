#!/usr/bin/env python3
"""Render the variable-R jet integration page.

Answers four questions about VR jets in ColliderBit, in order:

  what they depend on   fjcontrib's VariableRPlugin, which is why the build
                        changes on the FastJet page had to happen first
  where they were added seven files along the event pipeline, from YAML parsing
                        to detector smearing
  what was filled in    the schema, the clustering call, the flavour tagging,
                        the storage and the opt-outs
  where they stop       three paths deliberately skip VR, and one analysis
                        bypasses the pipeline entirely

Line counts, YAML keys, validation messages, the clustering call, the skip
sites and the per-analysis usage are all extracted from the worktree at
generation time.  No build was run and no events were processed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

UTILS = "ColliderBit/include/gambit/ColliderBit/Utils.hpp"
CONVERSIONS = "ColliderBit/include/gambit/ColliderBit/colliders/Pythia8/Py8EventConversions.hpp"
LHEF = "ColliderBit/src/lhef2heputils.cpp"
GETBUCKFAST = "ColliderBit/src/getBuckFast.cpp"
BUCKFAST_HPP = "ColliderBit/include/gambit/ColliderBit/detectors/BuckFast.hpp"
BUCKFAST_CPP = "ColliderBit/src/detectors/BuckFast.cpp"
EVENT_H = "contrib/heputils/include/HEPUtils/Event.h"

PIPELINE = [UTILS, CONVERSIONS, EVENT_H, BUCKFAST_HPP, BUCKFAST_CPP, GETBUCKFAST, LHEF]

ANALYSES = [
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_04.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_07.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_SUSY_2018_07.cpp",
]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def lines_of(root: Path, path: str) -> list[str]:
    return (root / path).read_text(errors="replace").splitlines()


def find(lines: list[str], pattern: str, start: int = 0) -> int:
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    raise SystemExit(f"pattern not found: {pattern!r}")


def find_all(lines: list[str], pattern: str) -> list[int]:
    rx = re.compile(pattern)
    return [i for i in range(len(lines)) if rx.search(lines[i])]


def quote(lines: list[str], lo: int, hi: int) -> str:
    """1-based inclusive source excerpt with line numbers."""
    return "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(lo, hi + 1))


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def collect(gambit: Path, baseline: str) -> dict:
    numstat = {}
    raw = git(gambit, "diff", "--numstat", "-M", baseline, "HEAD", "--", *PIPELINE, *ANALYSES)
    for row in raw.splitlines():
        added, removed, path = row.split("\t")
        numstat[path] = {"added": int(added), "removed": int(removed)}

    status = {}
    for row in git(gambit, "diff", "--name-status", "-M", baseline, "HEAD",
                   "--", *PIPELINE, *ANALYSES).splitlines():
        parts = row.split("\t")
        status[parts[-1]] = parts[0]

    utils = lines_of(gambit, UTILS)
    conv = lines_of(gambit, CONVERSIONS)
    lhef = lines_of(gambit, LHEF)
    buck_cpp = lines_of(gambit, BUCKFAST_CPP)
    buck_hpp = lines_of(gambit, BUCKFAST_HPP)
    getbf = lines_of(gambit, GETBUCKFAST)
    event = lines_of(gambit, EVENT_H)

    # ---- YAML schema, read off the settings struct and the parser ---------
    struct_lo = find(utils, r"struct jet_collection_settings")
    struct_hi = find(utils, r"^\s*\};", struct_lo)
    fields = []
    for i in range(struct_lo + 2, struct_hi):
        match = re.match(r"\s*([\w:<>]+)\s+(\w+)\s*(?:=\s*(.+?))?\s*;", utils[i])
        if match:
            fields.append({
                "type": match.group(1),
                "name": match.group(2),
                "default": match.group(3),
                "line": i + 1,
            })

    parse_lo = find(utils, r"read_jet_collection_settings_from_options")
    parse_hi = find(utils, r"^\s*\}\s*$", find(utils, r"return parsed;", parse_lo))
    vr_branch_lo = find(utils, r"if \(is_vr_algorithm\(algorithm\)\)", parse_lo)
    vr_keys, fixed_keys = [], []
    target = vr_keys
    for i in range(vr_branch_lo, parse_hi):
        if re.search(r"^\s*else\s*$", utils[i]):
            target = fixed_keys
        match = re.search(r'getValue<[\w:]+>\("(\w+)"\)', utils[i])
        if match:
            target.append({"key": match.group(1), "line": i + 1})
        if re.search(r"parsed\.collections\.push_back", utils[i]):
            break

    validations = []
    for i in find_all(utils, r"throw std::runtime_error"):
        text = utils[i].strip()
        probe = i
        while text.count("(") > text.count(")") and probe < len(utils) - 1:
            probe += 1
            text += " " + utils[probe].strip()
        literal = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        if literal:
            validations.append({"line": i + 1, "message": " ".join(literal).strip()})

    # ---- the clustering call ----------------------------------------------
    plugin_line = find(conv, r"VariableRPlugin\(")
    cluster_lo = find(conv, r"if \(is_vr_algorithm\(jetcollection\.algorithm\)\)")
    effective_r = find(conv, r"effectiveR")
    tag_line = find(conv, r"HEPUtils::Jet::TagCounts tags")
    add_jet = find(conv, r"result\.add_jet", tag_line)
    emplace = find(conv, r"emplace_clusterseq\(jetparticles, vr_jet_def")

    # ---- the opt-outs ------------------------------------------------------
    skips = []
    for path, src in ((CONVERSIONS, conv), (LHEF, lhef)):
        for i in find_all(src, r"is_vr_algorithm\([\w.]+\)\s*\)?\s*continue"):
            skips.append({"path": path, "line": i + 1, "text": src[i].strip()})

    no_smear_decl = find(buck_hpp, r"jetcollections_no_smear")
    no_smear_sites = [
        {"line": i + 1, "text": buck_cpp[i].strip()}
        for i in find_all(buck_cpp, r"jetcollections_no_smear")
    ]
    no_smear_wire = [
        {"line": i + 1, "text": getbf[i].strip()}
        for i in find_all(getbf, r"jetcollections_no_smear\s*=")
    ]

    # ---- Event.h storage ---------------------------------------------------
    event_diff = git(gambit, "diff", "-U2", baseline, "HEAD", "--", EVENT_H)
    clusterseq_getter = find(event, r"typename std::shared_ptr<const CS> clusterseq")

    # ---- analyses ----------------------------------------------------------
    analyses = []
    for path in ANALYSES:
        src = lines_of(gambit, path)
        declared = sorted({
            m.group(1)
            for line in src
            for m in [re.search(r'jets\("([\w]+)"\)', line)]
            if m
        })
        vr_collections = [c for c in declared if "VR" in c or "vr" in c]
        # Matches both "new VariableRPlugin(" and "VariableRPlugin vr_plugin(";
        # skips commented-out lines and bare "VariableRPlugin::AKTLIKE" references.
        self_cluster = [
            i for i in find_all(src, r"VariableRPlugin(?:\s+\w+)?\(")
            if not src[i].lstrip().startswith("//")
        ]
        eta_cuts = find_all(src, r"abseta\(\)\s*<\s*2\.5|fabs\([\w>.\-]*eta\(\)\)\s*<\s*2\.5")
        analyses.append({
            "path": path,
            "name": Path(path).stem.replace("Analysis_", ""),
            "lines": len(src),
            "collections": declared,
            "vr_collections": vr_collections,
            "self_clusters": [
                {"line": i + 1, "text": src[i].strip()} for i in self_cluster
            ],
            "eta_cut_sites": len(eta_cuts),
            "added": numstat.get(path, {}).get("added", 0),
            "status": status.get(path, "?"),
        })

    return {
        "generated_by": "scripts/build-vrjet-page.py",
        "refs": {
            "baseline": baseline,
            "head": git(gambit, "rev-parse", "--short", "HEAD").strip(),
        },
        "numstat": numstat,
        "status": status,
        "schema": {
            "fields": fields,
            "struct_lines": [struct_lo + 1, struct_hi + 1],
            "vr_keys": vr_keys,
            "fixed_keys": fixed_keys,
            "validations": validations,
        },
        "clustering": {
            "plugin": {"line": plugin_line + 1, "text": conv[plugin_line].strip()},
            "branch": {"line": cluster_lo + 1, "text": conv[cluster_lo].strip()},
            "emplace": {"line": emplace + 1, "text": conv[emplace].strip()},
            "effective_r": {"line": effective_r + 1, "text": conv[effective_r].strip()},
            "tags": {"line": tag_line + 1, "text": conv[tag_line].strip()},
            "add_jet": {"line": add_jet + 1, "text": conv[add_jet].strip()},
            "excerpt": quote(conv, plugin_line + 1, plugin_line + 5),
            "tag_excerpt": quote(conv, effective_r + 1, effective_r + 1),
        },
        "optouts": {
            "skips": skips,
            "no_smear_decl": {"line": no_smear_decl + 1, "text": buck_hpp[no_smear_decl].strip()},
            "no_smear_sites": no_smear_sites,
            "no_smear_wire": no_smear_wire,
            "buckfast_excerpt": quote(buck_cpp, no_smear_sites[0]["line"] - 3,
                                      no_smear_sites[-1]["line"] + 4) if no_smear_sites else "",
        },
        "storage": {
            "diff": event_diff,
            "getter": {"line": clusterseq_getter + 1, "text": event[clusterseq_getter].strip()},
            "excerpt": quote(event, clusterseq_getter + 1, clusterseq_getter + 5),
        },
        "analyses": analyses,
    }


# --------------------------------------------------------------------------
# numbered units
# --------------------------------------------------------------------------

def change_units(data: dict) -> list[dict]:
    schema = data["schema"]
    cl = data["clustering"]
    opt = data["optouts"]
    vr_keys = ", ".join(f'<code>{k["key"]}</code>' for k in schema["vr_keys"])
    fixed_keys = ", ".join(f'<code>{k["key"]}</code>' for k in schema["fixed_keys"])

    return [
        {
            "id": 1,
            "title": "A jet collection became a named, typed thing",
            "file": UTILS,
            "stage": "YAML",
            "what": f'<code>jet_collection_settings</code> carries {len(schema["fields"])} fields. '
                    f'A fixed-R collection reads {fixed_keys}; a variable-R one reads {vr_keys} '
                    "instead. The algorithm string decides which branch runs, so the two "
                    "parameter sets never mix.",
            "why": "VR jets are not a fixed-R jet with a different number in the R slot. "
                   "They have no single R at all &mdash; the radius is a function of "
                   "<code>rho</code> and the jet's own p<sub>T</sub>, clamped between "
                   "<code>Rmin</code> and <code>Rmax</code>. Reusing the <code>R</code> field "
                   "would have made a meaningless value mandatory.",
            "code": None,
            "code_key": "schema",
        },
        {
            "id": 2,
            "title": "The YAML is validated, not trusted",
            "file": UTILS,
            "stage": "YAML",
            "what": f'{len(schema["validations"])} explicit checks. Every VR parameter is read with '
                    "<code>getValue</code> rather than <code>getValueOrDef</code>, so a missing "
                    "<code>rho</code> is an error rather than a silent default.",
            "why": "A VR collection with a wrong radius law produces jets that look plausible "
                   "and are wrong. The failure has to happen at configure time, before any "
                   "events are read.",
            "code": None,
            "code_key": "validations",
        },
        {
            "id": 3,
            "title": "Clustering through the fjcontrib plugin",
            "file": CONVERSIONS,
            "stage": "conversion",
            "what": "A <code>VariableRPlugin</code> in <code>AKTLIKE</code> mode is wrapped in a "
                    "<code>JetDefinition</code> and handed to the event's cluster sequence. "
                    "<code>delete_plugin_when_unused()</code> hands the plugin's lifetime to "
                    "FastJet.",
            "why": "This is the single line that needs the build changes: "
                   "<code>VariableRPlugin</code> lives in fjcontrib and is a FastJet "
                   "<em>plugin</em>, which is why the link surface had to grow by "
                   "<code>fastjetplugins</code> and both SISCone libraries.",
            "code": data["clustering"]["excerpt"],
            "code_key": None,
        },
        {
            "id": 4,
            "title": "Flavour tagging by the jet's own radius",
            "file": CONVERSIONS,
            "stage": "conversion",
            "what": "b, c and &tau; association uses <code>effectiveR = min(Rmax, max(Rmin, "
                    "rho / pT))</code> &mdash; the radius that jet actually had &mdash; instead of a "
                    "fixed cone. W, Z and h association still uses a hard-coded &Delta;R &lt; 1.0, "
                    "marked <code>@todo Make selectable?</code> in the source.",
            "why": "Matching a 20 GeV VR jet and a 500 GeV VR jet with the same cone would "
                   "mis-tag both, in opposite directions. The whole point of a variable radius "
                   "is that the catchment shrinks with p<sub>T</sub>, and the tagging has to "
                   "follow it.",
            "code": data["clustering"]["tag_excerpt"],
            "code_key": None,
        },
        {
            "id": 5,
            "title": "The event stores cluster sequences by name",
            "file": EVENT_H,
            "stage": "storage",
            "what": "<code>emplace_clusterseq(particles, jetdef, key)</code> keeps one cluster "
                    "sequence per collection name, and the event owns it. The getter was also "
                    "fixed: it used to dereference the result of <code>find()</code> without "
                    "checking for <code>end()</code>.",
            "why": "Multiple named collections coexist in one event, and not every collection "
                   "exists on every path &mdash; the parton and LHEF readers skip VR entirely. "
                   "Asking for a collection that was never filled is normal, so it had to stop "
                   "being undefined behaviour.",
            "code": data["storage"]["excerpt"],
            "code_key": None,
        },
        {
            "id": 6,
            "title": "VR collections opt out of detector smearing",
            "file": BUCKFAST_CPP,
            "stage": "detector",
            "what": f'<code>{opt["no_smear_decl"]["text"]}</code> is filled from the VR collection '
                    "keys, and BuckFast skips those collections in two loops: jet-momentum "
                    "smearing, and the pass that clears b-tags outside |&eta;| &gt; 2.5.",
            "why": "The BuckFast jet smearing is tuned for calorimeter jets with a fixed radius. "
                   "VR track jets are a different object with different resolution, so applying "
                   "the same smearing would be worse than applying none.",
            "code": data["optouts"]["buckfast_excerpt"],
            "code_key": None,
        },
        {
            "id": 7,
            "title": "Two readers decline VR outright",
            "file": LHEF,
            "stage": "boundary",
            "what": f'{len(opt["skips"])} sites <code>continue</code> past any VR collection: the '
                    "parton-level Pythia conversion and the LHEF reader.",
            "why": "VR track jets are built from charged-particle tracks. A parton-level or "
                   "LHE-level event has no tracks to cluster, so producing a collection there "
                   "would be inventing an object rather than reconstructing one.",
            "code": None,
            "code_key": "skips",
        },
    ]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def pipeline_svg(data: dict) -> str:
    width, height = 1240, 340
    stages = [
        ("YAML", "jet_collections:", "algorithm / rho / Rmin / Rmax", "detail-data", [UTILS]),
        ("PARSE", "read_jet_collection_\n  settings_from_options", "typed struct + validation", "detail-primary", [UTILS]),
        ("CLUSTER", "VariableRPlugin", "AKTLIKE, one CS per key", "detail-focal", [CONVERSIONS]),
        ("TAG", "effectiveR", "b / c / tau by jet radius", "detail-focal", [CONVERSIONS]),
        ("STORE", "HEPUtils::Event", "named jets + cluster seqs", "detail-primary", [EVENT_H]),
        ("DETECTOR", "BuckFast", "VR keys skipped", "detail-optional", [BUCKFAST_CPP]),
        ("ANALYSIS", 'event->jets(key)', "EXOT 2019-04 / 2019-07", "detail-primary", []),
    ]
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="vr-title vr-desc">',
        '<title id="vr-title">The variable-R jet pipeline</title>',
        '<desc id="vr-desc">A VR collection is declared in YAML, parsed into a typed struct, '
        'clustered through the fjcontrib VariableRPlugin, tagged using its own effective radius, '
        'stored by name on the event, skipped by detector smearing, and read by analyses.</desc>',
        '<defs><marker id="vr-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]
    box_w, gap = 160, 16
    for index, (kind, title, sub, cls, _files) in enumerate(stages):
        x = 20 + index * (box_w + gap)
        out.append(f'<g class="node {cls}"><rect x="{x}" y="60" width="{box_w}" height="96" rx="8"/>')
        out.append(f'<text class="kind" x="{x + 14}" y="84">{esc(kind)}</text>')
        for line_index, chunk in enumerate(title.split("\n")):
            out.append(f'<text class="title" x="{x + 14}" y="{106 + line_index * 15}" '
                       f'style="font-size:10.5px">{esc(chunk)}</text>')
        offset = 106 + len(title.split("\n")) * 15 + 6
        for line_index, chunk in enumerate(wrap(sub, 20)):
            out.append(f'<text class="body" x="{x + 14}" y="{offset + line_index * 13}">{esc(chunk)}</text>')
        out.append("</g>")
        if index < len(stages) - 1:
            out.append(f'<path class="detail-edge" d="M{x + box_w} 108 H{x + box_w + gap - 5}" '
                       'marker-end="url(#vr-arrow)"/>')

    out.append(f'<rect class="zone" x="20" y="184" width="{width - 40}" height="60" rx="7"/>')
    out.append('<text class="zone-label" x="38" y="206">DEPENDS ON</text>')
    out.append('<text class="body" x="38" y="226" fill="#4f5d75">'
               'fjcontrib VariableRPlugin &#8594; FastJet plugin machinery &#8594; -lfastjetplugins, '
               '-lsiscone, -lsiscone_spherical &#8212; none of which the source branch linked</text>')
    out.append('<text class="legend-label" x="20" y="272">'
               'dashed = the stage that deliberately does nothing for VR collections</text>')
    out.append('<text class="legend-label" x="20" y="292">'
               'the parton-level and LHEF readers are not on this line at all: both skip VR, '
               'because neither has tracks to cluster</text>')
    out.append("</svg>")
    return "\n".join(out)


def wrap(text: str, width: int) -> list[str]:
    words, rows, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            rows.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        rows.append(current)
    return rows


def file_rows(data: dict) -> str:
    roles = {
        UTILS: "YAML schema, typed settings struct, validation, VR key list",
        CONVERSIONS: "VariableRPlugin clustering and effective-radius flavour tagging",
        EVENT_H: "named cluster-sequence storage, plus the missing-key fix",
        BUCKFAST_HPP: "the no-smear collection list",
        BUCKFAST_CPP: "skips VR in the smearing and b-tag-clearing loops",
        GETBUCKFAST: "fills the no-smear list from the parsed VR keys",
        LHEF: "declines VR at LHE level",
    }
    rows = []
    total_add = total_del = 0
    for path in PIPELINE:
        stat = data["numstat"].get(path, {"added": 0, "removed": 0})
        total_add += stat["added"]
        total_del += stat["removed"]
        rows.append(
            f'<tr><td><code>{esc(Path(path).name)}</code></td>'
            f'<td>{roles[path]}</td>'
            f'<td class="num"><span class="add">+{stat["added"]}</span> '
            f'<span class="del">&#8722;{stat["removed"]}</span></td></tr>'
        )
    rows.append(
        f'<tr><td><strong>pipeline total</strong></td><td>7 files, all modified in place</td>'
        f'<td class="num"><strong><span class="add">+{total_add}</span> '
        f'<span class="del">&#8722;{total_del}</span></strong></td></tr>'
    )
    return "".join(rows)


def analysis_rows(data: dict) -> str:
    rows = []
    for entry in data["analyses"]:
        if entry["self_clusters"]:
            source = ('<span class="status unchanged">clusters its own &mdash; '
                      f'<code>{esc(entry["self_clusters"][0]["text"][:58])}</code> '
                      f'at line {entry["self_clusters"][0]["line"]}</span>')
        elif entry["vr_collections"]:
            names = ", ".join(f'<code>{esc(c)}</code>' for c in entry["vr_collections"])
            source = f'<span class="status added-in-right">pipeline &mdash; {names}</span>'
        else:
            source = '<span class="status unchanged">&mdash;</span>'
        rows.append(
            f'<tr><td><code>{esc(entry["name"])}</code></td>'
            f'<td class="num">{entry["lines"]}</td>'
            f'<td>{source}</td>'
            f'<td class="num">{entry["eta_cut_sites"]}</td></tr>'
        )
    return "".join(rows)


def schema_rows(data: dict) -> str:
    vr = {k["key"] for k in data["schema"]["vr_keys"]}
    fixed = {k["key"] for k in data["schema"]["fixed_keys"]}
    rows = []
    for field in data["schema"]["fields"]:
        name = field["name"]
        if name in vr:
            use = '<span class="status added-in-right">variable-R only</span>'
        elif name in fixed:
            use = '<span class="status unchanged">fixed-R only</span>'
        else:
            use = '<span class="status">both</span>'
        rows.append(
            f'<tr><td><code>{esc(name)}</code></td>'
            f'<td><code>{esc(field["type"])}</code></td>'
            f'<td><code>{esc(field["default"] or "&mdash;")}</code></td>'
            f'<td>{use}</td><td class="num">{field["line"]}</td></tr>'
        )
    return "".join(rows)


def validation_rows(data: dict) -> str:
    return "".join(
        f'<tr><td class="num">{v["line"]}</td><td>{esc(v["message"])}</td></tr>'
        for v in data["schema"]["validations"]
    )


def optout_rows(data: dict) -> str:
    rows = []
    for skip in data["optouts"]["skips"]:
        rows.append(
            f'<tr><td><code>{esc(Path(skip["path"]).name)}:{skip["line"]}</code></td>'
            f'<td><code>{esc(skip["text"])}</code></td>'
            f'<td>no tracks exist at this level to cluster</td></tr>'
        )
    for site in data["optouts"]["no_smear_sites"]:
        rows.append(
            f'<tr><td><code>BuckFast.cpp:{site["line"]}</code></td>'
            f'<td><code>{esc(site["text"][:96])}</code></td>'
            f'<td>calorimeter-jet smearing does not describe VR track jets</td></tr>'
        )
    return "".join(rows)


def unit_cards(data: dict, units: list[dict]) -> str:
    cards = []
    for unit in units:
        code = unit["code"]
        if unit["code_key"] == "schema":
            code = quote_struct(data)
        elif unit["code_key"] == "validations":
            code = "\n".join(
                f'{v["line"]:>5}  throw std::runtime_error("{v["message"]}");'
                for v in data["schema"]["validations"]
            )
        elif unit["code_key"] == "skips":
            code = "\n".join(
                f'{Path(s["path"]).name}:{s["line"]}\n      {s["text"]}'
                for s in data["optouts"]["skips"]
            )
        block = (f'<details class="unit-diff"><summary>source</summary>'
                 f'<pre class="unit-hunks">{esc(code)}</pre></details>') if code else ""
        cards.append(f"""
        <article class="unit" id="unit-{unit["id"]}">
          <header class="unit-head">
            <span class="unit-num">{unit["id"]}</span>
            <span class="unit-title">{esc(unit["title"])}</span>
            <span class="unit-kind extracted">{esc(unit["stage"])}</span>
            <span class="unit-delta">{esc(Path(unit["file"]).name)}</span>
          </header>
          <dl class="unit-grid">
            <div><dt>what</dt><dd>{unit["what"]}</dd></div>
            <div><dt>why</dt><dd>{unit["why"]}</dd></div>
          </dl>
          {block}
        </article>""")
    return "\n".join(cards)


def quote_struct(data: dict) -> str:
    lo, hi = data["schema"]["struct_lines"]
    return "\n".join(
        f'{f["line"]:>5}  {f["type"]} {f["name"]}'
        + (f' = {f["default"]}' if f["default"] else "")
        + ";"
        for f in data["schema"]["fields"]
    )


def render_markdown(data: dict, units: list[dict]) -> str:
    total_add = sum(data["numstat"].get(p, {}).get("added", 0) for p in PIPELINE)
    total_del = sum(data["numstat"].get(p, {}).get("removed", 0) for p in PIPELINE)
    analysis_add = sum(a["added"] for a in data["analyses"])
    lines = [
        "# Variable-R jets in ColliderBit",
        "",
        f'Baseline `{data["refs"]["baseline"]}` &rarr; head `{data["refs"]["head"]}`.',
        "",
        "## Dependency",
        "",
        "`fastjet::contrib::VariableRPlugin`, a FastJet *plugin* from fjcontrib. That is why",
        "the build had to link `fastjetplugins`, `siscone` and `siscone_spherical` before any",
        "of this could compile.",
        "",
        "## Pipeline files",
        "",
        "| File | Role | Lines |",
        "|---|---|---|",
    ]
    roles = {
        UTILS: "YAML schema, validation, VR key list",
        CONVERSIONS: "clustering and flavour tagging",
        EVENT_H: "named cluster-sequence storage",
        BUCKFAST_HPP: "no-smear list",
        BUCKFAST_CPP: "skips VR when smearing",
        GETBUCKFAST: "fills the no-smear list",
        LHEF: "declines VR at LHE level",
    }
    for path in PIPELINE:
        stat = data["numstat"].get(path, {"added": 0, "removed": 0})
        lines.append(f'| `{Path(path).name}` | {roles[path]} | +{stat["added"]} / -{stat["removed"]} |')
    lines += [
        f"| **total** | 7 files | **+{total_add} / -{total_del}** |",
        "",
        f"Plus {analysis_add} lines across {len(data['analyses'])} new analyses.",
        "",
        "## Numbered additions",
        "",
    ]
    for unit in units:
        lines.append(f'{unit["id"]}. **{unit["title"]}** &mdash; `{Path(unit["file"]).name}`')
    lines += [
        "",
        "## Where VR stops",
        "",
        "Parton-level conversion and the LHEF reader skip VR collections outright; BuckFast",
        "skips them for jet smearing and for the |eta| > 2.5 b-tag clearing pass.",
        "",
        "`Analysis_ATLAS_SUSY_2018_07` does not use the pipeline: it constructs its own",
        "`VariableRPlugin` with hard-coded rho/Rmin/Rmax, so YAML cannot reach it.",
        "",
        "No build or run was performed for this document.",
        "",
    ]
    return "\n".join(lines)


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Variable-R jets in ColliderBit</title>
  <style>
    :root { --paper:#f5f5f5; --paper-2:#ececec; --ink:#2d3142; --muted:#4f5d75; --soft:#7a8399; --rule:rgba(45,49,66,.12); --accent:#eb6c36; --accent-tint:rgba(235,108,54,.08); --green:#4f8a69; --green-tint:#eef8f1; --red:#93513f; --red-tint:#f3e9e5; --font-sans:'Geist',system-ui,sans-serif; --font-mono:'Geist Mono',ui-monospace,monospace; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.55 var(--font-sans); }
    .frame { max-width:1520px; margin:0 auto; padding:42px 42px 64px; }
    .eyebrow,.kicker,.meta,.source,.status,th,footer { font-family:var(--font-mono); }
    .eyebrow { color:var(--muted); font-size:10px; letter-spacing:.16em; text-transform:uppercase; margin:0 0 12px; }
    h1 { font-family:'Instrument Serif',Georgia,serif; font-size:clamp(42px,5vw,72px); font-weight:400; letter-spacing:-.04em; line-height:.98; margin:0 0 14px; }
    h2 { font-size:28px; font-weight:600; letter-spacing:-.03em; line-height:1.08; margin:0 0 8px; }
    p { color:var(--muted); }
    .intro { max-width:1080px; font-size:15px; line-height:1.65; margin:0 0 18px; }
    .meta { display:flex; flex-wrap:wrap; gap:8px 18px; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); padding:12px 0; color:var(--muted); font-size:10px; }
    .meta strong { color:var(--accent); font-weight:600; }
    .note { border-left:3px solid var(--accent); color:var(--muted); font-size:11px; line-height:1.6; margin:18px 0; max-width:1160px; padding:8px 12px; }
    .backlink { align-items:baseline; background:#fff; border:1px solid var(--rule); border-left:3px solid var(--accent);
      border-radius:0 6px 6px 0; color:var(--muted); display:flex; flex-wrap:wrap; font-size:12.5px; gap:4px 12px;
      line-height:1.6; margin:18px 0 0; max-width:1160px; padding:11px 14px; }
    .backlink .lbl { color:var(--soft); font-family:var(--font-mono); font-size:9.5px; letter-spacing:.14em; text-transform:uppercase; }
    .backlink span:last-child { flex:1 1 420px; }
    .backlink a { border-bottom:1px solid rgba(235,108,54,.42); color:var(--accent); font-weight:600; text-decoration:none; }
    .backlink a:hover { background:var(--accent-tint); }
    .summary-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:22px 0 32px; }
    .card { background:#fff; border:1px solid var(--rule); border-radius:6px; padding:14px 16px; }
    .card.accent { border-color:rgba(235,108,54,.45); background:var(--accent-tint); }
    .card .n { color:var(--ink); display:block; font-size:26px; font-weight:600; letter-spacing:-.04em; line-height:1; margin-bottom:8px; }
    .card .label { color:var(--soft); font-family:var(--font-mono); font-size:9px; letter-spacing:.1em; text-transform:uppercase; }
    section { border-top:1px solid var(--rule); margin-top:28px; padding:24px 0 0; }
    .kicker { color:var(--soft); font-size:9px; letter-spacing:.16em; margin:0 0 8px; text-transform:uppercase; }
    .source { color:var(--soft); font-size:10px; line-height:1.55; margin:0 0 14px; }
    .diagram-shell { overflow-x:auto; background:#fff; border:1px solid var(--rule); border-radius:8px; padding:8px; }
    svg { display:block; min-width:1080px; width:100%; height:auto; }
    svg .zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .zone-label { fill:var(--soft); font:500 10px var(--font-mono); letter-spacing:1.6px; }
    svg .node .kind { fill:var(--soft); font:500 9px var(--font-mono); letter-spacing:1.2px; }
    svg .node .title { fill:var(--ink); font:600 12px var(--font-mono); }
    svg .node .body { fill:var(--muted); font:9px var(--font-mono); }
    svg .legend-label { fill:var(--soft); font:9px var(--font-mono); letter-spacing:.6px; }
    svg .detail-edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
    svg .node.detail-primary rect { fill:#fff; stroke:var(--soft); stroke-width:1.2; }
    svg .node.detail-data rect { fill:rgba(79,93,117,.08); stroke:var(--soft); stroke-width:1.2; }
    svg .node.detail-optional rect { fill:#fff; stroke:var(--soft); stroke-width:1.2; stroke-dasharray:5 4; }
    svg .node.detail-focal rect { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    svg .node.detail-focal .kind { fill:var(--accent); }
    .unit-list { display:grid; gap:14px; margin-top:18px; }
    .unit { border:1px solid var(--rule); border-radius:8px; background:#fff; padding:16px 18px; scroll-margin-top:20px; }
    .unit:target { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
    .unit-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
    .unit-num { display:grid; place-items:center; width:26px; height:26px; border-radius:50%;
      border:1.2px solid var(--ink); font:600 13px var(--font-mono); }
    .unit-title { font-size:16px; font-weight:600; letter-spacing:-.01em; }
    .unit-kind { padding:2px 7px; border-radius:3px; border:1px solid currentColor;
      font:8px var(--font-mono); letter-spacing:.9px; text-transform:uppercase;
      color:#4f8a69; background:var(--green-tint); }
    .unit-delta { margin-left:auto; font:11px var(--font-mono); color:var(--soft); }
    .unit-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px 24px; margin:0; }
    .unit-grid > div { display:flex; gap:10px; border-bottom:1px solid var(--rule); padding-bottom:8px; }
    .unit-grid dt { flex:0 0 46px; margin:2px 0 0; color:var(--soft);
      font:9px var(--font-mono); letter-spacing:1px; text-transform:uppercase; }
    .unit-grid dd { margin:0; color:var(--muted); font-size:12.5px; line-height:1.6; }
    .unit-diff { margin-top:11px; border:1px solid var(--rule); border-radius:6px; background:#fff; }
    .unit-diff summary { cursor:pointer; padding:9px 13px; color:var(--accent);
      font:11px var(--font-mono); letter-spacing:.4px; list-style:none; }
    .unit-diff summary::-webkit-details-marker { display:none; }
    .unit-diff summary::before { content:"\25b8 "; display:inline-block; width:14px; }
    .unit-diff[open] summary::before { content:"\25be "; }
    .unit-diff[open] summary { border-bottom:1px solid var(--rule); }
    .unit-diff summary:hover { background:rgba(235,108,54,.05); }
    .unit-hunks { margin:0; padding:12px 14px; overflow-x:auto; font:11px/1.7 var(--font-mono);
      background:#fff; border:0; color:var(--ink); white-space:pre; }
    .diagram-note { color:var(--muted); font-size:12px; line-height:1.6; margin:13px 0 0; max-width:1160px; }
    .mapping-table { overflow-x:auto; border:1px solid var(--rule); }
    .mapping-table table { min-width:900px; }
    table { border-collapse:collapse; font-size:11px; width:100%; }
    th,td { border-bottom:1px solid var(--rule); padding:8px 9px; text-align:left; vertical-align:top; }
    th { background:#ececec; color:var(--muted); font-size:9px; letter-spacing:.08em; text-transform:uppercase; }
    td code { color:var(--ink); font-family:var(--font-mono); font-size:10px; word-break:break-word; }
    td.num { text-align:right; font-family:var(--font-mono); white-space:nowrap; }
    .add { color:var(--green); } .del { color:var(--red); }
    .status { font-size:9px; font-weight:600; letter-spacing:.04em; }
    .status.added-in-right { color:var(--green); } .status.unchanged { color:#b55c2d; }
    footer { border-top:1px solid var(--rule); color:var(--soft); font-size:10px; margin-top:32px; padding-top:14px; }
    @media (max-width:900px) { .frame { padding:30px 20px 48px; } .summary-grid { grid-template-columns:repeat(2,1fr); } .unit-grid { grid-template-columns:1fr; } }
    @media (max-width:560px) { h1 { font-size:44px; } }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit &#183; event pipeline</p>
  <h1>Variable-R jets</h1>
  <p class="intro">How a variable-R jet collection was threaded through ColliderBit: what it depends on, which files it touches, what was filled in at each stage, and the three places where it deliberately does nothing. A VR jet has no fixed radius &mdash; its catchment is <code>rho / p<sub>T</sub></code>, clamped between <code>Rmin</code> and <code>Rmax</code> &mdash; and almost every decision below follows from that one fact.</p>
  <div class="meta"><span><strong>BASELINE</strong> __BASELINE__</span><span><strong>HEAD</strong> __HEAD__</span><span><strong>DEPENDS ON</strong> fjcontrib VariableRPlugin</span><span><strong>STATIC EVIDENCE</strong> no build / no events processed</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page expands <a href="cbs-change-ledger.html#9">slide 9 of the CBS change-ledger deck &#8599;</a>. The build work it rests on is on the <a href="cbs-fastjet-cmake.html#unit-4">FastJet &amp; fjcontrib page &#8599;</a> &mdash; <code>-lVariableR</code> and the FastJet plugin libraries had to exist before one line here could compile.</span></p>
  <div class="summary-grid" aria-label="Summary">
    <div class="card accent"><span class="n">__PIPELINE_FILES__</span><span class="label">pipeline files</span></div>
    <div class="card"><span class="n">+__PIPELINE_ADD__ &#8722;__PIPELINE_DEL__</span><span class="label">pipeline lines</span></div>
    <div class="card accent"><span class="n">__UNIT_COUNT__</span><span class="label">numbered additions</span></div>
    <div class="card"><span class="n">__ANALYSIS_LINES__</span><span class="label">lines &#183; new analyses</span></div>
    <div class="card"><span class="n">__OPTOUT_COUNT__</span><span class="label">deliberate opt-outs</span></div>
  </div>
  <div class="note">Everything below is read from the worktree when this page is generated: line counts from <code>git diff --numstat</code>, YAML keys from the parser, validation text from the throw sites, opt-outs from the <code>continue</code> statements. No CBS binary was built and no events were processed, so nothing here is a statement about physics results.</div>

  <section>
    <p class="kicker">01 &#183; the shape of it</p>
    <h2>One collection, seven stages</h2>
    <p class="source">A VR collection is declared once in YAML and then has to survive parsing, clustering, tagging, storage, the detector model and the analysis API. Each stage needed something.</p>
    <div class="diagram-shell">
      __PIPELINE__
    </div>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:22%">File</th><th>What it contributes</th><th style="width:14%">Lines</th></tr></thead>
      <tbody>__FILE_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">Every one of these is a modification, not a new file. VR jets were not bolted on beside the existing jet path &mdash; they were threaded through it, which is why the fixed-R behaviour had to keep working at each step.</p>
  </section>

  <section>
    <p class="kicker">02 &#183; the dependency</p>
    <h2>What it rests on</h2>
    <p class="source">One class, and everything that class drags in.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:26%">Needed</th><th style="width:24%">Comes from</th><th>Consequence</th></tr></thead>
      <tbody>
        <tr><td><code>fastjet::contrib::VariableRPlugin</code></td><td>fjcontrib 1.049</td>
            <td>The single class the pipeline is built around. Constructed in <code>AKTLIKE</code> mode at <code>Py8EventConversions.hpp:__PLUGIN_LINE__</code>.</td></tr>
        <tr><td>FastJet plugin machinery</td><td>FastJet 3.4.2</td>
            <td>VariableR is a <em>plugin</em>, not a built-in algorithm, so <code>-lfastjetplugins</code> became necessary &mdash; and it pulls both SISCone libraries with it.</td></tr>
        <tr><td><code>-lVariableR</code></td><td>fjcontrib build</td>
            <td>Added to <code>fjcontrib_LDFLAGS</code>, which previously carried only <code>-lRecursiveTools</code>.</td></tr>
        <tr><td>A provisioned FastJet install</td><td>the machine, not the repo</td>
            <td>If the FastJet probe fails, the build falls back to fjcore &mdash; which has no plugin support at all, so VR jets simply cannot exist in that configuration.</td></tr>
      </tbody>
    </table></div>
    <p class="diagram-note">This is the direct reason the build had to change first: the source branch linked FastJet without plugins, and no amount of ColliderBit code would have made <code>VariableRPlugin</code> resolve. The <a href="cbs-fastjet-cmake.html">FastJet &amp; fjcontrib page</a> covers that half.</p>
  </section>

  <section>
    <p class="kicker">03 &#183; what was filled in</p>
    <h2>Seven additions, stage by stage</h2>
    <p class="source">One card per stage, with the reason it was needed and the source it produced.</p>
    <div class="unit-list">
      __UNIT_CARDS__
    </div>
  </section>

  <section>
    <p class="kicker">04 &#183; the contract</p>
    <h2>What a YAML collection may say</h2>
    <p class="source">The settings struct, extracted field by field. Which keys are read depends on the <code>algorithm</code> string.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:16%">Field</th><th style="width:14%">Type</th><th style="width:16%">Default</th><th style="width:20%">Read for</th><th style="width:8%">Line</th></tr></thead>
      <tbody>__SCHEMA_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The VR keys are read with <code>getValue</code>, not <code>getValueOrDef</code> &mdash; the defaults visible in the struct are there for the fixed-R path and for direct construction in C++, not as YAML fallbacks. Omitting <code>rho</code> from a VR collection is an error, not a silent 30.0.</p>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:8%">Line</th><th>Rejected at configure time</th></tr></thead>
      <tbody>__VALIDATION_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The third one is the interesting one: <code>jet_collection_taus</code> may not point at a VR collection. Tau candidates are matched inside a fixed cone, and a collection whose radius changes per jet cannot serve that role &mdash; so rather than producing quietly wrong taus, the configuration is refused.</p>
  </section>

  <section>
    <p class="kicker">05 &#183; the boundaries</p>
    <h2>Where VR jets deliberately do nothing</h2>
    <p class="source">Four sites skip VR collections on purpose. Each is a physics decision written as a <code>continue</code>.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:24%">Site</th><th style="width:40%">Source</th><th>Reason</th></tr></thead>
      <tbody>__OPTOUT_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>One of these has a consequence worth stating aloud.</strong> BuckFast skips VR collections in two loops, and the second is the pass that clears b-tags outside |&eta;| &gt; 2.5. So a VR jet keeps whatever b-tag the truth matching gave it, at any &eta;. Both pipeline analyses cut <code>abseta() &lt; 2.5</code> themselves before using VR jets, so the effect does not reach them &mdash; but an analysis that forgets that cut would inherit b-tags the detector model was supposed to have removed.</p>
  </section>

  <section>
    <p class="kicker">06 &#183; the consumers</p>
    <h2>Three analyses, two ways of asking</h2>
    <p class="source">All three are new on this branch. Two take the collection the pipeline built; one builds its own.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:26%">Analysis</th><th style="width:8%">Lines</th><th>Where its VR jets come from</th><th style="width:14%">|&eta;|&lt;2.5 cut sites</th></tr></thead>
      <tbody>__ANALYSIS_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>The exception is the caveat from the deck, made concrete.</strong> <code>ATLAS_SUSY_2018_07</code> constructs its own <code>VariableRPlugin</code> with <code>rho</code>, <code>Rmin</code> and <code>Rmax</code> hard-coded in the analysis body. It works, but YAML cannot reach it: changing the collection definition in the input file changes nothing for that analysis, and it does not appear in <code>event-&gt;jet_collections()</code>. It is also outside every opt-out above &mdash; the no-smear list is keyed by collection name, and this collection has no name.</p>
    <p class="diagram-note">The recommendation that follows is the one already on the slide: declare the collection in YAML and read it with <code>event-&gt;jets("&lt;key&gt;")</code>. That is the path the validation, the tagging and the detector opt-outs all understand.</p>
  </section>

  <section>
    <p class="kicker">07 &#183; boundary</p>
    <h2>What this page does not claim</h2>
    <p class="source">The usual limits, stated rather than implied.</p>
    <div class="note">This page describes code paths, not results. No CBS binary was built for it and no events were clustered. It does not show that the VR jets produced here match ATLAS's, that the effective-radius flavour matching reproduces the published tagging efficiencies, or that the b-tag working points used in the analyses are right. Those are validation questions and need a run with real events on both sides, which is a separate exercise.</div>
    <p class="diagram-note">What it does establish, from source: which files a VR collection passes through, what each stage contributes, which YAML keys are mandatory, what the configuration refuses, and the four places where VR is deliberately absent.</p>
  </section>

  <p class="backlink"><span class="lbl">return</span><span>Back to <a href="cbs-change-ledger.html#9">the change-ledger deck &#183; slide 9 &#8599;</a>, or across to the <a href="cbs-fastjet-cmake.html">FastJet &amp; fjcontrib build integration &#8599;</a> that made this possible.</span></p>

  <footer>Generated by <code>scripts/build-vrjet-page.py</code>. Baseline <code>__BASELINE__</code>, head <code>__HEAD__</code>.</footer>
</main>
</body>
</html>'''


def render_html(data: dict, units: list[dict]) -> str:
    page = TEMPLATE
    pipeline_add = sum(data["numstat"].get(p, {}).get("added", 0) for p in PIPELINE)
    pipeline_del = sum(data["numstat"].get(p, {}).get("removed", 0) for p in PIPELINE)
    optouts = len(data["optouts"]["skips"]) + len(data["optouts"]["no_smear_sites"])
    replacements = {
        "__BASELINE__": esc(data["refs"]["baseline"]),
        "__HEAD__": esc(data["refs"]["head"]),
        "__PIPELINE_FILES__": str(len(PIPELINE)),
        "__PIPELINE_ADD__": str(pipeline_add),
        "__PIPELINE_DEL__": str(pipeline_del),
        "__UNIT_COUNT__": str(len(units)),
        "__ANALYSIS_LINES__": str(sum(a["added"] for a in data["analyses"])),
        "__OPTOUT_COUNT__": str(optouts),
        "__PIPELINE__": pipeline_svg(data),
        "__FILE_ROWS__": file_rows(data),
        "__UNIT_CARDS__": unit_cards(data, units),
        "__SCHEMA_ROWS__": schema_rows(data),
        "__VALIDATION_ROWS__": validation_rows(data),
        "__OPTOUT_ROWS__": optout_rows(data),
        "__ANALYSIS_ROWS__": analysis_rows(data),
        "__PLUGIN_LINE__": str(data["clustering"]["plugin"]["line"]),
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path,
                        default=Path("/Users/p.zhu/Gambit-Workshop/gambit"))
    parser.add_argument("--baseline-ref", default="9c955e3a7")
    parser.add_argument("--html", type=Path, default=Path("dependences/cbs-vr-jets.html"))
    parser.add_argument("--json", type=Path, default=Path("dependences/cbs-vr-jets.json"))
    parser.add_argument("--markdown", type=Path, default=Path("dependences/CBS_VR_JETS.md"))
    parser.add_argument("--site-html", type=Path, default=Path("site/cbs-vr-jets.html"))
    args = parser.parse_args()

    root = args.gambit_root.expanduser().resolve()
    data = collect(root, args.baseline_ref)
    units = change_units(data)

    page = render_html(data, units)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(page)
    args.site_html.parent.mkdir(parents=True, exist_ok=True)
    args.site_html.write_text(page)
    payload = json.loads(json.dumps(data, default=str))
    payload["units"] = units
    args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(render_markdown(data, units))

    print(json.dumps({
        "pipeline_files": len(PIPELINE),
        "pipeline_lines": f"+{sum(data['numstat'].get(p, {}).get('added', 0) for p in PIPELINE)}"
                          f"/-{sum(data['numstat'].get(p, {}).get('removed', 0) for p in PIPELINE)}",
        "units": len(units),
        "schema_fields": len(data["schema"]["fields"]),
        "vr_keys": [k["key"] for k in data["schema"]["vr_keys"]],
        "validations": len(data["schema"]["validations"]),
        "optouts": len(data["optouts"]["skips"]) + len(data["optouts"]["no_smear_sites"]),
        "analyses": len(data["analyses"]),
    }, sort_keys=True))
    for path in (args.json, args.html, args.markdown, args.site_html):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
