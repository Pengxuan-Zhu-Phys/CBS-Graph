#!/usr/bin/env python3
"""Build a small static site from GAMBIT Graphviz output and Glean facts."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable


DEFAULT_PREFIXES = ("ColliderBit/", "Core/", "Elements/", "Models/", "Utils/")


def unwrap(value: Any) -> Any:
    """Return a Glean fact's expanded key, when present."""
    if isinstance(value, dict) and "key" in value:
        return value["key"]
    return value


def scalar(value: Any) -> str | None:
    value = unwrap(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def function_name(value: Any) -> str | None:
    value = unwrap(value)
    if not isinstance(value, dict):
        return scalar(value)
    if "name" in value:
        return scalar(value["name"])
    if "operator_" in value:
        return "operator " + (scalar(value["operator_"]) or "?")
    if "literalOperator" in value:
        return scalar(value["literalOperator"])
    if "constructor" in value:
        return "<constructor>"
    if "destructor" in value:
        return "<destructor>"
    if "conversionOperator" in value:
        return "operator " + (scalar(value["conversionOperator"]) or "?")
    return None


def scope_name(value: Any) -> str:
    value = unwrap(value)
    if not isinstance(value, dict):
        return ""
    if "namespace_" in value:
        ns = unwrap(value["namespace_"])
        if isinstance(ns, dict):
            local = scalar(ns.get("name")) or ""
            parent = scope_name(ns.get("parent"))
            return "::".join(part for part in (parent, local) if part)
    if "recordWithAccess" in value:
        record = unwrap(value["recordWithAccess"])
        return qname(record.get("record")) if isinstance(record, dict) else ""
    if "local" in value:
        return qname(value["local"])
    return ""


def qname(value: Any) -> str:
    value = unwrap(value)
    if not isinstance(value, dict):
        return scalar(value) or "?"
    local = function_name(value.get("name"))
    if local is None:
        local = scalar(value.get("name")) or "?"
    scope = scope_name(value.get("scope"))
    return "::".join(part for part in (scope, local) if part)


def declaration_label(value: Any) -> str:
    value = unwrap(value)
    if not isinstance(value, dict):
        return scalar(value) or "?"
    kinds = (
        ("function_", "function"),
        ("record_", "record"),
        ("enum_", "enum"),
        ("variable", "variable"),
        ("typeAlias", "type"),
        ("namespace_", "namespace"),
        ("usingDeclaration", "using"),
        ("usingDirective", "using"),
    )
    for key, kind in kinds:
        if key not in value:
            continue
        payload = unwrap(value[key])
        if not isinstance(payload, dict):
            return f"{kind}: {scalar(payload) or '?'}"
        name = payload.get("name")
        label = qname(name) if name is not None else None
        return f"{kind}: {label or '?'}"
    return "declaration"


def declaration_kind(value: Any) -> str:
    value = unwrap(value)
    if not isinstance(value, dict):
        return "other"
    if "function_" in value:
        return "function"
    if "record_" in value:
        return "record"
    if "variable" in value:
        return "variable"
    return "other"


def declaration_source(value: Any) -> tuple[str | None, int | None]:
    value = unwrap(value)
    if not isinstance(value, dict):
        return None, None
    for key in ("function_", "record_", "enum_", "variable", "typeAlias", "namespace_"):
        if key in value:
            payload = unwrap(value[key])
            if isinstance(payload, dict):
                source = unwrap(payload.get("source"))
                if isinstance(source, dict):
                    file_name = scalar(source.get("file"))
                    line = source.get("lineBegin")
                    return file_name, int(line) if isinstance(line, (int, float)) else None
    return None, None


def read_json_stream(path: Path) -> list[Any]:
    raw = path.read_text(encoding="utf-8")
    raw = raw.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        out: list[Any] = []
        offset = 0
        while offset < len(raw):
            while offset < len(raw) and raw[offset].isspace():
                offset += 1
            if offset >= len(raw):
                break
            value, end = decoder.raw_decode(raw, offset)
            out.append(value)
            offset = end
        return out


def prefixes_match(path: str | None, prefixes: tuple[str, ...]) -> bool:
    return bool(path) and any(path.startswith(prefix) for prefix in prefixes)


def glean_edges(path: Path, prefixes: tuple[str, ...]) -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str]] = set()
    for result in read_json_stream(path):
        record = unwrap(result)
        if not isinstance(record, dict):
            continue
        source = record.get("source")
        targets = record.get("targets")
        if source is None or not isinstance(unwrap(targets), list):
            continue
        source_file, source_line = declaration_source(source)
        if not prefixes_match(source_file, prefixes):
            continue
        source_label = declaration_label(source)
        source_id = str(unwrap(source).get("id", source_label)) if isinstance(unwrap(source), dict) else source_label
        nodes[source_id] = {"label": source_label, "file": source_file, "line": source_line, "kind": declaration_kind(source)}
        target_values = unwrap(targets) or []
        for target in target_values:
            target_file, target_line = declaration_source(target)
            if not prefixes_match(target_file, prefixes):
                continue
            target_label = declaration_label(target)
            target_id = str(unwrap(target).get("id", target_label)) if isinstance(unwrap(target), dict) else target_label
            nodes[target_id] = {"label": target_label, "file": target_file, "line": target_line, "kind": declaration_kind(target)}
            if source_id != target_id:
                edges.add((source_id, target_id))
    return nodes, edges


def dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_glean_dot(nodes: dict[str, dict[str, Any]], edges: set[tuple[str, str]]) -> str:
    lines = ["digraph GleanDeclarations {", "  rankdir=LR;", "  graph [bgcolor=\"transparent\", pad=0.2];", "  node [shape=box, style=rounded, fontname=\"Helvetica\", fontsize=10];"]
    for node_id, data in sorted(nodes.items()):
        location = data.get("file") or "unknown file"
        if data.get("line"):
            location += f":{data['line']}"
        label = f"{data['label']}\\n{location}"
        color = {"function": "#dbeafe", "record": "#dcfce7", "variable": "#fef3c7"}.get(data.get("kind"), "#f3f4f6")
        lines.append(f'  "{dot_escape(node_id)}" [label="{dot_escape(label)}", fillcolor="{color}", style="rounded,filled"];')
    for source, target in sorted(edges):
        lines.append(f'  "{dot_escape(source)}" -> "{dot_escape(target)}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def run_dot(dot_text: str, output: Path) -> bool:
    dot = shutil.which("dot")
    if not dot:
        return False
    proc = subprocess.run([dot, "-Tsvg", "-o", str(output)], input=dot_text, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return False
    return True


def find_runtime_graph(gambit_root: Path) -> Path | None:
    candidates = list(gambit_root.glob("scratch/run_time/**/GAMBIT_active_functor_graph.gv"))
    if not candidates:
        candidates = list(gambit_root.glob("**/GAMBIT_active_functor_graph.gv"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def copy_graphviz(graph: Path, assets: Path) -> bool:
    shutil.copy2(graph, assets / "active-functor-graph.gv")
    return run_dot(graph.read_text(encoding="utf-8"), assets / "active-functor-graph.svg")


def page_html(metadata: dict[str, Any]) -> str:
    def status(key: str) -> str:
        return "available" if metadata.get(key) else "not generated"

    source_ref = html.escape(str(metadata.get("source_ref") or "not recorded"))
    runtime = status("runtime_graph")
    glean = status("glean_graph")
    runtime_panel = (
        '<object class="graph" data="assets/active-functor-graph.svg" type="image/svg+xml" aria-label="GAMBIT active functor dependency graph"></object>'
        if metadata.get("runtime_graph")
        else '<div class="empty">No GAMBIT_active_functor_graph.gv was found. Run CBS/GAMBIT with the graph-producing diagnostic enabled, then rebuild the site.</div>'
    )
    glean_panel = (
        '<object class="graph" data="assets/glean-declaration-graph.svg" type="image/svg+xml" aria-label="Glean C++ declaration target graph"></object>'
        if metadata.get("glean_graph")
        else '<div class="empty">No Glean query output was supplied. Run scripts/index-gambit.sh in a Linux Glean environment, then rebuild the site.</div>'
    )
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CBS Graph</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b1020; --panel:#121a2d; --muted:#9aa8c3; --line:#263452; --accent:#7dd3fc; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:#eef4ff; font:15px/1.5 system-ui,sans-serif; }}
    main {{ max-width:1400px; margin:0 auto; padding:36px 22px 60px; }} h1 {{ margin:0 0 8px; font-size:clamp(30px,5vw,52px); }}
    h2 {{ margin:0 0 8px; }} p {{ color:var(--muted); }} .meta {{ display:flex; gap:10px; flex-wrap:wrap; margin:22px 0; }}
    .pill {{ border:1px solid var(--line); border-radius:999px; padding:5px 11px; color:var(--muted); }} .pill strong {{ color:var(--accent); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(460px,1fr)); gap:18px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; min-height:420px; }}
    .graph {{ display:block; width:100%; height:620px; background:#fff; border-radius:9px; margin-top:16px; }}
    .empty {{ margin-top:16px; border:1px dashed var(--line); border-radius:9px; padding:28px; color:var(--muted); min-height:220px; display:grid; place-items:center; text-align:center; }}
    code {{ color:#bae6fd; }} a {{ color:var(--accent); }} footer {{ margin-top:24px; color:var(--muted); font-size:13px; }}
  </style>
</head>
<body><main>
  <h1>CBS Graph</h1>
  <p>ColliderBit Solo dependency and C++ declaration-target views.</p>
  <div class="meta">
    <span class="pill">runtime graph: <strong>{runtime}</strong></span>
    <span class="pill">Glean graph: <strong>{glean}</strong></span>
    <span class="pill">GAMBIT ref: <strong>{source_ref}</strong></span>
  </div>
  <div class="grid">
    <section><h2>GAMBIT active functors</h2><p>The runtime dependency graph emitted by GAMBIT's dependency resolver.</p>{runtime_panel}</section>
    <section><h2>Meta Glean C++ view</h2><p>Static declaration targets indexed from the C++ source tree; useful for tracing implementation calls.</p>{glean_panel}</section>
  </div>
  <footer>Generated by <code>CBS-Graph/scripts/build-site.py</code>. Review source paths before publishing.</footer>
</main></body></html>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path, required=True)
    parser.add_argument("--graphviz-file", type=Path)
    parser.add_argument("--glean-json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--source-prefix", action="append", dest="prefixes", default=[])
    args = parser.parse_args()

    output = args.output.resolve()
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    generated_files = list(assets.glob("*.svg")) + list(assets.glob("*.gv")) + list(assets.glob("*.json"))
    for generated in generated_files:
        generated.unlink()

    runtime_graph = args.graphviz_file or find_runtime_graph(args.gambit_root)
    runtime_ok = False
    if runtime_graph and runtime_graph.is_file():
        runtime_ok = copy_graphviz(runtime_graph, assets)

    prefixes = tuple(args.prefixes) if args.prefixes else DEFAULT_PREFIXES
    glean_ok = False
    node_count = edge_count = 0
    if args.glean_json and args.glean_json.is_file():
        nodes, edges = glean_edges(args.glean_json, prefixes)
        node_count, edge_count = len(nodes), len(edges)
        dot_text = render_glean_dot(nodes, edges)
        (assets / "glean-declaration-graph.gv").write_text(dot_text, encoding="utf-8")
        glean_ok = run_dot(dot_text, assets / "glean-declaration-graph.svg")
        (assets / "glean-summary.json").write_text(json.dumps({"nodes": node_count, "edges": edge_count, "prefixes": prefixes}, indent=2) + "\n", encoding="utf-8")

    metadata = {"runtime_graph": runtime_ok, "glean_graph": glean_ok, "source_ref": args.source_ref, "glean_nodes": node_count, "glean_edges": edge_count}
    (output / "index.html").write_text(page_html(metadata), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output / 'index.html'}")
    print(f"Runtime graph: {'yes' if runtime_ok else 'no'}")
    print(f"Glean graph: {'yes' if glean_ok else 'no'} ({node_count} nodes, {edge_count} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
