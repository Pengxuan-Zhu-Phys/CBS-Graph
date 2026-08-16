# CBS-Graph

Static dependency and C++ call graphs for ColliderBit Solo (CBS).

This repository deliberately separates two graph layers:

1. **GAMBIT runtime dependency graph** — the authoritative graph emitted by GAMBIT's dependency resolver as `GAMBIT_active_functor_graph.gv`.
2. **Meta Glean C++ graph** — a source-level index of C++ declarations and declaration targets, useful for following the implementation behind the CBS functor chain.

Glean is not a replacement for the first graph: Glean describes source-level symbols and references, while GAMBIT knows which functor dependencies are active for a concrete run.

## Repository layout

```text
config/gambit.env.example       local path/ref configuration
queries/cxx-declaration-targets.angle
scripts/index-gambit.sh          create the Glean DB and export query results
scripts/build-site.py            render `.gv` and Glean results into `site/`
site/                            GitHub Pages artifact
.github/workflows/deploy-pages.yml
```

## Local setup

Glean's upstream build is tested on Linux. The upstream documentation currently recommends GHC/Cabal plus the C++ indexer package, and documents `cpp-cmake` indexing from a CMake compilation database. On macOS, use a small Ubuntu VM/CI runner for the Glean part; keep the GAMBIT checkout and its generated `compile_commands.json` on a filesystem visible to that environment.

Install the Glean CLI and C++ indexer in the Linux environment:

```bash
cabal install glean
cabal install glean-clang
```

For a source build, follow the upstream dependency list first. The Docker demo is not used here because the upstream Docker page currently marks that image as unavailable.

Copy the local configuration and edit it:

```bash
cp config/gambit.env.example config/gambit.env
${EDITOR:-vi} config/gambit.env
```

The important paths are:

```bash
GAMBIT_SOURCE_DIR=/absolute/path/to/gambit
GAMBIT_BUILD_DIR=/absolute/path/to/gambit/build
```

The GAMBIT build must have a compilation database. If it is missing, the helper will re-run CMake with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` against the existing build directory:

```bash
cmake -S "$GAMBIT_SOURCE_DIR" -B "$GAMBIT_BUILD_DIR" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

Then index and export the C++ declaration-target facts:

```bash
./scripts/index-gambit.sh config/gambit.env
```

That command writes only local, ignored files under `.glean/`. It does not upload source code or the Glean database.

## Produce the Pages artifact

Run CBS/GAMBIT in the configuration that should be shown to collaborators so that the runtime dependency graph is emitted. Then render both layers:

```bash
python3 scripts/build-site.py \
  --gambit-root "$GAMBIT_SOURCE_DIR" \
  --glean-json .glean/cxx-declaration-targets.json \
  --source-ref "$(git -C "$GAMBIT_SOURCE_DIR" rev-parse --short HEAD)"
```

The script looks for `GAMBIT_active_functor_graph.gv` below `scratch/run_time/` automatically. A specific graph can be supplied with `--graphviz-file`.

Open the generated site locally:

```bash
python3 -m http.server --directory site 8000
```

The generated `site/` directory is the only output intended for GitHub Pages. Review it before committing; it may contain source paths and symbol names.

## GitHub Pages

1. Push the repository to `Pengxuan-Zhu-Phys/CBS-Graph`.
2. In **Settings → Pages**, select **GitHub Actions** as the source.
3. Commit and push the reviewed `site/` artifact to `main`.
4. The workflow in `.github/workflows/deploy-pages.yml` publishes `site/`.

The workflow does not run Glean or rebuild GAMBIT on GitHub. This is intentional: the indexed database and the full GAMBIT build are local/CI inputs, while the public site remains a small reproducible presentation artifact.

## Scope and limitations

- The runtime `.gv` graph is the graph to use when explaining active GAMBIT functor dependencies for a run.
- The Glean graph is a static C++ declaration/reference view; it is not a runtime data-provenance graph.
- The first version renders SVG and a small JSON summary. It does not publish the Glean database itself.
- For a before/after comparison, run the pipeline twice with the same CBS input, keep the two `site/` asset sets under separate directories, and add a diff layer after the baseline graph is stable.

Upstream references: [Glean](https://github.com/facebookincubator/Glean), [C++ indexer](https://glean.software/docs/indexer/cxx/), [Glean CLI](https://glean.software/docs/cli/), and [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
