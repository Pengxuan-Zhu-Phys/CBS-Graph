#!/usr/bin/env python3
"""Build a static, Glean-like comparison graph for two CBS worktrees.

The analyzer deliberately works from source text and Git metadata.  It does not
need Glean, a Linux-only file watcher, a CMake build, or a compile database.  The
result is a conservative graph of local includes, analysis registration edges,
and calls between functions that can be identified from C++ definitions.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".info",
    ".yaml",
    ".yml",
}

SKIP_PARTS = {".git", "build", "contrib", "scratch", ".ccache"}
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

FUNCTION_RE = re.compile(
    r"""
    ^[ \t]*
    (?:(?:template\s*<[^;{}]*>)[ \t]*)?
    (?:[A-Za-z_][\w:<>,~*&\[\]\.\-+ ]*[ \t]+)?
    (?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)
    [ \t]*\([^;{}\n]*\)
    [ \t]*(?:const\b|noexcept\b|override\b|final\b|&\b|&&\b|->[^\{]+)?
    [ \t]*\{
    """,
    re.MULTILINE | re.VERBOSE,
)
INCLUDE_RE = re.compile(r"^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]", re.MULTILINE)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(")
REGISTER_RE = re.compile(r"\bF\s*\(\s*([A-Za-z_]\w*)\s*\)")


@dataclass(frozen=True)
class FileInfo:
    path: str
    text: str
    digest: str
    lines: int


def run_git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def branch_metadata(root: Path, label: str) -> dict[str, str]:
    try:
        commit = run_git(root, "rev-parse", "HEAD")
        short = run_git(root, "rev-parse", "--short", "HEAD")
        branch = run_git(root, "branch", "--show-current") or "(detached HEAD)"
        subject = run_git(root, "show", "-s", "--format=%s", "HEAD")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Unable to read Git metadata from {root}: {exc}") from exc
    return {"label": label, "branch": branch, "commit": commit, "short": short, "subject": subject}


def in_scope(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if rel.startswith("ColliderBit/"):
        return path.name == "CMakeLists.txt" or path.suffix.lower() in SOURCE_SUFFIXES
    return rel in {"CMakeLists.txt", "cmake/standalones.cmake", "cmake/contrib.cmake"}


def collect_files(root: Path) -> dict[str, FileInfo]:
    if not root.is_dir():
        raise SystemExit(f"Worktree is not a directory: {root}")
    result: dict[str, FileInfo] = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if not in_scope(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result[rel] = FileInfo(rel, text, digest, text.count("\n") + (1 if text else 0))
    return result


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def resolve_include(source: str, include: str, available: set[str]) -> str | None:
    source_path = Path(source)
    candidates = [
        source_path.parent / include,
        Path(include),
        Path("ColliderBit/include") / include,
        Path("ColliderBit/include/gambit") / include,
        Path("ColliderBit") / include,
    ]
    for candidate in candidates:
        normalized = candidate.as_posix()
        if normalized in available:
            return normalized
    return None


def function_symbols(info: FileInfo) -> list[dict[str, Any]]:
    if info.path.endswith((".info", ".yaml", ".yml")):
        return []
    clean = strip_comments(info.text)
    symbols: list[dict[str, Any]] = []
    for match in FUNCTION_RE.finditer(clean):
        name = match.group("name")
        short_name = name.rsplit("::", 1)[-1]
        if short_name in CONTROL_CALLS or name in CONTROL_CALLS:
            continue
        line = clean.count("\n", 0, match.start()) + 1
        symbol_id = f"symbol:{info.path}::{name}"
        symbols.append(
            {
                "id": symbol_id,
                "kind": "symbol",
                "label": name,
                "file": info.path,
                "line": line,
                "name": name,
                "short_name": short_name,
                "file_digest": info.digest,
                "start": match.start(),
                "body_start": match.end(),
            }
        )
    unique: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        unique.setdefault(symbol["id"], symbol)
    return list(unique.values())


def add_edge(edges: set[tuple[str, str, str]], source: str, target: str, kind: str) -> None:
    if source and target and source != target:
        edges.add((source, target, kind))


def build_branch(root: Path, label: str) -> dict[str, Any]:
    files = collect_files(root)
    available = set(files)
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    symbols_by_file: dict[str, list[dict[str, Any]]] = {}
    symbols_by_name: dict[str, list[str]] = defaultdict(list)

    for rel, info in files.items():
        node_id = f"file:{rel}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "file",
            "label": rel,
            "file": rel,
            "line": 1,
            "file_digest": info.digest,
            "lines": info.lines,
        }
        for include_match in INCLUDE_RE.finditer(info.text):
            target = resolve_include(rel, include_match.group(2), available)
            if target:
                add_edge(edges, node_id, f"file:{target}", "include")

        symbols = function_symbols(info)
        symbols_by_file[rel] = symbols
        for symbol in symbols:
            nodes[symbol["id"]] = {
                key: value
                for key, value in symbol.items()
                if key not in {"start", "body_start", "name", "short_name"}
            }
            add_edge(edges, node_id, symbol["id"], "contains")
            symbols_by_name[symbol["name"]].append(symbol["id"])
            symbols_by_name[symbol["short_name"]].append(symbol["id"])

    for rel, symbols in symbols_by_file.items():
        clean = strip_comments(files[rel].text)
        for index, symbol in enumerate(symbols):
            end = symbols[index + 1]["start"] if index + 1 < len(symbols) else len(clean)
            body = clean[symbol["body_start"] : end]
            for call_match in CALL_RE.finditer(body):
                callee = call_match.group(1)
                if callee in CONTROL_CALLS or callee.startswith("std::"):
                    continue
                candidates = symbols_by_name.get(callee, [])
                if len(candidates) == 1:
                    add_edge(edges, symbol["id"], candidates[0], "call")

    for rel, info in files.items():
        if not rel.endswith("ColliderBit/src/analyses/AnalysisContainer.cpp"):
            continue
        for registration in REGISTER_RE.finditer(info.text):
            analysis = registration.group(1)
            target_suffix = f"/Analysis_{analysis}.cpp"
            target = next((candidate for candidate in available if candidate.endswith(target_suffix)), None)
            if target:
                add_edge(edges, f"file:{rel}", f"file:{target}", "registers")

    for rel, info in files.items():
        if rel.endswith("cmake/standalones.cmake") or rel == "CMakeLists.txt":
            for candidate in available:
                if candidate.startswith("ColliderBit/examples/") and Path(candidate).suffix in {".cpp", ".cc", ".cxx"}:
                    if Path(candidate).name in info.text:
                        add_edge(edges, f"file:{rel}", f"file:{candidate}", "builds")

    return {
        "metadata": branch_metadata(root, label),
        "files": files,
        "nodes": nodes,
        "edges": edges,
    }


def node_status(left: dict[str, Any] | None, right: dict[str, Any] | None) -> str:
    if left is None:
        return "added-in-right"
    if right is None:
        return "removed-in-right"
    if left.get("kind") == "file":
        return "unchanged" if left.get("file_digest") == right.get("file_digest") else "modified"
    return "unchanged" if left.get("file_digest") == right.get("file_digest") else "modified"


def compare_graphs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_nodes = left["nodes"]
    right_nodes = right["nodes"]
    nodes: list[dict[str, Any]] = []
    for node_id in sorted(set(left_nodes) | set(right_nodes)):
        lnode = left_nodes.get(node_id)
        rnode = right_nodes.get(node_id)
        base = dict(rnode or lnode or {})
        status = node_status(lnode, rnode)
        base["status"] = status
        base["left_line"] = lnode.get("line") if lnode else None
        base["right_line"] = rnode.get("line") if rnode else None
        base["left_file"] = lnode.get("file") if lnode else None
        base["right_file"] = rnode.get("file") if rnode else None
        nodes.append(base)

    left_edges = left["edges"]
    right_edges = right["edges"]
    edges: list[dict[str, str]] = []
    for source, target, kind in sorted(left_edges | right_edges):
        in_left = (source, target, kind) in left_edges
        in_right = (source, target, kind) in right_edges
        status = "unchanged" if in_left and in_right else "added-in-right" if in_right else "removed-in-right"
        edges.append({"source": source, "target": target, "kind": kind, "status": status})

    node_counts = Counter(node["status"] for node in nodes)
    edge_counts = Counter(edge["status"] for edge in edges)
    kind_counts = Counter(node["kind"] for node in nodes)
    file_changes = [node for node in nodes if node["kind"] == "file" and node["status"] != "unchanged"]
    changed_edges = [edge for edge in edges if edge["status"] != "unchanged"]

    return {
        "schema": "cbs-branch-comparison/v1",
        "baseline": left["metadata"],
        "comparison": right["metadata"],
        "scope": {
            "roots": ["ColliderBit/", "CMakeLists.txt", "cmake/standalones.cmake", "cmake/contrib.cmake"],
            "relations": ["include", "registers", "builds", "contains", "call"],
            "note": "Static source-text evidence; this is not a runtime trace or a complete C++ AST.",
        },
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "files": sum(1 for node in nodes if node["kind"] == "file"),
            "symbols": sum(1 for node in nodes if node["kind"] == "symbol"),
            "changed_files": len(file_changes),
            "changed_edges": len(changed_edges),
            "node_status": dict(sorted(node_counts.items())),
            "edge_status": dict(sorted(edge_counts.items())),
            "node_kind": dict(sorted(kind_counts.items())),
        },
        "nodes": nodes,
        "edges": edges,
        "changed_files": sorted(file_changes, key=lambda node: (node["status"], node["label"])),
        "changed_edges": changed_edges,
    }


STATUS_COLORS = {
    "unchanged": "#94a3b8",
    "modified": "#f59e0b",
    "added-in-right": "#22c55e",
    "removed-in-right": "#ef4444",
}


def page_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    baseline = data["baseline"]
    comparison = data["comparison"]
    summary = data["summary"]
    title = f"CBS branch comparison · {baseline['label']} vs {comparison['label']}"
    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1020; --panel:#121a2d; --panel2:#0f172a; --text:#eef4ff; --muted:#9aa8c3; --line:#263452; --accent:#7dd3fc; }
    * { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,sans-serif; }
    main { max-width:1500px; margin:auto; padding:34px 22px 60px; } h1 { margin:0 0 8px; font-size:clamp(28px,5vw,48px); letter-spacing:-.04em; }
    h2 { margin:0 0 10px; font-size:20px; } h3 { margin:20px 0 8px; font-size:17px; color:var(--accent); }
    p { color:var(--muted); } code,.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin:18px 0; } .pill { border:1px solid var(--line); border-radius:999px; padding:5px 10px; color:var(--muted); }
    .pill strong { color:var(--accent); } .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:18px 0; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; } .card .n { display:block; font-size:25px; font-weight:700; color:var(--accent); }
    .layout { display:grid; grid-template-columns:minmax(0,2fr) minmax(340px,1fr); gap:16px; } section { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; }
    .controls { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; } input,select { background:var(--panel2); border:1px solid var(--line); color:var(--text); border-radius:7px; padding:8px; }
    input[type=search] { min-width:260px; flex:1; } label { color:var(--muted); display:flex; align-items:center; gap:5px; }
    .scroll { overflow:auto; max-height:700px; border:1px solid var(--line); border-radius:8px; } table { width:100%; border-collapse:collapse; font-size:14px; }
    th,td { text-align:left; vertical-align:top; padding:8px 9px; border-bottom:1px solid var(--line); } th { position:sticky; top:0; background:#18233b; color:var(--accent); }
    td code { color:#dbeafe; word-break:break-word; } .status { font-weight:700; white-space:nowrap; } .status.modified { color:#fbbf24; } .status.added-in-right { color:#4ade80; } .status.removed-in-right { color:#f87171; } .status.unchanged { color:#94a3b8; }
    #graph-wrap { overflow:auto; background:#f8fafc; border-radius:8px; min-height:500px; } svg { display:block; min-width:900px; } .edge { stroke:#64748b; stroke-width:1.1; opacity:.55; } .edge.changed { stroke:#f59e0b; stroke-width:2; opacity:.9; } .node text { font:13px ui-monospace,SFMono-Regular,Menlo,monospace; fill:#0f172a; pointer-events:none; }
    .legend { display:flex; flex-wrap:wrap; gap:12px; color:var(--muted); font-size:14px; margin:9px 0; } .legend span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:50%; background:var(--c); margin-right:5px; }
    .note { padding:10px 12px; background:#17223a; border-left:3px solid var(--accent); color:var(--muted); } footer { margin-top:18px; color:var(--muted); font-size:14px; }
    @media (max-width:900px) { .layout { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<main>
  <h1>CBS branch comparison</h1>
  <p>Static source-dependency comparison for ColliderBit Solo. The baseline is shown on the left; the comparison branch is shown on the right.</p>
  <div class="meta"><span class="pill"><strong>baseline</strong> __BASELINE__</span><span class="pill"><strong>comparison</strong> __COMPARISON__</span><span class="pill">scope <strong>ColliderBit</strong></span></div>
  <div class="note">This graph uses Git snapshots, local <code>#include</code> resolution, analysis registration macros, CMake source references, and identifiable C++ calls. It is static evidence, not a runtime trace or a complete AST.</div>
  <div class="cards">
    <div class="card"><span class="n">__FILES__</span>files in union</div><div class="card"><span class="n">__NODES__</span>graph nodes</div><div class="card"><span class="n">__EDGES__</span>graph edges</div><div class="card"><span class="n">__CHANGED_FILES__</span>changed files</div><div class="card"><span class="n">__CHANGED_EDGES__</span>changed relations</div>
  </div>
  <div class="layout">
    <section><h2>Relationship graph</h2><div class="legend"><span style="--c:#f59e0b">modified</span><span style="--c:#22c55e">added in comparison</span><span style="--c:#ef4444">removed in comparison</span><span style="--c:#94a3b8">unchanged</span></div><div id="graph-wrap"><svg id="graph" role="img" aria-label="CBS branch relationship graph"></svg></div><p id="graph-note"></p></section>
    <section><h2>Changed files</h2><div class="controls"><input id="search" type="search" placeholder="filter path or symbol"><select id="status"><option value="all">all statuses</option><option value="modified">modified</option><option value="added-in-right">added in comparison</option><option value="removed-in-right">removed in comparison</option></select><select id="kind"><option value="all">all node kinds</option><option value="file">files</option><option value="symbol">symbols</option></select><label><input id="changed-only" type="checkbox" checked> changed only</label></div><div class="scroll"><table><thead><tr><th>Status</th><th>Kind</th><th>Path / symbol</th><th>Lines</th></tr></thead><tbody id="node-table"></tbody></table></div></section>
  </div>
  <section style="margin-top:16px"><h2>Changed relationships</h2><div class="scroll"><table><thead><tr><th>Status</th><th>Kind</th><th>Source</th><th>Target</th></tr></thead><tbody id="edge-table"></tbody></table></div></section>
  <footer>Generated by <code>scripts/compare-cbs-branches.py</code>. Baseline commit: <code>__BASE_COMMIT__</code>; comparison commit: <code>__COMPARE_COMMIT__</code>.</footer>
</main>
<script id="graph-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('graph-data').textContent);
const COLORS = {modified:'#f59e0b','added-in-right':'#22c55e','removed-in-right':'#ef4444',unchanged:'#94a3b8'};
const byId = new Map(DATA.nodes.map(n => [n.id,n]));
const short = value => String(value || '').replace(/^file:/,'').replace(/^symbol:/,'');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function matches(node) {
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('status').value;
  const kind = document.getElementById('kind').value;
  const changedOnly = document.getElementById('changed-only').checked;
  const text = `${node.label} ${node.file || ''}`.toLowerCase();
  return (!q || text.includes(q)) && (status === 'all' || node.status === status) && (kind === 'all' || node.kind === kind) && (!changedOnly || node.status !== 'unchanged');
}
function renderTable() {
  const rows = DATA.nodes.filter(matches).sort((a,b) => `${a.status}${a.label}`.localeCompare(`${b.status}${b.label}`));
  document.getElementById('node-table').innerHTML = rows.slice(0,1000).map(n => `<tr><td class="status ${n.status}">${esc(n.status)}</td><td>${esc(n.kind)}</td><td><code>${esc(n.label)}</code></td><td>${esc(n.left_line || '—')} / ${esc(n.right_line || '—')}</td></tr>`).join('') || '<tr><td colspan="4">No matching nodes.</td></tr>';
}
function renderEdges() {
  const rows = DATA.edges.filter(e => e.status !== 'unchanged').filter(e => {
    const q = document.getElementById('search').value.toLowerCase();
    return !q || `${e.kind} ${e.source} ${e.target}`.toLowerCase().includes(q);
  }).sort((a,b) => `${a.status}${a.kind}${a.source}`.localeCompare(`${b.status}${b.kind}${b.source}`));
  document.getElementById('edge-table').innerHTML = rows.slice(0,1000).map(e => `<tr><td class="status ${e.status}">${esc(e.status)}</td><td>${esc(e.kind)}</td><td><code>${esc(short(e.source))}</code></td><td><code>${esc(short(e.target))}</code></td></tr>`).join('') || '<tr><td colspan="4">No changed relationships.</td></tr>';
}
function renderGraph() {
  const all = DATA.nodes.filter(matches).sort((a,b) => `${a.status}${a.kind}${a.label}`.localeCompare(`${b.status}${b.kind}${b.label}`));
  const visible = all.slice(0,180);
  const ids = new Set(visible.map(n => n.id));
  const cols = Math.max(1, Math.min(5, Math.ceil(Math.sqrt(Math.max(1,visible.length)))));
  const width = Math.max(900, cols * 235 + 20), rows = Math.ceil(visible.length / cols), height = Math.max(500, rows * 62 + 30), nodeW = 215, nodeH = 38;
  const pos = new Map(visible.map((n,i) => [n.id,{x:10+(i%cols)*235,y:15+Math.floor(i/cols)*62}]));
  const line = e => { const a=pos.get(e.source),b=pos.get(e.target); if(!a||!b)return ''; return `<line class="edge ${e.status !== 'unchanged' ? 'changed':''}" x1="${a.x+nodeW/2}" y1="${a.y+nodeH/2}" x2="${b.x+nodeW/2}" y2="${b.y+nodeH/2}"/>`; };
  const box = n => { const p=pos.get(n.id), label=String(n.label||'').length>31?String(n.label).slice(0,28)+'…':n.label; return `<g class="node"><rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="6" fill="${COLORS[n.status]||'#94a3b8'}" fill-opacity=".72" stroke="#334155"/><text x="${p.x+8}" y="${p.y+16}">${esc(label)}</text><text x="${p.x+8}" y="${p.y+30}" font-size="9">${esc(n.kind)} · ${esc(n.status)}</text></g>`; };
  document.getElementById('graph').setAttribute('viewBox',`0 0 ${width} ${height}`); document.getElementById('graph').setAttribute('width',width); document.getElementById('graph').setAttribute('height',height);
  document.getElementById('graph').innerHTML = DATA.edges.filter(e => ids.has(e.source)&&ids.has(e.target)).map(line).join('') + visible.map(box).join('');
  document.getElementById('graph-note').textContent = all.length > visible.length ? `Showing ${visible.length} of ${all.length} matching nodes; use the table and filters for the full result.` : `${visible.length} matching nodes shown.`;
}
function render(){renderTable();renderEdges();renderGraph();}
['search','status','kind','changed-only'].forEach(id => document.getElementById(id).addEventListener('input',render)); render();
</script>
</body>
</html>'''
    replacements = {
        "__TITLE__": html.escape(title),
        "__BASELINE__": html.escape(f"{baseline['label']} · {baseline['short']}"),
        "__COMPARISON__": html.escape(f"{comparison['label']} · {comparison['short']}"),
        "__FILES__": str(summary["files"]),
        "__NODES__": str(summary["nodes"]),
        "__EDGES__": str(summary["edges"]),
        "__CHANGED_FILES__": str(summary["changed_files"]),
        "__CHANGED_EDGES__": str(summary["changed_edges"]),
        "__BASE_COMMIT__": html.escape(baseline["commit"]),
        "__COMPARE_COMMIT__": html.escape(comparison["commit"]),
        "__DATA__": payload,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def markdown_summary(data: dict[str, Any]) -> str:
    baseline = data["baseline"]
    comparison = data["comparison"]
    summary = data["summary"]
    lines = [
        "# CBS branch comparison",
        "",
        f"Baseline: `{baseline['label']}` (`{baseline['short']}`)",
        f"Comparison: `{comparison['label']}` (`{comparison['short']}`)",
        "",
        f"- Files in union: {summary['files']}",
        f"- Graph nodes: {summary['nodes']} ({summary['symbols']} symbols)",
        f"- Graph edges: {summary['edges']}",
        f"- Changed files: {summary['changed_files']}",
        f"- Changed relationships: {summary['changed_edges']}",
        "",
        "The graph is static source evidence from local includes, analysis registration, CMake source references, and identifiable C++ calls. It is not a runtime trace or a complete AST.",
        "",
        "## Changed files",
        "",
        "| Status | Kind | Path / symbol | Baseline line | Comparison line |",
        "|---|---|---|---:|---:|",
    ]
    for node in data["changed_files"]:
        lines.append(f"| {node['status']} | {node['kind']} | `{node['label']}` | {node.get('left_line') or '—'} | {node.get('right_line') or '—'} |")
    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="baseline CBS worktree")
    parser.add_argument("--comparison", type=Path, required=True, help="comparison CBS worktree")
    parser.add_argument("--baseline-label", default="ColliderBit_solo_development")
    parser.add_argument("--comparison-label", default="SUSYRun2")
    parser.add_argument("--output-json", type=Path, default=Path("dependences/cbs-branch-comparison.json"))
    parser.add_argument("--output-html", type=Path, default=Path("dependences/cbs-branch-comparison.html"))
    parser.add_argument("--site-html", type=Path, default=Path("site/cbs-branch-comparison.html"))
    parser.add_argument("--summary-md", type=Path, default=Path("dependences/CBS_BRANCH_COMPARISON.md"))
    args = parser.parse_args()

    left = build_branch(args.baseline.resolve(), args.baseline_label)
    right = build_branch(args.comparison.resolve(), args.comparison_label)
    data = compare_graphs(left, right)
    page = page_html(data)
    write_text(args.output_json.resolve(), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    write_text(args.output_html.resolve(), page)
    write_text(args.site_html.resolve(), page)
    write_text(args.summary_md.resolve(), markdown_summary(data))
    print(json.dumps(data["summary"], ensure_ascii=False, sort_keys=True))
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_html}")
    print(f"Wrote {args.site_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
