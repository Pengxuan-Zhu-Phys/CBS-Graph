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


def logic_flow_definitions() -> dict[str, Any]:
    """Return the deliberately grouped execution paths for solo.cpp.

    These are source-grounded editorial groups, not a runtime trace.  The
    groups keep the diagram readable while naming the concrete functions and
    helper modules that own each stage.
    """
    return {
        "baseline": {
            "title": "Before · helper-oriented execution flow",
            "description": "The baseline entrypoint delegates parsing, multi-file execution, merging, sampling advice, and output to dedicated Solo* helpers.",
            "nodes": [
                {
                    "id": "start",
                    "shape": "oval",
                    "class": "focal",
                    "kind": "ENTRYPOINT",
                    "title": "main(argc, argv)",
                    "body": ["ColliderBit Solo", "try { … }"],
                    "tag": "solo.cpp",
                },
                {
                    "id": "cli",
                    "shape": "rect",
                    "class": "wrapper",
                    "kind": "CLI WRAPPER",
                    "title": "SoloCLI::parse_command_line",
                    "body": ["--help / malformed args", "→ status::help|error|run"],
                    "tag": "solo_cli.hpp/.cpp",
                },
                {
                    "id": "input",
                    "shape": "rect",
                    "class": "wrapper",
                    "kind": "INPUT WRAPPER",
                    "title": "SoloInput::parse_and_prepare_input",
                    "body": ["YAML + analyses + settings", "event_file OR processes + xsec"],
                    "tag": "solo_input.hpp/.cpp",
                },
                {
                    "id": "config",
                    "shape": "rect",
                    "class": "stage",
                    "kind": "CONFIGURE IN MAIN",
                    "title": "backend + runtime options",
                    "body": ["FullLikes selector, cutflow/histogram", "Rivet/Contur + OutputConfig"],
                    "tag": "main + apply_setting_if_present",
                },
                {
                    "id": "mode",
                    "shape": "diamond",
                    "class": "decision",
                    "kind": "MODE DECISION",
                    "title": "settings.processes?",
                    "body": ["multi-file batch", "or one-pass event_file"],
                    "tag": "main",
                },
                {
                    "id": "batch",
                    "shape": "rect",
                    "class": "wrapper",
                    "kind": "BATCH WRAPPER",
                    "title": "SoloBatch::run_and_merge",
                    "body": ["per-file CBS subprocesses", "weighted SR/cutflow/hist merge"],
                    "tag": "solo_batch.cpp",
                },
                {
                    "id": "runtime",
                    "shape": "rect",
                    "class": "stage",
                    "kind": "RUNTIME WIRING",
                    "title": "event loop + dependencies",
                    "body": ["getEvent / convertEvent / xsec", "resolve functors + backends"],
                    "tag": "main · operateLHCLoop",
                },
                {
                    "id": "output",
                    "shape": "oval",
                    "class": "focal",
                    "kind": "STRUCTURED OUTPUT",
                    "title": "SoloOutput::emit_outputs",
                    "body": ["analyses + loglikes + Contur", "screen / JSON · catch → 1"],
                    "tag": "solo_output.hpp/.cpp",
                },
            ],
            "edges": [
                {"from": "start", "to": "cli"},
                {"from": "cli", "to": "input"},
                {"from": "input", "to": "config"},
                {"from": "config", "to": "mode"},
                {
                    "from": "mode",
                    "to": "batch",
                    "points": [[760, 580], [980, 580], [980, 700]],
                    "label": "YES · processes",
                    "label_x": 822,
                    "label_y": 567,
                },
                {
                    "from": "mode",
                    "to": "runtime",
                    "points": [[620, 645], [620, 660], [260, 660], [260, 700]],
                    "label": "NO · event_file",
                    "label_x": 430,
                    "label_y": 648,
                },
                {
                    "from": "batch",
                    "to": "output",
                    "points": [[980, 810], [980, 820], [760, 820], [760, 824]],
                },
                {
                    "from": "runtime",
                    "to": "output",
                    "points": [[260, 810], [260, 820], [480, 820], [480, 824]],
                },
            ],
        },
        "comparison": {
            "title": "After · main-owned execution flow",
            "description": "SUSYRun2 keeps the complete single-file path in solo.cpp::main, with no SoloCLI/SoloInput/SoloBatch/SoloOutput helper boundary.",
            "nodes": [
                {
                    "id": "start",
                    "shape": "oval",
                    "class": "focal",
                    "kind": "ENTRYPOINT",
                    "title": "main(argc, argv)",
                    "body": ["ColliderBit Solo", "try { … }"],
                    "tag": "solo.cpp",
                },
                {
                    "id": "argc",
                    "shape": "diamond",
                    "class": "decision",
                    "kind": "ARGUMENT GATE",
                    "title": "argc < 2?",
                    "body": ["usage + return 1", "otherwise argv[1]"],
                    "tag": "inline in main",
                },
                {
                    "id": "stop",
                    "shape": "oval",
                    "class": "stop",
                    "kind": "EARLY EXIT",
                    "title": "usage error",
                    "body": ["cerr << Usage", "return 1"],
                    "tag": "no helper boundary",
                },
                {
                    "id": "backend",
                    "shape": "rect",
                    "class": "stage",
                    "kind": "BACKEND GATES",
                    "title": "backendInfo().works",
                    "body": ["nulike + FullLikes required", "Rivet/Contur availability flags"],
                    "tag": "inline in main",
                },
                {
                    "id": "input",
                    "shape": "rect",
                    "class": "mod",
                    "kind": "INPUT IN MAIN",
                    "title": "YAML::LoadFile",
                    "body": ["analyses + Options(settings)", "event_file + extension check"],
                    "tag": "no SoloInput wrapper",
                },
                {
                    "id": "config",
                    "shape": "rect",
                    "class": "mod",
                    "kind": "CONFIG IN MAIN",
                    "title": "settings + Rivet/Contur",
                    "body": ["jet collections + cross section", "calc_LHC_LogLikes_full options"],
                    "tag": "single-file mode",
                },
                {
                    "id": "runtime",
                    "shape": "rect",
                    "class": "mod",
                    "kind": "RUNTIME WIRING IN MAIN",
                    "title": "resolve + nested functions",
                    "body": ["operateLHCLoop + event conversion", "ATLAS/CMS/Identity + FullLikes"],
                    "tag": "inline dependency graph",
                },
                {
                    "id": "run",
                    "shape": "rect",
                    "class": "mod",
                    "kind": "EXECUTE IN MAIN",
                    "title": "reset_and_calculate()",
                    "body": ["loop → CollectAnalyses", "full loglikes + optional Contur"],
                    "tag": "one pass over event_file",
                },
                {
                    "id": "output",
                    "shape": "oval",
                    "class": "focal",
                    "kind": "INLINE OUTPUT",
                    "title": "summary_line + cout",
                    "body": ["loop analyses → SR details", "total loglike · catch → 1"],
                    "tag": "no SoloOutput wrapper",
                },
            ],
            "edges": [
                {"from": "start", "to": "argc"},
                {
                    "from": "argc",
                    "to": "stop",
                    "points": [[470, 170], [360, 170], [360, 114], [230, 114]],
                    "label": "YES",
                    "label_x": 392,
                    "label_y": 156,
                },
                {
                    "from": "argc",
                    "to": "backend",
                    "points": [[620, 230], [620, 270]],
                    "label": "NO",
                    "label_x": 636,
                    "label_y": 252,
                },
                {"from": "backend", "to": "input"},
                {"from": "input", "to": "config"},
                {"from": "config", "to": "runtime"},
                {"from": "runtime", "to": "run"},
                {"from": "run", "to": "output"},
            ],
        },
    }


def logic_mapping_rows() -> list[dict[str, str]]:
    return [
        {
            "concern": "CLI / help / argument errors",
            "baseline": "SoloCLI::parse_command_line · solo_cli.cpp",
            "comparison": "main: argc check + argv[1]",
            "change": "helper boundary removed",
        },
        {
            "concern": "YAML, analyses, settings, event inputs",
            "baseline": "SoloInput::parse_and_prepare_input · solo_input.cpp",
            "comparison": "main: YAML::LoadFile + Options(settings)",
            "change": "input normalization moved inline",
        },
        {
            "concern": "multi-process / multi-file execution",
            "baseline": "SoloBatch::run_and_merge + build_sampling_advice",
            "comparison": "no batch branch; one settings.event_file",
            "change": "batch abstraction removed",
        },
        {
            "concern": "likelihood implementation choice",
            "baseline": "use_FullLikes selects calc_LHC_LogLikes(_full)",
            "comparison": "calc_LHC_LogLikes_full is hard-wired",
            "change": "runtime selector simplified",
        },
        {
            "concern": "cutflow / histogram policy",
            "baseline": "Cutflow::set_check_cutflow + Histogram1D::set_check_histogram",
            "comparison": "CollectAnalyses.setOption(print_cutflows, true)",
            "change": "runtime switches simplified",
        },
        {
            "concern": "output contract",
            "baseline": "OutputConfig + validate_output_config + emit_outputs",
            "comparison": "summary_line + cout in main",
            "change": "structured screen/JSON output removed",
        },
        {
            "concern": "Rivet / Contur wiring",
            "baseline": "main configures and output helper emits maps",
            "comparison": "main configures and prints pool details inline",
            "change": "ownership remains inline; output path changed",
        },
    ]


def _flow_path(points: list[list[int]]) -> str:
    if len(points) < 2:
        return ""
    if len(points) == 2:
        return f"M {points[0][0]} {points[0][1]} L {points[1][0]} {points[1][1]}"
    path = f"M {points[0][0]} {points[0][1]}"
    radius = 8
    for index in range(1, len(points) - 1):
        previous = points[index - 1]
        current = points[index]
        following = points[index + 1]
        dx_prev = current[0] - previous[0]
        dy_prev = current[1] - previous[1]
        dx_next = following[0] - current[0]
        dy_next = following[1] - current[1]
        prev_len = max(abs(dx_prev) + abs(dy_prev), 1)
        next_len = max(abs(dx_next) + abs(dy_next), 1)
        trim_prev = min(radius, prev_len // 2)
        trim_next = min(radius, next_len // 2)
        before = (current[0] - (dx_prev * trim_prev // prev_len), current[1] - (dy_prev * trim_prev // prev_len))
        after = (current[0] + (dx_next * trim_next // next_len), current[1] + (dy_next * trim_next // next_len))
        path += f" L {before[0]} {before[1]} Q {current[0]} {current[1]} {after[0]} {after[1]}"
    path += f" L {points[-1][0]} {points[-1][1]}"
    return path


def _flow_node_geometry(flow_id: str) -> dict[str, dict[str, int]]:
    if flow_id == "baseline":
        return {
            "start": {"x": 490, "y": 24, "w": 260, "h": 72},
            "cli": {"x": 470, "y": 132, "w": 300, "h": 104},
            "input": {"x": 430, "y": 264, "w": 380, "h": 104},
            "config": {"x": 400, "y": 396, "w": 440, "h": 108},
            "mode": {"cx": 620, "cy": 580, "w": 280, "h": 130},
            "batch": {"x": 800, "y": 700, "w": 360, "h": 110},
            "runtime": {"x": 80, "y": 700, "w": 360, "h": 110},
            "output": {"x": 400, "y": 824, "w": 440, "h": 72},
        }
    return {
        "start": {"x": 490, "y": 24, "w": 260, "h": 72},
        "argc": {"cx": 620, "cy": 170, "w": 300, "h": 120},
        "stop": {"x": 120, "y": 114, "w": 220, "h": 72},
        "backend": {"x": 420, "y": 270, "w": 400, "h": 104},
        "input": {"x": 420, "y": 398, "w": 400, "h": 104},
        "config": {"x": 420, "y": 534, "w": 400, "h": 104},
        "runtime": {"x": 420, "y": 670, "w": 400, "h": 104},
        "run": {"x": 420, "y": 806, "w": 400, "h": 104},
        "output": {"x": 420, "y": 942, "w": 400, "h": 88},
    }


def _flow_anchor(flow_id: str, node_id: str, side: str) -> tuple[int, int]:
    geo = _flow_node_geometry(flow_id)[node_id]
    if "cx" in geo:
        half_w = geo["w"] // 2
        half_h = geo["h"] // 2
        return {
            "top": (geo["cx"], geo["cy"] - half_h),
            "right": (geo["cx"] + half_w, geo["cy"]),
            "bottom": (geo["cx"], geo["cy"] + half_h),
            "left": (geo["cx"] - half_w, geo["cy"]),
        }[side]
    x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
    return {
        "top": (x + w // 2, y),
        "right": (x + w, y + h // 2),
        "bottom": (x + w // 2, y + h),
        "left": (x, y + h // 2),
    }[side]


def flowchart_svg(flow_id: str, definition: dict[str, Any]) -> str:
    geometry = _flow_node_geometry(flow_id)
    marker_id = f"solo-{flow_id}-flow-arrow"
    width, height = (1240, 980) if flow_id == "baseline" else (1240, 1120)
    title_id = f"solo-{flow_id}-flow-title"
    desc_id = f"solo-{flow_id}-flow-desc"
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{title_id} {desc_id}">',
        f'<title id="{title_id}">{html.escape(definition["title"])}</title>',
        f'<desc id="{desc_id}">{html.escape(definition["description"])}</desc>',
        "<defs>",
        f'<marker id="{marker_id}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#4f5d75"/></marker>',
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="#f5f5f5"/>',
        f'<rect class="zone" x="32" y="12" width="1176" height="{height - 70}" rx="10"/>',
        '<text class="zone-label" x="56" y="40">SOURCE-OWNED EXECUTION PATH · GROUPED BY RESPONSIBILITY</text>',
    ]

    for edge in definition["edges"]:
        points = edge.get("points")
        if points is None:
            source = edge["from"]
            target = edge["to"]
            if flow_id == "baseline":
                source_side, target_side = ("bottom", "top")
                if source == "mode" and target == "batch":
                    source_side, target_side = ("right", "top")
                elif source == "mode" and target == "runtime":
                    source_side, target_side = ("bottom", "top")
                elif source in {"batch", "runtime"} and target == "output":
                    source_side, target_side = ("bottom", "top")
                points = [_flow_anchor(flow_id, source, source_side), _flow_anchor(flow_id, target, target_side)]
            else:
                points = [_flow_anchor(flow_id, source, "bottom"), _flow_anchor(flow_id, target, "top")]
        else:
            source = edge["from"]
            target = edge["to"]
            if source == "argc" and target == "backend":
                points = [_flow_anchor(flow_id, source, "bottom"), _flow_anchor(flow_id, target, "top")]
        path = _flow_path(points)
        parts.append(f'<path class="flow-edge" d="{path}" style="marker-end:url(#{marker_id})"/>')
        if edge.get("label"):
            label_x = edge.get("label_x", 0)
            label_y = edge.get("label_y", 0)
            parts.append(f'<text class="edge-label" x="{label_x}" y="{label_y}">{html.escape(edge["label"])}</text>')

    for node in definition["nodes"]:
        node_id = node["id"]
        geo = geometry[node_id]
        node_class = f'node {node.get("class", "stage")}'
        if node["shape"] == "oval":
            x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
            cx, cy = x + w // 2, y + h // 2
            parts.append(f'<g class="{node_class}"><ellipse cx="{cx}" cy="{cy}" rx="{w // 2}" ry="{h // 2}"/><text class="kind" x="{cx}" y="{cy - 18}" text-anchor="middle">{html.escape(node["kind"])}</text><text class="title" x="{cx}" y="{cy + 4}" text-anchor="middle">{html.escape(node["title"])}</text><text class="body" x="{cx}" y="{cy + 20}" text-anchor="middle">{html.escape(node["body"][0])}</text><text class="tag" x="{cx}" y="{cy + 34}" text-anchor="middle">{html.escape(node["body"][1])}</text></g>')
            continue
        if "cx" in geo:
            cx, cy = geo["cx"], geo["cy"]
            if node["shape"] == "diamond":
                points = f"{cx},{cy - geo['h']//2} {cx + geo['w']//2},{cy} {cx},{cy + geo['h']//2} {cx - geo['w']//2},{cy}"
                parts.append(f'<g class="{node_class}"><polygon points="{points}"/><text class="kind" x="{cx}" y="{cy - 24}" text-anchor="middle">{html.escape(node["kind"])}</text><text class="title" x="{cx}" y="{cy + 2}" text-anchor="middle">{html.escape(node["title"])}</text><text class="body" x="{cx}" y="{cy + 22}" text-anchor="middle">{html.escape(node["body"][0])}</text><text class="body" x="{cx}" y="{cy + 36}" text-anchor="middle">{html.escape(node["body"][1])}</text><text class="tag" x="{cx}" y="{cy + 52}" text-anchor="middle">{html.escape(node["tag"])}</text></g>')
            else:
                rx = geo["w"] // 2
                ry = geo["h"] // 2
                parts.append(f'<g class="{node_class}"><ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"/><text class="kind" x="{cx}" y="{cy - 18}" text-anchor="middle">{html.escape(node["kind"])}</text><text class="title" x="{cx}" y="{cy + 5}" text-anchor="middle">{html.escape(node["title"])}</text><text class="body" x="{cx}" y="{cy + 23}" text-anchor="middle">{html.escape(node["body"][0])}</text><text class="tag" x="{cx}" y="{cy + 38}" text-anchor="middle">{html.escape(node["tag"])}</text></g>')
            continue
        x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
        parts.append(f'<g class="{node_class}" transform="translate({x} {y})"><rect width="{w}" height="{h}" rx="6"/><text class="kind" x="16" y="22">{html.escape(node["kind"])}</text><text class="title" x="16" y="50">{html.escape(node["title"])}</text><text class="body" x="16" y="70">{html.escape(node["body"][0])}</text><text class="body" x="16" y="84">{html.escape(node["body"][1])}</text><text class="tag" x="16" y="{h - 12}">{html.escape(node["tag"])}</text></g>')

    legend_y = height - 32
    parts.extend([
        f'<line x1="48" y1="{legend_y - 18}" x2="1192" y2="{legend_y - 18}" stroke="rgba(45,49,66,.12)" stroke-width="1"/>',
        f'<text class="legend-label" x="48" y="{legend_y}">LEGEND</text>',
        f'<rect x="112" y="{legend_y - 10}" width="20" height="10" rx="3" fill="#fff0e8" stroke="#b55c2d"/><text class="legend-label" x="142" y="{legend_y}">INLINE / MODIFIED OWNERSHIP</text>',
        f'<rect x="326" y="{legend_y - 10}" width="20" height="10" rx="3" fill="#fff" stroke="#7a8399"/><text class="legend-label" x="356" y="{legend_y}">EXTRACTED WRAPPER</text>',
        f'<polygon points="536,{legend_y-10} 546,{legend_y-5} 536,{legend_y} 526,{legend_y-5}" fill="rgba(79,93,117,.08)" stroke="#7a8399"/><text class="legend-label" x="556" y="{legend_y}">DECISION</text>',
        f'<text class="legend-label" x="680" y="{legend_y}">ARROWS = CONTROL FLOW · LABELS = BRANCH CONDITION</text>',
        "</svg>",
    ])
    return "".join(parts)


def detailed_logic_data() -> dict[str, Any]:
    """Source-grounded detail tables and diagrams for the SUSYRun2 main path."""
    settings_rows = [
        {"name": "analyses", "type": "vector<str>", "default": "required", "consumer": "infile → CBS YAML / CollectAnalyses", "source": "solo.cpp:86–90"},
        {"name": "settings", "type": "YAML map → Options", "default": "required", "consumer": "all runtime settings", "source": "solo.cpp:91–96"},
        {"name": "debug", "type": "bool", "default": "false", "consumer": "logger; HepMC notice; silenceLoop", "source": "solo.cpp:118"},
        {"name": "use_lognormal_distribution_for_1d_systematic", "type": "bool", "default": "false", "consumer": "lnpiln vs lnpin backend requirement", "source": "solo.cpp:121,285"},
        {"name": "jet_pt_min", "type": "double", "default": "10.0", "consumer": "convertHepMCEvent_HEPUtils", "source": "solo.cpp:122,217"},
        {"name": "event_file", "type": "str", "default": "required", "consumer": "getHepMCEvent; .hepmc/.hepmc2/.hepmc3 check", "source": "solo.cpp:123–128,216"},
        {"name": "jet_collections", "type": "YAML::Node", "default": "required", "consumer": "getEvent + convertEvent", "source": "solo.cpp:131,220–223"},
        {"name": "jet_collection_taus", "type": "string", "default": "antikt_R04", "consumer": "getEvent + convertEvent", "source": "solo.cpp:132,220–223"},
        {"name": "cross_section_pb OR cross_section_fb", "type": "double", "default": "one branch required", "consumer": "getYAMLCrossSection", "source": "solo.cpp:226–236"},
        {"name": "cross_section_fractional_uncert", "type": "double", "default": "optional alternative", "consumer": "otherwise absolute _uncert_pb/_fb is required", "source": "solo.cpp:229–236"},
        {"name": "rivet-settings", "type": "YAML map", "default": "absent → withRivet=false", "consumer": "Rivet_measurements", "source": "solo.cpp:141–145,267–272"},
        {"name": "rivet-settings.drop_YODA_file", "type": "bool", "default": "true", "consumer": "Rivet_measurements", "source": "solo.cpp:267"},
        {"name": "rivet-settings.analyses", "type": "vector<string>", "default": "required when Rivet is enabled", "consumer": "Rivet_measurements", "source": "solo.cpp:269–270"},
        {"name": "rivet-settings.exclude_analyses", "type": "vector<string>", "default": "empty", "consumer": "Rivet_measurements", "source": "solo.cpp:271–272"},
        {"name": "contur-settings", "type": "vector<string>", "default": "absent → withContur=false", "consumer": "Contur_LHC_measurements_from_stream", "source": "solo.cpp:147–154,273–274"},
        {"name": "Rivet / Contur pairing", "type": "presence gate", "default": "both absent or both present", "consumer": "mismatch throws; missing backend throws", "source": "solo.cpp:156–178"},
        {"name": "use_covariances", "type": "bool", "default": "not set in main; comment says true", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:242"},
        {"name": "use_marginalising", "type": "bool", "default": "not set in main; comment says false", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:243"},
        {"name": "combine_SRs_without_covariances", "type": "bool", "default": "not set in main; comment says false", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:244"},
        {"name": "nuisance_prof_initstep", "type": "double", "default": "0.1 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:246"},
        {"name": "nuisance_prof_convtol", "type": "double", "default": "0.01 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:247"},
        {"name": "nuisance_prof_maxsteps", "type": "int", "default": "10000 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:248"},
        {"name": "nuisance_prof_convacc", "type": "double", "default": "0.01 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:249"},
        {"name": "nuisance_prof_simplexsize", "type": "double", "default": "1e-5 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:250"},
        {"name": "nuisance_prof_method", "type": "int", "default": "6 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:251"},
        {"name": "nuisance_marg_convthres_abs", "type": "double", "default": "0.05 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:253"},
        {"name": "nuisance_marg_convthres_rel", "type": "double", "default": "0.05 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:254"},
        {"name": "nuisance_marg_nsamples_start", "type": "long", "default": "1000000 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:255"},
        {"name": "nuisance_marg_nulike1sr", "type": "bool", "default": "true (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:256"},
        {"name": "calc_noerr_loglikes", "type": "bool", "default": "false (comment)", "consumer": "alternate SR loglikes + summary_line", "source": "solo.cpp:258"},
        {"name": "calc_expected_loglikes", "type": "bool", "default": "false (comment)", "consumer": "alternate SR loglikes + summary_line", "source": "solo.cpp:259"},
        {"name": "calc_expected_noerr_loglikes", "type": "bool", "default": "false (comment)", "consumer": "alternate SR loglikes + summary_line", "source": "solo.cpp:260"},
        {"name": "calc_scaledsignal_loglikes", "type": "bool", "default": "false (comment)", "consumer": "alternate SR loglikes + summary_line", "source": "solo.cpp:261"},
        {"name": "signal_scalefactor", "type": "double", "default": "1.0 (comment)", "consumer": "calc_LHC_LogLikes_full", "source": "solo.cpp:262"},
    ]
    hardcoded_rows = [
        {"name": "CollectAnalyses.print_cutflows", "value": "true", "consumer": "CollectAnalyses", "source": "solo.cpp:190–191"},
        {"name": "CBS.min_nEvents", "value": "1000", "consumer": "operateLHCLoop", "source": "solo.cpp:208–213"},
        {"name": "CBS.max_nEvents", "value": "1000000000", "consumer": "operateLHCLoop", "source": "solo.cpp:208–213"},
        {"name": "operateLHCLoop.silenceLoop", "value": "!debug", "consumer": "operateLHCLoop", "source": "solo.cpp:212–213"},
        {"name": "Rivet_measurements.runningStandalone", "value": "true", "consumer": "Rivet_measurements", "source": "solo.cpp:267–268"},
    ]
    runtime_rows = [
        {"step": "operateLHCLoop.reset_and_calculate()", "container": "MCLoopInfo", "value": "event loop state; event_count[\"CBS\"]", "downstream": "n_events + nested event/analysis functors", "source": "solo.cpp:372,385"},
        {"step": "CollectAnalyses.reset_and_calculate()", "container": "AnalysisDataPointers", "value": "vector<AnalysisData*>; ATLAS + CMS + Identity", "downstream": "AllAnalysisNumbers dependency", "source": "solo.cpp:373; ColliderBit_eventloop.cpp:336"},
        {"step": "calc_LHC_LogLikes_full.reset_and_calculate()", "container": "map_str_AnalysisLogLikes", "value": "AnalysisLogLikes per analysis / SR", "downstream": "FullLikes backend + nulike marginaliser", "source": "solo.cpp:374; LHC_likelihoods.cpp:1335"},
        {"step": "get_LHC_LogLike_per_analysis.reset_and_calculate()", "container": "map_str_dbl", "value": "analysis → combination_loglike; alt keys appended", "downstream": "debug log + standalone functor output", "source": "solo.cpp:375; LHC_likelihoods.cpp:1386"},
        {"step": "calc_combined_LHC_LogLike.reset_and_calculate()", "container": "double", "value": "combined ATLAS+CMS log-likelihood", "downstream": "final loglike variable + stdout", "source": "solo.cpp:376; LHC_likelihoods.cpp:1503"},
        {"step": "Contur_LHC_measurements_LogLike.reset_and_calculate()", "container": "double", "value": "total Contur LLR", "downstream": "summary_line when withContur", "source": "solo.cpp:379,414; ColliderBit_measurements.cpp:454"},
        {"step": "Contur_LHC_measurements_LogLike_perPool.reset_and_calculate()", "container": "map_str_dbl", "value": "pool → LLR", "downstream": "pool loop in summary_line", "source": "solo.cpp:380,415; ColliderBit_measurements.cpp:495"},
        {"step": "Contur_LHC_measurements_histotags_perPool.reset_and_calculate()", "container": "map_str_str", "value": "pool → dominant measurement tag", "downstream": "pool_info[pool.first] in summary_line", "source": "solo.cpp:381,416; ColliderBit_measurements.cpp:533"},
        {"step": "inline summary aggregation", "container": "stringstream summary_line", "value": "analysis → SR → observed/background/signal/loglike", "downstream": "cout + total combined loglike", "source": "solo.cpp:384–431"},
    ]
    dependency_rows = [
        {"owner": "calc_combined_LHC_LogLike", "links": "calc_LHC_LogLikes_full; operateLHCLoop", "backend": "—", "source": "solo.cpp:280–281"},
        {"owner": "get_LHC_LogLike_per_analysis", "links": "calc_LHC_LogLikes_full", "backend": "—", "source": "solo.cpp:282"},
        {"owner": "calc_LHC_LogLikes_full", "links": "CollectAnalyses; operateLHCLoop", "backend": "nulike_lnpiln/lnpin; FullLikes_FileExists/ReadIn/Evaluate", "source": "solo.cpp:283–288"},
        {"owner": "CollectAnalyses", "links": "runATLASAnalyses; runCMSAnalyses; runIdentityAnalyses", "backend": "—", "source": "solo.cpp:289–291"},
        {"owner": "runATLASAnalyses", "links": "getATLASAnalysisContainer; smearEventATLAS", "backend": "—", "source": "solo.cpp:292–293"},
        {"owner": "runCMSAnalyses", "links": "getCMSAnalysisContainer; smearEventCMS", "backend": "—", "source": "solo.cpp:294–295"},
        {"owner": "runIdentityAnalyses", "links": "getIdentityAnalysisContainer; copyEvent", "backend": "—", "source": "solo.cpp:296–297"},
        {"owner": "analysis containers", "links": "getYAMLCrossSection; convertEvent; BuckFast/smear/copy", "backend": "ATLAS/CMS/Identity detector paths", "source": "solo.cpp:298–306"},
        {"owner": "Contur branch", "links": "Rivet_measurements → Contur_LHC_measurements_from_stream → three Contur outputs", "backend": "Contur_get_analyses_from_beam; Contur_LogLike_from_stream", "source": "solo.cpp:308–317"},
    ]
    settings_diagram = {
        "title": "SUSYRun2 YAML settings and defaults",
        "description": "Detailed SUSYRun2 path from YAML sections to validated settings, defaults, backend options, and configured functors.",
        "width": 1240,
        "height": 1220,
        "nodes": [
            {"id": "yaml", "shape": "oval", "class": "detail-focal", "x": 480, "y": 40, "w": 280, "h": 88, "kind": "YAML INPUT", "title": "YAML::LoadFile", "body": ["analyses + settings", "top-level sections"], "tag": "solo.cpp:86–96"},
            {"id": "required", "shape": "rect", "class": "detail-primary", "x": 400, "y": 168, "w": 440, "h": 104, "kind": "REQUIRED CONTRACT", "title": "event + analyses inputs", "body": ["event_file · jet_collections", "analyses · cross section"], "tag": "missing / bad suffix → throw"},
            {"id": "defaults", "shape": "rect", "class": "detail-primary", "x": 400, "y": 312, "w": 440, "h": 104, "kind": "SCALAR DEFAULTS", "title": "settings.getValueOrDef", "body": ["debug=false · use_lnpiln=false", "jet_pt_min=10 · taus=antikt_R04"], "tag": "seed=-1 → hardware seed"},
            {"id": "xsec", "shape": "rect", "class": "detail-primary", "x": 400, "y": 456, "w": 440, "h": 104, "kind": "CROSS SECTION", "title": "pb/fb branch + uncertainty", "body": ["cross_section_pb OR cross_section_fb", "fractional OR absolute uncertainty"], "tag": "getYAMLCrossSection"},
            {"id": "likes", "shape": "rect", "class": "detail-mod", "x": 400, "y": 600, "w": 440, "h": 104, "kind": "LIKELIHOOD OPTIONS", "title": "apply_setting_if_present", "body": ["18 optional likelihood switches", "only forwarded when hasKey"], "tag": "comments record backend defaults"},
            {"id": "rivet", "shape": "rect", "class": "detail-optional", "x": 400, "y": 744, "w": 440, "h": 104, "kind": "OPTIONAL MEASUREMENTS", "title": "Rivet + Contur settings", "body": ["both absent or both present", "YODA / analyses / pool options"], "tag": "withRivet / withContur"},
            {"id": "loop", "shape": "rect", "class": "detail-hardcoded", "x": 400, "y": 888, "w": 440, "h": 104, "kind": "HARDCODED MAIN OPTIONS", "title": "CBS loop policy", "body": ["print_cutflows=true · min=1000", "max=1e9 · silenceLoop=!debug"], "tag": "not loaded from YAML"},
            {"id": "functors", "shape": "oval", "class": "detail-focal", "x": 400, "y": 1032, "w": 440, "h": 88, "kind": "CONFIGURED FUNCTORS", "title": "getEvent + convertEvent + analyses", "body": ["setOption calls complete", "ready for dependency resolution"], "tag": "main continues"},
        ],
        "edges": [{"from": "yaml", "to": "required"}, {"from": "required", "to": "defaults"}, {"from": "defaults", "to": "xsec"}, {"from": "xsec", "to": "likes"}, {"from": "likes", "to": "rivet"}, {"from": "rivet", "to": "loop"}, {"from": "loop", "to": "functors"}],
    }
    runtime_diagram = {
        "title": "SUSYRun2 reset and calculate container chain",
        "description": "Detailed SUSYRun2 dependency and reset_and_calculate order showing the containers consumed by the standalone summary.",
        "width": 1240,
        "height": 1260,
        "nodes": [
            {"id": "resolve", "shape": "rect", "class": "detail-primary", "x": 400, "y": 32, "w": 440, "h": 108, "kind": "DEPENDENCY + LOOP WIRING", "title": "resolveDependency + setNestedList", "body": ["likelihood ← analyses ← detector paths", "loop managers + FullLikes/nulike pointers"], "tag": "solo.cpp:278–361"},
            {"id": "init", "shape": "rect", "class": "detail-hardcoded", "x": 400, "y": 176, "w": 440, "h": 108, "kind": "BACKEND INIT", "title": "nulike_init.reset_and_calculate", "body": ["always initialise nulike", "Rivet + Contur init when enabled"], "tag": "solo.cpp:363–369"},
            {"id": "loop", "shape": "rect", "class": "detail-focal", "x": 400, "y": 320, "w": 440, "h": 108, "kind": "EVENT LOOP", "title": "operateLHCLoop.reset_and_calculate", "body": ["MCLoopInfo; event_count[\"CBS\"]", "nested event + detector + analyses"], "tag": "solo.cpp:372,385"},
            {"id": "analyses", "shape": "rect", "class": "detail-data", "x": 400, "y": 464, "w": 440, "h": 108, "kind": "ANALYSIS CONTAINER", "title": "CollectAnalyses.reset_and_calculate", "body": ["AnalysisDataPointers", "ATLAS + CMS + Identity"], "tag": "solo.cpp:373"},
            {"id": "likes", "shape": "rect", "class": "detail-data", "x": 400, "y": 608, "w": 440, "h": 108, "kind": "LIKELIHOOD CONTAINER", "title": "calc_LHC_LogLikes_full.reset", "body": ["map_str_AnalysisLogLikes", "per analysis + signal region"], "tag": "solo.cpp:374"},
            {"id": "aggregate", "shape": "rect", "class": "detail-data", "x": 400, "y": 752, "w": 440, "h": 108, "kind": "AGGREGATION", "title": "per-analysis + combined loglikes", "body": ["get_LHC_LogLike_per_analysis", "calc_combined_LHC_LogLike → double"], "tag": "solo.cpp:375–376"},
            {"id": "contur_gate", "shape": "diamond", "class": "detail-decision", "cx": 620, "cy": 936, "w": 280, "h": 128, "kind": "OPTIONAL BRANCH", "title": "withContur?", "body": ["YES: three Contur maps", "NO: skip to summary"], "tag": "solo.cpp:377"},
            {"id": "contur", "shape": "rect", "class": "detail-optional", "x": 800, "y": 1096, "w": 360, "h": 108, "kind": "CONTUR CONTAINERS", "title": "reset_and_calculate × 3", "body": ["double total LLR", "map_str_dbl pools + map_str_str tags"], "tag": "solo.cpp:379–381"},
            {"id": "output", "shape": "oval", "class": "detail-focal", "x": 320, "y": 1096, "w": 360, "h": 88, "kind": "INLINE OUTPUT", "title": "summary_line + cout", "body": ["SR fields + total loglike", "catch std::exception → 1"], "tag": "solo.cpp:384–443"},
        ],
        "edges": [
            {"from": "resolve", "to": "init"}, {"from": "init", "to": "loop"}, {"from": "loop", "to": "analyses"}, {"from": "analyses", "to": "likes"}, {"from": "likes", "to": "aggregate"}, {"from": "aggregate", "to": "contur_gate"},
            {"from": "contur_gate", "to": "contur", "points": [[760, 936], [960, 936], [960, 1096]], "optional": True},
            {"from": "contur_gate", "to": "output", "points": [[620, 1064], [620, 1080], [500, 1080], [500, 1096]]},
            {"from": "contur", "to": "output", "points": [[980, 1204], [980, 1228], [680, 1228], [680, 1140]], "optional": True},
        ],
    }
    return {"settings_rows": settings_rows, "hardcoded_rows": hardcoded_rows, "runtime_rows": runtime_rows, "dependency_rows": dependency_rows, "settings_diagram": settings_diagram, "runtime_diagram": runtime_diagram}


def _detail_anchor(node: dict[str, Any], side: str) -> tuple[int, int]:
    if "cx" in node:
        cx, cy, w, h = node["cx"], node["cy"], node["w"], node["h"]
        return {"top": (cx, cy - h // 2), "right": (cx + w // 2, cy), "bottom": (cx, cy + h // 2), "left": (cx - w // 2, cy)}[side]
    x, y, w, h = node["x"], node["y"], node["w"], node["h"]
    return {"top": (x + w // 2, y), "right": (x + w, y + h // 2), "bottom": (x + w // 2, y + h), "left": (x, y + h // 2)}[side]


def detailed_svg(diagram_id: str, definition: dict[str, Any]) -> str:
    width, height = definition["width"], definition["height"]
    marker_id = f"solo-{diagram_id}-detail-arrow"
    title_id = f"solo-{diagram_id}-detail-title"
    desc_id = f"solo-{diagram_id}-detail-desc"
    nodes = {node["id"]: node for node in definition["nodes"]}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{title_id} {desc_id}">',
        f'<title id="{title_id}">{html.escape(definition["title"])}</title>',
        f'<desc id="{desc_id}">{html.escape(definition["description"])}</desc>',
        "<defs>",
        f'<marker id="{marker_id}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#4f5d75"/></marker>',
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="#f5f5f5"/>',
        f'<rect class="detail-zone" x="32" y="12" width="{width - 64}" height="{height - 48}" rx="10"/>',
        '<text class="zone-label" x="56" y="40">SOURCE-GROUNDED DETAIL · READ TOP TO BOTTOM</text>',
    ]
    for edge in definition["edges"]:
        points = edge.get("points")
        if points is None:
            points = [_detail_anchor(nodes[edge["from"]], "bottom"), _detail_anchor(nodes[edge["to"]], "top")]
        edge_class = "detail-edge optional" if edge.get("optional") else "detail-edge"
        parts.append(f'<path class="{edge_class}" d="{_flow_path(points)}" style="marker-end:url(#{marker_id})"/>')
    for node in definition["nodes"]:
        node_class = f'node {node.get("class", "detail-primary")}'
        if node["shape"] == "diamond":
            cx, cy, w, h = node["cx"], node["cy"], node["w"], node["h"]
            points = f"{cx},{cy-h//2} {cx+w//2},{cy} {cx},{cy+h//2} {cx-w//2},{cy}"
            parts.append(f'<g class="{node_class}"><polygon points="{points}"/><text class="kind" x="{cx}" y="{cy-24}" text-anchor="middle">{html.escape(node["kind"])}</text><text class="title" x="{cx}" y="{cy+2}" text-anchor="middle">{html.escape(node["title"])}</text><text class="body" x="{cx}" y="{cy+22}" text-anchor="middle">{html.escape(node["body"][0])}</text><text class="body" x="{cx}" y="{cy+36}" text-anchor="middle">{html.escape(node["body"][1])}</text><text class="tag" x="{cx}" y="{cy+52}" text-anchor="middle">{html.escape(node["tag"])}</text></g>')
        elif node["shape"] == "oval":
            x, y, w, h = node["x"], node["y"], node["w"], node["h"]
            cx, cy = x + w // 2, y + h // 2
            parts.append(f'<g class="{node_class}"><ellipse cx="{cx}" cy="{cy}" rx="{w//2}" ry="{h//2}"/><text class="kind" x="{cx}" y="{cy-18}" text-anchor="middle">{html.escape(node["kind"])}</text><text class="title" x="{cx}" y="{cy+4}" text-anchor="middle">{html.escape(node["title"])}</text><text class="body" x="{cx}" y="{cy+20}" text-anchor="middle">{html.escape(node["body"][0])}</text><text class="tag" x="{cx}" y="{cy+34}" text-anchor="middle">{html.escape(node["body"][1])}</text></g>')
        else:
            x, y, w, h = node["x"], node["y"], node["w"], node["h"]
            parts.append(f'<g class="{node_class}" transform="translate({x} {y})"><rect width="{w}" height="{h}" rx="6"/><text class="kind" x="16" y="22">{html.escape(node["kind"])}</text><text class="title" x="16" y="50">{html.escape(node["title"])}</text><text class="body" x="16" y="70">{html.escape(node["body"][0])}</text><text class="body" x="16" y="84">{html.escape(node["body"][1])}</text><text class="tag" x="16" y="{h-12}">{html.escape(node["tag"])}</text></g>')
    legend_y = height - 32
    parts.extend([
        f'<line x1="48" y1="{legend_y-18}" x2="{width-48}" y2="{legend_y-18}" stroke="rgba(45,49,66,.12)" stroke-width="1"/>',
        f'<text class="legend-label" x="48" y="{legend_y}">LEGEND</text>',
        f'<rect x="112" y="{legend_y-10}" width="20" height="10" rx="3" fill="#fff0e8" stroke="#b55c2d"/><text class="legend-label" x="142" y="{legend_y}">FOCAL / MAIN OWNERSHIP</text>',
        f'<rect x="322" y="{legend_y-10}" width="20" height="10" rx="3" fill="#fff" stroke="#7a8399"/><text class="legend-label" x="352" y="{legend_y}">DATA CONTAINER</text>',
        f'<rect x="478" y="{legend_y-10}" width="20" height="10" rx="3" fill="#fff" stroke="#7a8399" stroke-dasharray="5 4"/><text class="legend-label" x="508" y="{legend_y}">OPTIONAL</text>',
        f'<text class="legend-label" x="630" y="{legend_y}">ARROWS = EXECUTION ORDER · TABLES BELOW = COMPLETE FIELD EVIDENCE</text>',
        "</svg>",
    ])
    return "".join(parts)


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
    logic = logic_flow_definitions()
    logic_details = detailed_logic_data()
    return {
        "schema": "cbs-focus-comparison/v2",
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
        "logic_flows": logic,
        "logic_mapping": logic_mapping_rows(),
        "logic_details": logic_details,
        "diff": unified_diff(left, right),
        "scope_note": "Focused static source evidence for one file; the two flowcharts are grouped source paths, not a runtime trace or a complete C++ AST.",
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
    baseline_flow = flowchart_svg("baseline", data["logic_flows"]["baseline"])
    comparison_flow = flowchart_svg("comparison", data["logic_flows"]["comparison"])
    mapping_rows = "".join(
        f"<tr><td>{html.escape(row['concern'])}</td>"
        f"<td>{html.escape(row['baseline'])}</td>"
        f"<td>{html.escape(row['comparison'])}</td>"
        f"<td class=\"status modified\">{html.escape(row['change'])}</td></tr>"
        for row in data["logic_mapping"]
    )
    details = data["logic_details"]
    settings_rows = "".join(
        f"<tr><td><code>{html.escape(row['name'])}</code></td>"
        f"<td><code>{html.escape(row['type'])}</code></td>"
        f"<td>{html.escape(row['default'])}</td>"
        f"<td>{html.escape(row['consumer'])}</td>"
        f"<td><code>{html.escape(row['source'])}</code></td></tr>"
        for row in details["settings_rows"]
    )
    hardcoded_rows = "".join(
        f"<tr><td><code>{html.escape(row['name'])}</code></td>"
        f"<td><code>{html.escape(row['value'])}</code></td>"
        f"<td>{html.escape(row['consumer'])}</td>"
        f"<td><code>{html.escape(row['source'])}</code></td></tr>"
        for row in details["hardcoded_rows"]
    )
    runtime_rows = "".join(
        f"<tr><td><code>{html.escape(row['step'])}</code></td>"
        f"<td><code>{html.escape(row['container'])}</code></td>"
        f"<td>{html.escape(row['value'])}</td>"
        f"<td>{html.escape(row['downstream'])}</td>"
        f"<td><code>{html.escape(row['source'])}</code></td></tr>"
        for row in details["runtime_rows"]
    )
    dependency_rows = "".join(
        f"<tr><td><code>{html.escape(row['owner'])}</code></td>"
        f"<td>{html.escape(row['links'])}</td>"
        f"<td><code>{html.escape(row['backend'])}</code></td>"
        f"<td><code>{html.escape(row['source'])}</code></td></tr>"
        for row in details["dependency_rows"]
    )
    settings_detail_svg = detailed_svg("settings", details["settings_diagram"])
    runtime_detail_svg = detailed_svg("runtime", details["runtime_diagram"])
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
    svg .node.focal ellipse { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    svg .node .kind { fill:var(--soft); font:500 9px var(--font-mono); letter-spacing:1.2px; }
    svg .node .title { fill:var(--ink); font:600 13px var(--font-sans); }
    svg .node .body { fill:var(--muted); font:9px var(--font-mono); }
    svg .node .tag { fill:var(--soft); font:8px var(--font-mono); letter-spacing:.8px; }
    svg .node.mod .kind { fill:#b55c2d; } svg .node.add .kind { fill:var(--green); } svg .node.remove .kind { fill:var(--red); } svg .node.focal .kind { fill:var(--accent); }
    svg .edge-label, svg .legend-label { fill:var(--muted); font:8px var(--font-mono); letter-spacing:.8px; }
    .diagram-note { color:var(--muted); font-size:12px; line-height:1.6; margin:13px 0 0; max-width:1160px; }
    .flow-figure { background:#fff; border:1px solid var(--rule); border-radius:8px; padding:8px; }
    .flow-figure svg { min-width:1080px; }
    .mapping-table { overflow-x:auto; border:1px solid var(--rule); }
    .mapping-table table { min-width:1080px; }
    svg .flow-edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
    svg .node.wrapper rect, svg .node.wrapper ellipse { fill:#fff; stroke:var(--soft); }
    svg .node.decision polygon { fill:rgba(79,93,117,.08); stroke:var(--soft); stroke-width:1.2; }
    svg .node.stop ellipse { fill:var(--red-tint); stroke:var(--red); stroke-dasharray:5 4; }
    .detail-figure { background:#fff; border:1px solid var(--rule); border-radius:8px; padding:8px; }
    .detail-figure svg { min-width:1120px; }
    svg .detail-zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .detail-edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
    svg .detail-edge.optional { stroke-dasharray:5 4; }
    svg .node.detail-primary rect, svg .node.detail-primary ellipse { fill:#fff; stroke:var(--soft); }
    svg .node.detail-data rect { fill:rgba(79,93,117,.08); stroke:var(--soft); }
    svg .node.detail-mod rect { fill:#fff0e8; stroke:#b55c2d; }
    svg .node.detail-hardcoded rect { fill:rgba(79,93,117,.08); stroke:var(--soft); }
    svg .node.detail-optional rect { fill:#fff; stroke:var(--soft); stroke-dasharray:5 4; }
    svg .node.detail-decision polygon { fill:rgba(79,93,117,.08); stroke:var(--soft); stroke-width:1.2; }
    svg .node.detail-focal ellipse { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
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
  <p class="intro">A focused comparison of <code>__FOCUS_FILE__</code> between the baseline CBS Solo branch and SUSYRun2. The overview and two detail diagrams show where the old and new program logic lives; the evidence below expands to YAML ownership, defaults, data containers, functions, includes and exact diff hunks.</p>
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
    <p class="kicker">02 · baseline logic</p>
    <h2>Before · helper-oriented execution flow</h2>
    <p class="source">The baseline path is long because <code>main</code> coordinates several extracted responsibilities. The nodes name the concrete wrappers that own those responsibilities.</p>
    <div class="flow-figure"><div class="diagram-shell">__BASELINE_FLOW__</div></div>
    <p class="diagram-note">The key branch is <code>settings.processes?</code>: the YES path enters <code>SoloBatch::run_and_merge</code> and then emits structured output; the NO path wires the ordinary event loop directly.</p>
  </section>

  <section>
    <p class="kicker">03 · comparison logic</p>
    <h2>After · main-owned execution flow</h2>
    <p class="source">SUSYRun2 retains the event-loop and likelihood stages but places input validation, configuration, dependency wiring, result aggregation and printing directly in <code>solo.cpp::main</code>.</p>
    <div class="flow-figure"><div class="diagram-shell">__COMPARISON_FLOW__</div></div>
    <p class="diagram-note">Compared with the baseline, there is no <code>SoloInput</code>, <code>SoloBatch</code> or <code>SoloOutput</code> boundary in this file, and <code>calc_LHC_LogLikes_full</code> is selected directly.</p>
  </section>

  <section>
    <p class="kicker">04 · ownership migration</p>
    <h2>Where each piece of logic lives</h2>
    <p class="source">This table is the compact reading guide for the two flowcharts: baseline ownership versus SUSYRun2 ownership.</p>
    <div class="mapping-table"><table><thead><tr><th>Concern</th><th>Baseline owner</th><th>SUSYRun2 owner</th><th>Observed change</th></tr></thead><tbody>__MAPPING_ROWS__</tbody></table></div>
  </section>

  <section>
    <p class="kicker">05 · YAML contract detail</p>
    <h2>SUSYRun2 · settings, defaults and hard-coded policy</h2>
    <p class="source">This is the expanded view requested for the comparison branch. “Comment default” means the value is documented beside <code>apply_setting_if_present</code> but is not assigned by <code>solo.cpp</code> itself; the downstream ColliderBit backend supplies the fallback.</p>
    <div class="detail-figure"><div class="diagram-shell">__SETTINGS_DETAIL_SVG__</div></div>
    <p class="diagram-note">The diagram shows the configuration path; the tables preserve every setting name and its exact consumer.</p>
    <div class="scroll"><table><thead><tr><th>YAML key / gate</th><th>Type</th><th>Default / requirement</th><th>Consumer / effect</th><th>Source</th></tr></thead><tbody>__SETTINGS_ROWS__</tbody></table></div>
    <h3>Not loaded from YAML in SUSYRun2</h3>
    <div class="scroll"><table><thead><tr><th>Functor option</th><th>Value</th><th>Consumer</th><th>Source</th></tr></thead><tbody>__HARDCODED_ROWS__</tbody></table></div>
  </section>

  <section>
    <p class="kicker">06 · container execution detail</p>
    <h2>What reset_and_calculate() produces</h2>
    <p class="source">The order below is the explicit order in SUSYRun2 <code>solo.cpp</code>. It distinguishes the functor/container name from the data structure later consumed by the inline summary.</p>
    <div class="detail-figure"><div class="diagram-shell">__RUNTIME_DETAIL_SVG__</div></div>
    <div class="scroll"><table><thead><tr><th>Execution step</th><th>Container / return type</th><th>Contents</th><th>Downstream use</th><th>Source</th></tr></thead><tbody>__RUNTIME_ROWS__</tbody></table></div>
  </section>

  <section>
    <p class="kicker">07 · dependency wiring detail</p>
    <h2>Which functor depends on which module</h2>
    <p class="source">These are the explicit <code>resolveDependency</code> and <code>resolveBackendReq</code> relationships before the reset chain runs.</p>
    <div class="scroll"><table><thead><tr><th>Owner functor</th><th>Dependencies</th><th>Backend requirements</th><th>Source</th></tr></thead><tbody>__DEPENDENCY_ROWS__</tbody></table></div>
  </section>

  <section>
    <p class="kicker">08 · module slices</p>
    <h2>Direct dependency modules</h2>
    <div class="module-strip">__MODULE_ROWS__</div>
  </section>

  <div class="details-grid">
    <section>
      <p class="kicker">09 · function evidence</p>
      <h2>Function-level changes</h2>
      <div class="scroll"><table><thead><tr><th>Status</th><th>Function</th><th>Baseline</th><th>Comparison</th><th>Diff</th></tr></thead><tbody>__FUNCTION_ROWS__</tbody></table></div>
    </section>
    <section>
      <p class="kicker">10 · source surface</p>
      <h2>Include and build relations</h2>
      <div class="scroll"><table><thead><tr><th>Status</th><th>Relation</th><th>Module</th><th>Line / path</th></tr></thead><tbody>__INCLUDE_ROWS__</tbody></table></div>
    </section>
  </div>

  <section>
    <p class="kicker">11 · exact evidence</p>
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
        "__BASELINE_FLOW__": baseline_flow,
        "__COMPARISON_FLOW__": comparison_flow,
        "__MAPPING_ROWS__": mapping_rows,
        "__SETTINGS_DETAIL_SVG__": settings_detail_svg,
        "__RUNTIME_DETAIL_SVG__": runtime_detail_svg,
        "__SETTINGS_ROWS__": settings_rows,
        "__HARDCODED_ROWS__": hardcoded_rows,
        "__RUNTIME_ROWS__": runtime_rows,
        "__DEPENDENCY_ROWS__": dependency_rows,
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
        "## Logic flow",
        "",
        "The generated HTML contains two grouped static flowcharts: one for the helper-oriented baseline and one for the main-owned SUSYRun2 path.",
        "",
        "| Concern | Baseline owner | SUSYRun2 owner | Observed change |",
        "|---|---|---|---|",
    ]
    for row in data["logic_mapping"]:
        lines.append(f"| {row['concern']} | `{row['baseline']}` | `{row['comparison']}` | {row['change']} |")
    lines.extend([
        "",
        "## SUSYRun2 detail",
        "",
        "The HTML page contains the full YAML/default table and dependency table. The reset chain is summarized here:",
        "",
        "| Step | Container | Contents | Source |",
        "|---|---|---|---|",
    ])
    for row in data["logic_details"]["runtime_rows"]:
        lines.append(f"| `{row['step']}` | `{row['container']}` | {row['value']} | `{row['source']}` |")
    lines.extend([
        "",
        "## Functions",
        "",
        "| Status | Function | Baseline | Comparison | Diff |",
        "|---|---|---:|---:|---:|",
    ])
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
