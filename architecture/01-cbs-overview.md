# CBS Overview

ColliderBit Solo (CBS) is a standalone LHC recast tool built from the GAMBIT ColliderBit
module. It reads Monte Carlo events in HepMC2/3 format, applies the BuckFast fast detector
simulation and compiled-in LHC analyses, and computes per-signal-region and combined
log-likelihoods — without requiring a full GAMBIT scan setup.

```
HepMC file(s) ──> getHepMCEvent ──> convertHepMCEvent_HEPUtils (FastJet clustering)
                                          │
                          BuckFast smearing (ATLAS / CMS / Identity)
                                          │
                          AnalysisContainer::analyze(event)   [OpenMP threads]
                                          │
                          CollectAnalyses ──> calc_LHC_LogLikes[_full]
                                          │
                          combined loglike ──> screen + JSON output
```

## Source layout

| Path | Role |
|---|---|
| `ColliderBit/examples/solo.cpp` | CBS `main()`: backend init, settings, manual functor wiring, run |
| `ColliderBit/examples/solo_input.{hpp,cpp}` | YAML parsing → `SoloInput::PreparedInput` (analyses, settings, processes, xsec) |
| `ColliderBit/examples/solo_batch.{hpp,cpp}` | Multi-process batch mode: per-file subprocess runs, SR-level merge, sampling advice |
| `ColliderBit/examples/solo_output.{hpp,cpp}` | Screen summary + schema-versioned JSON output |
| `ColliderBit/examples/functors_for_CBS.cpp` | **Generated** by `standalone_facilitator.py` — never edit |
| `ColliderBit/src/` | The ColliderBit module proper (event loop, detectors, likelihoods, analyses) |
| `ColliderBit/src/analyses/` | One `.cpp` + `.info` per analysis, plus `AnalysisContainer.cpp` (registry) |
| `ColliderBit/include/gambit/ColliderBit/analyses/` | `Analysis.hpp`, `AnalysisMacros.hpp`, `Cutflow.hpp`, `Histogram.hpp`, … |
| `ColliderBit/scripts/plot_cbs_histograms.py` | Plots histograms from CBS JSON output |
| `CBS_yaml/` | YAML templates and run configs |

## Execution modes

1. **Single-file mode** (`settings.event_file`): one HepMC file run in-process through the
   full functor chain.
2. **Batch / multi-process mode** (`settings.processes`): a list of named physics processes,
   each with its own cross-section and HepMC files. Each file runs as a CBS *subprocess*
   (same binary, generated per-file YAML); results are merged at signal-region level
   (same process → event-count-weighted; different processes → summed, errors in quadrature)
   and the merged `AnalysisData` is passed once through the likelihood machinery.
   Batch mode also emits **MC sampling advice** (how many more events to generate per process
   to reach target fractional uncertainties). Rivet/Contur are not supported in batch mode.

Mode selection is automatic from the YAML; the two keys are mutually exclusive.

3. **Optional Rivet+Contur**: with `rivet-settings` and `contur-settings` blocks (both
   required together), CBS additionally streams events through Rivet measurement analyses
   and computes Contur pool likelihoods.

## Backends used by CBS

| Backend | Required | Used for |
|---|---|---|
| nulike 1.0.9 | yes | marginalised Poisson likelihood (`nulike_lnpin` / `nulike_lnpiln`) |
| ATLAS_FullLikes 1.0 | only with `use_FullLikes: true` | pyhf full likelihoods (background JSON per analysis) |
| Rivet 4.1.0 + Contur 3.0.0 | optional | measurement-based constraints |

Version strings are `#define`d at the top of `solo.cpp`.

## Build

```bash
cmake --preset macos-clang-ccache    # or your own configure line
cd build && make CBS -j8
./CBS CBS_yaml/CBS_defaults.yaml
```

- The CBS target is declared in [cmake/standalones.cmake](../../../cmake/standalones.cmake);
  the heavy lifting (module object lists, functor generation) is in `add_standalone()` in
  [cmake/utilities.cmake](../../../cmake/utilities.cmake).
- A standalone links: its own sources + generated functors + **all object files** of each
  required module (`$<TARGET_OBJECTS:ColliderBit>`) + the common objects
  (Logs, Utils, Models, Backends, Elements, Printers).
- Compile-time options: `-DCUTFLOW=ON` enables cutflow bookkeeping (`CHECK_CUTFLOW`);
  runtime YAML keys `check_cutflow` / `check_histogram` then switch the features on per run.
- Excluding heavy dependencies (`WITH_ROOT=OFF`, `EXCLUDE_ONNXRUNTIME=ON`, no RestFrames)
  compiles out the corresponding analyses via the registration groups (see
  [03-analysis-framework.md](03-analysis-framework.md)).

## Design pattern: manual functor wiring

GAMBIT normally resolves module-function dependencies at runtime with its dependency
resolver. CBS replaces that with explicit calls in `solo.cpp`:

```cpp
convertEvent.resolveDependency(&getEvent);
calcLogLikes->resolveBackendReq(&nulike_lnpin);
getEvent.resolveLoopManager(&operateLHCLoop);
operateLHCLoop.setNestedList(nested_functions);
...
operateLHCLoop.reset_and_calculate();
```

When adding a new capability to the CBS pipeline you must wire it here (dependency,
loop manager, nested-function list) — there is no automatic resolution.

See [02-event-loop.md](02-event-loop.md) for the runtime sequence.
