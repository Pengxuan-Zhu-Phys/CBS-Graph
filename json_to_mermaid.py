#!/usr/bin/env python3
"""Convert a nodes/edges dependency JSON file into a Mermaid flowchart."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any


DEPENDENCY_EDGE_KINDS = {
    "dependency",
    "dynamic_dispatch",
    "runtime_dependency",
}


def csv_values(value: str | None) -> set[str]:
    """Parse a comma-separated option into a normalized set."""
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def mermaid_text(value: Any) -> str:
    """Escape text for a Mermaid quoted label."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "<br/>".join(html.escape(part, quote=True) for part in text.split("\n"))
    return text.replace("`", "&#96;").replace("|", "&#124;")


def mermaid_edge_text(value: Any) -> str:
    """Escape an edge label without encoding arrow characters as HTML entities."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("->", "→").replace("<-", "←")
    return text.replace("|", "¦").replace("`", "'")


def mermaid_id(raw_id: Any, index: int, used: set[str]) -> str:
    """Create a stable Mermaid-safe identifier."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", str(raw_id))
    if not base or not re.match(r"^[A-Za-z_]", base):
        base = f"n_{base}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def arrow_for(kind: str, label: str | None) -> str:
    """Return a Mermaid connector, optionally carrying an edge label."""
    if kind in DEPENDENCY_EDGE_KINDS:
        return f"-.->|{label}|" if label else "-.->"
    return f"-->|{label}|" if label else "-->"


def parse_graph(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    if not isinstance(payload.get("nodes"), list):
        raise ValueError("JSON must contain a 'nodes' array")
    if not isinstance(payload.get("edges"), list):
        raise ValueError("JSON must contain an 'edges' array")
    return payload


def build_mermaid(payload: dict[str, Any], args: argparse.Namespace) -> str:
    requested_statuses = csv_values(args.status)
    requested_node_ids = csv_values(args.node_id)
    requested_node_kinds = csv_values(args.node_kind)
    requested_edge_kinds = csv_values(args.edge_kind)

    nodes = [node for node in payload["nodes"] if isinstance(node, dict)]
    edges = [edge for edge in payload["edges"] if isinstance(edge, dict)]

    selected_nodes = []
    for node in nodes:
        status = str(node.get("status", ""))
        kind = str(node.get("kind", ""))
        raw_id = str(node.get("id"))
        if requested_node_ids and raw_id not in requested_node_ids:
            continue
        if requested_statuses and status not in requested_statuses:
            continue
        if requested_node_kinds and kind not in requested_node_kinds:
            continue
        selected_nodes.append(node)

    selected_ids = {str(node.get("id")) for node in selected_nodes}
    edges = [
        edge
        for edge in edges
        if str(edge.get("source")) in selected_ids
        and str(edge.get("target")) in selected_ids
        and (
            not requested_edge_kinds
            or str(edge.get("kind", "")) in requested_edge_kinds
        )
    ]

    used_ids: set[str] = set()
    node_ids = {
        str(node.get("id")): mermaid_id(node.get("id"), index, used_ids)
        for index, node in enumerate(selected_nodes)
    }

    lines = [f"flowchart {args.direction}"]
    title = args.title or payload.get("scope", {}).get("path") or "dependency graph"
    lines.append(f"    %% Generated from {mermaid_text(title)}")

    for node in selected_nodes:
        raw_id = str(node.get("id"))
        label = node.get("label", raw_id)
        if args.metadata:
            metadata = [
                str(value)
                for value in (node.get("kind"), node.get("status"))
                if value
            ]
            if metadata:
                label = f"{label}\n{' · '.join(metadata)}"
        lines.append(f'    {node_ids[raw_id]}["{mermaid_text(label)}"]')

    for edge in edges:
        source = node_ids[str(edge.get("source"))]
        target = node_ids[str(edge.get("target"))]
        kind = str(edge.get("kind", "relation"))
        label = edge.get("label") or kind
        edge_label = mermaid_edge_text(label) if args.edge_labels else None
        lines.append(f"    {source} {arrow_for(kind, edge_label)} {target}")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert dependency JSON with nodes/edges into Mermaid flowchart syntax."
    )
    parser.add_argument("input", type=Path, help="input JSON file")
    parser.add_argument("-o", "--output", type=Path, help="output .mmd file; default: stdout")
    parser.add_argument(
        "--direction",
        choices=("TD", "LR", "RL", "BT"),
        default="TD",
        help="Mermaid flow direction (default: TD)",
    )
    parser.add_argument("--title", help="comment title for the generated diagram")
    parser.add_argument(
        "--status",
        help="only keep nodes with these comma-separated statuses, e.g. target,unchanged",
    )
    parser.add_argument(
        "--node-id",
        help="only keep nodes with these comma-separated IDs",
    )
    parser.add_argument(
        "--node-kind",
        help="only keep nodes with these comma-separated kinds",
    )
    parser.add_argument(
        "--edge-kind",
        help="only keep edges with these comma-separated kinds",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="append node kind and status to node labels",
    )
    parser.add_argument(
        "--no-edge-labels",
        dest="edge_labels",
        action="store_false",
        help="omit edge labels",
    )
    parser.set_defaults(edge_labels=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        diagram = build_mermaid(parse_graph(args.input), args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(diagram, encoding="utf-8")
    else:
        sys.stdout.write(diagram)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
