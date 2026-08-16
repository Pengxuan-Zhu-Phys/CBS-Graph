#!/usr/bin/env python3
"""Harvest metadata from all ColliderBit analyses into catalogue.json / catalogue.md.

Run from anywhere inside the gambit repo:

    python3 P.Zhu/docs/analyses/harvest_analyses.py

It scans ColliderBit/src/analyses/Analysis_*.cpp and the matching .info files,
cross-references the registration macros in AnalysisContainer.cpp, and writes

    P.Zhu/docs/analyses/catalogue.json   (machine-readable, for agents/tools)
    P.Zhu/docs/analyses/catalogue.md     (human-readable tables)

Re-run after adding/registering a new analysis to refresh the catalogue.
"""

import json
import os
import re
import sys
from datetime import date

# ----------------------------------------------------------------------------
# Locate repo root (the directory containing ColliderBit/)
# ----------------------------------------------------------------------------
here = os.path.abspath(os.path.dirname(__file__))
root = here
while root != "/" and not os.path.isdir(os.path.join(root, "ColliderBit", "src", "analyses")):
    root = os.path.dirname(root)
if root == "/":
    sys.exit("Could not locate gambit repo root (no ColliderBit/src/analyses found)")

ANA_DIR = os.path.join(root, "ColliderBit", "src", "analyses")
CONTAINER = os.path.join(ANA_DIR, "AnalysisContainer.cpp")

# ----------------------------------------------------------------------------
# Parse registration macros in AnalysisContainer.cpp
# ----------------------------------------------------------------------------
registered = {}  # name -> registration group
with open(CONTAINER) as f:
    text = f.read()

for group in ("MAP_ANALYSES_WITH_ROOT_RESTFRAMES", "MAP_ANALYSES_WITH_ROOT",
              "MAP_ANALYSES_WITH_ONNX", "MAP_ANALYSES"):
    m = re.search(r"#define %s\(F\)" % group, text)
    if not m:
        continue
    # A macro definition continues while lines end with a backslash.
    block_lines = []
    for line in text[m.end():].splitlines():
        block_lines.append(line)
        if not line.rstrip().endswith("\\"):
            break
    for name in re.findall(r"\bF\((\w+)\)", "\n".join(block_lines)):
        registered.setdefault(name, group)

# ----------------------------------------------------------------------------
# Technique detection patterns (token -> human label)
# ----------------------------------------------------------------------------
TECH_PATTERNS = [
    (r"\bmt2_bisect|\bMT2|asymm_mt2", "MT2"),
    (r"METSignificance", "MET significance"),
    (r"RestFrames", "RestFrames (RJR)"),
    (r"onnx|Ort::", "ONNX neural net"),
    (r"\bBDT\b|Forest|xgboost|XGBoost|TMVA|LGBM", "BDT/MVA"),
    (r"topness", "Topness"),
    (r"ClusterSequence|fastjet::|FastJet", "FastJet reclustering"),
    (r"vrjets|VRJet", "Variable-R jets"),
    (r'jets\(\s*"antikt_R10"|largeRJets|fatjet|FatJet', "Large-R jets"),
    (r"Nsubjettiness|tau21|tau32", "N-subjettiness"),
    (r"lester|cheated_bisect", "Lester MT2"),
    (r"DEFINE_HISTOGRAM_SR", "Histogram-backed SRs"),
    (r"DEFINE_HISTOGRAM", "Histograms"),
]

INFO_KEYS = ("Summary", "InspireID", "ExptRun", "Lumi_ifb", "Ecm_TeV", "OldName")

entries = []
for fn in sorted(os.listdir(ANA_DIR)):
    if not (fn.startswith("Analysis_") and fn.endswith(".cpp")):
        continue
    if fn in ("Analysis_Dummy.cpp",):
        pass  # keep special analyses; they are documented as 'special'
    path = os.path.join(ANA_DIR, fn)
    with open(path, errors="replace") as f:
        src = f.read()

    stem = fn[len("Analysis_"):-len(".cpp")]

    classes = re.findall(r"class\s+Analysis_(\w+)\s*:\s*public\s+(\w+)", src)
    factories = re.findall(r"DEFINE_ANALYSIS_FACTORY\(\s*(\w+)\s*\)", src)
    detectors = re.findall(r'detector\s*=\s*"(\w+)"', src)
    names = re.findall(r'set_analysis_name\("([^"]+)"\)', src)
    lumis = re.findall(r"set_luminosity\(([\d.eE+-]+)\)", src)
    n_sr_macro = len(re.findall(r"\bDEFINE_SIGNAL_REGION(?:_NOCUTS)?\(", src))
    n_sr_multi = re.findall(r"\bDEFINE_SIGNAL_REGIONS(?:_NOCUTS)?\(\s*\"?[\w]*\"?\s*,\s*(\d+)", src)
    n_sr_legacy = len(set(re.findall(r'_counters\[\s*"([^"]+)"\s*\]', src)))
    n_commit = len(re.findall(r"\b(?:COMMIT_SIGNAL_REGION|add_result)\s*\(", src))
    has_cov = bool(re.search(r"set_covariance|COMMIT_COVARIANCE_MATRIX", src))
    has_fulllikes = bool(re.search(r"set_bkgjson", src))
    has_cutflow = bool(re.search(r"ADD_CUTFLOW|addCutflow|COMMIT_CUTFLOWS", src))
    techniques = sorted({label for pat, label in TECH_PATTERNS if re.search(pat, src)})

    info = {}
    info_path = path[:-4] + ".info"
    if os.path.exists(info_path):
        with open(info_path, errors="replace") as f:
            for line in f:
                m = re.match(r"^(\w+):\s*(.*)$", line.strip())
                if m and m.group(1) in INFO_KEYS:
                    info[m.group(1)] = m.group(2).strip()

    sr_count = n_sr_macro + sum(int(n) for n in n_sr_multi) or n_sr_legacy

    entries.append({
        "file": "ColliderBit/src/analyses/" + fn,
        "stem": stem,
        "classes": [c[0] for c in classes],
        "registered_names": [n for n in factories if n in registered],
        "unregistered_factories": [n for n in factories if n not in registered],
        "registration_group": next((registered[n] for n in factories if n in registered), None),
        "detector": detectors[0] if detectors else None,
        "analysis_names": names,
        "luminosity_invfb": lumis[0] if lumis else info.get("Lumi_ifb"),
        "n_signal_regions": sr_count,
        "n_committed_results": n_commit,
        "covariance": has_cov,
        "fulllikes_bkgjson": has_fulllikes,
        "cutflows": has_cutflow,
        "techniques": techniques,
        "info": info,
        "has_info_file": os.path.exists(info_path),
    })

# Registered names with no cpp factory found (e.g. registration typos)
all_factories = {n for e in entries for n in e["registered_names"] + e["unregistered_factories"]}
orphan_registrations = sorted(set(registered) - all_factories)

result = {
    "generated": str(date.today()),
    "generator": "P.Zhu/docs/analyses/harvest_analyses.py",
    "n_source_files": len(entries),
    "n_registered_analysis_names": len(registered),
    "orphan_registrations": orphan_registrations,
    "analyses": entries,
}

out_json = os.path.join(here, "catalogue.json")
with open(out_json, "w") as f:
    json.dump(result, f, indent=2)

# ----------------------------------------------------------------------------
# Markdown rendering
# ----------------------------------------------------------------------------
def yesno(b):
    return "yes" if b else ""

def exp_of(stem):
    if stem.startswith("ATLAS"):
        return "ATLAS"
    if stem.startswith("CMS"):
        return "CMS"
    return "Special"

lines = []
lines.append("# ColliderBit analysis catalogue")
lines.append("")
lines.append(f"*Generated {result['generated']} by `harvest_analyses.py` — do not edit by hand; re-run the script instead.*")
lines.append("")
lines.append(f"- Source files scanned: **{len(entries)}**")
lines.append(f"- Registered analysis names (in `AnalysisContainer.cpp`): **{len(registered)}**")
if orphan_registrations:
    lines.append(f"- **WARNING** registered names with no factory found: {', '.join(orphan_registrations)}")
lines.append("")
lines.append("Registration groups: `MAP_ANALYSES` (plain), `MAP_ANALYSES_WITH_ROOT` (needs ROOT), "
             "`MAP_ANALYSES_WITH_ROOT_RESTFRAMES` (needs ROOT+RestFrames), `MAP_ANALYSES_WITH_ONNX` (needs ONNXRuntime).")
lines.append("")

for exp in ("ATLAS", "CMS", "Special"):
    sub = [e for e in entries if exp_of(e["stem"]) == exp]
    if not sub:
        continue
    lines.append(f"## {exp} ({len(sub)} source files)")
    lines.append("")
    lines.append("| Source stem | Detector | √s (TeV) | Lumi (fb⁻¹) | #SR | Cov. | FullLikes | Techniques | Registered variants | InspireID |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for e in sub:
        ecm = e["info"].get("Ecm_TeV", "")
        lumi = e["luminosity_invfb"] or ""
        variants = ", ".join(e["registered_names"]) or "(none)"
        if e["unregistered_factories"]:
            variants += " / UNREGISTERED: " + ", ".join(e["unregistered_factories"])
        tech = ", ".join(e["techniques"])
        inspire = e["info"].get("InspireID", "")
        lines.append(f"| {e['stem']} | {e['detector'] or ''} | {ecm} | {lumi} | "
                     f"{e['n_signal_regions']} | {yesno(e['covariance'])} | {yesno(e['fulllikes_bkgjson'])} | "
                     f"{tech} | {variants} | {inspire} |")
    lines.append("")

with open(os.path.join(here, "catalogue.md"), "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Wrote {out_json}")
print(f"Wrote {os.path.join(here, 'catalogue.md')}")
print(f"{len(entries)} source files, {len(registered)} registered names, "
      f"{len(orphan_registrations)} orphan registrations")
