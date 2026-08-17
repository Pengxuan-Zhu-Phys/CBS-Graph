#!/usr/bin/env python3
"""Render the CBS JSON output-contract page from the emitter source.

Unlike ``compare-cbs-focus.py`` this is not a comparison.  ``private-SUSYRun2``
has no JSON output at all -- no ``Utils/include/gambit/Utils/json.hpp``, and
``grep -ci json ColliderBit/examples/solo.cpp`` returns 0 -- so there is no
"before" side to draw.  The page describes the new contract only.

Everything structural on the page is read out of the source at generation time:
top-level keys, per-object field lists, the value expression behind each field,
the ``append_term`` call sites, and the set of fields that ``solo_batch.cpp``
reads back when it merges per-file runs.  The prose around them is curated, but
no key name or line number is typed by hand, so the page cannot quietly drift
away from the emitter.

Nothing here was produced by running CBS.  The JSON excerpts show the *shape*
with the C++ expression left in the value position precisely so they cannot be
mistaken for a recorded run.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path

OUTPUT_CPP = "ColliderBit/examples/solo_output.cpp"
OUTPUT_HPP = "ColliderBit/examples/solo_output.hpp"
BATCH_CPP = "ColliderBit/examples/solo_batch.cpp"
SOLO_CPP = "ColliderBit/examples/solo.cpp"
JSON_HPP = "Utils/include/gambit/Utils/json.hpp"

# A run whose output is committed in the tree, used to show each top-level key
# as it actually comes out.  This is the only place on the page where a value
# comes from an execution rather than from the emitter source, and the cards
# say so.
SAMPLE_RUN = "runs/CBS_result.json"

# How much of each key to show.  Field names are unique enough across the
# document to key on directly, so a rule applies at whatever depth the field
# turns up rather than being scoped to one parent.
ELIDE_FIELDS = {"cutflows", "histograms", "targets"}
LIST_LIMIT = {"terms": 1, "analyses": 1, "cuts": 2, "process_recommendations": 1}
DICT_LIMIT = {"analyses": 1, "signal_regions": 1}
DEFAULT_LIST_LIMIT = 2


def elide_note(value) -> str:
    if isinstance(value, list):
        return f"... {len(value)} entries, same shape ..."
    if isinstance(value, dict):
        inner = value.get("1d")
        if isinstance(inner, list):
            return f"... {len(inner)} 1D, {len(value.get('2d') or [])} 2D ..."
        return f"... {len(value)} entries ..."
    return "..."


def trim_sample(value, key=None, depth=0):
    """Shrink a run-output value to something quotable, marking what was cut."""
    if isinstance(value, dict):
        limit = DICT_LIMIT.get(key)
        out, shown = {}, 0
        for name, item in value.items():
            if limit is not None and shown >= limit:
                out[f"... {len(value) - shown} more keys"] = "..."
                break
            out[name] = (elide_note(item) if name in ELIDE_FIELDS
                         else trim_sample(item, name, depth + 1))
            shown += 1
        return out

    if isinstance(value, list):
        limit = LIST_LIMIT.get(key, DEFAULT_LIST_LIMIT)
        head = [trim_sample(item, None, depth + 1) for item in value[:limit]]
        if len(value) > limit:
            head.append(f"... {len(value) - limit} more, same shape ...")
        return head

    if isinstance(value, float):
        return round(value, 6)
    return value


def run_samples(gambit_root) -> dict:
    """One quotable excerpt per top-level key, from the committed run output."""
    path = gambit_root / SAMPLE_RUN
    if not path.exists():
        return {}
    document = json.loads(path.read_text())
    out = {key: json.dumps(trim_sample(value, key), indent=2)
           for key, value in document.items()}
    out["__meta__"] = {
        "path": SAMPLE_RUN,
        "n_events": document.get("run", {}).get("n_events"),
        "present": sorted(document),
    }
    return out


# --------------------------------------------------------------------------
# source access
# --------------------------------------------------------------------------

class Source:
    """A source file addressed by 1-based line number."""

    def __init__(self, root: Path, rel: str):
        self.rel = rel
        self.path = root / rel
        if not self.path.is_file():
            raise SystemExit(f"missing source file: {self.path}")
        self.lines = self.path.read_text(errors="replace").splitlines()

    def line(self, index: int) -> str:
        return self.lines[index - 1]

    def find(self, pattern: str, start: int = 1) -> int:
        """First 1-based line at or after ``start`` matching ``pattern``."""
        rx = re.compile(pattern)
        for i in range(start, len(self.lines) + 1):
            if rx.search(self.line(i)):
                return i
        raise SystemExit(f"pattern not found in {self.rel}: {pattern!r}")

    def find_all(self, pattern: str) -> list[int]:
        rx = re.compile(pattern)
        return [i for i in range(1, len(self.lines) + 1) if rx.search(self.line(i))]

    def count(self) -> int:
        return len(self.lines)


STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def strip_strings(text: str) -> str:
    """Blank out string literals so brace counting is not fooled by them."""
    return STRING_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', text)


def block_span(src: Source, start: int) -> tuple[int, int]:
    """Line span of the brace block opened at or after ``start``."""
    depth = 0
    opened = False
    for i in range(start, src.count() + 1):
        text = strip_strings(src.line(i))
        for ch in text:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return start, i
    raise SystemExit(f"unterminated block from {src.rel}:{start}")


# --------------------------------------------------------------------------
# emitter extraction
# --------------------------------------------------------------------------

ASSIGN_RE = re.compile(
    r'\b(?P<var>[A-Za-z_]\w*)(?P<chain>(?:\s*\[\s*"[^"]+"\s*\])+)\s*=(?!=)\s*(?P<rhs>.*)$'
)
CHAIN_KEY_RE = re.compile(r'\[\s*"([^"]+)"\s*\]')
PAIR_RE = re.compile(r'\{\s*"([^"]+)"\s*,\s*([^{}]+?)\s*\}')


def normalise_rhs(rhs: str, src: Source, line_no: int) -> str:
    """The value expression, joined across continuation lines and de-noised."""
    text = rhs.strip()
    probe = line_no
    while not text.rstrip().endswith(";") and probe < src.count():
        probe += 1
        text = f"{text} {src.line(probe).strip()}"
        if probe - line_no > 6:
            break
    text = text.rstrip()
    if text.endswith(";"):
        text = text[:-1]
    return re.sub(r"\s+", " ", text).strip()


def object_fields(src: Source, var: str, span: tuple[int, int] | None = None) -> list[dict]:
    """Ordered, de-duplicated ``var["key"] = expr`` assignments."""
    lo, hi = span if span else (1, src.count())
    fields: list[dict] = []
    seen: set[str] = set()
    for i in range(lo, hi + 1):
        match = ASSIGN_RE.search(src.line(i))
        if not match or match.group("var") != var:
            continue
        keys = CHAIN_KEY_RE.findall(match.group("chain"))
        key = ".".join(keys)
        if key in seen:
            continue
        seen.add(key)
        fields.append({
            "key": key,
            "expr": normalise_rhs(match.group("rhs"), src, i),
            "line": i,
        })
    if not fields:
        raise SystemExit(f"no assignments found for {var!r} in {src.rel}")
    return fields


def initializer_pairs(src: Source, lo: int, hi: int) -> list[dict]:
    """``{"key", expr}`` pairs inside a brace-initialised object."""
    pairs: list[dict] = []
    for i in range(lo, hi + 1):
        for key, expr in PAIR_RE.findall(src.line(i)):
            pairs.append({"key": key, "expr": expr.strip(), "line": i})
    return pairs


def append_term_calls(src: Source) -> list[dict]:
    """Literal arguments of every ``append_term(...)`` call site."""
    src.find(r"void append_term\(")  # fail loudly if the helper is gone
    calls: list[dict] = []
    for start in src.find_all(r"^\s*append_term\($"):
        depth = 0
        chunk: list[str] = []
        end = start
        for i in range(start, src.count() + 1):
            text = src.line(i)
            chunk.append(text.strip())
            stripped = strip_strings(text)
            depth += stripped.count("(") - stripped.count(")")
            if depth == 0:
                end = i
                break
        body = " ".join(chunk)
        inner = body[body.index("(") + 1:body.rindex(")")]
        args = [a.strip() for a in split_top_level(inner)]
        # A bare identifier says nothing on its own; resolve one level back to
        # the local it was assigned from, so the table shows the composed key.
        args = [resolve_local(src, arg, start) for arg in args]
        calls.append({"args": args, "line": start, "end": end})
    if not calls:
        raise SystemExit("no append_term call sites found")
    return calls


def resolve_local(src: Source, arg: str, before: int, window: int = 40) -> str:
    """Substitute a bare local identifier with the expression it was assigned.

    Only one level, only backwards, only within a short window: enough to turn
    ``sr_group`` into the string it is built from, without pretending to be a
    constant propagator.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*", arg):
        return arg
    pattern = re.compile(rf"\b(?:const\s+)?[\w:<>]+\s+{re.escape(arg)}\s*=\s*(.+?);\s*$")
    for i in range(before - 1, max(before - window, 0), -1):
        text = src.line(i).strip()
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return arg


def split_top_level(text: str) -> list[str]:
    """Split on commas that are not nested inside brackets or strings."""
    out: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            current.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        out.append("".join(current))
    return out


# --------------------------------------------------------------------------
# batch consumer extraction
# --------------------------------------------------------------------------

READ_RE = re.compile(
    r'\b(?P<recv>[A-Za-z_]\w*(?:\[[^\]]*\])?)\s*\.\s*(?:at|value|contains)\(\s*"(?P<key>[^"]+)"'
)
THROW_RE = re.compile(r'throw std::runtime_error\(\s*$|throw std::runtime_error\(\s*"([^"]*)"')


def function_span(src: Source, name: str, marker: str | None = None) -> tuple[int, int]:
    start = src.find(marker or rf"^\s*[\w:<>&*,\s]+\b{re.escape(name)}\s*\(")
    brace = start
    while "{" not in strip_strings(src.line(brace)):
        brace += 1
        if brace - start > 24:
            raise SystemExit(f"no opening brace for {name} in {src.rel}")
    return block_span(src, brace)


def reads_in(src: Source, span: tuple[int, int]) -> list[dict]:
    """Every ``receiver.at("key")`` style read in a line span.

    The receiver is kept because key names repeat across objects: ``name``
    belongs to both a cutflow and a histogram, ``analyses`` to both the document
    root and the sampling-advice block.  Matching on the name alone would mark
    fields as load-bearing that the merge never touches.

    Every occurrence is kept rather than de-duplicated, because a receiver name
    is itself reused across loops -- ``h_json`` names both the 1D and the 2D
    histogram in the same function -- and collapsing to the first hit would put
    the surviving line number in the wrong loop.
    """
    lo, hi = span
    out: list[dict] = []
    for i in range(lo, hi + 1):
        for match in READ_RE.finditer(src.line(i)):
            out.append({
                "receiver": match.group("recv"),
                "key": match.group("key"),
                "line": i,
            })
    return out


def guards_in(src: Source, span: tuple[int, int]) -> list[dict]:
    """Merge-time ``runtime_error`` messages, joined across continuations."""
    lo, hi = span
    out: list[dict] = []
    for i in range(lo, hi + 1):
        if "throw std::runtime_error(" not in src.line(i):
            continue
        text = src.line(i).strip()
        probe = i
        while text.count("(") > text.count(")") and probe < hi:
            probe += 1
            text = f"{text} {src.line(probe).strip()}"
        literals = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        if not literals:
            continue
        # Literals around an interpolated variable are joined with an ellipsis
        # so the gap reads as a placeholder rather than as a stray quote pair.
        message = "…".join(literals)
        message = re.sub(r"\s+", " ", message).strip()
        out.append({"message": message, "line": i})
    return out


# --------------------------------------------------------------------------
# document model
# --------------------------------------------------------------------------

def build_data(gambit_root: Path) -> dict:
    out = Source(gambit_root, OUTPUT_CPP)
    hpp = Source(gambit_root, OUTPUT_HPP)
    batch = Source(gambit_root, BATCH_CPP)
    solo = Source(gambit_root, SOLO_CPP)
    jsonlib = Source(gambit_root, JSON_HPP)

    emit_span = function_span(out, "emit_outputs", r"^\s*void emit_outputs\($")
    schema_line = out.find(r"kSchemaVersion\s*=")
    schema_version = re.search(r'"([^"]+)"', out.line(schema_line)).group(1)
    indent_line = out.find(r"kJsonIndent\s*=")
    indent_value = re.search(r"=\s*(\d+)", out.line(indent_line)).group(1)

    lib_major = re.search(r"VERSION_MAJOR (\d+)", jsonlib.line(jsonlib.find(r"NLOHMANN_JSON_VERSION_MAJOR \d"))).group(1)
    lib_minor = re.search(r"VERSION_MINOR (\d+)", jsonlib.line(jsonlib.find(r"NLOHMANN_JSON_VERSION_MINOR \d"))).group(1)
    lib_patch = re.search(r"VERSION_PATCH (\d+)", jsonlib.line(jsonlib.find(r"NLOHMANN_JSON_VERSION_PATCH \d"))).group(1)
    object_type_line = jsonlib.find(r"class ObjectType =")

    # ---- top-level keys, in emission order -------------------------------
    # ``root["run"]["enabled_variants"]`` assigns through the chain, so split
    # the single-segment keys (the document's own keys) from the nested ones.
    all_root_assignments = object_fields(out, "root", emit_span)
    root_fields = [f for f in all_root_assignments if "." not in f["key"]]
    nested_root = [f for f in all_root_assignments if "." in f["key"]]
    run_lo = out.find(r'root\["run"\] =', emit_span[0])
    run_pairs = initializer_pairs(out, run_lo, run_lo + 4)
    for field in nested_root:
        parent = field["key"].split(".")[0]
        if parent == "run":
            run_pairs.append({
                "key": field["key"].split(".", 1)[1],
                "expr": field["expr"],
                "line": field["line"],
            })

    # ---- nested objects ---------------------------------------------------
    h1d_start = out.find(r"for \(const Histogram1D& h :")
    h2d_start = out.find(r"for \(const Histogram2D& h :")
    hist_span = function_span(out, "build_histograms_json", r"nlohmann::json build_histograms_json\(")
    cutflow_span = function_span(out, "build_cutflows_json", r"nlohmann::json build_cutflows_json\(")

    objects = [
        {
            "id": "analysis",
            "path": 'analyses["<ANALYSIS_NAME>"]',
            "keyed_by": "AnalysisData::analysis_name",
            "fields": object_fields(out, "analysis_obj", emit_span),
        },
        {
            "id": "combination",
            "path": 'analyses["<A>"].combination',
            "keyed_by": None,
            "fields": object_fields(out, "combination", emit_span),
        },
        {
            "id": "signal_region",
            "path": 'analyses["<A>"].signal_regions["<SR_LABEL>"]',
            "keyed_by": "SignalRegionData::sr_label",
            "fields": object_fields(out, "sr_obj", emit_span),
        },
        {
            "id": "cutflow",
            "path": 'analyses["<A>"].cutflows[]',
            "keyed_by": None,
            "fields": object_fields(out, "cutflow_json", cutflow_span),
        },
        {
            "id": "cut",
            "path": 'analyses["<A>"].cutflows[].cuts[]',
            "keyed_by": None,
            "fields": object_fields(out, "cut_json", cutflow_span),
        },
        {
            "id": "histogram_1d",
            "path": 'analyses["<A>"].histograms["1d"][]',
            "keyed_by": None,
            "fields": object_fields(out, "hobj", (h1d_start, h2d_start - 1)),
        },
        {
            "id": "histogram_bin",
            "path": 'analyses["<A>"].histograms["1d"][].bins[]',
            "keyed_by": None,
            "fields": object_fields(out, "bin", (h1d_start, h2d_start - 1)),
        },
        {
            "id": "histogram_2d",
            "path": 'analyses["<A>"].histograms["2d"][]',
            "keyed_by": None,
            "fields": object_fields(out, "hobj", (h2d_start, hist_span[1])),
        },
        {
            "id": "term",
            "path": "terms[]",
            "keyed_by": None,
            "fields": object_fields(out, "term", (1, emit_span[0])),
        },
        {
            "id": "summary",
            "path": "summary",
            "keyed_by": None,
            "fields": object_fields(out, "summary", emit_span),
        },
        {
            "id": "advice",
            "path": "sampling_advice",
            "keyed_by": None,
            "fields": object_fields(out, "advice_json", emit_span),
        },
        {
            "id": "advice_analysis",
            "path": "sampling_advice.analyses[]",
            "keyed_by": None,
            "fields": object_fields(out, "analysis_advice_json", emit_span),
        },
        {
            "id": "advice_target",
            "path": "sampling_advice.analyses[].targets[]",
            "keyed_by": None,
            "fields": object_fields(out, "target_json", emit_span),
        },
        {
            "id": "advice_process",
            "path": "sampling_advice.analyses[].targets[].process_recommendations[]",
            "keyed_by": None,
            "fields": object_fields(out, "process_json", emit_span),
        },
        {
            "id": "contur",
            "path": "contur",
            "keyed_by": None,
            "fields": object_fields(out, "contur_json", emit_span),
        },
        {
            "id": "contur_pool",
            "path": 'contur.pools["<POOL>"]',
            "keyed_by": "pool name from Contur_LHC_measurements_LogLike_perPool",
            "fields": object_fields(out, "pool_obj", emit_span),
        },
    ]

    # ---- what the batch merge reads back ---------------------------------
    consumer_specs = [
        ("parse_sorted_sr_payloads", r"std::vector<SRPayload> parse_sorted_sr_payloads\("),
        ("parse_cutflows_or_empty", r"Cutflows parse_cutflows_or_empty\("),
        ("parse_histograms_or_empty", r"Histograms parse_histograms_or_empty\("),
        ("parse_covariance_or_empty", r"\bparse_covariance\w*\("),
        ("initialize_accumulator", r"void initialize_accumulator\("),
        ("validate_payload_consistency", r"void validate_payload_consistency\("),
        ("run_and_merge", r"MergedRunResult run_and_merge\($"),
    ]
    consumers = []
    for name, marker in consumer_specs:
        try:
            span = function_span(batch, name, marker)
        except SystemExit:
            continue
        consumers.append({
            "name": name,
            "span": span,
            "reads": reads_in(batch, span),
            "guards": guards_in(batch, span),
        })

    # Which merge receiver corresponds to which emitted object.  ``h_json`` is
    # reused for both histogram dimensions in the parser exactly as ``hobj`` is
    # in the emitter, so both sides are split on the same 1d/2d boundary.
    hist_consumer = next(c for c in consumers if c["name"] == "parse_histograms_or_empty")
    h1d_read_start = batch.find(r'histo_json\.contains\("1d"\)', hist_consumer["span"][0])
    h2d_read_start = batch.find(r'histo_json\.contains\("2d"\)', hist_consumer["span"][0])

    receiver_map = {
        "analysis": [("analysis_json", None)],
        "signal_region": [("sr", None)],
        "cutflow": [("cf_json", None)],
        "cut": [("cut_json", None)],
        "histogram_1d": [("h_json", (h1d_read_start, h2d_read_start - 1))],
        "histogram_bin": [("bins[i]", None)],
        "histogram_2d": [("h_json", (h2d_read_start, hist_consumer["span"][1]))],
    }

    all_reads = [
        dict(read, function=consumer["name"])
        for consumer in consumers
        for read in consumer["reads"]
    ]

    for obj in objects:
        allowed = receiver_map.get(obj["id"], [])
        keys: set[str] = set()
        for receiver, window in allowed:
            for read in all_reads:
                if read["receiver"] != receiver:
                    continue
                if window and not (window[0] <= read["line"] <= window[1]):
                    continue
                keys.add(read["key"])
        for field in obj["fields"]:
            field["read_back"] = field["key"] in keys

    emitted_total = sum(len(o["fields"]) for o in objects) + len(run_pairs)
    read_back_total = sum(
        1 for o in objects for f in o["fields"] if f["read_back"]
    )

    guard_total = sum(len(c["guards"]) for c in consumers)

    # ---- terms taxonomy ---------------------------------------------------
    terms = []
    for call in append_term_calls(out):
        args = call["args"]
        # append_term(terms, term_id, component, analysis, sr_label, variant,
        #             loglike, safe_to_sum, exclusive_group, selected_in_default)
        if len(args) != 10:
            raise SystemExit(f"unexpected append_term arity at {OUTPUT_CPP}:{call['line']}")
        terms.append({
            "line": call["line"],
            "term_id": args[1],
            "component": args[2].strip('"'),
            "variant": args[5],
            "safe_to_sum": args[7],
            "exclusive_group": args[8],
            "selected_in_default": args[9],
        })

    # ---- gates ------------------------------------------------------------
    write_file_line = solo.find(r"output_config\.write_file\s*=")
    output_file_line = solo.find(r"output_config\.output_file\s*=")
    screen_line = solo.find(r"output_config\.screen_output\s*=")
    validate_line = solo.find(r"validate_output_config\(")
    batch_output_line = batch.find(r'settings_node\["output"\] =')
    batch_screen_line = batch.find(r'settings_node\["screen_output"\] =')
    batch_reject_line = batch.find(r"Batch mode does not support rivet-settings")

    # The two emit_outputs call sites decide which conditional keys can appear.
    call_lines = solo.find_all(r"SoloOutput::emit_outputs\($")
    if len(call_lines) != 2:
        raise SystemExit(f"expected 2 emit_outputs call sites in {SOLO_CPP}, found {len(call_lines)}")
    batch_call, single_call = sorted(call_lines)

    return {
        "generated_by": "scripts/build-json-output-page.py",
        "schema_version": schema_version,
        "schema_version_line": schema_line,
        "indent": int(indent_value),
        "indent_line": indent_line,
        "library": {
            "version": f"{lib_major}.{lib_minor}.{lib_patch}",
            "object_type_line": object_type_line,
            "path": JSON_HPP,
        },
        "sources": {
            "emitter": {"path": OUTPUT_CPP, "lines": out.count(), "emit_span": emit_span},
            "header": {"path": OUTPUT_HPP, "lines": hpp.count()},
            "batch": {"path": BATCH_CPP, "lines": batch.count()},
            "entrypoint": {"path": SOLO_CPP, "lines": solo.count()},
        },
        "root_fields": root_fields,
        "run_pairs": run_pairs,
        "objects": objects,
        "consumers": consumers,
        "terms": terms,
        "samples": run_samples(gambit_root),
        "totals": {
            "top_level_keys": len(root_fields),
            "emitted_fields": emitted_total,
            "read_back_fields": read_back_total,
            "merge_guards": guard_total,
        },
        "gates": {
            "write_file": {"line": write_file_line, "text": solo.line(write_file_line).strip()},
            "output_file": {"line": output_file_line, "text": solo.line(output_file_line).strip()},
            "screen_output": {"line": screen_line, "text": solo.line(screen_line).strip()},
            "validate": {"line": validate_line, "text": solo.line(validate_line).strip()},
            "batch_output": {"line": batch_output_line, "text": batch.line(batch_output_line).strip()},
            "batch_screen": {"line": batch_screen_line, "text": batch.line(batch_screen_line).strip()},
            "batch_reject": {"line": batch_reject_line, "text": batch.line(batch_reject_line).strip()},
        },
        "call_sites": {
            "batch": {"line": batch_call, "path": SOLO_CPP},
            "single": {"line": single_call, "path": SOLO_CPP},
        },
    }


# --------------------------------------------------------------------------
# curated per-key commentary
# --------------------------------------------------------------------------

KEY_NOTES = {
    "schema_version": {
        "role": "contract identifier",
        "gate": "always",
        "what": "A single string constant. Every consumer should branch on it before "
                "reading anything else, because it is the only field guaranteed to "
                "keep its meaning across future revisions.",
        "detail": "objects",
    },
    "run": {
        "role": "run-level facts",
        "gate": "always",
        "what": "Event count, whether Contur ran, and the set of likelihood variants "
                "that actually appear in this file. <code>enabled_variants</code> is "
                "assembled while the analyses are walked, so it is written last even "
                "though it lives under a key created first.",
        "detail": "objects",
    },
    "analyses": {
        "role": "the physics payload",
        "gate": "always",
        "what": "An object keyed by analysis name. Everything an analysis produced in "
                "this run &mdash; signal regions, the selected combination, cutflows, "
                "histograms and the SR covariance when one exists &mdash; hangs here.",
        "detail": "nesting",
    },
    "terms": {
        "role": "flat likelihood index",
        "gate": "always",
        "what": "A flat array over the same numbers already present under "
                "<code>analyses</code>, re-expressed so a fitter can consume them "
                "without walking the nested tree. Each entry carries the flags that "
                "say whether it may be summed and what it is mutually exclusive with.",
        "detail": "terms",
    },
    "summary": {
        "role": "headline numbers",
        "gate": "always",
        "what": "Analysis count and the combined log-likelihood, plus the Contur total "
                "when Contur ran. This is the block a human reads first.",
        "detail": "objects",
    },
    "sampling_advice": {
        "role": "MC budget guidance",
        "gate": "only when the batch path produced advice entries",
        "what": "Per analysis, for the selected signal region: current fractional "
                "uncertainty, and for each requested target how many more events each "
                "process needs. Absent entirely in a single-file run.",
        "detail": "objects",
    },
    "predefined_sets": {
        "role": "consumption recipe",
        "gate": "always",
        "what": "Named lists of <code>term_id</code>s. <code>default_total</code> is "
                "the one set the emitter guarantees is safe to sum &mdash; it holds the "
                "per-analysis combined terms, plus the Contur total when present.",
        "detail": "sets",
    },
    "contur": {
        "role": "measurement likelihoods",
        "gate": "only when Contur ran",
        "what": "Total Contur log-likelihood and a per-pool breakdown with the "
                "dominant measurement tag. Batch mode refuses Contur settings, so this "
                "key and <code>sampling_advice</code> never appear in the same file.",
        "detail": "objects",
    },
}

CONSUMER_NOTES = {
    "parse_sorted_sr_payloads": "Reads each signal region back and sorts by "
        "<code>sr_index</code>; refuses a file whose indices are not contiguous.",
    "parse_cutflows_or_empty": "Rebuilds <code>Cutflows</code> from the array, "
        "reconstructing cut names by dropping the synthetic <code>initial</code> row.",
    "parse_histograms_or_empty": "Rebuilds 1D and 2D histograms including "
        "<code>sumw2</code>, so the merged histogram carries a real statistical error "
        "rather than a re-derived one.",
    "initialize_accumulator": "Seeds the accumulator from the first file seen for "
        "an analysis: luminosity, background JSON path, SR labels and indices.",
    "validate_payload_consistency": "Every later file for the same analysis must "
        "agree with that seed &mdash; same SR count, same labels in the same order, same "
        "observed and background numbers, same luminosity, same background path.",
    "run_and_merge": "Drives the whole round trip: writes a YAML per job, forks a "
        "CBS child, reads the child's JSON back, and merges.",
}


# --------------------------------------------------------------------------
# svg helpers
# --------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def node_svg(x, y, w, h, cls, number=None, title="", subtitle="", kind="", href=None):
    parts = [f'<g class="node {cls}">']
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7"/>')
    text_x = x + 16
    if number is not None:
        cx, cy = x + 22, y + h / 2
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="13" fill="#fff" stroke="currentColor" stroke-width="1.3"/>'
        )
        parts.append(
            f'<text class="unit-number" x="{cx}" y="{cy + 4.5}" text-anchor="middle">{number}</text>'
        )
        text_x = x + 46
    baseline = y + (22 if subtitle else h / 2 + 4)
    if kind:
        parts.append(f'<text class="kind" x="{text_x}" y="{y + 15}">{esc(kind)}</text>')
        baseline = y + 32
    parts.append(f'<text class="title" x="{text_x}" y="{baseline}">{esc(title)}</text>')
    if subtitle:
        parts.append(f'<text class="body" x="{text_x}" y="{baseline + 16}">{esc(subtitle)}</text>')
    parts.append("</g>")
    body = "".join(parts)
    if href:
        return f'<a href="{esc(href)}">{body}</a>'
    return body


def elbow(x1, y1, x2, y2, cls="edge"):
    mid = x1 + (x2 - x1) / 2
    return f'<path class="{cls}" d="M{x1} {y1} H{mid} V{y2} H{x2}"/>'


def numbered_keys(data: dict) -> tuple[list[dict], list[dict]]:
    """Top-level keys split by gate, numbered in reading order.

    Numbering follows the diagram top to bottom rather than emission order.
    Emission order is not observable anyway -- the file itself is alphabetical
    -- so a number that matches what the reader sees is worth more than one
    that matches the order of assignments in the emitter.
    """
    always, conditional = [], []
    for field in data["root_fields"]:
        note = KEY_NOTES.get(field["key"])
        if note is None:
            raise SystemExit(f"no curated note for top-level key {field['key']!r}")
        entry = {"key": field["key"], "note": note, "line": field["line"], "expr": field["expr"]}
        (conditional if note["gate"] != "always" else always).append(entry)
    for number, entry in enumerate(always + conditional, start=1):
        entry["n"] = number
    return always, conditional


def shape_tree_svg(data: dict) -> str:
    always, conditional = numbered_keys(data)

    leaf_h, gap = 48, 10
    lane_x, leaf_x, leaf_w = 268, 508, 470
    top = 34
    rows = []
    y = top
    for group_label, entries in (("ALWAYS PRESENT", always), ("CONDITIONAL", conditional)):
        group_top = y
        for entry in entries:
            entry["y"] = y
            y += leaf_h + gap
        rows.append({
            "label": group_label,
            "entries": entries,
            "top": group_top,
            "bottom": y - gap,
        })
        y += 26

    height = y + 20
    width = 1160
    root_y = top + (height - top - 40) / 2 - 34

    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="shape-title shape-desc">',
        '<title id="shape-title">Top-level shape of the CBS JSON output</title>',
        f'<desc id="shape-desc">One root document with {len(data["root_fields"])} top-level keys, '
        f'{len(always)} always present and {len(conditional)} conditional.</desc>',
        '<defs><marker id="json-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]
    out.append(node_svg(
        20, root_y, 210, 68, "focal",
        kind="ROOT OBJECT",
        title="CBS_output.json",
        subtitle=data["schema_version"],
    ))

    for row in rows:
        centre = (row["top"] + row["bottom"]) / 2
        gy = centre - 24
        out.append(node_svg(
            lane_x, gy, 200, 48, "stage",
            title=row["label"].title(),
            subtitle=f'{len(row["entries"])} keys',
        ))
        out.append(elbow(230, root_y + 34, lane_x, gy + 24))
        for entry in row["entries"]:
            cls = "add" if row["label"] == "ALWAYS PRESENT" else "mod"
            out.append(node_svg(
                leaf_x, entry["y"], leaf_w, leaf_h, cls,
                number=entry["n"],
                title=entry["key"],
                subtitle=entry["note"].get("role", ""),
                href=f'#key-{entry["n"]}',
            ))
            out.append(elbow(lane_x + 200, gy + 24, leaf_x, entry["y"] + leaf_h / 2))

    out.append(
        f'<text class="legend-label" x="{leaf_x}" y="{height - 8}">'
        f'numbered nodes link to the matching detail card below</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def nesting_svg(data: dict) -> str:
    width, height = 1160, 430
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="nest-title nest-desc">',
        '<title id="nest-title">Nesting under a single analysis</title>',
        '<desc id="nest-desc">The analyses object is keyed by analysis name; each analysis '
        'holds scalar metadata, a combination block, signal regions keyed by label, cutflows, '
        'histograms and an optional covariance matrix.</desc>',
    ]
    out.append(f'<rect class="zone" x="16" y="20" width="{width - 32}" height="{height - 44}" rx="9"/>')
    out.append('<text class="zone-label" x="34" y="46">ANALYSES &#183; OBJECT KEYED BY ANALYSIS NAME</text>')
    out.append(f'<rect class="detail-zone" x="36" y="62" width="{width - 72}" height="{height - 100}" rx="8"/>')
    out.append('<text class="zone-label" x="54" y="88">"ATLAS_SUSY_2018_05" &#183; ONE ENTRY PER ANALYSIS</text>')

    cells = [
        ("scalars", "n_signal_regions, luminosity,\nbkgjson_path", "detail-data"),
        ("combination", "selected_sr_label / _index,\nnominal_loglike, alternatives", "detail-primary"),
        ("signal_regions", "keyed by sr_label:\nyields, errors, loglike, alt_loglikes", "detail-mod"),
        ("cutflows[]", "name + cuts[]:\ncount, two acceptances", "detail-primary"),
        ("histograms", "1d[] with bins[] and sumw2,\n2d[] with counts/errors matrices", "detail-primary"),
        ("covariance", "square matrix, present only when\nsrcov has rows and columns", "detail-optional"),
    ]
    cell_w, cell_h = 348, 108
    x0, y0 = 56, 104
    for index, (name, body, cls) in enumerate(cells):
        col, row = index % 3, index // 3
        x = x0 + col * (cell_w + 12)
        y = y0 + row * (cell_h + 14)
        out.append(f'<g class="node {cls}">')
        out.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="7"/>')
        out.append(f'<text class="title" x="{x + 16}" y="{y + 28}">{esc(name)}</text>')
        for line_index, text in enumerate(body.split("\n")):
            out.append(f'<text class="body" x="{x + 16}" y="{y + 52 + line_index * 15}">{esc(text)}</text>')
        out.append("</g>")

    out.append(
        f'<text class="legend-label" x="56" y="{height - 12}">'
        'dashed = conditional &#183; orange = also keyed by a runtime string</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def roundtrip_svg(data: dict) -> str:
    width, height = 1160, 300
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="rt-title rt-desc">',
        '<title id="rt-title">The same schema is the batch wire format</title>',
        '<desc id="rt-desc">In batch mode the parent writes one YAML per HepMC file, forks a CBS '
        'child that writes run_N.json, then reads those files back and merges them into a single '
        'output document.</desc>',
        '<defs><marker id="rt-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#4f5d75"/></marker></defs>',
    ]
    boxes = [
        (20, 110, 176, "PARENT", "build_run_jobs", "one job per HepMC file", "detail-primary"),
        (232, 110, 196, "CHILD YAML", "run_N.yaml", "output + screen_output forced", "detail-data"),
        (464, 110, 196, "CHILD PROCESS", "fork + exec CBS", "writes run_N.json", "detail-primary"),
        (696, 110, 196, "PARENT", "read_json_file", "parse + validate + merge", "detail-mod"),
        (928, 110, 212, "PARENT", "emit_outputs", "one merged document", "detail-focal"),
    ]
    for x, y, w, kind, title, subtitle, cls in boxes:
        out.append(node_svg(x, y, w, 72, cls, kind=kind, title=title, subtitle=subtitle))
    for index in range(len(boxes) - 1):
        x1 = boxes[index][0] + boxes[index][2]
        x2 = boxes[index + 1][0]
        out.append(f'<path class="detail-edge" d="M{x1} 146 H{x2 - 8}" marker-end="url(#rt-arrow)"/>')

    out.append('<path class="detail-edge optional" d="M562 110 V70 H562" marker-end="url(#rt-arrow)"/>')
    out.append('<text class="legend-label" x="392" y="62">the child never prints: screen_output is forced false</text>')
    out.append('<text class="legend-label" x="20" y="234">'
               'the per-file JSON is not a by-product &#8212; it is the only channel by which a child result reaches the parent</text>')
    out.append('<text class="legend-label" x="20" y="252">'
               'so every field the merge reads back is load-bearing: change it and batch mode breaks, not just a downstream plot</text>')
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# html fragments
# --------------------------------------------------------------------------

def json_skeleton(fields, indent=2, keyed_by=None) -> str:
    pad = " " * indent
    rows = ["{"]
    if keyed_by:
        rows.append(f'{pad}// key: {keyed_by}')
    for index, field in enumerate(fields):
        comma = "," if index < len(fields) - 1 else ""
        rows.append(f'{pad}"{field["key"]}": {field["expr"]}{comma}')
    rows.append("}")
    return esc("\n".join(rows))


def sample_block(data: dict, key: str) -> str:
    """The key as it comes out of a real run, or a note that it was absent."""
    samples = data.get("samples") or {}
    meta = samples.get("__meta__") or {}
    if not meta:
        return ""

    if key in samples:
        events = f'{meta["n_events"]:,}' if meta.get("n_events") else "a"
        body = samples[key]
        summary = f"example &#183; from a {events}-event run"
    else:
        body = (f"// absent from {meta['path']}\n"
                "// the gate on this key did not fire, so the emitter never wrote it")
        summary = "example &#183; absent from this run"

    return (f'<details class="unit-diff"><summary>{summary}</summary>'
            f'<pre class="unit-hunks">{esc(body)}</pre></details>')


def key_cards(data: dict) -> str:
    always, conditional = numbered_keys(data)
    cards = []
    for field in always + conditional:
        index = field["n"]
        key = field["key"]
        note = field["note"]
        gate = note["gate"]
        kind_cls = "extracted" if gate == "always" else "in-place"
        extra = ""
        if key == "run":
            rows = "".join(
                f'<tr><td><code>{esc(p["key"])}</code></td>'
                f'<td><code>{esc(p["expr"])}</code></td>'
                f'<td><code>{OUTPUT_CPP}:{p["line"]}</code></td></tr>'
                for p in data["run_pairs"]
            )
            extra = (
                '<div class="mapping-table" style="margin-top:12px"><table>'
                "<thead><tr><th>Field</th><th>Value expression</th><th>Emitted at</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )
        cards.append(f"""
        <article class="unit" id="key-{index}">
          <header class="unit-head">
            <span class="unit-num">{index}</span>
            <span class="unit-title">{esc(key)}</span>
            <span class="unit-kind {kind_cls}">{esc(gate)}</span>
            <span class="unit-delta">{OUTPUT_CPP}:{field["line"]}</span>
          </header>
          <dl class="unit-grid">
            <div><dt>role</dt><dd>{note["role"]}</dd></div>
            <div><dt>value</dt><dd><code>{esc(field["expr"])}</code></dd></div>
          </dl>
          <p class="diagram-note">{note["what"]}</p>
          {extra}
          {sample_block(data, key)}
        </article>""")
    return "\n".join(cards)


def object_tables(data: dict) -> str:
    blocks = []
    for obj in data["objects"]:
        rows = []
        for field in obj["fields"]:
            flag = (
                '<span class="status added-in-right">read back</span>'
                if field["read_back"] else '<span class="status unchanged">emit only</span>'
            )
            rows.append(
                f'<tr><td><code>{esc(field["key"])}</code></td>'
                f'<td><code>{esc(field["expr"])}</code></td>'
                f'<td>{flag}</td>'
                f'<td><code>{field["line"]}</code></td></tr>'
            )
        keyed = (
            f'<p class="diagram-note">Object keys come from <code>{esc(obj["keyed_by"])}</code> '
            "&mdash; they are run data, not part of the schema.</p>"
            if obj["keyed_by"] else ""
        )
        read_count = sum(1 for f in obj["fields"] if f["read_back"])
        blocks.append(f"""
        <article class="unit" id="obj-{esc(obj["id"])}">
          <header class="unit-head">
            <span class="unit-title"><code>{esc(obj["path"])}</code></span>
            <span class="unit-delta">{len(obj["fields"])} fields &#183; {read_count} read back by merge</span>
          </header>
          {keyed}
          <div class="mapping-table"><table>
            <thead><tr><th style="width:20%">Field</th><th style="width:46%">Value expression</th>
            <th style="width:14%">Merge</th><th style="width:8%">Line</th></tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table></div>
          <pre class="unit-code">{json_skeleton(obj["fields"], keyed_by=obj["keyed_by"])}</pre>
        </article>""")
    return "\n".join(blocks)


def terms_table(data: dict) -> str:
    rows = []
    for term in data["terms"]:
        rows.append(
            f'<tr><td><code>{esc(term["component"])}</code></td>'
            f'<td><code>{esc(term["term_id"])}</code></td>'
            f'<td><code>{esc(term["variant"])}</code></td>'
            f'<td><code>{esc(term["safe_to_sum"])}</code></td>'
            f'<td><code>{esc(term["exclusive_group"])}</code></td>'
            f'<td><code>{esc(term["selected_in_default"])}</code></td>'
            f'<td><code>{term["line"]}</code></td></tr>'
        )
    return "".join(rows)


def consumer_rows(data: dict) -> str:
    rows = []
    for consumer in data["consumers"]:
        note = CONSUMER_NOTES.get(consumer["name"], "")
        distinct = sorted({r["key"] for r in consumer["reads"]})
        keys = ", ".join(f"<code>{esc(k)}</code>" for k in distinct) or "&mdash;"
        rows.append(
            f'<tr><td><code>{esc(consumer["name"])}</code></td>'
            f'<td>{note}</td>'
            f'<td>{keys}</td>'
            f'<td><code>{consumer["span"][0]}&#8211;{consumer["span"][1]}</code></td></tr>'
        )
    return "".join(rows)


def guard_rows(data: dict) -> str:
    rows = []
    for consumer in data["consumers"]:
        for guard in consumer["guards"]:
            rows.append(
                f'<tr><td><code>{esc(consumer["name"])}</code></td>'
                f'<td>{esc(guard["message"])}</td>'
                f'<td><code>{guard["line"]}</code></td></tr>'
            )
    return "".join(rows)


def gate_rows(data: dict) -> str:
    labels = {
        "write_file": ("solo.cpp", "The file is written only when the YAML has an <code>output</code> key."),
        "output_file": ("solo.cpp", "Path default if the key is present but empty-valued."),
        "screen_output": ("solo.cpp", "Screen summary is independent of the file; both, either or neither."),
        "validate": ("solo.cpp", "Refuses a run that asks for a file without a usable path, before any events are read."),
        "batch_output": ("solo_batch.cpp", "Batch overrides the child's output path to a temp file &mdash; the user's <code>output</code> key is removed from the child YAML."),
        "batch_screen": ("solo_batch.cpp", "Batch forces the child silent so the parent owns all screen output."),
        "batch_reject": ("solo_batch.cpp", "Batch refuses Rivet/Contur settings outright rather than merging them wrongly."),
    }
    rows = []
    for key, gate in data["gates"].items():
        source, note = labels[key]
        rows.append(
            f'<tr><td><code>{esc(source)}:{gate["line"]}</code></td>'
            f'<td><code>{esc(gate["text"])}</code></td>'
            f'<td>{note}</td></tr>'
        )
    return "".join(rows)


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

def render_html(data: dict) -> str:
    template = TEMPLATE
    totals = data["totals"]
    replacements = {
        "__SCHEMA__": esc(data["schema_version"]),
        "__INDENT__": str(data["indent"]),
        "__LIB_VERSION__": esc(data["library"]["version"]),
        "__LIB_LINE__": str(data["library"]["object_type_line"]),
        "__EMITTER_LINES__": str(data["sources"]["emitter"]["lines"]),
        "__BATCH_LINES__": str(data["sources"]["batch"]["lines"]),
        "__TOP_LEVEL_KEYS__": str(totals["top_level_keys"]),
        "__EMITTED_FIELDS__": str(totals["emitted_fields"]),
        "__READ_BACK__": str(totals["read_back_fields"]),
        "__MERGE_GUARDS__": str(totals["merge_guards"]),
        "__SHAPE_TREE__": shape_tree_svg(data),
        "__NESTING__": nesting_svg(data),
        "__ROUNDTRIP__": roundtrip_svg(data),
        "__KEY_CARDS__": key_cards(data),
        "__OBJECT_TABLES__": object_tables(data),
        "__TERM_ROWS__": terms_table(data),
        "__CONSUMER_ROWS__": consumer_rows(data),
        "__GUARD_ROWS__": guard_rows(data),
        "__GATE_ROWS__": gate_rows(data),
        "__TERM_COUNT__": str(len(data["terms"])),
        "__CONSUMER_COUNT__": str(len(data["consumers"])),
        "__SCHEMA_LINE__": str(data["schema_version_line"]),
        "__BATCH_CALL__": str(data["call_sites"]["batch"]["line"]),
        "__SINGLE_CALL__": str(data["call_sites"]["single"]["line"]),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    if "__" in re.sub(r"__[a-z_]+__", "", template):
        pass
    return template


def render_markdown(data: dict) -> str:
    lines = [
        "# CBS JSON output contract",
        "",
        f"Schema: `{data['schema_version']}` (`{OUTPUT_CPP}:{data['schema_version_line']}`)",
        f"Writer: `{OUTPUT_CPP}` &middot; indent {data['indent']} &middot; "
        f"nlohmann::json {data['library']['version']}",
        "",
        "`private-SUSYRun2` has no JSON output at all, so this document describes the new",
        "contract only; there is no before/after to compare.",
        "",
        "## Top-level keys",
        "",
        "| # | Key | Gate | Emitted at |",
        "|---:|---|---|---|",
    ]
    for index, field in enumerate(data["root_fields"], start=1):
        note = KEY_NOTES[field["key"]]
        lines.append(f"| {index} | `{field['key']}` | {note['gate']} | `{OUTPUT_CPP}:{field['line']}` |")

    lines += [
        "",
        "## Object shapes",
        "",
        "| Path | Fields | Read back by batch merge |",
        "|---|---:|---:|",
    ]
    for obj in data["objects"]:
        read = sum(1 for f in obj["fields"] if f["read_back"])
        lines.append(f"| `{obj['path']}` | {len(obj['fields'])} | {read} |")

    lines += [
        "",
        "## Likelihood terms",
        "",
        "| Component | Variant | safe_to_sum | selected_in_default |",
        "|---|---|---|---|",
    ]
    for term in data["terms"]:
        lines.append(
            f"| `{term['component']}` | `{term['variant']}` | "
            f"`{term['safe_to_sum']}` | `{term['selected_in_default']}` |"
        )

    lines += [
        "",
        "## Batch round trip",
        "",
        "The same schema is the batch wire format: the parent forces the child's",
        f"`output` path (`{BATCH_CPP}:{data['gates']['batch_output']['line']}`) and silences its",
        f"screen output (`{BATCH_CPP}:{data['gates']['batch_screen']['line']}`), then reads the",
        "per-file documents back and merges them.",
        "",
        f"{data['totals']['read_back_fields']} of {data['totals']['emitted_fields']} emitted fields are",
        f"read back by the merge, guarded by {data['totals']['merge_guards']} explicit consistency checks.",
        "",
        "No CBS build or run was performed to produce this document.",
        "",
    ]
    return "\n".join(lines)


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CBS JSON output contract &#183; __SCHEMA__</title>
  <style>
    :root { --paper:#f5f5f5; --paper-2:#ececec; --ink:#2d3142; --muted:#4f5d75; --soft:#7a8399; --rule:rgba(45,49,66,.12); --accent:#eb6c36; --accent-tint:rgba(235,108,54,.08); --green:#4f8a69; --green-tint:#eef8f1; --red:#93513f; --red-tint:#f3e9e5; --font-sans:'Geist',system-ui,sans-serif; --font-mono:'Geist Mono',ui-monospace,monospace; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 var(--font-sans); }
    .frame { max-width:1520px; margin:0 auto; padding:42px 42px 64px; }
    .eyebrow,.kicker,.meta,.source,.status,th,footer,.tag { font-family:var(--font-mono); }
    .eyebrow { color:var(--muted); font-size:12px; letter-spacing:.16em; text-transform:uppercase; margin:0 0 12px; }
    h1 { font-family:'Instrument Serif',Georgia,serif; font-size:clamp(42px,5vw,72px); font-weight:400; letter-spacing:-.04em; line-height:.98; margin:0 0 14px; }
    h2 { font-size:28px; font-weight:600; letter-spacing:-.03em; line-height:1.08; margin:0 0 8px; }
    h3 { font-size:18px; margin:0 0 8px; }
    p { color:var(--muted); }
    .intro { max-width:1080px; font-size:17px; line-height:1.65; margin:0 0 18px; }
    .meta { display:flex; flex-wrap:wrap; gap:8px 18px; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); padding:12px 0; color:var(--muted); font-size:12px; }
    .meta strong { color:var(--accent); font-weight:600; }
    .note { border-left:3px solid var(--accent); color:var(--muted); font-size:13px; line-height:1.6; margin:18px 0; max-width:1160px; padding:8px 12px; }
    .backlink { align-items:baseline; background:#fff; border:1px solid var(--rule); border-left:3px solid var(--accent);
      border-radius:0 6px 6px 0; color:var(--muted); display:flex; flex-wrap:wrap; font-size:14.5px; gap:4px 12px;
      line-height:1.6; margin:18px 0 0; max-width:1160px; padding:11px 14px; }
    .backlink .lbl { color:var(--soft); font-family:var(--font-mono); font-size:11.5px; letter-spacing:.14em; text-transform:uppercase; }
    .backlink span:last-child { flex:1 1 420px; }
    .backlink a { border-bottom:1px solid rgba(235,108,54,.42); color:var(--accent); font-weight:600; text-decoration:none; }
    .backlink a:hover { background:var(--accent-tint); }
    .summary-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:22px 0 32px; }
    .card { background:#fff; border:1px solid var(--rule); border-radius:6px; padding:14px 16px; }
    .card.accent { border-color:rgba(235,108,54,.45); background:var(--accent-tint); }
    .card .n { color:var(--ink); display:block; font-size:28px; font-weight:600; letter-spacing:-.04em; line-height:1; margin-bottom:8px; }
    .card .label { color:var(--soft); font-family:var(--font-mono); font-size:11px; letter-spacing:.1em; text-transform:uppercase; }
    section { border-top:1px solid var(--rule); margin-top:28px; padding:24px 0 0; }
    .kicker { color:var(--soft); font-size:11px; letter-spacing:.16em; margin:0 0 8px; text-transform:uppercase; }
    .source { color:var(--soft); font-size:12px; line-height:1.55; margin:0 0 14px; }
    .diagram-shell { overflow-x:auto; background:#fff; border:1px solid var(--rule); border-radius:8px; padding:8px; }
    svg { display:block; min-width:1080px; width:100%; height:auto; }
    svg .zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .zone-label { fill:var(--soft); font:500 12px var(--font-mono); letter-spacing:1.6px; }
    svg .edge { fill:none; stroke:var(--muted); stroke-width:1.2; marker-end:url(#json-arrow); }
    svg .node rect { fill:#fff; stroke:var(--ink); stroke-width:1.2; }
    svg .node.stage rect { fill:rgba(79,93,117,.08); stroke:var(--soft); }
    svg .node.mod rect { fill:#fff0e8; stroke:#b55c2d; }
    svg .node.add rect { fill:var(--green-tint); stroke:var(--green); }
    svg .node.focal rect { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    svg .node .kind { fill:var(--soft); font:500 11px var(--font-mono); letter-spacing:1.2px; }
    svg .node .title { fill:var(--ink); font:600 15px var(--font-mono); }
    svg .node .body { fill:var(--muted); font:11.5px var(--font-mono); }
    svg .node.mod .kind { fill:#b55c2d; } svg .node.add .kind { fill:var(--green); } svg .node.focal .kind { fill:var(--accent); }
    svg .legend-label { fill:var(--soft); font:11px var(--font-mono); letter-spacing:.6px; }
    svg .node.add { color:#4f8a69; } svg .node.mod { color:#b55c2d; }
    svg .unit-number { fill:var(--ink); font:600 14px var(--font-mono); }
    svg a { cursor:pointer; }
    svg a:hover .title { text-decoration:underline; }
    svg .detail-zone { fill:rgba(45,49,66,.025); stroke:rgba(45,49,66,.13); stroke-width:1; }
    svg .detail-edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
    svg .detail-edge.optional { stroke-dasharray:5 4; }
    svg .node.detail-primary rect { fill:#fff; stroke:var(--soft); }
    svg .node.detail-data rect { fill:rgba(79,93,117,.08); stroke:var(--soft); }
    svg .node.detail-mod rect { fill:#fff0e8; stroke:#b55c2d; }
    svg .node.detail-optional rect { fill:#fff; stroke:var(--soft); stroke-dasharray:5 4; }
    svg .node.detail-focal rect { fill:var(--accent-tint); stroke:var(--accent); stroke-width:1.6; }
    .unit-list { display:grid; gap:14px; margin-top:18px; }
    .unit { border:1px solid var(--rule); border-radius:8px; background:#fff; padding:16px 18px; scroll-margin-top:20px; }
    .unit:target { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
    .unit-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
    .unit-num { display:grid; place-items:center; width:26px; height:26px; border-radius:50%;
      border:1.2px solid var(--ink); font:600 15px var(--font-mono); }
    .unit-title { font-size:18px; font-weight:600; letter-spacing:-.01em; }
    .unit-title code { font-size:16px; }
    .unit-kind { padding:2px 7px; border-radius:3px; border:1px solid currentColor;
      font:10px var(--font-mono); letter-spacing:.9px; text-transform:uppercase; }
    .unit-kind.extracted { color:#4f8a69; background:var(--green-tint); }
    .unit-kind.in-place { color:#b55c2d; background:#fff0e8; }
    .unit-delta { margin-left:auto; font:13px var(--font-mono); color:var(--soft); }
    .unit-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px 24px; margin:0; }
    .unit-grid > div { display:flex; gap:10px; border-bottom:1px solid var(--rule); padding-bottom:8px; }
    .unit-grid dt { flex:0 0 62px; margin:2px 0 0; color:var(--soft);
      font:11px var(--font-mono); letter-spacing:1px; text-transform:uppercase; }
    .unit-grid dd { margin:0; color:var(--muted); font-size:14.5px; line-height:1.6; }
    .unit-code { margin:13px 0 0; padding:13px 15px; border-radius:6px; overflow-x:auto;
      background:rgba(45,49,66,.04); border:1px solid var(--rule);
      font:13.5px/1.7 var(--font-mono); color:var(--ink); white-space:pre; }
    .diagram-note { color:var(--muted); font-size:14px; line-height:1.6; margin:13px 0 0; max-width:1160px; }
    .mapping-table { overflow-x:auto; border:1px solid var(--rule); }
    .mapping-table table { min-width:900px; }
    table { border-collapse:collapse; font-size:13px; width:100%; }
    th,td { border-bottom:1px solid var(--rule); padding:8px 9px; text-align:left; vertical-align:top; }
    th { background:#ececec; color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }
    td code { color:var(--ink); font-family:var(--font-mono); font-size:12px; word-break:break-word; }
    .status { font-size:11px; font-weight:600; letter-spacing:.04em; white-space:nowrap; }
    .status.added-in-right { color:var(--green); } .status.unchanged { color:var(--soft); }
    footer { border-top:1px solid var(--rule); color:var(--soft); font-size:12px; margin-top:32px; padding-top:14px; }
    @media (max-width:900px) { .frame { padding:30px 20px 48px; } .summary-grid { grid-template-columns:repeat(2,1fr); } .unit-grid { grid-template-columns:1fr; } }
    @media (max-width:560px) { h1 { font-size:44px; } }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
<main class="frame">
  <p class="eyebrow">ColliderBit Solo &#183; JSON output contract</p>
  <h1>__SCHEMA__</h1>
  <p class="intro">How a CBS run arranges its results on disk. This is a new-only description: <code>private-SUSYRun2</code> has no JSON output at all &mdash; no <code>Utils/include/gambit/Utils/json.hpp</code>, and zero occurrences of <code>json</code> in its <code>solo.cpp</code> &mdash; so there is no earlier layout to compare against. Every key, field and line number below is read out of the emitter at page-generation time.</p>
  <div class="meta"><span><strong>SCHEMA</strong> __SCHEMA__</span><span><strong>WRITER</strong> ColliderBit/examples/solo_output.cpp</span><span><strong>INDENT</strong> __INDENT__</span><span><strong>LIBRARY</strong> nlohmann::json __LIB_VERSION__</span><span><strong>STATIC EVIDENCE</strong> no build / no run</span></div>
  <p class="backlink"><span class="lbl">context</span><span>This page expands <a href="cbs-change-ledger.html#7">slide 6 of the CBS change-ledger deck &#8599;</a> &mdash; <em>Results became a data contract</em>. The deck says the contract exists; this page says what is actually in it.</span></p>
  <div class="summary-grid" aria-label="Schema summary">
    <div class="card accent"><span class="n">__TOP_LEVEL_KEYS__</span><span class="label">top-level keys</span></div>
    <div class="card"><span class="n">__EMITTED_FIELDS__</span><span class="label">emitted fields</span></div>
    <div class="card accent"><span class="n">__READ_BACK__</span><span class="label">read back by merge</span></div>
    <div class="card"><span class="n">__MERGE_GUARDS__</span><span class="label">merge guards</span></div>
    <div class="card"><span class="n">__TERM_COUNT__</span><span class="label">term kinds</span></div>
  </div>
  <div class="note">The value column throughout shows the <em>C++ expression</em> that fills the field, not a number from a run. Nothing on this page was produced by executing CBS: no build, no events, no output file. Field lists and line numbers are extracted from source; the prose around them is written.</div>

  <section>
    <p class="kicker">01 &#183; document shape</p>
    <h2>Eight top-level keys, two of them conditional</h2>
    <p class="source">One document per run. Six keys are always written; <code>sampling_advice</code> and <code>contur</code> appear only when their feature ran. Click a numbered node to jump to its card.</p>
    <div class="diagram-shell">
      __SHAPE_TREE__
    </div>
    <p class="diagram-note"><strong>The order above is emission order, not file order.</strong> <code>nlohmann::json</code> defaults to <code>std::map</code> for objects (<code>Utils/include/gambit/Utils/json.hpp:__LIB_LINE__</code>), so keys land in the file alphabetically: <code>analyses</code>, <code>contur</code>, <code>predefined_sets</code>, <code>run</code>, <code>sampling_advice</code>, <code>schema_version</code>, <code>summary</code>, <code>terms</code>. A consumer must never depend on key order &mdash; and a reviewer comparing two output files should not read a reordering as a change.</p>
  </section>

  <section>
    <p class="kicker">02 &#183; keyed detail</p>
    <h2>What each key carries</h2>
    <p class="source">One card per top-level key, in the order the emitter writes them.</p>
    <div class="unit-list">
      __KEY_CARDS__
    </div>
  </section>

  <section>
    <p class="kicker">03 &#183; the payload</p>
    <h2>Nesting under one analysis</h2>
    <p class="source">Two levels of the document are keyed by run data rather than by the schema: the analysis name, and the signal-region label. Everything below them has fixed field names.</p>
    <div class="diagram-shell">
      __NESTING__
    </div>
    <p class="diagram-note">Dynamic keys are convenient to read and awkward to validate &mdash; a schema checker cannot enumerate them, and a diff tool will report an added analysis as a wholesale subtree change. The flat <code>terms</code> array in section 04 exists partly to give consumers a fixed-shape alternative.</p>
  </section>

  <section>
    <p class="kicker">04 &#183; likelihood index</p>
    <h2>The same numbers, twice, on purpose</h2>
    <p class="source">Every log-likelihood already present in the nested tree is emitted a second time as a flat term. Each call site fixes the flags below; the emitter has __TERM_COUNT__ of them.</p>
    <div class="mapping-table"><table>
      <thead><tr><th>Component</th><th>term_id</th><th>Variant</th><th>safe_to_sum</th><th>exclusive_group</th><th>in default set</th><th>Line</th></tr></thead>
      <tbody>__TERM_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>The flags carry the arithmetic rules the numbers cannot.</strong> Signal-region terms are <code>safe_to_sum: false</code> because the SRs of one analysis overlap &mdash; summing them double-counts events. Only the per-analysis combined terms and the Contur total are <code>true</code>. Alternative variants of the same quantity share an <code>exclusive_group</code>: pick one per group, never add them. A consumer that ignores these flags and sums the <code>loglike</code> column will get a confident, wrong number, which is exactly why they are in the file rather than in a README.</p>
    <p class="diagram-note"><code>predefined_sets.default_total</code> is the ready-made answer: the list of <code>term_id</code>s the emitter guarantees is a valid sum. Start there, and treat everything else as opt-in.</p>
  </section>

  <section>
    <p class="kicker">05 &#183; second consumer</p>
    <h2>The file is also the wire format</h2>
    <p class="source">Batch mode does not merge in memory. The parent writes one YAML per HepMC file, forks a CBS child per job, and gets the result back only through this schema.</p>
    <div class="diagram-shell">
      __ROUNDTRIP__
    </div>
    <div class="mapping-table" style="margin-top:16px"><table>
      <thead><tr><th style="width:18%">Merge function</th><th style="width:34%">Role</th><th style="width:38%">Fields it reads</th><th style="width:10%">Lines</th></tr></thead>
      <tbody>__CONSUMER_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">__READ_BACK__ of the __EMITTED_FIELDS__ emitted fields are read back by these __CONSUMER_COUNT__ functions, matched on receiver <em>and</em> key so that a name shared by two objects &mdash; <code>name</code> on both a cutflow and a histogram, <code>analyses</code> at both the root and inside <code>sampling_advice</code> &mdash; is not credited to the wrong one. Renaming a read-back field breaks batch mode itself, not just a downstream plot script.</p>
    <p class="diagram-note"><strong>What the merge pointedly does not read is as informative as what it does.</strong> Every log-likelihood is emit-only: <code>loglike</code>, <code>alt_loglikes</code> and the whole <code>combination</code> block are ignored on the way back in. The merge combines <em>yields</em> and then recomputes the likelihood from the merged numbers, because averaging per-file log-likelihoods is not the same quantity and would be quietly wrong. The other unread fields &mdash; <code>nbins</code>, <code>integral</code>, <code>bin_index</code>, <code>x_low</code>, <code>x_high</code>, <code>error</code>, <code>sr_label</code> &mdash; are conveniences for a human or a plotting script, each recomputable from <code>edges</code>, <code>counts</code> and <code>sumw2</code>.</p>
  </section>

  <section>
    <p class="kicker">06 &#183; merge guards</p>
    <h2>What the merge refuses</h2>
    <p class="source">Rather than combining whatever it finds, the merge asserts that the per-file documents describe the same experiment. Each row is an explicit throw in the merge path.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:20%">Function</th><th>Message</th><th style="width:8%">Line</th></tr></thead>
      <tbody>__GUARD_ROWS__</tbody>
    </table></div>
    <p class="diagram-note">The combination arithmetic these guards protect: files of the <em>same</em> process are combined with event-count weights that sum to one, so the process keeps its full cross section; yields across <em>different</em> processes then add linearly, while their MC errors accumulate in quadrature.</p>
    <p class="diagram-note"><strong>One asymmetry worth knowing before reading a batch cutflow.</strong> Histograms are scaled by the process weight before being accumulated; cutflow counts are not &mdash; they are added raw. That is self-consistent for a cutflow read as "how many MC events survived each cut", but it means a batch cutflow table is <em>not</em> a luminosity-scaled yield and its rows do not correspond to the scaled numbers in <code>signal_regions</code>. Worth stating explicitly to anyone about to quote a cutflow from a multi-process run.</p>
  </section>

  <section>
    <p class="kicker">07 &#183; object shapes</p>
    <h2>Every field, with the expression behind it</h2>
    <p class="source">The complete extracted field list, one block per object shape in the document. "Read back" marks a field the batch merge parses.</p>
    <div class="unit-list">
      __OBJECT_TABLES__
    </div>
  </section>

  <section>
    <p class="kicker">08 &#183; gates</p>
    <h2>What makes the file appear</h2>
    <p class="source">Writing is opt-in and independent of the screen summary. Batch mode overrides both for its children.</p>
    <div class="mapping-table"><table>
      <thead><tr><th style="width:22%">Site</th><th style="width:38%">Source</th><th>Effect</th></tr></thead>
      <tbody>__GATE_ROWS__</tbody>
    </table></div>
    <p class="diagram-note"><strong>The two conditional keys can never appear in the same document.</strong> The entrypoint has exactly two <code>emit_outputs</code> call sites. The batch path (<code>solo.cpp:__BATCH_CALL__</code>) passes sampling advice but hard-codes <code>with_contur = false</code> and empty Contur maps; the single-file path (<code>solo.cpp:__SINGLE_CALL__</code>) passes real Contur results and no sampling advice at all. So <code>sampling_advice</code> implies a batch run, <code>contur</code> implies a single-file run, and a file carrying both would mean a third call site that does not exist today.</p>
    <p class="diagram-note"><strong>Boundary.</strong> This page describes what the emitter writes, established by reading <code>solo_output.cpp</code> (__EMITTER_LINES__ lines) and <code>solo_batch.cpp</code> (__BATCH_LINES__ lines). It is not a validation of the numbers: no CBS binary was built and no events were processed. Whether the values are physically correct is a separate exercise and is not claimed here.</p>
  </section>

  <p class="backlink"><span class="lbl">return</span><span>Back to <a href="cbs-change-ledger.html#7">the change-ledger deck &#183; slide 6 &#8599;</a>, or across to the <a href="cbs-solo-comparison.html#unit-4">entrypoint's output contract change &#8599;</a> that introduced this file.</span></p>

  <footer>Generated by <code>scripts/build-json-output-page.py</code> from <code>ColliderBit/examples/solo_output.cpp</code> and <code>solo_batch.cpp</code>. Schema constant at <code>solo_output.cpp:__SCHEMA_LINE__</code>.</footer>
</main>
</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gambit-root",
        type=Path,
        default=Path("/Users/p.zhu/Gambit-Workshop/gambit"),
        help="worktree that carries the CBS runner",
    )
    parser.add_argument("--html", type=Path, default=Path("dependences/cbs-json-output.html"))
    parser.add_argument("--json", type=Path, default=Path("dependences/cbs-json-output.json"))
    parser.add_argument("--markdown", type=Path, default=Path("dependences/CBS_JSON_OUTPUT.md"))
    parser.add_argument("--site-html", type=Path, default=Path("site/cbs-json-output.html"))
    args = parser.parse_args()

    root = args.gambit_root.expanduser().resolve()
    data = build_data(root)

    page = render_html(data)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(page)
    args.site_html.parent.mkdir(parents=True, exist_ok=True)
    args.site_html.write_text(page)
    args.json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(render_markdown(data))

    print(json.dumps(data["totals"], sort_keys=True))
    for path in (args.json, args.html, args.markdown, args.site_html):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
