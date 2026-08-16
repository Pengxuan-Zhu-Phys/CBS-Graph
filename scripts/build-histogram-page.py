#!/usr/bin/env python3
"""Render the ColliderBit histogram page.

One class, `Histogram1D`, does two jobs, and the difference between them is
whether one vector is empty:

  plain histogram   bins, counts, sumw2, under/overflow. A diagnostic object.
                    Nothing downstream reads it as physics.
  signal-region     the same, plus per-bin observed / background / background
                    error. `to_signal_regions()` then turns every bin into a
                    SignalRegionData that enters the likelihood.

That is the whole distinction, and it is worth being precise about, because a
YAML flag named `check_histogram` gates both -- so on one analysis the flag
changes how many signal regions contribute to the likelihood.

Bin edges, observed and background arrays, macro definitions, the JSON field
names and the batch merge path are all extracted from the worktree.  Nothing
is built or run.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

HISTOGRAM_HPP = "ColliderBit/include/gambit/ColliderBit/analyses/Histogram.hpp"
MACROS_HPP = "ColliderBit/include/gambit/ColliderBit/analyses/AnalysisMacros.hpp"
ANALYSIS_HPP = "ColliderBit/include/gambit/ColliderBit/analyses/Analysis.hpp"
ANALYSIS_DATA = "ColliderBit/include/gambit/ColliderBit/analyses/AnalysisData.hpp"
SOLO = "ColliderBit/examples/solo.cpp"
SOLO_OUTPUT = "ColliderBit/examples/solo_output.cpp"
SOLO_BATCH = "ColliderBit/examples/solo_batch.cpp"
PLOTTER = "ColliderBit/scripts/plot_cbs_histograms.py"

BASE = "9c955e3a78"

CONSUMERS = [
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_04.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_07.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2021_35.cpp",
]

TOUCHED = [HISTOGRAM_HPP, MACROS_HPP, ANALYSIS_HPP, ANALYSIS_DATA,
           SOLO, SOLO_OUTPUT, SOLO_BATCH, PLOTTER]


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
    return "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(lo, min(hi, len(lines)) + 1))


def macro_table(macros: list[str]) -> list[dict]:
    """Every histogram macro, with the body it expands to."""
    out = []
    for index, line in enumerate(macros):
        match = re.match(r"#define\s+((?:DEFINE|FILL|COMMIT)_HISTOGRAM\w*)\s*(\([^)]*\))?", line)
        if not match:
            continue
        body, probe = [], index
        while probe < len(macros) and macros[probe].rstrip().endswith("\\"):
            probe += 1
            body.append(macros[probe].strip().rstrip("\\").strip())
        doc = macros[index - 1].strip().lstrip("/ ") if index and \
            macros[index - 1].strip().startswith("///") else ""
        out.append({
            "name": match.group(1),
            "args": (match.group(2) or "").strip("()"),
            "body": " ".join(b for b in body if b),
            "doc": doc,
            "line": index + 1,
        })
    return out


def numbers(text: str) -> list[float]:
    return [float(v) for v in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", text)]


def array_after(src: list[str], index: int) -> list[float]:
    """Collect a brace-delimited numeric initialiser starting at `index`."""
    blob, probe = src[index], index
    while blob.count("{") > blob.count("}") and probe < len(src) - 1:
        probe += 1
        blob += " " + src[probe]
    inner = blob[blob.index("{") + 1:blob.rindex("}")] if "{" in blob and "}" in blob else ""
    return numbers(inner)


def analyse_consumer(root: Path, path: str) -> dict:
    src = lines_of(root, path)
    name = Path(path).stem.replace("Analysis_", "")

    sr_defs, plain_defs = [], []
    for i in find_all(src, r"DEFINE_HISTOGRAM_SR_1D\("):
        hname = re.search(r'DEFINE_HISTOGRAM_SR_1D\(\s*"([^"]+)"', src[i])
        if not hname:
            continue
        # The bin/obs/bkg arrays are declared just above the macro call.
        block = {}
        for key, pattern in (("edges", r"_bins\s*=\s*\{"), ("obs", r"_obs\s*=\s*\{"),
                             ("bkg", r"_bkg\s*=\s*\{"), ("bkg_err", r"_bkg_err\s*=\s*\{")):
            spot = next((j for j in range(max(0, i - 14), i)
                         if re.search(pattern, src[j])), None)
            block[key] = array_after(src, spot) if spot is not None else []
        sr_defs.append({"hist": hname.group(1), "line": i + 1, **block,
                        "nbins": max(0, len(block["edges"]) - 1)})

    for i in find_all(src, r"DEFINE_HISTOGRAM_1D_UNIFORM\(|DEFINE_HISTOGRAM_1D\(|DEFINE_HISTOGRAM_2D"):
        hname = re.search(r'\(\s*"([^"]+)"', src[i])
        args = numbers(src[i][src[i].index('"', src[i].index('"') + 1):])
        plain_defs.append({
            "hist": hname.group(1) if hname else "?",
            "line": i + 1,
            "uniform": "UNIFORM" in src[i],
            "args": args[:3],
        })

    # Each histogram is booked twice -- in the constructor and again in
    # analysis_specific_reset() -- so count distinct names, not call sites.
    def dedup(defs: list[dict]) -> list[dict]:
        seen, out = set(), []
        for d in defs:
            if d["hist"] in seen:
                continue
            seen.add(d["hist"])
            out.append(d)
        return out

    sr_defs, plain_defs = dedup(sr_defs), dedup(plain_defs)

    live = [i for i in range(len(src)) if not src[i].lstrip().startswith("//")]
    commit_srs = dedup([{"line": i + 1, "hist": re.search(r'\(\s*"([^"]+)"', src[i]).group(1)}
                        for i in find_all(src, r"COMMIT_HISTOGRAM_SRS\(")
                        if re.search(r'\(\s*"([^"]+)"', src[i])])

    # Cut-and-count regions are committed two ways in this codebase: through the
    # macro, or by constructing SignalRegionData directly. Commented-out lines
    # are excluded -- one analysis keeps a whole block of them, see below.
    counting_srs = [i + 1 for i in live
                    if re.search(r"COMMIT_SIGNAL_REGION\(|add_result\(\s*SignalRegionData\(", src[i])]

    # The block this feature replaced: hand-written per-bin signal regions,
    # still present as comments in one analysis.
    retired_manual = [i + 1 for i in range(len(src))
                      if src[i].lstrip().startswith("//")
                      and re.search(r"add_result\(\s*SignalRegionData\(.*_bin", src[i])]

    gated = len(find_all(src, r"Histogram1D::check_histogram\(\)"))
    fills = len(find_all(src, r"FILL_HISTOGRAM_"))

    # The same three stages on both sides, quoted from source: where the
    # histogram is booked, where it is filled, where it is committed.
    def stage(pattern: str, before: int, after: int) -> dict:
        spot = next((i for i in find_all(src, pattern) if not src[i].lstrip().startswith("//")), None)
        if spot is None:
            return {"line": None, "code": ""}
        lo, hi = max(1, spot + 1 - before), min(len(src), spot + 1 + after)
        return {"line": spot + 1, "code": quote(src, lo, hi)}

    book_pat = (r"DEFINE_HISTOGRAM_SR_1D\(" if sr_defs else
                r"DEFINE_HISTOGRAM_1D_UNIFORM\(|DEFINE_HISTOGRAM_1D\(")

    # The return type is sometimes on the previous line, so anchor on the name
    # and its empty argument list rather than on a full signature.
    body_open = next((i for i in find_all(src, r"collect_results\s*\(\s*\)")
                      if i + 1 < len(src) and src[i + 1].strip().startswith("{")), None)
    if body_open is not None:
        close = next((j for j in range(body_open, len(src))
                      if src[j].strip() in ("}", "};")), body_open + 9)
        commit = {"line": body_open + 1, "code": quote(src, body_open + 1, close + 1)}
    else:
        commit = {"line": None, "code": ""}

    example = {
        "book": stage(book_pat, 4 if sr_defs else 2, 2 if sr_defs else 2),
        "fill": stage(r"FILL_HISTOGRAM_1D\(", 1, 1),
        "commit": commit,
    }

    hist_srs = sum(d["nbins"] for d in sr_defs if any(c["hist"] == d["hist"] for c in commit_srs))
    return {
        "path": path,
        "name": name,
        "mode": "signal region" if commit_srs else "plain",
        "sr_defs": sr_defs,
        "plain_defs": plain_defs,
        "commit_srs": commit_srs,
        "counting_srs": counting_srs,
        "retired_manual": retired_manual,
        "example": example,
        "gates": gated,
        "fills": fills,
        "srs_without_flag": len(counting_srs),
        "srs_with_flag": len(counting_srs) + hist_srs,
    }


def collect(root: Path) -> dict:
    hist = lines_of(root, HISTOGRAM_HPP)
    macros = lines_of(root, MACROS_HPP)
    solo = lines_of(root, SOLO)
    batch = lines_of(root, SOLO_BATCH)
    output = lines_of(root, SOLO_OUTPUT)

    struct_lines = {}
    for struct in ("Histogram1D", "Histogram2D", "Histograms"):
        lo = find(hist, rf"struct {struct}\b")
        struct_lines[struct] = lo + 1

    # The members that decide which of the two jobs an object is doing.
    members = []
    lo = find(hist, r"// ----- Data members -----")
    hi = find(hist, r"// ----- Constructors -----", lo)
    for i in range(lo, hi):
        match = re.match(r"\s*([\w:<>, ]+?)\s+(\w+);\s*(?://[/<]*\s*(.*))?$", hist[i])
        if match:
            members.append({"type": match.group(1).strip(), "name": match.group(2),
                            "doc": (match.group(3) or "").strip(), "line": i + 1})

    sr_predicate = find(hist, r"bool is_signal_region\(\) const")
    to_srs = find(hist, r"std::vector<SignalRegionData> to_signal_regions\(\) const")
    sr_name = find(hist, r'name \+ "_bin" \+ std::to_string')
    validate = find(hist, r"void validate_signal_region_data\(\) const")
    combine = find(hist, r"void combine\(const Histogram1D& other\)")

    switch_read = find(solo, r'getValueOrDef<bool>\(false, "check_histogram"\)')
    switch_set = find(solo, r"Histogram1D::set_check_histogram")

    json_fields = []
    lo = find(output, r"nlohmann::json build_histograms_json")
    hi = find(output, r"^\s*\}\s*$", find(output, r"return .*;", lo))
    for i in range(lo, hi):
        match = re.search(r'(?:hobj|bin|counts_2d|sw2_row)\["([\w_]+)"\]\s*=', output[i])
        if match:
            json_fields.append({"key": match.group(1), "line": i + 1})

    merge = {
        "parse": find(batch, r"Histograms parse_histograms_or_empty") + 1,
        "accumulate": find(batch, r"void accumulate_histograms") + 1,
        "scale": find(batch, r"weighted_histograms\.scale\(process_weight\)") + 1,
        "guard": find(batch, r"Inconsistent number of histograms across batch runs") + 1,
    }

    consumers = [analyse_consumer(root, path) for path in CONSUMERS]

    numstat = {}
    raw = git(root, "diff", "--numstat", "-M", BASE, "HEAD", "--", *TOUCHED)
    for row in raw.splitlines():
        added, removed, path = row.split("\t")
        numstat[path] = {"added": int(added) if added != "-" else 0,
                         "removed": int(removed) if removed != "-" else 0}
    status = {}
    for row in git(root, "diff", "--name-status", "-M", BASE, "HEAD", "--", *TOUCHED).splitlines():
        parts = row.split("\t")
        status[parts[-1]] = parts[0]

    return {
        "generated_by": "scripts/build-histogram-page.py",
        "refs": {"baseline": BASE, "head": git(root, "rev-parse", "--short", "HEAD").strip()},
        "struct_lines": struct_lines,
        "members": members,
        "hist_lines": len(hist),
        "anchors": {
            "is_signal_region": {"line": sr_predicate + 1, "text": hist[sr_predicate].strip()},
            "to_signal_regions": {"line": to_srs + 1},
            "sr_naming": {"line": sr_name + 1, "text": hist[sr_name].strip()},
            "validate": {"line": validate + 1},
            "combine": {"line": combine + 1},
        },
        "excerpts": {
            "predicate": quote(hist, sr_predicate + 1, sr_predicate + 1),
            "to_srs": quote(hist, to_srs + 1, to_srs + 22),
            "validate": quote(hist, validate + 1, validate + 9),
            "switch": quote(solo, switch_read, switch_set + 1),
        },
        "switch": {
            "read": {"line": switch_read + 1, "text": solo[switch_read].strip()},
            "set": {"line": switch_set + 1, "text": solo[switch_set].strip()},
            "default": False,
        },
        "macros": macro_table(macros),
        "json_fields": json_fields,
        "merge": merge,
        "consumers": consumers,
        "numstat": numstat,
        "status": status,
        "plotter_lines": len(lines_of(root, PLOTTER)),
        "caveat": "Static read of the worktree. Nothing was built or run.",
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def modes_svg(data: dict) -> str:
    """One class, two jobs, forking on whether obs is empty."""
    width, height = 1240, 330
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="hm-t hm-d">',
        '<title id="hm-t">The two jobs one Histogram1D does</title>',
        '<desc id="hm-d">A Histogram1D booked without observed and background arrays stays a '
        'diagnostic object that only reaches the JSON output and the plotter. Booked with them, '
        'every bin also becomes a SignalRegionData that enters the likelihood.</desc>',
        '<defs><marker id="hm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]

    def box(x, y, w, h, cls, kind, title, subs):
        out.append(f'<g class="node {cls}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>')
        out.append(f'<text class="kind" x="{x + 13}" y="{y + 21}">{esc(kind)}</text>')
        out.append(f'<text class="title" x="{x + 13}" y="{y + 41}" style="font-size:11px">{esc(title)}</text>')
        for i, chunk in enumerate(subs):
            out.append(f'<text class="body" x="{x + 13}" y="{y + 59 + i * 13}">{esc(chunk)}</text>')
        out.append("</g>")

    box(20, 120, 196, 92, "detail-data", "BOOK",
        "DEFINE_HISTOGRAM_*", ["edges, name, x label", "one object either way"])
    box(238, 120, 168, 92, "detail-focal", "FORK",
        "obs.empty()?", [f'L{data["anchors"]["is_signal_region"]["line"]}', "the only difference"])

    box(430, 20, 300, 92, "detail-primary", "PLAIN HISTOGRAM",
        "is_signal_region() == false", ["counts + sumw2 only", "never reaches the likelihood"])
    box(430, 218, 300, 92, "detail-focal", "SIGNAL-REGION HISTOGRAM",
        "is_signal_region() == true", ["obs / bkg / bkg_err per bin",
                                       "to_signal_regions() -> one SR per bin"])

    box(756, 20, 210, 92, "detail-data", "OUT",
        "JSON histograms", ["read back by batch merge", "plotted by the script"])
    box(756, 218, 210, 92, "detail-data", "OUT",
        "add_result(sr)", ["name_bin0 ... name_binN", "enters the likelihood"])

    box(990, 120, 230, 92, "detail-optional", "GATE",
        "check_histogram", [f'solo.cpp:{data["switch"]["read"]["line"]}',
                            "default false — gates both"])

    for d in ["M216 166 H233", "M406 166 H418 V66 H425", "M406 166 H418 V264 H425",
              "M730 66 H751", "M730 264 H751", "M966 66 H978 V166 H985",
              "M966 264 H978 V166 H985"]:
        out.append(f'<path class="detail-edge" d="{d}" marker-end="url(#hm-arrow)"/>')

    out.append('<text class="legend-label" x="20" y="252">one class, one booking macro family;</text>')
    out.append('<text class="legend-label" x="20" y="270">the fork is a single empty-vector test</text>')
    out.append("</svg>")
    return "\n".join(out)


def consumer_rows(data: dict) -> str:
    rows = []
    for c in data["consumers"]:
        mode = ("<span class=\"status unchanged\">signal region</span>"
                if c["mode"] == "signal region"
                else "<span class=\"status added-in-right\">plain</span>")
        hists = ", ".join(f'<code>{esc(d["hist"])}</code>'
                          for d in (c["sr_defs"] or c["plain_defs"]))
        if c["srs_with_flag"] != c["srs_without_flag"]:
            srs = (f'<strong>{c["srs_without_flag"]} &rarr; {c["srs_with_flag"]}</strong>'
                   '<span class="ln">flag off &rarr; on</span>')
        else:
            srs = f'{c["srs_without_flag"]}<span class="ln">unaffected by the flag</span>'
        rows.append(
            f'<tr><td><code>{esc(c["name"])}</code></td>'
            f'<td>{mode}</td><td>{hists}</td>'
            f'<td class="num">{sum(d["nbins"] for d in c["sr_defs"]) or "&#8212;"}</td>'
            f'<td>{srs}</td></tr>'
        )
    return "\n".join(rows)


def macro_rows(data: dict) -> str:
    return "\n".join(
        f'<tr><td><code>{esc(m["name"])}</code></td>'
        f'<td><code>{esc(m["args"])}</code></td>'
        f'<td><code>{esc(m["body"][:120])}</code></td></tr>'
        for m in data["macros"]
    )


def member_rows(data: dict) -> str:
    sr_only = {"obs", "bkg", "bkg_err"}
    rows = []
    for m in data["members"]:
        tag = ('<span class="status unchanged">signal region only</span>'
               if m["name"] in sr_only else '<span class="status">always</span>')
        rows.append(f'<tr><td><code>{esc(m["name"])}</code></td>'
                    f'<td><code>{esc(m["type"])}</code></td>'
                    f'<td>{tag}</td><td>{esc(m["doc"])}</td></tr>')
    return "\n".join(rows)


def file_rows(data: dict) -> str:
    roles = {
        HISTOGRAM_HPP: "the class itself: Histogram1D, Histogram2D, and the Histograms container",
        MACROS_HPP: "the booking, filling and committing macros",
        ANALYSIS_HPP: "<code>_histograms</code> member and <code>add_histograms</code>",
        ANALYSIS_DATA: "carries the histograms alongside the signal regions",
        SOLO: "reads <code>check_histogram</code> from YAML and sets the global switch",
        SOLO_OUTPUT: "serialises histograms into the run JSON",
        SOLO_BATCH: "parses them back, scales by process weight, accumulates across files",
        PLOTTER: "renders the JSON histograms",
    }
    rows = []
    total_add = total_del = 0
    for path in TOUCHED:
        stat = data["numstat"].get(path, {"added": 0, "removed": 0})
        total_add += stat["added"]
        total_del += stat["removed"]
        state = data["status"].get(path, "M")
        badge = ('<span class="status added-in-right">new file</span>'
                 if state.startswith("A") else '<span class="status">modified</span>')
        rows.append(
            f'<tr><td><code>{esc(Path(path).name)}</code></td>'
            f'<td>{badge}</td><td>{roles.get(path, "")}</td>'
            f'<td class="num"><span class="add">+{stat["added"]}</span> '
            f'<span class="del">&minus;{stat["removed"]}</span></td></tr>'
        )
    rows.append(f'<tr><td><strong>total</strong></td><td></td>'
                f'<td>{len(TOUCHED)} files</td>'
                f'<td class="num"><strong><span class="add">+{total_add}</span> '
                f'<span class="del">&minus;{total_del}</span></strong></td></tr>')
    return "\n".join(rows)


def json_rows(data: dict) -> str:
    seen, rows = set(), []
    for field in data["json_fields"]:
        if field["key"] in seen:
            continue
        seen.add(field["key"])
        rows.append(f'<tr><td><code>{esc(field["key"])}</code></td>'
                    f'<td class="num">{field["line"]}</td></tr>')
    return "\n".join(rows)


def render_markdown(data: dict) -> str:
    lines = [
        "# Histograms in ColliderBit",
        "",
        f'Baseline `{data["refs"]["baseline"]}` &rarr; head `{data["refs"]["head"]}`.',
        "",
        "## One class, two jobs",
        "",
        "`Histogram1D` is a plain histogram when its `obs` vector is empty and a",
        "signal-region histogram when it is not. That single test at",
        f'`Histogram.hpp:{data["anchors"]["is_signal_region"]["line"]}` is the whole distinction.',
        "",
        "A plain histogram reaches the JSON output and the plotter and stops there.",
        "A signal-region histogram additionally turns every bin into a `SignalRegionData`",
        f'named `<hist>_bin<i>` (`Histogram.hpp:{data["anchors"]["sr_naming"]["line"]}`), which",'
        " enters the likelihood.",
        "",
        "## Consumers",
        "",
        "| Analysis | Mode | Histogram | Bins | Signal regions |",
        "|---|---|---|---|---|",
    ]
    for c in data["consumers"]:
        hists = ", ".join(d["hist"] for d in (c["sr_defs"] or c["plain_defs"]))
        srs = (f'{c["srs_without_flag"]} -> {c["srs_with_flag"]}'
               if c["srs_with_flag"] != c["srs_without_flag"] else str(c["srs_without_flag"]))
        lines.append(f'| `{c["name"]}` | {c["mode"]} | `{hists}` | '
                     f'{sum(d["nbins"] for d in c["sr_defs"]) or "-"} | {srs} |')
    lines += [
        "",
        "## The flag",
        "",
        f'`check_histogram` is read from YAML at `solo.cpp:{data["switch"]["read"]["line"]}`',
        "and **defaults to false**. It gates booking, filling and committing.",
        "",
        "On the two signal-region analyses it therefore changes how many signal regions",
        "reach the likelihood, which is more than a diagnostic switch normally does.",
        "",
        "No build or run was performed for this document.",
        "",
    ]
    return "\n".join(lines)


CSS = Path(__file__).with_name("_page_css.html")


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Histograms in ColliderBit</title>
__CSS__
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit &#183; analysis layer</p>
  <h1>Histograms</h1>
  <p class="intro">One class does two jobs. Booked one way it is a diagnostic object that reaches the JSON output and the plotter and stops. Booked the other way every bin becomes a signal region that enters the likelihood. The difference is whether one vector is empty &mdash; and a single YAML flag, defaulting to off, gates both.</p>
  <div class="meta"><span><strong>BASELINE</strong> __BASELINE__</span><span><strong>HEAD</strong> __HEAD__</span><span><strong>NEW FILE</strong> Histogram.hpp, __HIST_LINES__ lines</span><span><strong>STATIC EVIDENCE</strong> no build / no events processed</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page expands <a href="cbs-change-ledger.html#8">slide 7 of the CBS change-ledger deck &#8599;</a>. The JSON fields it produces are part of the <a href="cbs-json-output.html">output contract &#8599;</a>, and the batch merge reads them back.</span></p>

  <div class="summary-grid" aria-label="Summary">
    <div class="card accent"><span class="n">__FILES__</span><span class="label">files touched</span></div>
    <div class="card"><span class="n">__HIST_LINES__</span><span class="label">lines &#183; Histogram.hpp</span></div>
    <div class="card"><span class="n">__MACROS__</span><span class="label">booking macros</span></div>
    <div class="card accent"><span class="n">__SR_ANALYSES__</span><span class="label">use SR mode</span></div>
    <div class="card"><span class="n">__PLAIN_ANALYSES__</span><span class="label">use plain mode</span></div>
    <div class="card accent"><span class="n">__EXTRA_SRS__</span><span class="label">SRs the flag adds</span></div>
  </div>
  <div class="note">Bin edges, observed and background arrays, macro bodies, JSON field names and the batch merge sites are read from the worktree when this page is generated. Nothing was compiled and no events were processed, so nothing here is a statement about yields.</div>

  <section id="two-jobs">
    <p class="kicker">01 &#183; one class, two jobs</p>
    <h2>The fork is an empty vector</h2>
    <p class="source">There is no <code>HistogramSR</code> type. The same object behaves differently depending on how it was booked.</p>
    <div class="diagram-shell">__MODES__</div>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:16%">Member</th><th style="width:24%">Type</th><th style="width:18%">Present when</th><th>What it holds</th></tr></thead>
      <tbody>__MEMBER_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">Three members carry the whole distinction: <code>obs</code>, <code>bkg</code> and <code>bkg_err</code>. <code>is_signal_region()</code> is literally <code>return !obs.empty();</code> at <code>Histogram.hpp:__SR_PRED_LINE__</code>. Everything else &mdash; the bins, the weights, the under- and overflow accounting &mdash; is identical in both modes, which is why one class is enough and why the plain mode costs nothing to keep.</p>
  </section>

  <section id="promotion">
    <p class="kicker">02 &#183; the promotion</p>
    <h2>How a bin becomes a signal region</h2>
    <p class="source"><code>to_signal_regions()</code>, quoted from source.</p>
    <details class="unit-diff" open><summary>Histogram.hpp:__TO_SRS_LINE__</summary><pre class="unit-hunks">__TO_SRS__</pre></details>
    <p class="diagram-note">Each bin becomes one <code>SignalRegionData</code> named <code>&lt;histogram&gt;_bin&lt;i&gt;</code>, carrying that bin's observed count, its own content as the signal prediction, and the published background with its error. The MC statistical error is <code>sqrt(sumw2)</code> &mdash; so the histogram's weight bookkeeping is not decoration, it is what makes the per-bin likelihood honest about limited MC.</p>
    <p class="diagram-note"><strong>Two guards make this safe rather than merely convenient.</strong> <code>validate_signal_region_data()</code> refuses a histogram whose <code>obs</code>/<code>bkg</code>/<code>bkg_err</code> lengths do not match the bin count, and it runs on every promotion, not just at construction. <code>combine()</code> refuses to merge two histograms whose signal-region data disagree. Both throw rather than silently producing a shorter or mismatched set of signal regions &mdash; which matters because these objects are merged across batch subprocesses.</p>
    <details class="unit-diff"><summary>the length guard &#183; Histogram.hpp:__VALIDATE_LINE__</summary><pre class="unit-hunks">__VALIDATE__</pre></details>
  </section>

  <section id="macros">
    <p class="kicker">03 &#183; the macro surface</p>
    <h2>What an analysis actually writes</h2>
    <p class="source">Extracted from <code>AnalysisMacros.hpp</code>, with the expansion each one produces.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:24%">Macro</th><th style="width:30%">Arguments</th><th>Expands to</th></tr></thead>
      <tbody>__MACRO_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The pairing is deliberate: <code>DEFINE_HISTOGRAM_1D</code> and <code>DEFINE_HISTOGRAM_SR_1D</code> differ only by the three data arrays, and <code>COMMIT_HISTOGRAMS</code> and <code>COMMIT_HISTOGRAM_SRS</code> are separate calls. An analysis that wants plots but not extra signal regions commits the first and not the second &mdash; the two decisions never get accidentally coupled at the analysis level. <strong>They are coupled at the flag level instead</strong>, which is the next section.</p>
  </section>

  <section id="example">
    <p class="kicker">04 &#183; worked example</p>
    <h2>The same three stages, side by side</h2>
    <p class="source">Both analyses book, fill and commit. Quoted from source &mdash; the only difference is in the first and third.</p>
    <div class="example-grid">
      <div class="example-col">
        <p class="example-h"><span class="tag-plain">plain histogram</span> __PLAIN_NAME__</p>
        <p class="example-note"><strong>Book</strong> &mdash; bin count, range, axis label. Nothing else.</p>
        <pre class="unit-hunks">__PLAIN_BOOK__</pre>
        <p class="example-note"><strong>Fill</strong> &mdash; identical on both sides.</p>
        <pre class="unit-hunks">__PLAIN_FILL__</pre>
        <p class="example-note"><strong>Commit</strong> &mdash; <code>COMMIT_HISTOGRAMS</code> only. The signal regions above it are cut-and-count and the histogram does not touch them.</p>
        <pre class="unit-hunks">__PLAIN_COMMIT__</pre>
        <p class="example-note">Result: __PLAIN_SRS__ signal regions with the flag on or off, plus two histograms in the JSON for whoever wants to look at the shape.</p>
      </div>
      <div class="example-col">
        <p class="example-h"><span class="tag-sr">signal-region histogram</span> __SR_NAME__</p>
        <p class="example-note"><strong>Book</strong> &mdash; the same call plus three arrays read off the paper: observed, background, background error, one entry per bin.</p>
        <pre class="unit-hunks">__SR_BOOK__</pre>
        <p class="example-note"><strong>Fill</strong> &mdash; identical to the left.</p>
        <pre class="unit-hunks">__SR_FILL__</pre>
        <p class="example-note"><strong>Commit</strong> &mdash; one extra line. <code>COMMIT_HISTOGRAM_SRS</code> is what promotes the bins.</p>
        <pre class="unit-hunks">__SR_COMMIT__</pre>
        <p class="example-note">Result: __SR_SRS_OFF__ signal region with the flag off, __SR_SRS_ON__ with it on &mdash; <code>SR</code> plus <code>m_VLB_bin0</code> &hellip; <code>m_VLB_bin__SR_LAST_BIN__</code>.</p>
      </div>
    </div>
    <p class="diagram-note">Line for line, the difference is <strong>three arrays at booking and one macro at commit</strong>. Everything between them &mdash; the fill, the event loop, the reset &mdash; is the same code. That is what makes the two modes cheap to hold in one class, and it is also why the distinction is easy to miss when reading an analysis quickly: a histogram that silently adds seven signal regions looks almost exactly like one that adds none.</p>
    <p class="diagram-note">The three arrays are the real content. <code>mVLB_obs</code>, <code>mVLB_bkg</code> and <code>mVLB_bkg_err</code> are the published numbers, and <code>validate_signal_region_data()</code> insists there be exactly one of each per bin &mdash; so a bin-edge edit that forgets to update the arrays throws instead of quietly producing a shorter set of regions.</p>
  </section>

  <section id="consumers">
    <p class="kicker">05 &#183; who uses which</p>
    <h2>Two analyses take the signal regions, one does not</h2>
    <p class="source">All three are new on this branch.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:24%">Analysis</th><th style="width:14%">Mode</th><th style="width:20%">Histogram</th><th style="width:8%">Bins</th><th>Signal regions</th></tr></thead>
      <tbody>__CONSUMER_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">__CONSUMER_NOTE__</p>
    <p class="diagram-note">__RETIRED_NOTE__</p>
  </section>

  <section id="flag">
    <p class="kicker">06 &#183; the flag</p>
    <h2>A diagnostic switch that moves the likelihood</h2>
    <p class="source">One YAML key, read once, set globally.</p>
    <details class="unit-diff" open><summary>solo.cpp:__SWITCH_LINE__</summary><pre class="unit-hunks">__SWITCH__</pre></details>
    <p class="diagram-note"><code>check_histogram</code> is read with <code>getValueOrDef</code> and <strong>defaults to <code>false</code></strong>, then set on a static that every analysis reads. It gates three things at once: whether histograms are booked, whether <code>FILL_HISTOGRAM_*</code> does anything, and whether <code>COMMIT_HISTOGRAM_SRS</code> runs.</p>
    <div class="note"><strong>This is the thing to say aloud.</strong> On the two signal-region analyses the flag does not only decide whether plots are produced &mdash; it decides how many signal regions exist. __FLAG_SENTENCE__ A flag named like a diagnostic toggle changes the likelihood, and because it defaults to off, the histogram-derived regions are absent unless someone opts in. Neither behaviour is wrong, but the name does not warn anyone, and two runs of the same YAML with the flag flipped are not comparable.</div>
  </section>

  <section id="roundtrip">
    <p class="kicker">07 &#183; the round trip</p>
    <h2>Out to JSON, back through the batch merge</h2>
    <p class="source">Histograms are not write-only: batch mode reads them back and accumulates them.</p>
    <div class="grid-2">
      <div class="mapping-table"><table>
        <thead><tr><th style="width:60%">JSON key</th><th>Line</th></tr></thead>
        <tbody>__JSON_ROWS__</tbody>
      </table></div>
      <div>
        <div class="mapping-table"><table>
          <thead><tr><th style="width:46%">Batch step</th><th style="width:16%">Line</th><th>What it does</th></tr></thead>
          <tbody>
            <tr><td><code>parse_histograms_or_empty</code></td><td class="num">__MERGE_PARSE__</td><td>Rebuilds <code>Histograms</code> from a per-file JSON, or returns empty if the key is absent.</td></tr>
            <tr><td><code>scale(process_weight)</code></td><td class="num">__MERGE_SCALE__</td><td>Applies the cross-section weight before merging, so each subprocess contributes in proportion.</td></tr>
            <tr><td><code>accumulate_histograms</code></td><td class="num">__MERGE_ACC__</td><td>Adds bin contents and <code>sumw2</code> across files.</td></tr>
            <tr><td>count guard</td><td class="num">__MERGE_GUARD__</td><td>Throws if two files disagree on how many histograms an analysis has.</td></tr>
          </tbody>
        </table></div>
      </div>
    </div>
    <p class="diagram-note">Because the batch merge reads these fields back, the histogram block is part of the wire format between subprocesses and the merge step &mdash; not just a report. Renaming <code>edges</code>, <code>counts</code> or <code>sumw2</code> breaks batch mode, not merely the plotting script. The same is true of the cutflow and signal-region blocks, and the <a href="cbs-json-output.html">output-contract page</a> covers which fields are load-bearing in that sense.</p>
  </section>

  <section id="files">
    <p class="kicker">08 &#183; the footprint</p>
    <h2>Where it landed</h2>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:22%">File</th><th style="width:12%">State</th><th>Role</th><th style="width:14%">Lines</th></tr></thead>
      <tbody>__FILE_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">One new header carries the whole feature; everything else is a small edit at a seam that already existed &mdash; the analysis base class, the data container, the output writer, the batch merge. The plotting script (<code>__PLOTTER_LINES__</code> lines) is the only other new file and it reads the JSON rather than linking against anything.</p>
  </section>

  <section>
    <p class="kicker">09 &#183; boundary</p>
    <h2>What this page does not tell you</h2>
    <div class="note">Everything above is read from source text. No analysis was compiled, no histogram was filled, and no likelihood was evaluated &mdash; so this page shows how a bin becomes a signal region, not whether the resulting per-bin limits reproduce the published ones. The observed and background arrays are quoted as they appear in the source; whether they match the paper's tables is a validation question this page cannot answer, and <code>ATLAS_EXOT_2021_35</code> is in any case marked unvalidated in its own source.</div>
  </section>

  <p class="backlink" style="margin-top:26px"><span class="lbl">back</span><span>Return to <a href="cbs-change-ledger.html#8">slide 7 &#8599;</a>, or to the <a href="cbs-change-ledger.html#1">start of the deck &#8599;</a>.</span></p>
  <footer>Generated by <code>scripts/build-histogram-page.py</code>. Baseline <code>__BASELINE__</code>, head <code>__HEAD__</code>.</footer>
</main>
</body>
</html>'''


def render_html(data: dict) -> str:
    sr_analyses = [c for c in data["consumers"] if c["mode"] == "signal region"]
    plain_analyses = [c for c in data["consumers"] if c["mode"] == "plain"]
    extra = sum(c["srs_with_flag"] - c["srs_without_flag"] for c in data["consumers"])

    parts = []
    for c in sr_analyses:
        parts.append(f'<code>{esc(c["name"])}</code> goes from '
                     f'{c["srs_without_flag"]} to {c["srs_with_flag"]}')
    flag_sentence = ("With the flag on, " + "; ".join(parts) + ". "
                     f"That is {extra} extra signal regions in total.") if parts else ""

    if sr_analyses and plain_analyses:
        biggest = max(sr_analyses, key=lambda c: c["srs_with_flag"] - c["srs_without_flag"])
        plain = plain_analyses[0]
        consumer_note = (
            f'The split is real, not incidental. <code>{esc(biggest["name"])}</code> books its '
            f'histogram with observed and background arrays taken from the paper and commits every '
            f'bin, so its signal-region count moves from {biggest["srs_without_flag"]} to '
            f'{biggest["srs_with_flag"]}. <code>{esc(plain["name"])}</code> books plain uniform '
            f'histograms, calls <code>COMMIT_HISTOGRAMS</code> and never calls '
            f'<code>COMMIT_HISTOGRAM_SRS</code> &mdash; its signal regions stay the '
            f'{plain["srs_without_flag"]} cut-and-count ones and the histograms are there to be '
            'looked at. Both are legitimate uses of the same class, and the source makes which one '
            'is in play readable at a glance.'
        )
    else:
        consumer_note = "Every consumer uses the same mode."

    with_manual = [c for c in data["consumers"] if c["retired_manual"]]
    if with_manual:
        c = max(with_manual, key=lambda x: len(x["retired_manual"]))
        lo, hi = c["retired_manual"][0], c["retired_manual"][-1]
        retired_note = (
            f'<strong>The reason this mechanism exists is still in the source, commented out.</strong> '
            f'<code>{esc(c["name"])}</code> carries {len(c["retired_manual"])} dead lines at '
            f'L{lo}&ndash;{hi}, each one a hand-written <code>add_result(SignalRegionData(...))</code> '
            'for a single m<sub>JJ</sub> bin with its observed count and background pasted in as '
            'literals. That is what per-bin signal regions cost before: one counter per bin, one '
            'line per bin, and the same numbers repeated in two places that could drift apart. '
            f'<code>COMMIT_HISTOGRAM_SRS</code> replaces all {len(c["retired_manual"])} with one '
            'call reading the same arrays the histogram is booked from, so the bin edges, the '
            'observed counts and the backgrounds cannot disagree with the plot. Leaving the old '
            'block visible is the honest choice &mdash; it is the before-and-after, in one file.'
        )
    else:
        retired_note = ("No analysis retains a hand-written per-bin signal-region block, so the "
                        "before-and-after comparison is not visible in the current source.")

    # The worked example pairs the smallest plain user with the smallest
    # signal-region user, so the two columns stay comparable in length.
    plain_ex = min(plain_analyses, key=lambda c: len(c["plain_defs"]))
    sr_ex = min(sr_analyses, key=lambda c: sum(d["nbins"] for d in c["sr_defs"]))

    # Collect the template's own tokens first: macro bodies legitimately contain
    # __VA_ARGS__, so a blanket scan of the finished page would flag content.
    expected = set(re.findall(r"__[A-Z_]+__", TEMPLATE))

    css = CSS.read_text() if CSS.exists() else "<style></style>"
    page = TEMPLATE.replace("__CSS__", css)
    replacements = {
        "__BASELINE__": esc(data["refs"]["baseline"]),
        "__HEAD__": esc(data["refs"]["head"]),
        "__HIST_LINES__": str(data["hist_lines"]),
        "__FILES__": str(len(TOUCHED)),
        "__MACROS__": str(len(data["macros"])),
        "__SR_ANALYSES__": str(len(sr_analyses)),
        "__PLAIN_ANALYSES__": str(len(plain_analyses)),
        "__EXTRA_SRS__": str(extra),
        "__MODES__": modes_svg(data),
        "__MEMBER_ROWS__": member_rows(data),
        "__SR_PRED_LINE__": str(data["anchors"]["is_signal_region"]["line"]),
        "__TO_SRS_LINE__": str(data["anchors"]["to_signal_regions"]["line"]),
        "__TO_SRS__": esc(data["excerpts"]["to_srs"]),
        "__VALIDATE_LINE__": str(data["anchors"]["validate"]["line"]),
        "__VALIDATE__": esc(data["excerpts"]["validate"]),
        "__MACRO_ROWS__": macro_rows(data),
        "__CONSUMER_ROWS__": consumer_rows(data),
        "__CONSUMER_NOTE__": consumer_note,
        "__RETIRED_NOTE__": retired_note,
        "__PLAIN_NAME__": esc(plain_ex["name"]),
        "__PLAIN_BOOK__": esc(plain_ex["example"]["book"]["code"]),
        "__PLAIN_FILL__": esc(plain_ex["example"]["fill"]["code"]),
        "__PLAIN_COMMIT__": esc(plain_ex["example"]["commit"]["code"]),
        "__PLAIN_SRS__": str(plain_ex["srs_without_flag"]),
        "__SR_NAME__": esc(sr_ex["name"]),
        "__SR_BOOK__": esc(sr_ex["example"]["book"]["code"]),
        "__SR_FILL__": esc(sr_ex["example"]["fill"]["code"]),
        "__SR_COMMIT__": esc(sr_ex["example"]["commit"]["code"]),
        "__SR_SRS_OFF__": str(sr_ex["srs_without_flag"]),
        "__SR_SRS_ON__": str(sr_ex["srs_with_flag"]),
        "__SR_LAST_BIN__": str(max(0, sum(d["nbins"] for d in sr_ex["sr_defs"]) - 1)),
        "__SWITCH_LINE__": str(data["switch"]["read"]["line"]),
        "__SWITCH__": esc(data["excerpts"]["switch"]),
        "__FLAG_SENTENCE__": flag_sentence,
        "__JSON_ROWS__": json_rows(data),
        "__MERGE_PARSE__": str(data["merge"]["parse"]),
        "__MERGE_SCALE__": str(data["merge"]["scale"]),
        "__MERGE_ACC__": str(data["merge"]["accumulate"]),
        "__MERGE_GUARD__": str(data["merge"]["guard"]),
        "__FILE_ROWS__": file_rows(data),
        "__PLOTTER_LINES__": str(data["plotter_lines"]),
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    leftover = sorted(expected & set(re.findall(r"__[A-Z_]+__", page)))
    if leftover:
        raise SystemExit(f"unreplaced tokens: {leftover}")
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path,
                        default=Path.home() / "Gambit-Workshop" / "gambit")
    parser.add_argument("--out-dir", type=Path, default=Path("dependences"))
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    args = parser.parse_args()

    data = collect(args.gambit_root)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "cbs-histograms.json").write_text(json.dumps(data, indent=2) + "\n")
    page = render_html(data)
    (args.out_dir / "cbs-histograms.html").write_text(page)
    (args.out_dir / "CBS_HISTOGRAMS.md").write_text(render_markdown(data))
    if args.site_dir.exists():
        (args.site_dir / "cbs-histograms.html").write_text(page)

    print(json.dumps({
        "macros": [m["name"] for m in data["macros"]],
        "consumers": {c["name"]: {"mode": c["mode"],
                                  "srs": [c["srs_without_flag"], c["srs_with_flag"]]}
                      for c in data["consumers"]},
        "json_keys": sorted({f["key"] for f in data["json_fields"]}),
        "hist_lines": data["hist_lines"],
    }, indent=2))
    for name in ("cbs-histograms.json", "cbs-histograms.html", "CBS_HISTOGRAMS.md"):
        print(f"Wrote {args.out_dir / name}")


if __name__ == "__main__":
    main()
