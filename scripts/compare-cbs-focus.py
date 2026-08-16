#!/usr/bin/env python3
"""Generate a focused, diagram-design comparison for one CBS source file.

The full branch graph is useful for inventory, but it is too dense for a human
change review.  This script keeps the comparison reusable while limiting the
visual surface to one file, its direct include surface, and its functions.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import difflib
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
from typing import Any


INCLUDE_RE = re.compile(r"^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]", re.MULTILINE)
FUNCTION_RE = re.compile(
    r"(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*"
    r"\([^;{}\n]*\)\s*"
    r"(?:(?:const|noexcept|override|final|&{1,2})\s*)*\{",
    re.MULTILINE,
)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(")
CONTROL_CALLS = {
    "catch",
    "for",
    "if",
    "while",
    "switch",
    "return",
    "sizeof",
    "static_cast",
    "dynamic_cast",
    "reinterpret_cast",
    "const_cast",
}


@dataclass(frozen=True)
class Snapshot:
    path: str
    text: str
    digest: str


def run_git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def branch_metadata(root: Path, label: str) -> dict[str, str]:
    return {
        "label": label,
        "branch": run_git(root, "branch", "--show-current") or "(detached HEAD)",
        "commit": run_git(root, "rev-parse", "HEAD"),
        "short": run_git(root, "rev-parse", "--short", "HEAD"),
        "subject": run_git(root, "show", "-s", "--format=%s", "HEAD"),
    }


def load_snapshot(root: Path, relative: str) -> Snapshot:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Focused file does not exist: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    return Snapshot(relative, text, hashlib.sha256(text.encode("utf-8")).hexdigest())


def strip_comments(text: str) -> str:
    text = re.sub(
        r"/\*.*?\*/",
        lambda match: "\n" * match.group(0).count("\n"),
        text,
        flags=re.DOTALL,
    )
    return re.sub(r"//[^\n]*", "", text)


def matching_brace(text: str, opening: int) -> int:
    depth = 0
    in_string: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in {"\"", "'"}:
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def function_symbols(snapshot: Snapshot) -> list[dict[str, Any]]:
    clean = strip_comments(snapshot.text)
    symbols: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    for match in FUNCTION_RE.finditer(clean):
        name = match.group("name")
        short_name = name.rsplit("::", 1)[-1]
        if short_name in CONTROL_CALLS or name in CONTROL_CALLS:
            continue
        opening = clean.rfind("{", match.start(), match.end())
        end = matching_brace(clean, opening)
        if end <= opening:
            continue
        line = clean.count("\n", 0, match.start()) + 1
        line_end = clean.count("\n", 0, end) + 1
        seen[name] += 1
        suffix = f"#{seen[name]}" if seen[name] > 1 else ""
        source = clean[match.start() : end].strip()
        symbols.append(
            {
                "id": f"symbol:{snapshot.path}::{name}{suffix}",
                "name": name,
                "short_name": short_name,
                "line": line,
                "line_end": line_end,
                "start": match.start(),
                "end": end,
                "body_start": match.end(),
                "symbol_digest": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            }
        )
    return symbols


def resolve_include(root: Path, source: str, include: str) -> str | None:
    source_path = Path(source)
    candidates = [
        root / source_path.parent / include,
        root / include,
        root / "ColliderBit" / "include" / include,
        root / "ColliderBit" / "include" / "gambit" / include,
        root / "ColliderBit" / include,
    ]
    for component in ("Elements", "Utils", "Backends", "Printers", "Models", "ScannerBit"):
        candidates.append(root / component / "include" / include)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None


def module_for(path: str) -> str:
    if not path:
        return "external"
    if path == "CMakeLists.txt" or path.endswith("/CMakeLists.txt") or path.startswith("cmake/"):
        return "build / CMake"
    if path.startswith("ColliderBit/examples/"):
        return "examples / entrypoint"
    if any(path.startswith(f"{component}/") for component in ("Elements", "Utils", "Backends", "Printers", "Models", "ScannerBit")):
        return "GAMBIT core"
    if "/src/analyses/" in path:
        return "analysis framework"
    if "/src/" in path:
        return "runtime core"
    if "/include/gambit/ColliderBit/analyses/" in path:
        return "analysis framework"
    if "/include/" in path:
        return "ColliderBit API"
    if path.startswith("ColliderBit/"):
        return "ColliderBit"
    return "external"


def line_slice(text: str, start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[max(0, start - 1) : end])


def line_diff_stats(left: str, right: str) -> dict[str, int]:
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)
    added = 0
    removed = 0
    hunks = 0
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks += 1
        removed += left_end - left_start
        added += right_end - right_start
    return {"added_lines": added, "removed_lines": removed, "hunks": hunks}


def git_diff_stats(left: Path, right: Path) -> dict[str, int]:
    proc = subprocess.run(
        ["git", "diff", "--no-index", "--numstat", str(left), str(right)],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
            return {"added_lines": int(fields[0]), "removed_lines": int(fields[1])}
    return {}


def status_for(left: dict[str, Any] | None, right: dict[str, Any] | None) -> str:
    if left is None:
        return "added-in-right"
    if right is None:
        return "removed-in-right"
    return "unchanged" if left["symbol_digest"] == right["symbol_digest"] else "modified"


def compare_functions(left: Snapshot, right: Snapshot) -> list[dict[str, Any]]:
    left_symbols = {symbol["name"]: symbol for symbol in function_symbols(left)}
    right_symbols = {symbol["name"]: symbol for symbol in function_symbols(right)}
    result: list[dict[str, Any]] = []
    for name in sorted(set(left_symbols) | set(right_symbols)):
        lsymbol = left_symbols.get(name)
        rsymbol = right_symbols.get(name)
        status = status_for(lsymbol, rsymbol)
        left_chunk = line_slice(left.text, lsymbol["line"], lsymbol["line_end"]) if lsymbol else ""
        right_chunk = line_slice(right.text, rsymbol["line"], rsymbol["line_end"]) if rsymbol else ""
        result.append(
            {
                "name": name,
                "short_name": name.rsplit("::", 1)[-1],
                "status": status,
                "baseline_line": lsymbol["line"] if lsymbol else None,
                "baseline_line_end": lsymbol["line_end"] if lsymbol else None,
                "comparison_line": rsymbol["line"] if rsymbol else None,
                "comparison_line_end": rsymbol["line_end"] if rsymbol else None,
                "baseline_digest": lsymbol["symbol_digest"] if lsymbol else None,
                "comparison_digest": rsymbol["symbol_digest"] if rsymbol else None,
                **line_diff_stats(left_chunk, right_chunk),
            }
        )
    return result


def compare_includes(left_root: Path, right_root: Path, focus_file: str) -> list[dict[str, Any]]:
    snapshots = {
        "baseline": (left_root, load_snapshot(left_root, focus_file)),
        "comparison": (right_root, load_snapshot(right_root, focus_file)),
    }
    includes: dict[str, dict[str, Any]] = {}
    for side, (root, snapshot) in snapshots.items():
        for match in INCLUDE_RE.finditer(snapshot.text):
            token = match.group(2)
            resolved = resolve_include(root, focus_file, token)
            entry = includes.setdefault(
                token,
                {
                    "include": token,
                    "baseline": None,
                    "comparison": None,
                },
            )
            entry[side] = {
                "resolved": resolved,
                "module": module_for(resolved or "external"),
                "line": snapshot.text.count("\n", 0, match.start()) + 1,
            }
    result = []
    for token in sorted(includes):
        entry = includes[token]
        if entry["baseline"] is None:
            status = "added-in-right"
        elif entry["comparison"] is None:
            status = "removed-in-right"
        else:
            status = "unchanged" if (
                entry["baseline"]["resolved"] == entry["comparison"]["resolved"]
                and entry["baseline"]["module"] == entry["comparison"]["module"]
            ) else "modified"
        entry["status"] = status
        result.append(entry)
    return result


def build_relations(root: Path, focus_file: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    focus_name = Path(focus_file).name
    candidates = [
        "CMakeLists.txt",
        "cmake/standalones.cmake",
        "cmake/contrib.cmake",
        "ColliderBit/CMakeLists.txt",
    ]
    for relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if focus_name in text or focus_file in text:
            relations.append(
                {
                    "kind": "builds",
                    "source": relative,
                    "target": focus_file,
                    "module": module_for(relative),
                }
            )
    return relations


def unified_diff(left: Snapshot, right: Snapshot) -> str:
    lines = difflib.unified_diff(
        left.text.splitlines(),
        right.text.splitlines(),
        fromfile=f"{left.path} · baseline",
        tofile=f"{right.path} · comparison",
        lineterm="",
    )
    return "\n".join(lines)


def display_diff(diff: str) -> str:
    """Make trailing spaces visible in HTML without hiding source evidence."""
    displayed = []
    for line in diff.splitlines():
        trimmed = line.rstrip(" ")
        displayed.append(trimmed + ("·" * (len(line) - len(trimmed))))
    return "\n".join(displayed)


def module_summary(includes: list[dict[str, Any]], relations: list[dict[str, Any]], focus_file: str) -> list[dict[str, Any]]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    buckets[module_for(focus_file)]["focus"] += 1
    for include in includes:
        module = include["baseline"]["module"] if include["baseline"] else include["comparison"]["module"]
        buckets[module][include["status"]] += 1
    for relation in relations:
        buckets[relation["module"]][relation["kind"]] += 1
    result = []
    for module, counts in sorted(buckets.items(), key=lambda item: (-sum(item[1].values()), item[0])):
        result.append(
            {
                "id": module,
                "focus": counts["focus"],
                "added": counts["added-in-right"],
                "modified": counts["modified"],
                "removed": counts["removed-in-right"],
                "unchanged": counts["unchanged"],
                "builds": counts["builds"],
            }
        )
    return result


def build_data(args: argparse.Namespace) -> dict[str, Any]:
    baseline_root = args.baseline.resolve()
    comparison_root = args.comparison.resolve()
    focus_file = Path(args.focus_file).as_posix()
    left = load_snapshot(baseline_root, focus_file)
    right = load_snapshot(comparison_root, focus_file)
    includes = compare_includes(baseline_root, comparison_root, focus_file)
    baseline_relations = build_relations(baseline_root, focus_file)
    comparison_relations = build_relations(comparison_root, focus_file)
    relation_keys = {(r["kind"], r["source"], r["target"]) for r in baseline_relations} | {
        (r["kind"], r["source"], r["target"]) for r in comparison_relations
    }
    relation_rows = []
    baseline_set = {(r["kind"], r["source"], r["target"]) for r in baseline_relations}
    comparison_set = {(r["kind"], r["source"], r["target"]) for r in comparison_relations}
    for kind, source, target in sorted(relation_keys):
        relation_rows.append(
            {
                "kind": kind,
                "source": source,
                "target": target,
                "module": module_for(source),
                "status": "unchanged" if (kind, source, target) in baseline_set and (kind, source, target) in comparison_set else "added-in-right" if (kind, source, target) in comparison_set else "removed-in-right",
            }
        )
    functions = compare_functions(left, right)
    file_stats = line_diff_stats(left.text, right.text)
    file_stats.update(git_diff_stats(baseline_root / focus_file, comparison_root / focus_file))
    changed_functions = [function for function in functions if function["status"] != "unchanged"]
    changed_relations = [relation for relation in relation_rows if relation["status"] != "unchanged"]
    changed_includes = [include for include in includes if include["status"] != "unchanged"]
    return {
        "schema": "cbs-focus-comparison/v1",
        "focus": {
            "file": focus_file,
            "module": module_for(focus_file),
            "baseline": {"lines": len(left.text.splitlines()), "digest": left.digest},
            "comparison": {"lines": len(right.text.splitlines()), "digest": right.digest},
            **file_stats,
        },
        "baseline": branch_metadata(baseline_root, args.baseline_label),
        "comparison": branch_metadata(comparison_root, args.comparison_label),
        "summary": {
            "functions": len(functions),
            "changed_functions": len(changed_functions),
            "includes": len(includes),
            "changed_includes": len(changed_includes),
            "relations": len(includes) + len(relation_rows),
            "changed_relations": len(changed_includes) + len(changed_relations),
            "changed_build_relations": len(changed_relations),
        },
        "functions": functions,
        "includes": includes,
        "relations": relation_rows,
        "modules": module_summary(includes, relation_rows, focus_file),
        "diff": unified_diff(left, right),
        "scope_note": "Focused static source evidence for one file; this is not a runtime trace or a complete C++ AST.",
    }


def page_html(data: dict[str, Any]) -> str:
    baseline = data["baseline"]
    comparison = data["comparison"]
    focus = data["focus"]
    summary = data["summary"]
    include_status = Counter(include["status"] for include in data["includes"])
    baseline_removed_helpers = sum(
        1
        for include in data["includes"]
        if include["status"] == "removed-in-right"
        and include["baseline"]
        and (include["baseline"]["resolved"] or "").startswith("ColliderBit/examples/")
    )
    comparison_added_helpers = sum(
        1
        for include in data["includes"]
        if include["status"] == "added-in-right"
        and include["comparison"]
        and (include["comparison"]["resolved"] or "").startswith("ColliderBit/examples/")
    )
    shared_includes = include_status["unchanged"]
    status_labels = {
        "added-in-right": "added in comparison",
        "removed-in-right": "removed in baseline",
        "unchanged": "unchanged",
        "modified": "modified",
    }

    def line_range(start: int | None, end: int | None) -> str:
        return f"{start}–{end or start}" if start else "—"

    function_rows = "".join(
        f"<tr><td class=\"status {function['status']}\">{html.escape(status_labels[function['status']])}</td>"
        f"<td><code>{html.escape(function['name'])}</code></td>"
        f"<td>{html.escape(line_range(function.get('baseline_line'), function.get('baseline_line_end')))}</td>"
        f"<td>{html.escape(line_range(function.get('comparison_line'), function.get('comparison_line_end')))}</td>"
        f"<td>+{function['added_lines']} / −{function['removed_lines']} · {function['hunks']} hunks</td></tr>"
        for function in data["functions"]
    )
    include_rows = "".join(
        f"<tr><td class=\"status {include['status']}\">{html.escape(status_labels[include['status']])}</td>"
        f"<td><code>#include {html.escape(include['include'])}</code></td>"
        f"<td>{html.escape((include['comparison'] or include['baseline'])['module'])}</td>"
        f"<td>{html.escape((include['comparison'] or include['baseline'])['resolved'] or 'external')} · "
        f"{html.escape(str((include['comparison'] or include['baseline'])['line']))}</td></tr>"
        for include in data["includes"]
    )
    module_rows_parts = []
    for module in data["modules"]:
        build_note = f" · {module['builds']} build" if module["builds"] else ""
        module_rows_parts.append(
            f"<span><strong>{html.escape(module['id'])}</strong> · +{module['added']} −{module['removed']} · "
            f"{module['unchanged']} retained{build_note}</span>"
        )
    module_rows = "".join(module_rows_parts)
    diff_summary = f"Show exact diff · +{focus['added_lines']} / −{focus['removed_lines']} lines · {focus['hunks']} hunks"
    title = f"{focus['file']} · {baseline['label']} vs {comparison['label']}"
    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root { --paper:#f5f5f5; --paper-2:#ececec; --ink:#2d3142; --muted:#4f5d75; --soft:#7a8399; --rule:rgba(45,49,66,.12); --accent:#eb6c36; --accent-tint:rgba(235,108,54,.08); --green:#4f8a69; --green-tint:#eef8f1; --red:#93513f; --red-tint:#f3e9e5; --font-sans:'Geist',system-ui,sans-serif; --font-mono:'Geist Mono',ui-monospace,monospace; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.55 var(--font-sans); }
    .frame { max-width:1520px; margin:0 auto; padding:42px 42px 64px; }
    .eyebrow,.kicker,.meta,.source,.status,th,footer,.tag { font-family:var(--font-mono); }
    .eyebrow { color:var(--muted); font-size:10px; letter-spacing:.16em; text-transform:uppercase; margin:0 0 12px; }
    h1 { font-family:'Instrument Serif',Georgia,serif; font-size:clamp(42px,5vw,72px); font-weight:400; letter-spacing:-.04em; line-height:.98; margin:0 0 14px; }
    h2 { font-size:28px; font-weight:600; letter-spacing:-.03em; line-height:1.08; margin:0 0 8px; }
    h3 { font-size:16px; margin:0 0 8px; }
    p { color:var(--muted); }
    .intro { max-width:1080px; font-size:15px; line-height:1.65; margin:0 0 18px; }
    .meta { display:flex; flex-wrap:wrap; gap:8px 18px; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); padding:12px 0; color:var(--muted); font-size:10px; }
    .meta strong { color:var(--accent); font-weight:600; }
    .note { border-left:3px solid var(--accent); color:var(--muted); font-size:11px; line-height:1.6; margin:18px 0; max-width:1160px; padding:8px 12px; }
    .summary-grid { display:grid; grid-template-columns:1.2fr .9fr .9fr 1.1fr 1.1fr; gap:12px; margin:22px 0 32px; }
    .card { background:#fff; border:1px solid var(--rule); border-radius:6px; padding:14px 16px; }
    .card.accent { border-color:rgba(235,108,54,.45); background:var(--accent-tint); }
    .card .n { color:var(--ink); display:block; font-size:28px; font-weight:600; letter-spacing:-.04em; line-height:1; margin-bottom:8px; }
    .card .label { color:var(--soft); font-family:var(--font-mono); font-size:9px; letter-spacing:.1em; text-transform:uppercase; }
    section { border-top:1px solid var(--rule); margin-top:28px; padding:24px 0 0; }
    .kicker { color:var(--soft); font-size:9px; letter-spacing:.16em; margin:0 0 8px; text-transform:uppercase; }
    .source { color:var(--soft); font-size:10px; line-height:1.55; margin:0 0 14px; }
    .diagram-shell { overflow-x:auto; }
    svg { display:block; min-width:1000px; width:100%; height:auto; }
    svg .zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .zone-label { fill:var(--soft); font:500 10px var(--font-mono); letter-spacing:1.6px; }
    svg .edge { fill:none; stroke:var(--muted); stroke-width:1.2; marker-end:url(#focus-arrow); }
    svg .edge.delta { stroke:var(--accent); stroke-dasharray:5 4; marker-end:url(#focus-arrow-accent); }
    svg .node rect { fill:#fff; stroke:var(--ink); stroke-width:1.2; }
    svg .node.stage rect { fill:rgba(79,93,117,.08); stroke:var(--soft); }
    svg .node.mod rect { fill:#fff0e8; stroke:#b55c2d; }
    svg .node.add rect { fill:var(--green-tint); stroke:var(--green); }
    svg .node.remove rect { fill:var(--red-tint); stroke:var(--red); stroke-dasharray:5 4; }
    svg .node.focal rect { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    svg .node .kind { fill:var(--soft); font:500 9px var(--font-mono); letter-spacing:1.2px; }
    svg .node .title { fill:var(--ink); font:600 13px var(--font-sans); }
    svg .node .body { fill:var(--muted); font:9px var(--font-mono); }
    svg .node .tag { fill:var(--soft); font:8px var(--font-mono); letter-spacing:.8px; }
    svg .node.mod .kind { fill:#b55c2d; } svg .node.add .kind { fill:var(--green); } svg .node.remove .kind { fill:var(--red); } svg .node.focal .kind { fill:var(--accent); }
    svg .edge-label, svg .legend-label { fill:var(--muted); font:8px var(--font-mono); letter-spacing:.8px; }
    .diagram-note { color:var(--muted); font-size:12px; line-height:1.6; margin:13px 0 0; max-width:1160px; }
    .details-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:start; }
    .controls { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:12px 0; }
    input,select { background:#fff; border:1px solid rgba(45,49,66,.2); border-radius:4px; color:var(--ink); font:11px var(--font-mono); padding:8px 9px; }
    input[type=search] { flex:1; min-width:220px; }
    .scroll { border:1px solid var(--rule); max-height:520px; overflow:auto; }
    table { border-collapse:collapse; font-size:11px; width:100%; }
    th,td { border-bottom:1px solid var(--rule); padding:8px 9px; text-align:left; vertical-align:top; }
    th { background:#ececec; color:var(--muted); font-size:9px; letter-spacing:.08em; position:sticky; text-transform:uppercase; top:0; z-index:1; }
    td code { color:var(--ink); font-family:var(--font-mono); font-size:10px; word-break:break-word; }
    .status { font-size:9px; font-weight:600; letter-spacing:.04em; white-space:nowrap; }
    .status.modified { color:#b55c2d; } .status.added-in-right { color:var(--green); } .status.removed-in-right { color:var(--red); } .status.unchanged { color:var(--soft); }
    .module-strip { display:flex; flex-wrap:wrap; gap:8px 18px; border-bottom:1px solid var(--rule); padding:0 0 14px; }
    .module-strip span { color:var(--muted); font:10px var(--font-mono); }
    .module-strip strong { color:var(--ink); font-weight:600; }
    details { border-top:1px solid var(--rule); margin-top:16px; }
    summary { cursor:pointer; color:var(--ink); font:11px var(--font-mono); padding:12px 0; }
    pre { background:#fff; border:1px solid var(--rule); color:var(--ink); font:10px/1.45 var(--font-mono); margin:0; max-height:720px; overflow:auto; padding:16px; white-space:pre; }
    footer { border-top:1px solid var(--rule); color:var(--soft); font-size:10px; margin-top:32px; padding-top:14px; }
    @media (max-width:900px) { .frame { padding:30px 20px 48px; } .summary-grid { grid-template-columns:repeat(2,1fr); } .details-grid { grid-template-columns:1fr; } }
    @media (max-width:560px) { .summary-grid { grid-template-columns:1fr 1fr; } h1 { font-size:48px; } }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit Solo · focused source comparison</p>
  <h1>solo.cpp / branch delta</h1>
  <p class="intro">A focused comparison of <code>__FOCUS_FILE__</code> between the baseline CBS Solo branch and SUSYRun2. The overview isolates the entrypoint and its direct source surface; the evidence below expands to functions, includes and exact diff hunks.</p>
  <div class="meta"><span><strong>BASELINE</strong> __BASELINE__</span><span><strong>COMPARISON</strong> __COMPARISON__</span><span><strong>MODULE</strong> __MODULE__</span><span><strong>STATIC EVIDENCE</strong> no build / no runtime trace</span></div>
  <div class="note">__SCOPE_NOTE__ Function status uses a per-function digest rather than inheriting the whole-file status. Include and build relationships are compared by their source tokens.</div>
  <div class="summary-grid" aria-label="Focused comparison summary">
    <div class="card accent"><span class="n">__ADDED_LINES__</span><span class="label">lines added</span></div>
    <div class="card"><span class="n">__REMOVED_LINES__</span><span class="label">lines removed</span></div>
    <div class="card"><span class="n">__FUNCTIONS__</span><span class="label">functions inspected</span></div>
    <div class="card accent"><span class="n">__CHANGED_FUNCTIONS__</span><span class="label">functions changed</span></div>
    <div class="card"><span class="n">__CHANGED_RELATIONS__</span><span class="label">changed relations</span></div>
  </div>

  <section>
    <p class="kicker">01 · focused architecture</p>
    <h2>One entrypoint, two source surfaces</h2>
    <p class="source">The branch lanes keep the comparison direction explicit: baseline on the left, SUSYRun2 on the right.</p>
    <div class="diagram-shell">
      <svg viewBox="0 0 1440 560" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="solo-focus-title solo-focus-desc">
        <title id="solo-focus-title">solo.cpp focused branch comparison</title>
        <desc id="solo-focus-desc">Focused comparison of the solo.cpp entrypoint, its branch-specific include surface, and the resulting source delta between two CBS branches.</desc>
        <defs>
          <marker id="focus-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#4f5d75"/></marker>
          <marker id="focus-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#eb6c36"/></marker>
        </defs>
        <rect width="1440" height="560" fill="#f5f5f5"/>
        <rect class="zone" x="32" y="56" width="648" height="272" rx="8"/>
        <rect class="zone" x="760" y="56" width="648" height="272" rx="8"/>
        <rect x="52" y="68" width="220" height="16" rx="2" fill="#f5f5f5"/>
        <rect x="780" y="68" width="220" height="16" rx="2" fill="#f5f5f5"/>
        <text class="zone-label" x="56" y="80">BASELINE · COLLIDERBIT SOLO</text>
        <text class="zone-label" x="784" y="80">COMPARISON · SUSYRUN2</text>
        <path class="edge" d="M 224 188 H 272"/>
        <path class="edge" d="M 528 188 H 576"/>
        <path class="edge" d="M 952 188 H 1000"/>
        <path class="edge" d="M 1256 188 H 1304"/>
        <path class="edge delta" d="M 440 264 V 364 H 696 Q 704 364 704 372 V 412"/>
        <path class="edge delta" d="M 1160 264 V 364 H 744 Q 736 364 736 372 V 412"/>
        <g class="node stage" transform="translate(56 132)"><rect width="168" height="112" rx="6"/><text class="kind" x="12" y="20">BRANCH SNAPSHOT</text><text class="title" x="12" y="48">baseline</text><text class="body" x="12" y="68">commit __BASE_COMMIT__</text><text class="tag" x="12" y="92">__BASE_LINES__ lines</text></g>
        <g class="node mod" transform="translate(272 132)"><rect width="256" height="112" rx="6"/><text class="kind" x="12" y="20">FOCUS · MODIFIED</text><text class="title" x="12" y="48">solo.cpp</text><text class="body" x="12" y="68">__BASE_REMOVED__ removed includes</text><text class="tag" x="12" y="92">__BASE_LINES__ lines · entrypoint</text></g>
        <g class="node remove" transform="translate(576 132)"><rect width="96" height="112" rx="6"/><text class="kind" x="12" y="20">SURFACE</text><text class="title" x="12" y="48">helpers</text><text class="body" x="12" y="68">__BASE_HELPERS__</text><text class="tag" x="12" y="92">removed</text></g>
        <g class="node stage" transform="translate(784 132)"><rect width="168" height="112" rx="6"/><text class="kind" x="12" y="20">BRANCH SNAPSHOT</text><text class="title" x="12" y="48">comparison</text><text class="body" x="12" y="68">commit __COMPARE_COMMIT__</text><text class="tag" x="12" y="92">__COMPARE_LINES__ lines</text></g>
        <g class="node focal" transform="translate(1000 132)"><rect width="256" height="112" rx="6"/><text class="kind" x="12" y="20">FOCUS · MODIFIED</text><text class="title" x="12" y="48">solo.cpp</text><text class="body" x="12" y="68">__COMPARE_ADDED__ new include surface</text><text class="tag" x="12" y="92">__COMPARE_LINES__ lines · entrypoint</text></g>
        <g class="node add" transform="translate(1304 132)"><rect width="96" height="112" rx="6"/><text class="kind" x="12" y="20">SURFACE</text><text class="title" x="12" y="48">shared API</text><text class="body" x="12" y="68">__SHARED_INCLUDES__</text><text class="tag" x="12" y="92">retained</text></g>
        <g class="node focal" transform="translate(360 412)"><rect width="720" height="96" rx="8"/><text class="kind" x="24" y="28">FILE DELTA · FUNCTION-AWARE</text><text class="title" x="24" y="56" id="delta-title">__ADDED_LINES__ additions · __REMOVED_LINES__ deletions</text><text class="body" x="24" y="78" id="delta-body">__CHANGED_FUNCTIONS__ of __FUNCTIONS__ detected functions changed · __CHANGED_RELATIONS__ direct relations changed</text></g>
        <line x1="40" y1="520" x2="1400" y2="520" stroke="rgba(45,49,66,.12)" stroke-width="1"/>
        <text class="legend-label" x="40" y="544">LEGEND</text>
        <rect x="128" y="534" width="20" height="10" rx="3" fill="#fff0e8" stroke="#b55c2d"/><text class="legend-label" x="158" y="544">MODIFIED</text>
        <rect x="260" y="534" width="20" height="10" rx="3" fill="#eef8f1" stroke="#4f8a69"/><text class="legend-label" x="290" y="544">COMPARISON SURFACE</text>
        <rect x="450" y="534" width="20" height="10" rx="3" fill="#f3e9e5" stroke="#93513f" stroke-dasharray="5 4"/><text class="legend-label" x="480" y="544">BASELINE-ONLY SURFACE</text>
        <text class="legend-label" x="760" y="544">SOLID = SOURCE SURFACE</text><text class="legend-label" x="1020" y="544">DASHED = CHANGE EVIDENCE</text>
      </svg>
    </div>
    <p class="diagram-note">The diagram deliberately stops at the direct source surface. Function-level and exact line-level evidence are below, so the overview remains readable when the focused file is large.</p>
  </section>

  <section>
    <p class="kicker">02 · module slices</p>
    <h2>Direct dependency modules</h2>
    <div class="module-strip">__MODULE_ROWS__</div>
  </section>

  <div class="details-grid">
    <section>
      <p class="kicker">03 · function evidence</p>
      <h2>Function-level changes</h2>
      <div class="scroll"><table><thead><tr><th>Status</th><th>Function</th><th>Baseline</th><th>Comparison</th><th>Diff</th></tr></thead><tbody>__FUNCTION_ROWS__</tbody></table></div>
    </section>
    <section>
      <p class="kicker">04 · source surface</p>
      <h2>Include and build relations</h2>
      <div class="scroll"><table><thead><tr><th>Status</th><th>Relation</th><th>Module</th><th>Line / path</th></tr></thead><tbody>__INCLUDE_ROWS__</tbody></table></div>
    </section>
  </div>

  <section>
    <p class="kicker">05 · exact evidence</p>
    <h2>Unified diff</h2>
    <p class="source">The generated page keeps the exact file-level diff next to the summarized diagram. Added lines belong to the comparison branch; removed lines belong to the baseline branch.</p>
    <details open><summary>__DIFF_SUMMARY__</summary><pre>__DIFF__</pre></details>
  </section>

  <footer>Generated by <code>scripts/compare-cbs-focus.py</code>. Baseline commit: <code>__BASE_COMMIT_FULL__</code>; comparison commit: <code>__COMPARE_COMMIT_FULL__</code>.</footer>
</main>
</body>
</html>'''
    replacements = {
        "__TITLE__": html.escape(title),
        "__FOCUS_FILE__": html.escape(focus["file"]),
        "__BASELINE__": html.escape(f"{baseline['label']} · {baseline['short']}"),
        "__COMPARISON__": html.escape(f"{comparison['label']} · {comparison['short']}"),
        "__MODULE__": html.escape(focus["module"]),
        "__SCOPE_NOTE__": html.escape(data["scope_note"]),
        "__BASE_COMMIT__": html.escape(baseline["short"]),
        "__COMPARE_COMMIT__": html.escape(comparison["short"]),
        "__BASE_COMMIT_FULL__": html.escape(baseline["commit"]),
        "__COMPARE_COMMIT_FULL__": html.escape(comparison["commit"]),
        "__BASE_LINES__": str(focus["baseline"]["lines"]),
        "__COMPARE_LINES__": str(focus["comparison"]["lines"]),
        "__BASE_REMOVED__": str(baseline_removed_helpers),
        "__BASE_HELPERS__": str(baseline_removed_helpers),
        "__COMPARE_ADDED__": str(comparison_added_helpers),
        "__SHARED_INCLUDES__": str(shared_includes),
        "__ADDED_LINES__": str(focus["added_lines"]),
        "__REMOVED_LINES__": str(focus["removed_lines"]),
        "__FUNCTIONS__": str(summary["functions"]),
        "__CHANGED_FUNCTIONS__": str(summary["changed_functions"]),
        "__CHANGED_RELATIONS__": str(summary["changed_relations"]),
        "__MODULE_ROWS__": module_rows,
        "__FUNCTION_ROWS__": function_rows,
        "__INCLUDE_ROWS__": include_rows,
        "__DIFF_SUMMARY__": html.escape(diff_summary),
        "__DIFF__": html.escape(display_diff(data["diff"])),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def markdown_summary(data: dict[str, Any]) -> str:
    focus = data["focus"]
    baseline = data["baseline"]
    comparison = data["comparison"]
    lines = [
        "# Focused CBS source comparison",
        "",
        f"File: `{focus['file']}`",
        f"Baseline: `{baseline['label']}` (`{baseline['short']}`)",
        f"Comparison: `{comparison['label']}` (`{comparison['short']}`)",
        "",
        f"- Lines: +{focus['added_lines']} / -{focus['removed_lines']} ({focus['hunks']} hunks)",
        f"- Functions: {data['summary']['changed_functions']} changed of {data['summary']['functions']}",
        f"- Changed includes: {data['summary']['changed_includes']}",
        f"- Changed source relations: {data['summary']['changed_relations']}",
        f"- Changed build relations: {data['summary']['changed_build_relations']}",
        "",
        data["scope_note"],
        "",
        "## Functions",
        "",
        "| Status | Function | Baseline | Comparison | Diff |",
        "|---|---|---:|---:|---:|",
    ]
    for function in data["functions"]:
        lines.append(
            f"| {function['status']} | `{function['name']}` | {function.get('baseline_line') or '—'}–{function.get('baseline_line_end') or '—'} | {function.get('comparison_line') or '—'}–{function.get('comparison_line_end') or '—'} | +{function['added_lines']} / -{function['removed_lines']} |"
        )
    return "\n".join(lines) + "\n"


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="baseline CBS worktree")
    parser.add_argument("--comparison", type=Path, required=True, help="comparison CBS worktree")
    parser.add_argument("--focus-file", default="ColliderBit/examples/solo.cpp", help="file path relative to both worktrees")
    parser.add_argument("--baseline-label", default="ColliderBit_solo_development")
    parser.add_argument("--comparison-label", default="SUSYRun2")
    parser.add_argument("--output-json", type=Path, default=Path("dependences/cbs-solo-comparison.json"))
    parser.add_argument("--output-html", type=Path, default=Path("dependences/cbs-solo-comparison.html"))
    parser.add_argument("--site-html", type=Path, default=Path("site/cbs-solo-comparison.html"))
    parser.add_argument("--summary-md", type=Path, default=Path("dependences/CBS_SOLO_COMPARISON.md"))
    args = parser.parse_args()
    data = build_data(args)
    page = page_html(data)
    write_text(args.output_json.resolve(), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    write_text(args.output_html.resolve(), page)
    write_text(args.site_html.resolve(), page)
    write_text(args.summary_md.resolve(), markdown_summary(data))
    print(json.dumps({"focus": data["focus"]["file"], **data["summary"]}, ensure_ascii=False, sort_keys=True))
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_html}")
    print(f"Wrote {args.site_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
