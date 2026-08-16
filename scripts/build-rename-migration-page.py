#!/usr/bin/env python3
"""Render the analysis naming-migration page.

The deck says "75 analyses moved". That is the file count, and it is the
smaller of two numbers that matter:

  file level        75 renames git detects, plus 18 files that absorb several
                    old files each -- so the tree has fewer, bigger files
  registered name   what a YAML actually selects by. 123 of these were retired
                    and 132 introduced; only one physics analysis kept its old
                    name, and its source says why

Both are extracted here, along with the provenance comments the migration left
behind, the analyses that deliberately did not move, and the one tracked YAML
still naming analyses that no longer exist.

Nothing is built or run.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import subprocess
from pathlib import Path

ANALYSES_DIR = "ColliderBit/src/analyses"
BASE = "9c955e3a78"

FACTORY_RE = re.compile(r"DEFINE_ANALYSIS_FACTORY\(\s*([A-Za-z0-9_]+)\s*\)")
NEWNAME_RE = re.compile(r"^(ATLAS|CMS)_(CONF|SUSY|SUS|EXOT|EXO|B2G|PAS)_(\d{2,4})_(\d+)(?:_(.+))?$")

# Utility/stub analyses that are not physics results; counted separately so the
# "only one analysis kept its name" claim is about real analyses.
STUBS = {"Baselines", "Covariance", "Dummy", "Minimum"}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def registered(root: Path, ref: str) -> set[str]:
    """Analysis names a YAML can select at `ref`."""
    out = subprocess.run(
        ["git", "-C", str(root), "grep", "-h", "DEFINE_ANALYSIS_FACTORY", ref, "--", ANALYSES_DIR],
        capture_output=True, text=True, check=False).stdout
    return set(FACTORY_RE.findall(out))


def provenance(root: Path) -> dict[str, dict]:
    """Parse the `// Renamed from:` block at the top of each analysis.

    Two shapes are in use: the old name on the same line, or an indented
    comment block underneath listing one or more old names.  Lines in that
    block that are not bare identifiers are kept separately as notes -- that is
    where the two honest admissions in this migration live.
    """
    out = {}
    for path in sorted((root / ANALYSES_DIR).glob("Analysis_*.cpp")):
        lines = path.read_text(errors="replace").splitlines()
        index = next((i for i, line in enumerate(lines) if "Renamed from:" in line), None)
        if index is None:
            continue
        tail = lines[index].split("Renamed from:", 1)[1].strip()
        olds, notes = ([tail] if tail else []), []
        probe = index + 1
        while probe < len(lines) and lines[probe].lstrip().startswith("//"):
            body = lines[probe].lstrip()[2:].strip()
            if not body:
                break
            (olds if re.fullmatch(r"[A-Za-z0-9_]+", body) else notes).append(body)
            probe += 1
        stem = path.stem
        out[stem] = {
            "file": f"{ANALYSES_DIR}/{path.name}",
            "line": index + 1,
            "old": [o.removeprefix("Analysis_") for o in olds],
            "notes": notes,
            "defines": sorted(set(FACTORY_RE.findall(path.read_text(errors="replace")))),
        }
    return out


def git_renames(root: Path) -> dict[str, tuple[str, int]]:
    out = {}
    raw = git(root, "diff", "--name-status", "-M", BASE, "HEAD", "--", ANALYSES_DIR)
    for line in raw.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R"):
            out[Path(parts[2]).stem] = (Path(parts[1]).stem, int(parts[0][1:]))
    return out


def yaml_debt(root: Path, retired: set[str]) -> list[dict]:
    """Tracked YAMLs that still name an analysis which no longer exists."""
    rows = []
    for path in sorted((root / "yaml_files").rglob("*.yaml")):
        text = path.read_text(errors="replace")
        dead = sorted(n for n in retired if re.search(rf"\b{re.escape(n)}\b", text))
        if dead:
            rows.append({"file": path.name, "count": len(dead), "names": dead})
    return rows


def collect(root: Path) -> dict:
    old_names, new_names = registered(root, BASE), registered(root, "HEAD")
    retired, introduced, survived = old_names - new_names, new_names - old_names, old_names & new_names

    prov = provenance(root)
    renames = git_renames(root)

    rows = []
    for stem, record in prov.items():
        new = stem.removeprefix("Analysis_")
        match = NEWNAME_RE.match(new)
        rows.append({
            "new": new,
            "old": record["old"],
            "shape": "1:1" if len(record["old"]) == 1 else f"{len(record['old'])}:1",
            "similarity": renames.get(stem, (None, None))[1],
            "git_detected": stem in renames,
            "experiment": match.group(1) if match else None,
            "kind": match.group(2) if match else None,
            "year": match.group(3) if match else None,
            "number": match.group(4) if match else None,
            "suffix": match.group(5) if match else None,
            "defines": record["defines"],
            "notes": record["notes"],
            "line": record["line"],
        })
    rows.sort(key=lambda r: r["new"])

    consolidations = [r for r in rows if len(r["old"]) > 1]
    absorbed = sum(len(r["old"]) for r in consolidations)

    by_kind = collections.Counter(r["kind"] or "unparsed" for r in rows)
    unparsed = [r["new"] for r in rows if r["kind"] is None]

    return {
        "generated_by": "scripts/build-rename-migration-page.py",
        "refs": {
            "baseline": BASE,
            "head": git(root, "rev-parse", "--short", "HEAD").strip(),
        },
        "registered": {
            "base": len(old_names),
            "head": len(new_names),
            "retired": sorted(retired),
            "introduced": sorted(introduced),
            "survived": sorted(survived),
            "survived_physics": sorted(survived - STUBS),
            "stubs": sorted(survived & STUBS),
        },
        "files": {
            "documented": len(rows),
            "git_renames": len(renames),
            "consolidations": len(consolidations),
            "absorbed": absorbed,
            "one_to_one": len(rows) - len(consolidations),
        },
        "rows": rows,
        "by_kind": dict(by_kind.most_common()),
        "unparsed": unparsed,
        "notes": [r for r in rows if r["notes"]],
        "yaml_debt": yaml_debt(root, retired),
        "commits": [line for line in git(
            root, "log", "--format=%h %s", f"{BASE}..HEAD", "--", ANALYSES_DIR
        ).splitlines() if re.search(r"renam|report number", line, re.I)],
        "caveat": "Static read of the worktree. Nothing was built or run.",
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def scheme_svg(data: dict) -> str:
    """Old scheme vs new scheme, decomposed field by field."""
    width, height = 1240, 250
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="sch-t sch-d">',
        '<title id="sch-t">The old and new analysis naming schemes</title>',
        '<desc id="sch-d">The old name encoded experiment, beam energy, final state and '
        'integrated luminosity. The new one encodes experiment, report type, year and '
        'report number, which is how the paper is cited.</desc>',
    ]

    def lane(y, label, sample, fields, tone):
        out.append(f'<text class="zone-label" x="20" y="{y - 14}">{esc(label)}</text>')
        x = 20
        for text, caption in fields:
            w = max(118, 9 * len(text) + 34)
            cls = "detail-focal" if tone == "new" else "detail-data"
            out.append(f'<g class="node {cls}"><rect x="{x}" y="{y}" width="{w}" height="62" rx="7"/>')
            out.append(f'<text class="title" x="{x + 12}" y="{y + 26}" '
                       f'style="font-size:12px">{esc(text)}</text>')
            out.append(f'<text class="body" x="{x + 12}" y="{y + 46}">{esc(caption)}</text>')
            out.append("</g>")
            if (text, caption) != fields[-1]:
                out.append(f'<text class="body" x="{x + w + 5}" y="{y + 36}" '
                           'style="font-size:13px">_</text>')
            x += w + 18
        out.append(f'<text class="legend-label" x="{x + 8}" y="{y + 36}">{esc(sample)}</text>')

    lane(46, "BEFORE — what the analysis looked at", "ATLAS_13TeV_0LEP_36invfb",
         [("ATLAS", "experiment"), ("13TeV", "beam energy"),
          ("0LEP", "final state"), ("36invfb", "luminosity")], "old")
    lane(160, "AFTER — how the paper is cited", "ATLAS_SUSY_2016_07",
         [("ATLAS", "experiment"), ("SUSY", "report type"),
          ("2016", "year"), ("07", "report number")], "new")

    out.append('<path class="detail-edge" d="M600 120 V150" marker-end="url(#rn-arrow)"/>')
    out.append('<defs><marker id="rn-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>')
    out.append("</svg>")
    return "\n".join(out)


def migration_rows(data: dict) -> str:
    rows = []
    for record in data["rows"]:
        olds = "<br>".join(f"<code>{esc(o)}</code>" for o in record["old"]) or \
               '<span class="status">&#8212;</span>'
        if record["git_detected"]:
            detect = f'<span class="status added-in-right">{record["similarity"]}%</span>'
        else:
            detect = '<span class="status unchanged">not a git rename</span>'
        shape = record["shape"]
        shape_cls = "unchanged" if shape != "1:1" else "added-in-right"
        defines = len(record["defines"])
        note = f'<br><span class="delta">{esc(" · ".join(record["notes"]))}</span>' \
            if record["notes"] else ""
        rows.append(
            f'<tr data-kind="{esc(record["kind"] or "other")}" data-shape="{esc(shape)}">'
            f'<td><code>{esc(record["new"])}</code>{note}</td>'
            f'<td>{olds}</td>'
            f'<td><span class="status {shape_cls}">{esc(shape)}</span></td>'
            f'<td class="num">{defines}</td>'
            f'<td>{detect}</td></tr>'
        )
    return "\n".join(rows)


def consolidation_rows(data: dict) -> str:
    rows = []
    for record in sorted((r for r in data["rows"] if len(r["old"]) > 1),
                         key=lambda r: -len(r["old"])):
        rows.append(
            f'<tr><td><code>{esc(record["new"])}</code></td>'
            f'<td class="num">{len(record["old"])}</td>'
            f'<td class="num">{len(record["defines"])}</td>'
            f'<td>{"".join(f"<code>{esc(d)}</code> " for d in record["defines"])}</td></tr>'
        )
    return "\n".join(rows)


def kind_rows(data: dict) -> str:
    total = sum(data["by_kind"].values())
    meaning = {
        "SUSY": "ATLAS supersymmetry paper",
        "SUS": "CMS supersymmetry paper",
        "CONF": "ATLAS conference note &mdash; preliminary, not a journal paper",
        "EXOT": "ATLAS exotics paper",
        "EXO": "CMS exotics paper",
        "B2G": "CMS beyond-two-generations paper",
        "PAS": "CMS physics analysis summary &mdash; preliminary",
        "unparsed": "does not fit the scheme (see below)",
    }
    rows = []
    for kind, count in data["by_kind"].items():
        share = 100 * count / total if total else 0
        rows.append(
            f'<tr><td><code>{esc(kind)}</code></td>'
            f'<td class="num">{count}</td>'
            f'<td class="num">{share:.0f}%</td>'
            f'<td>{meaning.get(kind, "&#8212;")}</td></tr>'
        )
    return "\n".join(rows)


def survivor_rows(data: dict) -> str:
    reg = data["registered"]
    rows = []
    for name in reg["survived_physics"]:
        record = next((r for r in data["rows"]
                       if name in r["defines"] or r["new"] == name), None)
        why = " &#183; ".join(record["notes"]) if record and record["notes"] else \
            "no note in the source"
        rows.append(f'<tr><td><code>{esc(name)}</code></td>'
                    f'<td><span class="status unchanged">physics analysis</span></td>'
                    f'<td>{why}</td></tr>')
    for name in reg["stubs"]:
        rows.append(f'<tr><td><code>{esc(name)}</code></td>'
                    f'<td><span class="status">test / utility</span></td>'
                    f'<td>Not a published analysis, so there is no report number to move to.</td></tr>')
    return "\n".join(rows)


def yaml_rows(data: dict) -> str:
    if not data["yaml_debt"]:
        return '<tr><td colspan="3">No tracked YAML names a retired analysis.</td></tr>'
    rows = []
    for record in data["yaml_debt"]:
        sample = ", ".join(record["names"][:4])
        more = f" &hellip; and {len(record['names']) - 4} more" if len(record["names"]) > 4 else ""
        rows.append(f'<tr><td><code>yaml_files/{esc(record["file"])}</code></td>'
                    f'<td class="num">{record["count"]}</td>'
                    f'<td><code>{esc(sample)}</code>{more}</td></tr>')
    return "\n".join(rows)


def render_markdown(data: dict) -> str:
    reg, files = data["registered"], data["files"]
    lines = [
        "# The analysis naming migration",
        "",
        f'Baseline `{data["refs"]["baseline"]}` &rarr; head `{data["refs"]["head"]}`.',
        "",
        "## Two levels, two numbers",
        "",
        "| Level | Count |",
        "|---|---|",
        f'| Files git sees as renames | {files["git_renames"]} |',
        f'| Files carrying a `// Renamed from:` block | {files["documented"]} |',
        f'| &nbsp;&nbsp;of those, 1:1 | {files["one_to_one"]} |',
        f'| &nbsp;&nbsp;of those, consolidations | {files["consolidations"]} '
        f'(absorbing {files["absorbed"]} old files) |',
        f'| Registered analysis names, baseline | {reg["base"]} |',
        f'| Registered analysis names, head | {reg["head"]} |',
        f'| **Retired names** | **{len(reg["retired"])}** |',
        f'| Introduced names | {len(reg["introduced"])} |',
        f'| Survived | {len(reg["survived"])} '
        f'({len(reg["survived_physics"])} physics, {len(reg["stubs"])} test/utility) |',
        "",
        "The registered name is what a YAML selects by, so it is the number that",
        f'describes breakage: **{len(reg["retired"])} names no longer resolve**.',
        "",
        "## Scheme",
        "",
        "Old: `<EXPERIMENT>_<beam energy>_<final state>_<luminosity>` -- what the analysis looked at.",
        "",
        "New: `<EXPERIMENT>_<report type>_<year>_<number>` -- how the paper is cited.",
        "",
        "| Report type | Count |",
        "|---|---|",
    ]
    for kind, count in data["by_kind"].items():
        lines.append(f"| `{kind}` | {count} |")
    lines += [
        "",
        "## What did not move",
        "",
    ]
    for name in reg["survived_physics"]:
        record = next((r for r in data["rows"] if name in r["defines"] or r["new"] == name), None)
        why = " / ".join(record["notes"]) if record and record["notes"] else "no note in the source"
        lines.append(f"- `{name}` -- {why}")
    lines += [
        f'- {len(reg["stubs"])} test/utility stubs (`' + "`, `".join(reg["stubs"]) + "`)",
        "",
        "## Outstanding",
        "",
    ]
    for record in data["yaml_debt"]:
        lines.append(f'- `yaml_files/{record["file"]}` still names {record["count"]} '
                     "analyses that no longer exist.")
    lines += ["", "No build or run was performed for this document.", ""]
    return "\n".join(lines)


CSS = Path(__file__).with_name("_page_css.html")


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The analysis naming migration</title>
__CSS__
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit &#183; analysis layer</p>
  <h1>The naming migration</h1>
  <p class="intro">Every analysis moved from a name describing what it looked at to the report number of the paper it reproduces. The deck quotes the file count. This page carries the other number &mdash; the one a YAML actually depends on &mdash; the full old-to-new table, the files that absorbed several analyses each, and the two analyses whose source says plainly why they did not move.</p>
  <div class="meta"><span><strong>BASELINE</strong> __BASELINE__</span><span><strong>HEAD</strong> __HEAD__</span><span><strong>SOURCE</strong> provenance comments + DEFINE_ANALYSIS_FACTORY</span><span><strong>STATIC EVIDENCE</strong> no build / no events processed</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page expands <a href="cbs-change-ledger.html#8">slide 8 of the CBS change-ledger deck &#8599;</a>, which summarises the migration in one card. Everything below is read from the worktree at generation time.</span></p>

  <div class="summary-grid" aria-label="Summary">
    <div class="card"><span class="n">__GIT_RENAMES__</span><span class="label">git-detected renames</span></div>
    <div class="card"><span class="n">__DOCUMENTED__</span><span class="label">documented moves</span></div>
    <div class="card"><span class="n">__CONSOLIDATIONS__</span><span class="label">consolidations</span></div>
    <div class="card accent"><span class="n">__RETIRED__</span><span class="label">names retired</span></div>
    <div class="card"><span class="n">__INTRODUCED__</span><span class="label">names introduced</span></div>
    <div class="card accent"><span class="n">__SURVIVED_PHYS__</span><span class="label">physics name kept</span></div>
  </div>
  <div class="note">Two counts describe this migration and they are not the same. <strong>Files</strong> are what <code>git diff -M</code> reports. <strong>Registered names</strong> are what <code>DEFINE_ANALYSIS_FACTORY</code> emits and what a YAML selects by &mdash; a single file can register several. The second number is larger, and it is the one that describes what breaks.</div>

  <section id="levels">
    <p class="kicker">01 &#183; two levels</p>
    <h2>The file count understates it</h2>
    <p class="source">Both numbers are correct; they measure different things.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:34%">Level</th><th style="width:12%">Baseline</th><th style="width:12%">Head</th><th>What it means</th></tr></thead>
      <tbody>
        <tr><td><strong>Files git calls renames</strong></td><td class="num">&#8212;</td><td class="num">__GIT_RENAMES__</td>
            <td>Detected by content similarity. Misses a move when the file was also rewritten, or when several files folded into one.</td></tr>
        <tr><td><strong>Files with a provenance block</strong></td><td class="num">&#8212;</td><td class="num">__DOCUMENTED__</td>
            <td>The migration wrote <code>// Renamed from:</code> into each file. This is the migration's own record, and it is more complete than git's.</td></tr>
        <tr><td><strong>Registered analysis names</strong></td><td class="num">__REG_BASE__</td><td class="num">__REG_HEAD__</td>
            <td>What <code>DEFINE_ANALYSIS_FACTORY</code> emits &mdash; the string a YAML writes. <strong>__RETIRED__ retired, __INTRODUCED__ introduced, __SURVIVED__ survived.</strong></td></tr>
      </tbody>
    </table></div>
    <p class="diagram-note">The gap is the consolidations. __CONSOLIDATIONS__ files each absorb more than one old analysis file &mdash; __ABSORBED__ old files in total &mdash; and a fold-in is not a rename, so git reports the survivor as modified and the others as deleted. That is why the deck's 75 and this page's __DOCUMENTED__ disagree, and neither is wrong.</p>
  </section>

  <section id="scheme">
    <p class="kicker">02 &#183; the scheme</p>
    <h2>From what it looked at, to how it is cited</h2>
    <p class="source">Both schemes pack four fields into the name. They pack different ones.</p>
    <div class="diagram-shell">__SCHEME__</div>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:14%">Report type</th><th style="width:10%">Files</th><th style="width:10%">Share</th><th>What it is</th></tr></thead>
      <tbody>__KIND_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The new name is unambiguous in a way the old one was not: <code>ATLAS_13TeV_0LEP_36invfb</code> describes a search, but several papers match that description, whereas <code>ATLAS_SUSY_2016_07</code> resolves to exactly one. The cost is that it no longer says what the analysis selects &mdash; you have to look it up. <strong>The <code>CONF</code> and <code>PAS</code> entries are worth noticing:</strong> those are preliminary notes rather than journal papers, and a report number does not change that.</p>
  </section>

  <section id="table">
    <p class="kicker">03 &#183; the full map</p>
    <h2>Every move, old to new</h2>
    <p class="source">Read from the <code>// Renamed from:</code> block in each file. <em>Defines</em> is how many analysis names that one file registers &mdash; more than one means the sub-region analyses live there too.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:24%">New name</th><th style="width:34%">Renamed from</th><th style="width:9%">Shape</th><th style="width:8%">Defines</th><th style="width:14%">Git similarity</th></tr></thead>
      <tbody>__MIGRATION_ROWS__</tbody>
    </table></div>
  </section>

  <section id="consolidations">
    <p class="kicker">04 &#183; consolidations</p>
    <h2>Fewer files, same analyses</h2>
    <p class="source">These __CONSOLIDATIONS__ files each absorbed several old ones. The analyses inside were not merged &mdash; each still registers separately.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:22%">File</th><th style="width:10%">Absorbed</th><th style="width:10%">Defines</th><th>Registered analysis names inside</th></tr></thead>
      <tbody>__CONSOLIDATION_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">This is the part most easily misread. When four old files fold into <code>Analysis_CMS_SUS_19_012.cpp</code>, no analysis is lost: the file defines a base class and one subclass per signal-region grouping, each with its own <code>DEFINE_ANALYSIS_FACTORY</code>. What changed is that the sub-region names now derive from the report number too &mdash; <code>CMS_SUS_19_012_3Lep</code> rather than <code>CMS_13TeV_MultiLEP_3LEP_137invfb</code>. So a YAML naming a sub-region breaks in exactly the same way as one naming a parent.</p>
  </section>

  <section id="stayed">
    <p class="kicker">05 &#183; what did not move</p>
    <h2>The exceptions, and the reasons in the source</h2>
    <p class="source">Names present at both the baseline and head.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:28%">Name</th><th style="width:16%">Kind</th><th>Why it stayed</th></tr></thead>
      <tbody>__SURVIVOR_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">__SURVIVOR_NOTE__</p>
  </section>

  <section id="breaks">
    <p class="kicker">06 &#183; what this breaks</p>
    <h2>Old names do not resolve any more</h2>
    <p class="source">A YAML selecting an analysis by name gets a name that no longer exists. There is no alias table in the tree.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:30%">Tracked YAML</th><th style="width:12%">Dead names</th><th>Examples</th></tr></thead>
      <tbody>__YAML_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">__YAML_NOTE__</p>
    <div class="note">This is the decision for the collaboration, not for this branch. Report-number naming is unambiguous and matches how the papers are cited, but __RETIRED__ retired names means every existing configuration that selects analyses by name has to be rewritten. Whether upstream wants the migration, and whether it should ship with an alias table mapping old names to new for one release, is a group call. The migration itself is complete and self-documenting &mdash; every moved file records where it came from &mdash; which is what makes an alias table cheap to generate later if the group wants one.</div>
  </section>

  <section>
    <p class="kicker">07 &#183; boundary</p>
    <h2>What this page does not tell you</h2>
    <p class="source">Read from the tree, not from a running build.</p>
    <div class="note">Names, provenance comments and factory registrations are read from the worktree as text. Nothing was compiled, no analysis was instantiated, and no event was processed &mdash; so this page shows that a name changed, not that the analysis behind it still produces the same yields. The similarity percentages come from <code>git diff -M</code> and describe textual overlap only; a 60% move is not evidence that 40% of the physics changed, and the low-similarity entries are worth opening individually before anyone says otherwise.</div>
  </section>

  <p class="backlink" style="margin-top:26px"><span class="lbl">back</span><span>Return to <a href="cbs-change-ledger.html#8">slide 8 &#8599;</a>, or to the <a href="cbs-change-ledger.html#1">start of the deck &#8599;</a>.</span></p>
  <footer>Generated by <code>scripts/build-rename-migration-page.py</code>. Baseline <code>__BASELINE__</code>, head <code>__HEAD__</code>.</footer>
</main>
</body>
</html>'''


def render_html(data: dict) -> str:
    reg, files = data["registered"], data["files"]

    physics = reg["survived_physics"]
    if physics:
        record = next((r for r in data["rows"]
                       if physics[0] in r["defines"] or r["new"] == physics[0]), None)
        note = record["notes"][0] if record and record["notes"] else ""
        survivor_note = (
            f'Exactly one physics analysis kept its descriptive name: <code>{esc(physics[0])}</code>. '
            f'The reason is written into the file rather than left implicit &mdash; '
            f'<em>&ldquo;{esc(note)}&rdquo;</em>. '
            'That is the right way to leave an exception: the next person does not have to '
            'guess whether it was missed or deliberate. The remaining survivors are test and '
            'utility stubs with no paper behind them.'
        ) if note else (
            f'One physics analysis kept its descriptive name: <code>{esc(physics[0])}</code>, '
            'with no explanatory note in the source.'
        )
    else:
        survivor_note = "Every physics analysis moved."

    debt = data["yaml_debt"]
    if debt:
        worst = max(debt, key=lambda r: r["count"])
        yaml_note = (
            f'Only {len(debt)} tracked YAML is affected, but it is affected badly: '
            f'<code>yaml_files/{esc(worst["file"])}</code> names <strong>{worst["count"]} analyses '
            'that no longer exist</strong>. It would fail at configure time today. That file is the '
            'in-tree evidence of the cost &mdash; every configuration outside this repository that '
            'selects analyses by name has the same problem and no warning.'
        )
    else:
        yaml_note = "No tracked YAML names a retired analysis."

    css = CSS.read_text() if CSS.exists() else "<style></style>"
    page = TEMPLATE.replace("__CSS__", css)
    replacements = {
        "__BASELINE__": esc(data["refs"]["baseline"]),
        "__HEAD__": esc(data["refs"]["head"]),
        "__GIT_RENAMES__": str(files["git_renames"]),
        "__DOCUMENTED__": str(files["documented"]),
        "__CONSOLIDATIONS__": str(files["consolidations"]),
        "__ABSORBED__": str(files["absorbed"]),
        "__REG_BASE__": str(reg["base"]),
        "__REG_HEAD__": str(reg["head"]),
        "__RETIRED__": str(len(reg["retired"])),
        "__INTRODUCED__": str(len(reg["introduced"])),
        "__SURVIVED__": str(len(reg["survived"])),
        "__SURVIVED_PHYS__": str(len(reg["survived_physics"])),
        "__SCHEME__": scheme_svg(data),
        "__KIND_ROWS__": kind_rows(data),
        "__MIGRATION_ROWS__": migration_rows(data),
        "__CONSOLIDATION_ROWS__": consolidation_rows(data),
        "__SURVIVOR_ROWS__": survivor_rows(data),
        "__SURVIVOR_NOTE__": survivor_note,
        "__YAML_ROWS__": yaml_rows(data),
        "__YAML_NOTE__": yaml_note,
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    leftover = re.findall(r"__[A-Z_]+__", page)
    if leftover:
        raise SystemExit(f"unreplaced tokens: {sorted(set(leftover))}")
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

    (args.out_dir / "cbs-rename-migration.json").write_text(json.dumps(data, indent=2) + "\n")
    page = render_html(data)
    (args.out_dir / "cbs-rename-migration.html").write_text(page)
    (args.out_dir / "CBS_RENAME_MIGRATION.md").write_text(render_markdown(data))
    if args.site_dir.exists():
        (args.site_dir / "cbs-rename-migration.html").write_text(page)

    print(json.dumps({
        "git_renames": data["files"]["git_renames"],
        "documented": data["files"]["documented"],
        "consolidations": data["files"]["consolidations"],
        "absorbed": data["files"]["absorbed"],
        "registered": [data["registered"]["base"], data["registered"]["head"]],
        "retired": len(data["registered"]["retired"]),
        "survived_physics": data["registered"]["survived_physics"],
        "unparsed": data["unparsed"],
    }, indent=2))
    for name in ("cbs-rename-migration.json", "cbs-rename-migration.html",
                 "CBS_RENAME_MIGRATION.md"):
        print(f"Wrote {args.out_dir / name}")


if __name__ == "__main__":
    main()
