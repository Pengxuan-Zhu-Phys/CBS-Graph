#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_file="${1:-$repo_root/config/gambit.env}"

if [[ ! -f "$config_file" ]]; then
  echo "Configuration file not found: $config_file" >&2
  echo "Copy config/gambit.env.example to config/gambit.env first." >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$config_file"

: "${GAMBIT_SOURCE_DIR:?Set GAMBIT_SOURCE_DIR in $config_file}"
: "${GAMBIT_BUILD_DIR:?Set GAMBIT_BUILD_DIR in $config_file}"

GLEAN_BIN="${GLEAN_BIN:-glean}"
GLEAN_DB_ROOT="${GLEAN_DB_ROOT:-$repo_root/.glean/db}"
GLEAN_DB_NAME="${GLEAN_DB_NAME:-cbs}"
GLEAN_DB_INSTANCE="${GLEAN_DB_INSTANCE:-0}"
GLEAN_JOBS="${GLEAN_JOBS:-4}"

if ! command -v "$GLEAN_BIN" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Glean was not found on PATH.

The open-source Glean build is tested on Linux. In a Linux environment install
the CLI and C++ indexer first, for example:

  cabal install glean
  cabal install glean-clang
EOF
  exit 127
fi

if [[ ! -d "$GAMBIT_SOURCE_DIR" ]]; then
  echo "GAMBIT_SOURCE_DIR is not a directory: $GAMBIT_SOURCE_DIR" >&2
  exit 2
fi

mkdir -p "$GLEAN_DB_ROOT" "$repo_root/.glean"

compile_commands="$GAMBIT_BUILD_DIR/compile_commands.json"
if [[ ! -f "$compile_commands" ]]; then
  echo "compile_commands.json is missing; reconfiguring the existing GAMBIT build..."
  cmake -S "$GAMBIT_SOURCE_DIR" -B "$GAMBIT_BUILD_DIR" \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
fi

if [[ ! -f "$compile_commands" ]]; then
  echo "CMake did not create $compile_commands" >&2
  exit 2
fi

db_ref="$GLEAN_DB_NAME/$GLEAN_DB_INSTANCE"
query_file="$repo_root/queries/cxx-declaration-targets.angle"
query_output="$repo_root/.glean/cxx-declaration-targets.json"

echo "Indexing $GAMBIT_SOURCE_DIR"
(
  cd "$GAMBIT_SOURCE_DIR"
  "$GLEAN_BIN" --db-root "$GLEAN_DB_ROOT" index cpp-cmake \
    --db "$db_ref" \
    --cdb-dir "$GAMBIT_BUILD_DIR" \
    . \
    -j"$GLEAN_JOBS"
)

echo "Exporting C++ declaration targets to $query_output"
"$GLEAN_BIN" --db-root "$GLEAN_DB_ROOT" query \
  --db "$db_ref" \
  --expand \
  --limit 100000 \
  --output "$query_output" \
  "@$query_file"

echo "Glean indexing complete."
echo "Next: python3 scripts/build-site.py --gambit-root '$GAMBIT_SOURCE_DIR' --glean-json '$query_output'"
