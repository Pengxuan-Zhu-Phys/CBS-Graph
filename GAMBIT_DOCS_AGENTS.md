# AGENTS.md — AI agent entry point for ColliderBit / CBS work

You are working in the **GAMBIT** repository on the `ColliderBit_solo_development` branch.
The maintainer is **Pengxuan Zhu**, the ColliderBit convener. Most tasks here concern
**ColliderBit Solo (CBS)** — a standalone LHC recast executable built from the ColliderBit module.

## 30-second orientation

- **CBS** = standalone binary (`./CBS <yaml>`) that reads HepMC events, runs fast detector
  smearing (BuckFast) + LHC analyses, and computes per-signal-region and combined log-likelihoods.
- CBS main program: [ColliderBit/examples/solo.cpp](../../ColliderBit/examples/solo.cpp)
  (+ `solo_input.cpp`, `solo_batch.cpp`, `solo_output.cpp` in the same directory).
- Analyses live in `ColliderBit/src/analyses/Analysis_<NAME>.cpp`, one class per file,
  each with a YAML metadata file `Analysis_<NAME>.info`.
- Every analysis must be **registered** in
  [ColliderBit/src/analyses/AnalysisContainer.cpp](../../ColliderBit/src/analyses/AnalysisContainer.cpp)
  via the `MAP_ANALYSES*` macros — registration is compile-time, there is no runtime plugin loading.
- Build: CMake; the CBS target is declared in [cmake/standalones.cmake](../../cmake/standalones.cmake).
  The maintainer performs all builds manually; agents must not invoke build commands.

## Task routing — read these before acting

| Task | Read first |
|---|---|
| Implement a new LHC analysis | [skills/add-new-analysis/SKILL.md](skills/add-new-analysis/SKILL.md) — follow it verbatim |
| Modify an existing analysis | [architecture/03-analysis-framework.md](architecture/03-analysis-framework.md) + the analysis source |
| Which analyses exist / their SR counts, lumi, techniques | [analyses/catalogue.md](analyses/catalogue.md) or `catalogue.json` |
| CBS YAML options | [architecture/05-yaml-config.md](architecture/05-yaml-config.md) |
| CBS JSON output format | [architecture/06-output-schema.md](architecture/06-output-schema.md) |
| Event loop / functor wiring / threading | [architecture/02-event-loop.md](architecture/02-event-loop.md) |
| Likelihood machinery (covariance, FullLikes, nulike) | [architecture/04-likelihoods.md](architecture/04-likelihoods.md) |
| Build/link performance on macOS | [build/macos-linking.md](build/macos-linking.md) |

## Hard rules

1. **Never edit generated files**: `ColliderBit/examples/functors_for_CBS.cpp`,
   `P.Zhu/docs/analyses/catalogue.{md,json}`.
2. **Registration is mandatory**: a new `Analysis_X.cpp` that is not added to a `MAP_ANALYSES*`
   macro in `AnalysisContainer.cpp` compiles fine but is invisible at runtime —
   `mkAnalysis()` will raise "not a known ColliderBit analysis".
3. **Choose the right registration group**: plain analyses → `MAP_ANALYSES`; needs ROOT →
   `MAP_ANALYSES_WITH_ROOT`; needs ROOT+RestFrames → `MAP_ANALYSES_WITH_ROOT_RESTFRAMES`;
   needs ONNXRuntime → `MAP_ANALYSES_WITH_ONNX`. Wrong group breaks builds configured
   without that dependency.
4. **Thread safety**: `run()` is called concurrently on per-thread `Analysis` instances inside
   an OpenMP loop. Do not introduce `static` mutable state or shared globals in analysis code.
   Cross-thread merging happens via `Analysis::add()` (`combine`/`+=` semantics).
5. **Observed/background numbers** in `collect_results()` come from the experimental paper /
   HEPData, never invented. If unknown at draft stage, mark them `TBD` loudly.
6. **`.info` file required** for every new analysis (same name stem as the `.cpp`).
7. **Never build GAMBIT or CBS after modifying project sources.** The maintainer compiles
   manually. Do not run `cmake --build`, `make`, `ninja`, CMake configure commands, or any
   other build command unless the maintainer explicitly overrides this rule. Source-level
   checks that do not build are allowed. If an analysis catalogue update is requested,
   re-run `python3 P.Zhu/docs/analyses/harvest_analyses.py` only.
8. macOS link flags: do **not** add `-Wl,-flat_namespace` anywhere; see
   [build/macos-linking.md](build/macos-linking.md) for why.

## Vocabulary

| Term | Meaning |
|---|---|
| **CBS** | ColliderBit Solo, the standalone recast executable |
| **SR** | Signal region — one counting bin of an analysis with (n_obs, n_bkg ± err) |
| **BuckFast** | GAMBIT's smearing-based fast detector simulation (ATLAS/CMS/Identity flavours) |
| **functor** | GAMBIT's wrapper around a module function; CBS wires them manually with `resolveDependency()` |
| **rollcall** | Header-macro system declaring module capabilities (`ColliderBit_rollcall.hpp`) |
| **FullLikes** | ATLAS pyhf-based full likelihood backend (needs `set_bkgjson(...)` in the analysis) |
| **nulike** | Backend providing marginalised Poisson likelihoods |
| **HEPUtils::Event** | The smeared event format analyses consume (electrons/muons/taus/photons/jets/met) |
| **.info file** | Per-analysis YAML metadata (lumi, √s, InspireID, SR signatures) |
| **Histogram-backed SRs** | `DEFINE_HISTOGRAM_SR_1D` bins that auto-convert to one SR per bin |
