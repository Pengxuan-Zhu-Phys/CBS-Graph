#!/usr/bin/env python3
"""Render the user-YAML configuration page.

Compares the original CBS input file with the one a user writes now, and
answers the question the diff alone does not: for each setting that used to be
in the file, who decides it today.

Four destinations, and every key is placed in one of them by reading the call
that consumes it:

  user        still read from YAML, and still required
  program     read with getValueOrDef, so the user may omit it
  CBS policy  overwritten in solo.cpp regardless of what the YAML says
  dead        no .cpp/.hpp in the repository reads it, at either ref

The last two are the interesting ones and neither is visible in a YAML diff.

Nothing is built or run.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

BASE = "9c955e3a78"
EXAMPLE = "ColliderBit/examples/solo_example.yaml"
SOLO = "ColliderBit/examples/solo.cpp"
SOLO_INPUT = "ColliderBit/examples/solo_input.cpp"
EVENTLOOP = "ColliderBit/src/ColliderBit_eventloop.cpp"
UTILS = "ColliderBit/include/gambit/ColliderBit/Utils.hpp"

# The new-style user file lives outside git (CBS_yaml/* is ignored), so it is
# read from the worktree if present and quoted with explanatory annotations.
NEW_STYLE = "CBS_yaml/ATLAS_EXOT_2019_04.yaml"
DEFAULTS = "CBS_yaml/CBS_defaults.yaml"

READERS = [SOLO, SOLO_INPUT, EVENTLOOP, UTILS]

ORDEF_RE = re.compile(r'getValueOrDef<([\w:<>, ]+)>\(\s*([^,]+?)\s*,\s*"([\w_]+)"')
VALUE_RE = re.compile(r'(?<!OrDef)getValue<([\w:<>, ]+)>\(\s*"([\w_]+)"')
POLICY_RE = re.compile(r'CBS\["([\w_]+)"\]\s*=\s*(.+?);')


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def show(root: Path, ref: str, path: str) -> str:
    return git(root, "show", f"{ref}:{path}")


def line_counts(text: str) -> dict:
    """Total lines, and lines that are neither blank nor a comment.

    Raw line counts mislead here: the current user file carries a long comment
    header and several commented-out alternatives, so counting every line makes
    it look longer than the original when its actual content is half the size.
    """
    total = text.splitlines()
    code = [line for line in total
            if line.strip() and not line.strip().startswith("#")]
    return {"total": len(total), "code": len(code),
            "comment": len(total) - len(code)}


def yaml_settings(text: str) -> list[dict]:
    """Top-level keys under `settings:`, in file order, with their values."""
    lines, out, inside = text.splitlines(), [], False
    for index, line in enumerate(lines):
        if re.match(r"^settings:\s*$", line):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            match = re.match(r"^  ([\w_]+):\s*(.*)$", line)
            if match:
                out.append({"key": match.group(1),
                            "value": match.group(2).strip(),
                            "line": index + 1})
    return out


def readers(root: Path, ref: str) -> dict[str, dict]:
    """Where each option key is consumed, and whether it has a default.

    A key can be read both ways in different branches -- target_fractional_uncert
    is mandatory when convergence checks run and defaulted when they do not.
    Those are reported as `conditional` with both sites, because picking either
    one alone would misdescribe what a CBS run does.
    """
    sites: dict[str, list[dict]] = {}
    for path in READERS:
        src = show(root, ref, path)
        if not src:
            continue
        for index, line in enumerate(src.splitlines()):
            for match in ORDEF_RE.finditer(line):
                sites.setdefault(match.group(3), []).append({
                    "kind": "program", "default": match.group(2).strip(),
                    "file": Path(path).name, "line": index + 1})
            for match in VALUE_RE.finditer(line):
                sites.setdefault(match.group(2), []).append({
                    "kind": "user", "default": None,
                    "file": Path(path).name, "line": index + 1})

    found = {}
    for key, entries in sites.items():
        kinds = {e["kind"] for e in entries}
        if kinds == {"program", "user"}:
            defaulted = next(e for e in entries if e["kind"] == "program")
            required = next(e for e in entries if e["kind"] == "user")
            found[key] = {**defaulted, "kind": "conditional", "other": required}
        else:
            found[key] = entries[0]
    return found


# Keys that are required only as a group: exactly one of each set must appear.
ALTERNATIVES = {
    "event_file": "processes",
    "processes": "event_file",
    "cross_section_pb": "cross_section_fb",
    "cross_section_fb": "cross_section_pb",
    "cross_section_fractional_uncert": "cross_section_uncert_fb / _pb",
}


MACROS_HPP = "ColliderBit/include/gambit/ColliderBit/analyses/AnalysisMacros.hpp"
HISTOGRAM_HPP = "ColliderBit/include/gambit/ColliderBit/analyses/Histogram.hpp"

HIST_CONSUMERS = [
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_04.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2019_07.cpp",
    "ColliderBit/src/analyses/Analysis_ATLAS_EXOT_2021_35.cpp",
]


def histogram_gate(root: Path, ref: str) -> dict:
    """What `check_histogram` actually gates, macro by macro.

    Only the FILL macros test the flag themselves.  Booking and committing are
    guarded by the analysis writing the test by hand, which is why the two
    histogram modes end up with different consequences for a run.
    """
    macros = show(root, ref, MACROS_HPP).splitlines()
    hist = show(root, ref, HISTOGRAM_HPP).splitlines()
    solo = show(root, ref, SOLO).splitlines()

    guarded = {}
    for index, line in enumerate(macros):
        match = re.match(r"#define\s+((?:DEFINE|FILL|COMMIT)_HISTOGRAM\w*)", line)
        if not match:
            continue
        body, probe = [line], index
        while probe < len(macros) and macros[probe].rstrip().endswith("\\"):
            probe += 1
            body.append(macros[probe])
        guarded[match.group(1)] = {
            "self_guarded": any("check_histogram()" in b for b in body),
            "line": index + 1,
        }

    fill_guard = next((i + 1 for i, line in enumerate(hist)
                       if "if (!check_histogram()) return;" in line), None)
    read = next((i + 1 for i, line in enumerate(solo)
                 if 'getValueOrDef<bool>(false, "check_histogram")' in line), None)

    # Does each consumer wrap its own booking and committing?
    consumers = []
    for path in HIST_CONSUMERS:
        src = show(root, ref, path).splitlines()
        gates = [i + 1 for i, line in enumerate(src)
                 if "Histogram1D::check_histogram()" in line]
        consumers.append({
            "name": Path(path).stem.replace("Analysis_", ""),
            "gates": gates,
            "commits_srs": any("COMMIT_HISTOGRAM_SRS" in line for line in src),
        })

    return {
        "read_line": read,
        "default": False,
        "macros": guarded,
        "fill_guard_line": fill_guard,
        "consumers": consumers,
    }


def policies(root: Path, ref: str) -> dict[str, dict]:
    """Keys solo.cpp writes into the collider options node itself."""
    src = show(root, ref, SOLO)
    out = {}
    lines = src.splitlines()
    for index, line in enumerate(lines):
        match = POLICY_RE.search(line)
        if not match or match.group(1) == "analyses":
            continue
        comment = ""
        probe = index - 1
        while probe >= 0 and lines[probe].strip().startswith("//"):
            comment = lines[probe].strip().lstrip("/ ") + " " + comment
            probe -= 1
        out[match.group(1)] = {"value": match.group(2).strip(),
                               "line": index + 1, "why": comment.strip()}
    return out


def is_dead(root: Path, key: str) -> bool:
    """True when no C++ source at either ref mentions the key at all."""
    for ref in (BASE, "HEAD"):
        hit = git(root, "grep", "-l", key, ref, "--", "*.cpp", "*.hpp")
        if hit.strip():
            return False
    return True


def classify(key: str, reads: dict, policy: dict, dead: bool) -> dict:
    if key in policy:
        return {"where": "CBS policy", "detail": policy[key]}
    if dead:
        return {"where": "dead", "detail": None}
    if key in reads:
        return {"where": reads[key]["kind"], "detail": reads[key]}
    return {"where": "unread", "detail": None}


def collect(root: Path) -> dict:
    original = show(root, BASE, EXAMPLE)
    current_example = show(root, "HEAD", EXAMPLE)

    new_style_path = root / NEW_STYLE
    new_style = new_style_path.read_text(errors="replace") if new_style_path.exists() else ""
    defaults_path = root / DEFAULTS
    defaults = defaults_path.read_text(errors="replace") if defaults_path.exists() else ""

    orig_keys = yaml_settings(original)
    new_keys = yaml_settings(new_style)
    example_keys = yaml_settings(current_example)

    reads = readers(root, "HEAD")
    policy = policies(root, "HEAD")

    rows = []
    for entry in orig_keys:
        key = entry["key"]
        dead = is_dead(root, key)
        verdict = classify(key, reads, policy, dead)
        rows.append({**entry, **verdict,
                     "still_in_new": any(k["key"] == key for k in new_keys)})

    # Keys the branch introduced: present in the current example but not the original.
    orig_names = {k["key"] for k in orig_keys}
    added = [k for k in example_keys if k["key"] not in orig_names]
    for entry in added:
        entry.update(classify(entry["key"], reads, policy, False))

    jet_required = "jet_collections" in reads and reads["jet_collections"]["kind"] == "user"
    gate = histogram_gate(root, "HEAD")

    counts = {"user": 0, "program": 0, "conditional": 0,
              "CBS policy": 0, "dead": 0, "unread": 0}
    for row in rows:
        counts[row["where"]] += 1

    defaults_tracked = bool(git(root, "ls-files", DEFAULTS).strip())

    return {
        "generated_by": "scripts/build-yaml-config-page.py",
        "refs": {"baseline": BASE, "head": git(root, "rev-parse", "--short", "HEAD").strip()},
        "original": {"path": EXAMPLE, "text": original, "keys": orig_keys,
                     "lines": line_counts(original)},
        "current_example": {"path": EXAMPLE, "keys": example_keys,
                            "lines": line_counts(current_example)},
        "new_style": {"path": NEW_STYLE, "text": new_style, "keys": new_keys,
                      "lines": line_counts(new_style), "exists": bool(new_style)},
        "defaults": {"path": DEFAULTS, "text": defaults, "exists": bool(defaults),
                     "tracked": defaults_tracked,
                     "lines": line_counts(defaults)},
        "rows": rows,
        "added": added,
        "policy": policy,
        "counts": counts,
        "jet_collections_required": jet_required,
        "histogram_gate": gate,
        "caveat": "Static read of the worktree. Nothing was built or run.",
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


CONVERGENCE_KEYS = (
    "events_between_convergence_checks",
    "target_fractional_uncert",
    "halt_when_systematic_dominated",
    "all_analyses_must_converge",
    "all_SR_must_converge",
)


def annotated_example_text(text: str, side: str, data: dict) -> str:
    """Add inline comments that classify settings in the two examples."""
    if not text:
        return text

    dead_keys = [row["key"] for row in data["rows"] if row["where"] == "dead"]
    lines = text.splitlines()
    annotated = []

    if side == "before":
        convergence_note_added = False
        dead_note_added = False
        for line in lines:
            match = re.match(r"^\s*([A-Za-z_]\w*):", line)
            key = match.group(1) if match else ""
            if key in CONVERGENCE_KEYS and not convergence_note_added:
                annotated.extend([
                    "# LEGACY / INERT IN CURRENT CBS:",
                    "# These settings may still parse, but solo.cpp forces",
                    "# run_convergence_checks=false, so they no longer control early stopping.",
                ])
                convergence_note_added = True
            if key in dead_keys and not dead_note_added:
                annotated.extend([
                    "# DEAD KEYS / NO C++ READER IN THE CURRENT TREE:",
                    *[f"# - {key}" for key in dead_keys],
                ])
                dead_note_added = True
            annotated.append(line)
        annotated.extend([
            "",
            "  # Jet definitions had to be supplied explicitly in the old standalone YAML.",
            "  jet_collections:",
            "    antikt_R04:",
            "      algorithm: antikt",
            "      R: 0.4",
            "      recombination_scheme: E_scheme",
            "      strategy: Best",
            "  jet_collection_taus: antikt_R04",
        ])
        return "\n".join(annotated)

    if side == "after":
        # Keep the generated example focused on the active batch input.  The
        # source YAML still carries several historical, commented-out
        # single-file alternatives; showing all of them makes the example
        # look like a mixture of mutually exclusive configurations.  Retain
        # one explicit single-file alternative below instead.
        cleaned_lines = []
        yaml_started = False
        for line in lines:
            stripped = line.strip()
            if not yaml_started:
                if stripped in {"analyses:", "settings:"}:
                    yaml_started = True
                else:
                    continue
            if re.match(r"^\s*#\s*-?\s*CMS_SUS_", line):
                continue
            if re.match(r"^\s*#\s*(event_file|cross_section_fb):", line):
                continue
            cleaned_lines.append(line)
        lines = cleaned_lines

        for line in lines:
            if line.strip().startswith("# jet_collections"):
                annotated.extend([
                    "  # SINGLE-FILE ALTERNATIVE (replace the processes block above):",
                    "  # event_file: /Users/p.zhu/Workshop/GambitWS/ATLAS_EXOT_2019_04/Events/singletB_2000_50K.hepmc",
                    "  # cross_section_fb: 17.564",
                    "  # cross_section_fractional_uncert: 0.20  # replace with the appropriate value",
                ])
            annotated.append(line)
        return "\n".join(annotated)

    raise ValueError(f"unknown example side: {side}")


WHERE_CLASS = {"user": "unchanged", "program": "added-in-right",
               "conditional": "unchanged", "CBS policy": "added-in-right",
               "dead": "", "unread": ""}
WHERE_LABEL = {"user": "still yours", "program": "program default",
               "conditional": "conditional", "CBS policy": "CBS policy",
               "dead": "dead key", "unread": "not read"}


def key_rows(data: dict) -> str:
    rows = []
    for row in data["rows"]:
        detail = row["detail"]
        if row["where"] == "program":
            says = (f'<code>getValueOrDef({esc(detail["default"])})</code>'
                    f'<span class="ln">{esc(detail["file"])}:{detail["line"]}</span>')
        elif row["where"] == "CBS policy":
            says = (f'<code>= {esc(detail["value"])}</code>'
                    f'<span class="ln">solo.cpp:{detail["line"]}</span>')
        elif row["where"] == "conditional":
            other = detail["other"]
            says = (f'<code>getValue</code> at <code>{esc(other["file"])}:{other["line"]}</code> '
                    f'when convergence checks run, else '
                    f'<code>getValueOrDef({esc(detail["default"])})</code>'
                    f'<span class="ln">CBS forces the second branch</span>')
        elif row["where"] == "user":
            alt = ALTERNATIVES.get(row["key"])
            extra = f' &mdash; or <code>{esc(alt)}</code>' if alt else " &mdash; required"
            says = (f'<code>getValue</code>{extra}'
                    f'<span class="ln">{esc(detail["file"])}:{detail["line"]}</span>')
        elif row["where"] == "dead":
            says = '<span class="status">no reader in any .cpp/.hpp</span>'
        else:
            says = '<span class="status">&#8212;</span>'
        rows.append(
            f'<tr><td><code>{esc(row["key"])}</code></td>'
            f'<td><code>{esc(row["value"])}</code></td>'
            f'<td><span class="status {WHERE_CLASS[row["where"]]}">'
            f'{WHERE_LABEL[row["where"]]}</span></td>'
            f'<td>{says}</td></tr>'
        )
    return "\n".join(rows)


def policy_rows(data: dict) -> str:
    return "\n".join(
        f'<tr><td><code>{esc(key)}</code></td>'
        f'<td><code>{esc(record["value"])}</code></td>'
        f'<td class="num">{record["line"]}</td>'
        f'<td>{esc(record["why"]) or "&#8212;"}</td></tr>'
        for key, record in data["policy"].items()
    )


def added_rows(data: dict) -> str:
    rows = []
    for entry in data["added"]:
        where = WHERE_LABEL.get(entry["where"], entry["where"])
        rows.append(f'<tr><td><code>{esc(entry["key"])}</code></td>'
                    f'<td><span class="status {WHERE_CLASS.get(entry["where"], "")}">'
                    f'{where}</span></td>'
                    f'<td><code>{esc(entry["value"])[:70]}</code></td></tr>')
    return "\n".join(rows)


def macro_gate_rows(data: dict) -> str:
    rows = []
    for name, record in data["histogram_gate"]["macros"].items():
        if record["self_guarded"]:
            badge = '<span class="status added-in-right">yes</span>'
            note = "Expands to a guarded statement; safe to call unconditionally."
        else:
            badge = '<span class="status unchanged">no</span>'
            note = ("Runs whenever the analysis calls it. The analysis must supply the "
                    "<code>if (Histogram1D::check_histogram())</code> itself.")
        rows.append(f'<tr><td><code>{esc(name)}</code>'
                    f'<span class="ln">AnalysisMacros.hpp:{record["line"]}</span></td>'
                    f'<td>{badge}</td><td>{note}</td></tr>')
    return "\n".join(rows)


def render_markdown(data: dict) -> str:
    counts = data["counts"]
    lines = [
        "# The user YAML, before and after",
        "",
        f'Baseline `{data["refs"]["baseline"]}` &rarr; head `{data["refs"]["head"]}`.',
        "",
        f'Input file: {data["original"]["lines"]["code"]} lines of settings then, '
        f'{data["new_style"]["lines"]["code"]} now (blank and comment lines excluded).',
        "",
        "## Where the original settings went",
        "",
        "| Setting | Original value | Who decides now |",
        "|---|---|---|",
    ]
    for row in data["rows"]:
        lines.append(f'| `{row["key"]}` | `{row["value"]}` | {WHERE_LABEL[row["where"]]} |')
    lines += [
        "",
        f'{counts["user"]} still the user\'s, {counts["program"]} now defaulted inside the '
        f'program, {counts["CBS policy"]} decided by CBS regardless of the YAML, '
        f'{counts["dead"]} read by nothing at all.',
        "",
        "## What CBS decides for you",
        "",
        "| Key | Value | solo.cpp |",
        "|---|---|---|",
    ]
    for key, record in data["policy"].items():
        lines.append(f'| `{key}` | `{record["value"]}` | {record["line"]} |')
    lines += ["", "No build or run was performed for this document.", ""]
    return "\n".join(lines)


CSS = Path(__file__).with_name("_page_css.html")


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The user YAML, before and after</title>
__CSS__
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit Solo &#183; configuration</p>
  <h1>The user YAML</h1>
  <p class="intro">The original input file and the one a user writes now, side by side &mdash; and then the question a YAML diff cannot answer: for each setting that used to be in that file, who decides it today. Some are still the user&#8217;s. Some the program now defaults. Three are overwritten by CBS whatever the file says. Three were read by nothing at all, then or now.</p>
  <div class="meta"><span><strong>BASELINE</strong> __BASELINE__</span><span><strong>HEAD</strong> __HEAD__</span><span><strong>METHOD</strong> every key traced to the call that consumes it</span><span><strong>STATIC EVIDENCE</strong> no build / no events processed</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page expands <a href="cbs-change-ledger.html#6">slide 6 of the CBS change-ledger deck &#8599;</a>.</span></p>

  <div class="summary-grid" aria-label="Summary">
    <div class="card"><span class="n">__ORIG_CODE__ &rarr; __NEW_CODE__</span><span class="label">lines of settings</span></div>
    <div class="card accent"><span class="n">__ORIG_KEYS__ &rarr; __NEW_KEYS__</span><span class="label">top-level keys</span></div>
    <div class="card"><span class="n">__C_USER__</span><span class="label">still yours</span></div>
    <div class="card accent"><span class="n">__C_PROGRAM__</span><span class="label">program defaults</span></div>
    <div class="card accent"><span class="n">__C_POLICY__</span><span class="label">CBS policy</span></div>
    <div class="card"><span class="n">__C_DEAD__</span><span class="label">read by nothing</span></div>
  </div>

  <section id="files">
    <p class="kicker">01 &#183; the two files</p>
    <h2>What a user actually writes</h2>
  <p class="source">Left: <code>__ORIG_PATH__</code> at the baseline. Right: <code>__NEW_PATH__</code> today. The YAML is retained and annotated in place so the examples show what is optional, forced by CBS, inert, or absent only because this example uses batch input. Counts exclude blank and comment lines &mdash; __COUNT_NOTE__</p>
    <div class="example-grid">
      <div class="example-col">
        <p class="example-h"><span class="tag-plain">before</span> __ORIG_CODE__ lines of settings + explicit jet configuration</p>
        <p class="example-note">The historical standalone YAML, including the explicit jet configuration expected by the old <code>solo.cpp</code> path:</p>
        <pre class="unit-hunks json-block">__ORIG_TEXT__</pre>
      </div>
      <div class="example-col">
        <p class="example-h"><span class="tag-sr">after</span> __NEW_CODE__ lines of settings</p>
    <p class="example-note">The analysis, the cross-section and its files, four switches, plus one explicit single-file alternative.</p>
        <pre class="unit-hunks json-block">__NEW_TEXT__</pre>
      </div>
    </div>
    <p class="diagram-note"><strong>The shape of the change is not &ldquo;shorter&rdquo;.</strong> The historical standalone example omitted <code>jet_collections</code>, but the old standalone code already expected that setting from the user. Current CBS keeps the jet definitions required in the merged settings while allowing <code>CBS_defaults.yaml</code> to supply them, so the main user file can stay compact. Separately, the convergence block that used to be the user&#8217;s business stopped being the user&#8217;s business. Those are two different movements and the file diff shows neither.</p>
  </section>

  <section id="where">
    <p class="kicker">02 &#183; where each setting went</p>
    <h2>Who decides it now</h2>
    <p class="source">Every key from the original file, traced to the call that reads it today.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:32%">Setting</th><th style="width:16%">Original value</th><th style="width:16%">Who decides</th><th>Evidence</th></tr></thead>
      <tbody>__KEY_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">__WHERE_NOTE__</p>
  </section>

  <section id="policy">
    <p class="kicker">03 &#183; what CBS decides for you</p>
    <h2>Three settings the YAML cannot reach</h2>
    <p class="source"><code>solo.cpp</code> builds the collider options node from the user settings and then writes over it.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:26%">Key</th><th style="width:22%">Forced to</th><th style="width:10%">Line</th><th>Reason in the source</th></tr></thead>
      <tbody>__POLICY_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>This is the one to say aloud.</strong> <code>run_convergence_checks</code> is forced to <code>false</code>, so CBS always processes every event the user supplied and never stops early. That makes the whole convergence group from the original file inert &mdash; <code>target_fractional_uncert</code>, <code>halt_when_systematic_dominated</code>, <code>all_analyses_must_converge</code>, <code>all_SR_must_converge</code>, <code>events_between_convergence_checks</code> are still read, still have defaults, and no longer change what a CBS run does. The event loop was edited to match: <code>ColliderBit_eventloop.cpp:197</code> keeps <code>target_fractional_uncert</code> mandatory when convergence checks are on, and falls back to <code>0.30</code> when they are off, with the comment <em>&ldquo;For explicit no-convergence runs (CBS policy), this value is unused.&rdquo;</em></p>
    <p class="diagram-note">A user carrying an old file forward will not be told any of this. The keys still parse, so nothing warns; they simply stop meaning anything. Worth a line in the CBS documentation rather than leaving it to be discovered.</p>
  </section>

  <section id="added">
    <p class="kicker">04 &#183; what the branch added</p>
    <h2>New keys the original never had</h2>
    <p class="source">Present in the shipped example at HEAD, absent at the baseline.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:28%">Key</th><th style="width:16%">Who decides</th><th>Value in the shipped example</th></tr></thead>
      <tbody>__ADDED_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">Note which one is <em>required</em>: <code>jet_collections</code>. The old standalone path expected the user to provide it explicitly; current CBS still requires it in the merged settings, but <code>CBS_defaults.yaml</code> can now supply it before the lookup. If neither source provides it, <code>Utils.hpp:96</code> throws.</p>
  </section>

  <section id="check-histogram">
    <p class="kicker">05 &#183; one switch, two consequences</p>
    <h2><code>check_histogram</code> does not mean the same thing twice</h2>
    <p class="source">Read once at <code>solo.cpp:__CH_LINE__</code> with <code>getValueOrDef&lt;bool&gt;(false, &hellip;)</code> and set on a static that every analysis shares. <strong>The default is <code>false</code>.</strong></p>
    <div class="mapping-table"><table>
      <thead><tr>
        <th style="width:20%">Histogram kind</th>
        <th style="width:26%"><code>check_histogram: false</code> &mdash; the default</th>
        <th style="width:26%"><code>check_histogram: true</code></th>
        <th>What the flag actually costs</th>
      </tr></thead>
      <tbody>
        <tr>
          <td><strong>plain</strong><span class="ln">obs empty</span></td>
          <td>Not booked, not filled, not written. Nothing in the JSON, nothing to plot.</td>
          <td>Appears under <code>histograms.1d</code> with counts and <code>sumw2</code>.</td>
          <td><span class="status added-in-right">output only</span> Signal regions are identical either way. Turning it on adds a diagnostic and changes no result.</td>
        </tr>
        <tr>
          <td><strong>signal region</strong><span class="ln">obs / bkg / bkg_err set</span></td>
          <td>Same as above &mdash; <em>and</em> <code>COMMIT_HISTOGRAM_SRS</code> never runs, so the per-bin regions do not exist.</td>
          <td>Appears in the JSON <em>and</em> every bin is added as a <code>SignalRegionData</code>.</td>
          <td><span class="status unchanged">changes the likelihood</span> The analysis contributes a different number of signal regions depending on this flag.</td>
        </tr>
      </tbody>
    </table></div>
    <p class="diagram-note">__CH_CONSUMER_NOTE__</p>

    <h3 style="margin-top:22px;font-size:15px">Where the gate actually sits</h3>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:32%">Macro</th><th style="width:20%">Tests the flag itself?</th><th>Consequence</th></tr></thead>
      <tbody>__CH_MACRO_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>Only the fill macros are self-guarding.</strong> <code>FILL_HISTOGRAM_1D</code> and <code>FILL_HISTOGRAM_2D</code> expand to <code>if (Histogram1D::check_histogram()) &hellip;</code>, and <code>Histogram1D::fill</code> checks again at <code>Histogram.hpp:__CH_FILL_GUARD__</code>. Booking and committing are <em>not</em> guarded by the macro &mdash; each analysis writes <code>if (Histogram1D::check_histogram())</code> around them by hand.</p>
    <div class="note"><strong>The failure mode this leaves open.</strong> An analysis that books and commits signal-region histograms <em>without</em> the hand-written guard would, with the flag off, still create the histogram and still commit its bins &mdash; but the fills would all have been skipped. The result is a full set of per-bin signal regions with a signal prediction of exactly zero in every bin. That is not a crash and not a missing key; it is a likelihood built on empty predictions, and nothing in the framework would report it. All three current consumers do write the guard, so this is a latent hazard rather than a present bug &mdash; but the guard belongs inside <code>COMMIT_HISTOGRAM_SRS</code>, where it cannot be forgotten.</div>
  </section>

  <section id="defaults">
    <p class="kicker">06 &#183; the default card</p>
    <h2>Three layers, user wins</h2>
    <p class="source">__DEFAULTS_SOURCE__</p>
    <div class="grid-2">
      <div>
        <div class="mapping-table"><table>
          <thead><tr><th style="width:34%">Layer</th><th>What it contributes</th></tr></thead>
          <tbody>
            <tr><td><strong>1 &#183; global</strong></td><td><code>CBS_defaults.yaml &rarr; settings:</code></td></tr>
            <tr><td><strong>2 &#183; per analysis</strong></td><td><code>analysis_defaults: &lt;NAME&gt;:</code>, merged in the order the analyses appear in the user's YAML</td></tr>
            <tr><td><strong>3 &#183; user</strong></td><td>the input file &mdash; always last, always wins</td></tr>
          </tbody>
        </table></div>
        <p class="diagram-note"><code>merge_yaml_nodes</code> (<code>solo_input.cpp:62</code>) recurses through maps, but <strong>scalars and sequences are replaced whole</strong>: a list can be overridden, never appended to. Lookup for the defaults file runs five steps &mdash; <code>cbs_defaults_file:</code>, <code>$CBS_DEFAULTS_FILE</code>, then three paths &mdash; and <code>use_cbs_defaults: false</code> opts out entirely.</p>
      </div>
      <div>
        <p class="example-note">__DEFAULTS_CAPTION__</p>
        <pre class="unit-hunks json-block">__DEFAULTS_TEXT__</pre>
      </div>
    </div>
    <div class="note">__DEFAULTS_WARNING__</div>
  </section>

  <section>
    <p class="kicker">07 &#183; boundary</p>
    <h2>What this page does not tell you</h2>
    <div class="note">Each key is placed by the call that reads it, found by scanning four source files for <code>getValue</code> and <code>getValueOrDef</code>. That is a textual match, not an execution trace: a key consumed through some other path would be reported as unread, and the &ldquo;dead key&rdquo; verdict means only that no <code>.cpp</code> or <code>.hpp</code> in the repository names it at either ref. Nothing was compiled and no run was performed, so this page describes what the code says it will do with a setting, not what a run then produces.</div>
  </section>

  <p class="backlink" style="margin-top:26px"><span class="lbl">back</span><span>Return to <a href="cbs-change-ledger.html#6">slide 6 &#8599;</a>, or to the <a href="cbs-change-ledger.html#1">start of the deck &#8599;</a>.</span></p>
  <footer>Generated by <code>scripts/build-yaml-config-page.py</code>. Baseline <code>__BASELINE__</code>, head <code>__HEAD__</code>.</footer>
</main>
</body>
</html>'''


def render_html(data: dict) -> str:
    counts = data["counts"]

    dead = [r["key"] for r in data["rows"] if r["where"] == "dead"]
    program = [r["key"] for r in data["rows"] if r["where"] == "program"]
    where_note = (
        f'{counts["user"]} of the original settings are still read from the user file and still '
        f'required. {counts["program"]} gained a default inside the program, so omitting them is '
        f'now legal &mdash; that is the bulk of why the new file is shorter. '
    )
    if dead:
        where_note += (
            f'And {len(dead)} were read by <strong>nothing at all</strong>, at either ref: '
            + ", ".join(f"<code>{esc(k)}</code>" for k in dead) +
            '. They were already inert when the original example shipped them, which is worth '
            'knowing before anyone copies that file forward as a reference.'
        )

    if data["defaults"]["exists"]:
        defaults_source = (f'<code>{esc(data["defaults"]["path"])}</code>, '
                           f'{data["defaults"]["lines"]["code"]} lines of settings '
                           f'in the working tree.')
        defaults_caption = "The card for one analysis, verbatim."
        defaults_text = esc(data["defaults"]["text"])
    else:
        defaults_source = "No defaults file was found in the working tree."
        defaults_caption = ""
        defaults_text = ""

    if not data["defaults"]["tracked"]:
        defaults_warning = (
            '<strong>The defaults file is not in the repository.</strong> '
            '<code>.gitignore</code> ignores <code>CBS_yaml/*</code> and '
            '<code>git ls-files CBS_yaml/</code> is empty, so a fresh clone has no '
            '<code>CBS_defaults.yaml</code>. All five lookup steps then fail and '
            '<code>apply_default_settings</code> returns the user settings unchanged and '
            '<strong>silently</strong> (<code>solo_input.cpp:130</code>). The run dies later at '
            '<code>Utils.hpp:96</code> with <em>&ldquo;Could not find jet_collections option. '
            'Please provide this in the YAML file&rdquo;</em> &mdash; pointing the user at their '
            'own file rather than at the missing defaults. Committing the card, or printing one '
            'line when the lookup fails, would close this.'
        )
    else:
        defaults_warning = "The defaults file is tracked in the repository."

    orig_lines, new_lines = data["original"]["lines"], data["new_style"]["lines"]
    count_note = (
        f'{orig_lines["total"]} and {new_lines["total"]} lines raw, which points the wrong way: '
        f'the current file carries {new_lines["comment"]} comment and blank lines against the '
        f'original\u2019s {orig_lines["comment"]}, so counting everything makes the shorter file '
        'look longer.'
    )

    gate = data["histogram_gate"]
    sr_users = [c["name"] for c in gate["consumers"] if c["commits_srs"]]
    plain_users = [c["name"] for c in gate["consumers"] if not c["commits_srs"]]
    ch_consumer_note = (
        "Both rows are live in this branch. "
        + ", ".join(f"<code>{esc(n)}</code>" for n in sr_users)
        + (" commit" if len(sr_users) != 1 else " commits")
        + " histogram-backed signal regions, so the flag moves their likelihood; "
        + ", ".join(f"<code>{esc(n)}</code>" for n in plain_users)
        + (" books" if len(plain_users) == 1 else " book")
        + " plain histograms only, so the flag decides whether a plot exists and nothing more. "
        "A reader cannot tell which case they are in from the YAML &mdash; the key looks the same "
        "in both, and the analysis source is the only place the difference is written down."
    )

    css = CSS.read_text() if CSS.exists() else "<style></style>"
    expected = set(re.findall(r"__[A-Z_]+__", TEMPLATE))
    page = TEMPLATE.replace("__CSS__", css)
    replacements = {
        "__BASELINE__": esc(data["refs"]["baseline"]),
        "__HEAD__": esc(data["refs"]["head"]),
        "__ORIG_KEYS__": str(len(data["original"]["keys"])),
        "__NEW_KEYS__": str(len(data["new_style"]["keys"])),
        "__C_USER__": str(counts["user"]),
        "__C_PROGRAM__": str(counts["program"]),
        "__C_POLICY__": str(len(data["policy"])),
        "__C_DEAD__": str(counts["dead"]),
        "__ORIG_PATH__": esc(data["original"]["path"]),
        "__NEW_PATH__": esc(data["new_style"]["path"]),
        "__ORIG_CODE__": str(data["original"]["lines"]["code"]),
        "__NEW_CODE__": str(data["new_style"]["lines"]["code"]),
        "__COUNT_NOTE__": count_note,
        "__ORIG_TEXT__": esc(annotated_example_text(data["original"]["text"], "before", data)),
        "__NEW_TEXT__": esc(annotated_example_text(data["new_style"]["text"], "after", data)),
        "__KEY_ROWS__": key_rows(data),
        "__WHERE_NOTE__": where_note,
        "__POLICY_ROWS__": policy_rows(data),
        "__ADDED_ROWS__": added_rows(data),
        "__CH_LINE__": str(gate["read_line"]),
        "__CH_FILL_GUARD__": str(gate["fill_guard_line"]),
        "__CH_MACRO_ROWS__": macro_gate_rows(data),
        "__CH_CONSUMER_NOTE__": ch_consumer_note,
        "__DEFAULTS_SOURCE__": defaults_source,
        "__DEFAULTS_CAPTION__": defaults_caption,
        "__DEFAULTS_TEXT__": defaults_text,
        "__DEFAULTS_WARNING__": defaults_warning,
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
    (args.out_dir / "cbs-yaml-config.json").write_text(json.dumps(data, indent=2) + "\n")
    page = render_html(data)
    (args.out_dir / "cbs-yaml-config.html").write_text(page)
    (args.out_dir / "CBS_YAML_CONFIG.md").write_text(render_markdown(data))
    if args.site_dir.exists():
        (args.site_dir / "cbs-yaml-config.html").write_text(page)

    print(json.dumps({
        "counts": data["counts"],
        "policy": {k: v["value"] for k, v in data["policy"].items()},
        "dead": [r["key"] for r in data["rows"] if r["where"] == "dead"],
        "added": [e["key"] for e in data["added"]],
        "defaults_tracked": data["defaults"]["tracked"],
    }, indent=2))
    for name in ("cbs-yaml-config.json", "cbs-yaml-config.html", "CBS_YAML_CONFIG.md"):
        print(f"Wrote {args.out_dir / name}")


if __name__ == "__main__":
    main()
