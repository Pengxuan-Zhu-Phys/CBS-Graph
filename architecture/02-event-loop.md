# The ColliderBit Event Loop

Master function: `operateLHCLoop` in
[ColliderBit/src/ColliderBit_eventloop.cpp:101](../../../ColliderBit/src/ColliderBit_eventloop.cpp).
It is a GAMBIT *loop manager*: every per-event function (event reading, conversion,
smearing, analysis) is a *nested functor* executed via `Loop::executeIteration(i)`.

## Iteration protocol

Nested functors receive an iteration index. Non-negative indices are event numbers;
negative indices are control phases, defined in
[ColliderBit_eventloop_utils.hpp:50](../../../ColliderBit/include/gambit/ColliderBit/ColliderBit_eventloop_utils.hpp):

| Phase | Value | Runs | Typical work |
|---|---|---|---|
| `BASE_INIT` | -1 | once, serial | global setup before any collider |
| `COLLIDER_INIT` | -2 | per collider, serial | read per-collider options (analysis lists, nEvents) |
| `COLLIDER_INIT_OMP` | -3 | per collider, **in parallel region** | per-thread setup: open event file readers, create per-thread `AnalysisContainer`s, BuckFast instances |
| `XSEC_CALCULATION` | -4 | per collider, serial | obtain cross-section (for CBS: `getYAMLCrossSection` from the input file) |
| `START_SUBPROCESS` | -5 | per thread | per-thread (re)initialisation before event generation |
| *event iterations* | 1…N | OpenMP threads | read → convert → smear → analyze one event |
| `COLLECT_CONVERGENCE_DATA` | -6 | between event chunks | gather per-SR statistics across threads |
| `CHECK_CONVERGENCE` | -7 | between event chunks | decide whether enough events were generated |
| `END_SUBPROCESS` | -8 | per thread | per-thread teardown |
| `COLLIDER_FINALIZE` | -9 | per collider, serial | merge per-thread analysis results (`collect_and_add_signal`), scale by xsec |
| `BASE_FINALIZE` | -10 | once, serial | final cleanup |

The main event loop (`ColliderBit_eventloop.cpp:300`) is an `#pragma omp parallel` block;
each thread claims event indices under `#pragma omp critical`, so event order across
threads is nondeterministic but each event is processed exactly once. A
`std::domain_error` from an event iteration is caught, the event is discarded, and
counters are decremented.

## CBS specifics

`solo.cpp` configures the loop with a synthetic collider named `"CBS"`:

- `min_nEvents = 1000`, `max_nEvents = INT_MAX`, `run_convergence_checks = false` —
  CBS always processes **all events in the file(s)**; convergence-based early stopping
  is disabled by policy.
- The nested-functor list (in execution-relevant order):
  `getHepMCEvent → convertHepMCEvent_HEPUtils → getBuckFast{ATLAS,CMS,Identity} →
  getYAMLCrossSection → get{ATLAS,CMS,Identity}AnalysisContainer →
  smearEvent{ATLAS,CMS} / copyEvent → run{ATLAS,CMS,Identity}Analyses`
  (+ `Rivet_measurements`, `Contur_LHC_measurements_from_stream` when enabled).
- HepMC reading is serialised internally (file readers are not thread-safe); analysis
  execution is the parallel part.

## Per-thread analysis containers

`AnalysisContainer` ([src/analyses/AnalysisContainer.cpp](../../../ColliderBit/src/analyses/AnalysisContainer.cpp))
maintains a static `instances_map[base_key][thread_id]`. During `COLLIDER_INIT_OMP`
each OpenMP thread registers its own container holding fresh `Analysis` instances
(`mkAnalysis(name)` string factory). After the loop:

1. `collect_and_add_signal()` — thread 0's analyses absorb all other threads' results
   via `Analysis::add(other)` (event counters, cutflows, histograms are `+=`-combined).
2. `scale(xsec_per_event)` — converts raw MC counts to luminosity-scaled predictions
   (`n_sig_scaled = lumi × xsec_fb / N_events × n_sig_MC`, handled in `Analysis::scale`).
3. `CollectAnalyses` gathers `AnalysisData*` pointers from all containers into one
   `AnalysisDataPointers` vector for the likelihood stage.

**Consequence for analysis authors:** member variables of an `Analysis` are per-thread;
never use static mutable state. Anything that must survive to the results must live in
`_counters`, `_cutflows`, `_histograms`, or `_results` (all merged/scaled by the framework).

## Detector simulation

`getBuckFast{ATLAS,CMS,Identity}` create per-thread smearing engines
(`ColliderBit/src/getBuckFast.cpp`, `src/detectors/`); `smearEventATLAS/CMS` apply
electron/muon/photon/jet/MET smearing + tagging efficiencies to the converted
`HEPUtils::Event`; `copyEvent` is the no-smearing passthrough for the `Identity` detector.
Each analysis declares which flavour it needs via its
`static constexpr const char* detector` member ("ATLAS", "CMS", or "Identity");
`getDetector(name)` in `AnalysisContainer.cpp` routes the analysis into the right container.

## Jet clustering

Jets are built during HepMC→HEPUtils conversion
(`getHepMCEvent.cpp` / `Py8EventConversions.hpp` path), driven by the YAML
`jet_collections` map (FastJet algorithm, R, recombination scheme), an optional
`VRJet_collections` map (variable-R jets via fjcontrib), and `jet_collection_taus`
(which collection hadronic taus are associated to). Analyses fetch them with
`event->jets("antikt_R04")`, `event->jets("antikt_R10")`, `event->vrjets("<key>")`, etc.
Every collection an analysis uses **must be declared in the run YAML**, otherwise the
event converter throws.
