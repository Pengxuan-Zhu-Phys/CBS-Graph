#!/usr/bin/env python3
"""Extract the three-way package/backend matrix behind deck slide 10.

Compares what each of three refs declares it depends on:

  gambit/master        the upstream GAMBIT the branch forked from
  private-SUSYRun2     the sibling branch (and its merge-base with us)
  HEAD                 ColliderBit_solo_development

Four independent sources are read, because they can disagree -- and on one
backend they do:

  cmake/backends.cmake                     the version that gets downloaded
  Backends/.../frontends/*.hpp             the version GAMBIT declares it speaks
  Backends/.../backend_types/<name>_<ver>  the BOSS-generated wrapper tree
  Backends/patches/<name>/<ver>/           the patch that must exist to build

Line counts come from `git diff --numstat -M`, split two ways so that work
inherited from SUSYRun2 is not reported as ours: a path with a non-zero delta
against master but a zero delta against the merge-base was done on SUSYRun2 and
carried over unchanged.

Nothing here is built or run.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

MASTER = "gambit/master"
SR2_TIP = "private-SUSYRun2"
BASE = "9c955e3a78"          # merge-base of HEAD and private-SUSYRun2
HEAD = "HEAD"

REFS = {"master": MASTER, "base": BASE, "sr2": SR2_TIP, "head": HEAD}

FRONTENDS = "Backends/include/gambit/Backends/frontends"
TYPES = "Backends/include/gambit/Backends/backend_types"
PATCHES = "Backends/patches"

# Paths grouped by the thing a reader would ask about.  Each is measured
# against master and against the merge-base, and the pair tells us who did it.
AREAS = {
    "Rivet BOSS wrappers": [f"{TYPES}/Rivet_4_1_0/", f"{TYPES}/Rivet_3_1_5/"],
    "Rivet frontend": [f"{FRONTENDS}/Rivet_4_1_0.hpp", f"{FRONTENDS}/Rivet_3_1_5.hpp"],
    "Contur frontend": [f"{FRONTENDS}/Contur_3_0_0.hpp", f"{FRONTENDS}/Contur_2_1_1.hpp"],
    "Pythia frontend + patch": [f"{FRONTENDS}/Pythia_8_312.hpp", f"{PATCHES}/pythia/"],
    "Pythia BOSS wrappers": [f"{TYPES}/Pythia_8_312/"],
    "ATLAS_FullLikes": [f"{FRONTENDS}/ATLAS_FullLikes_1_0.hpp", f"{PATCHES}/ATLAS_FullLikes/"],
    "BOSS scripts + config": ["Backends/scripts/BOSS/"],
    "cmake/backends.cmake": ["cmake/backends.cmake"],
    "cmake/contrib.cmake": ["cmake/contrib.cmake"],
    "cmake build wiring": ["cmake/utilities.cmake", "cmake/executables.cmake",
                           "cmake/standalones.cmake"],
    "config/*.yaml": ["config/"],
    "Utils (incl. json.hpp)": ["Utils/"],
    "DecayBit": ["DecayBit/"],
    ".gitignore": [".gitignore"],
}


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False)


def show(root: Path, ref: str, path: str) -> str | None:
    result = git(root, "show", f"{ref}:{path}")
    return result.stdout if result.returncode == 0 else None


def tree(root: Path, ref: str, path: str) -> list[str]:
    """Basenames directly under `path` at `ref`; empty if the path is absent."""
    result = git(root, "ls-tree", "--name-only", ref, path.rstrip("/") + "/")
    if result.returncode != 0:
        return []
    return sorted(Path(line).name for line in result.stdout.split() if line)


def declared_versions(root: Path, ref: str) -> dict[str, set[str]]:
    """(name, version) pairs from cmake/backends.cmake -- what gets downloaded."""
    src = show(root, ref, "cmake/backends.cmake") or ""
    out: dict[str, set[str]] = collections.defaultdict(set)
    name = None
    for line in src.splitlines():
        match = re.match(r'\s*set\(name\s+"([^"]+)"\)', line)
        if match:
            name = match.group(1)
            continue
        match = re.match(r'\s*set\(ver\s+"([^"]+)"\)', line)
        if match and name:
            out[name].add(match.group(1))
    return dict(out)


def frontend_versions(root: Path, ref: str) -> dict[str, set[str]]:
    """(name, version) pairs from the frontend header filenames."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for entry in tree(root, ref, FRONTENDS):
        match = re.match(r"(.+?)_(\d+(?:_\d+)*)\.hpp$", entry)
        if match:
            out[match.group(1)].add(match.group(2).replace("_", "."))
    return dict(out)


def numstat(root: Path, left: str, right: str, paths: list[str]) -> dict:
    result = git(root, "diff", "--numstat", "-M", left, right, "--", *paths)
    files = added = removed = 0
    for row in result.stdout.splitlines():
        parts = row.split("\t")
        if parts[0] == "-":          # binary
            files += 1
            continue
        added += int(parts[0])
        removed += int(parts[1])
        files += 1
    return {"files": files, "added": added, "removed": removed}


def contur_consistency(root: Path, ref: str) -> dict:
    """Cross-check the four places a backend version is written down.

    Contur is the one backend where they disagree at HEAD, so the check is
    reported rather than asserted: cmake, frontend, patch tree, and whether
    the patch file cmake names actually exists.
    """
    src = show(root, ref, "cmake/backends.cmake") or ""
    lines = src.splitlines()
    cmake_ver, patch_ref, line_no = None, None, None
    for index, line in enumerate(lines):
        if re.match(r'\s*set\(name\s+"contur"\)', line):
            for probe in lines[index:index + 20]:
                match = re.match(r'\s*set\(ver\s+"([^"]+)"\)', probe)
                if match and cmake_ver is None:
                    cmake_ver = match.group(1)
                    line_no = index + 2
                match = re.match(r'\s*set\(patch\s+"([^"]+)"\)', probe)
                if match and patch_ref is None:
                    patch_ref = match.group(1)
            break

    frontends = sorted(frontend_versions(root, ref).get("Contur", set()))
    patch_dirs = tree(root, ref, f"{PATCHES}/contur")

    resolved = None
    if patch_ref and cmake_ver:
        resolved = (patch_ref
                    .replace("${PROJECT_SOURCE_DIR}/", "")
                    .replace("${name}", "contur")
                    .replace("${ver}", cmake_ver))
    patch_exists = None
    if resolved:
        patch_exists = git(root, "cat-file", "-e", f"{ref}:{resolved}").returncode == 0

    # SUSYRun2 comments the patch line out on purpose ("Contur 3.0.0 shouldn't
    # need a patch"), so "no patch referenced" is a valid state, not a failure.
    patch_ok = patch_exists is not False

    return {
        "cmake_version": cmake_ver,
        "cmake_line": line_no,
        "frontend_versions": frontends,
        "patch_dirs": patch_dirs,
        "patch_referenced": resolved,
        "patch_exists": patch_exists,
        "patch_ok": patch_ok,
        "consistent": bool(frontends) and cmake_ver in frontends and patch_ok,
    }


def blame_line(root: Path, ref: str, path: str, line: int) -> str:
    result = git(root, "log", "--format=%h %s", "-1", f"-L{line},{line}:{path}", ref)
    head = result.stdout.splitlines()
    return head[0] if head else ""


def collect(root: Path) -> dict:
    resolved = {key: git(root, "rev-parse", "--short", ref).stdout.strip()
                for key, ref in REFS.items()}

    declared = {key: declared_versions(root, ref) for key, ref in REFS.items()}
    frontends = {key: frontend_versions(root, ref) for key, ref in REFS.items()}
    types = {key: tree(root, ref, TYPES) for key, ref in REFS.items()}

    # Backends whose declared version or frontend differs across any two refs.
    # cmake spells them lowercase and the frontend headers capitalise, so the
    # two sources are joined case-insensitively or every backend appears twice.
    def fold(mapping: dict[str, set[str]]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = collections.defaultdict(set)
        for key, values in mapping.items():
            out[key.lower()] |= values
        return out

    declared_l = {k: fold(v) for k, v in declared.items()}
    frontends_l = {k: fold(v) for k, v in frontends.items()}
    names = sorted(set().union(*[set(d) for d in declared_l.values()],
                               *[set(f) for f in frontends_l.values()]))
    moved = []
    for name in names:
        cmake_row = {k: sorted(declared_l[k].get(name, set())) for k in REFS}
        front_row = {k: sorted(frontends_l[k].get(name, set())) for k in REFS}
        if len({tuple(v) for v in cmake_row.values()}) == 1 and \
           len({tuple(v) for v in front_row.values()}) == 1:
            continue
        moved.append({
            "name": name,
            "cmake": cmake_row,
            "frontend": front_row,
            # True when cmake would download a version the frontend cannot use.
            "split": any(cmake_row[k] and front_row[k] and
                         set(cmake_row[k]).isdisjoint(front_row[k]) for k in REFS),
        })

    areas = {}
    for label, paths in AREAS.items():
        vs_master = numstat(root, MASTER, HEAD, paths)
        vs_base = numstat(root, BASE, HEAD, paths)
        if vs_master["files"] == 0 and vs_base["files"] == 0:
            origin = "untouched"
        elif vs_base["files"] == 0:
            origin = "inherited"        # SUSYRun2 did it, we kept it verbatim
        elif vs_master == vs_base:
            origin = "ours"             # master and the base agree; we changed it
        else:
            origin = "both"             # SUSYRun2 moved it and we moved it again
        areas[label] = {"vs_master": vs_master, "vs_base": vs_base, "origin": origin}

    contur = {key: contur_consistency(root, ref) for key, ref in REFS.items()}
    head_contur = contur["head"]
    if head_contur["cmake_line"]:
        head_contur["blame"] = blame_line(root, HEAD, "cmake/backends.cmake",
                                          head_contur["cmake_line"])

    json_hpp = show(root, HEAD, "Utils/include/gambit/Utils/json.hpp") or ""
    json_ver = re.search(r"version (\d+\.\d+\.\d+)", json_hpp[:2000])

    contrib = {key: tree(root, ref, "contrib") for key, ref in REFS.items()}
    config = {key: tree(root, ref, "config") for key, ref in REFS.items()}

    return {
        "generated_by": "scripts/build-package-matrix.py",
        "refs": resolved,
        "moved": moved,
        "backend_types": {k: sorted(set(types[k])) for k in REFS},
        "areas": areas,
        "contur_check": contur,
        "json_version": json_ver.group(1) if json_ver else None,
        "contrib_dirs": contrib,
        "config_files": config,
        "caveat": "Static read of four declaration sources. Nothing was built or run.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gambit-root", type=Path,
                        default=Path.home() / "Gambit-Workshop" / "gambit")
    parser.add_argument("--out", type=Path,
                        default=Path("dependences/cbs-package-matrix.json"))
    args = parser.parse_args()

    data = collect(args.gambit_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n")

    print(json.dumps({
        "refs": data["refs"],
        "moved": [m["name"] for m in data["moved"]],
        "contur_consistent_at_head": data["contur_check"]["head"]["consistent"],
        "inherited": [k for k, v in data["areas"].items() if v["origin"] == "inherited"],
        "ours": [k for k, v in data["areas"].items() if v["origin"] in ("ours", "both")],
    }, indent=2))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
