# The Analysis Framework

Everything an analysis author touches lives in
`ColliderBit/include/gambit/ColliderBit/analyses/` and `ColliderBit/src/analyses/`.

## Class anatomy

Every analysis is one class in one `.cpp` file, inheriting from `Analysis`
([Analysis.hpp](../../../ColliderBit/include/gambit/ColliderBit/analyses/Analysis.hpp)):

```cpp
class Analysis_EXPT_YYYY_NN : public Analysis
{
public:
  static constexpr const char* detector = "ATLAS";   // or "CMS" / "Identity"

  Analysis_EXPT_YYYY_NN()
  {
    set_analysis_name("EXPT_YYYY_NN");
    set_luminosity(139.);                            // fb^-1
    set_bkgjson("ColliderBit/data/analyses_json_files/..._bkgonly.json"); // optional, FullLikes
    DEFINE_SIGNAL_REGION("SR1", "cut A", "cut B")    // counter + cutflow per SR
  }

  void run(const HEPUtils::Event* event)  { /* per-event selection */ }

  virtual void collect_results()
  {
    COMMIT_SIGNAL_REGION("SR1", n_obs, n_bkg, n_bkg_err)
    // optional: COMMIT_COVARIANCE_MATRIX(cov)  COMMIT_CUTFLOWS  COMMIT_HISTOGRAMS
  }

protected:
  void analysis_specific_reset()
  { for (auto& pair : _counters) pair.second.reset(); }
};

DEFINE_ANALYSIS_FACTORY(EXPT_YYYY_NN)   // creates create_Analysis_* + getDetector_*
```

Lifecycle (driven by the event loop, see [02-event-loop.md](02-event-loop.md)):
**ctor** (per thread) → `run(event)` × N events (parallel) → `add(other)` thread merge →
`scale(xsec_per_event)` → `collect_results()` → results consumed by likelihood code.
`reset()`/`analysis_specific_reset()` allow instance reuse between scan points.

### Base-class state available to subclasses

| Member | Type | Purpose |
|---|---|---|
| `_counters` | `map<str, EventCounter>` | weighted event counts per SR (`add_event(event)`) |
| `_cutflows` | `Cutflows` | named cut sequences with weighted pass counts |
| `_histograms` | `Histograms` | 1D/2D histograms (in-house, no YODA/ROOT) |
| `add_result(SignalRegionData)` | — | commit one SR result |
| `set_covariance(...)` | — | SR×SR background covariance (enables simplified-likelihood combination) |
| `set_bkgjson(path)` | — | path to ATLAS FullLikes background-only pyhf JSON |

`SignalRegionData` ([SignalRegionData.hpp](../../../ColliderBit/include/gambit/ColliderBit/analyses/SignalRegionData.hpp))
carries `sr_label, n_obs, n_sig_MC, n_sig_MC_sys, n_sig_MC_stat, n_sig_scaled, n_bkg, n_bkg_err`.
`AnalysisData` bundles all SRs of one analysis + optional covariance + lumi + bkgjson path.

## The macro language

[AnalysisMacros.hpp](../../../ColliderBit/include/gambit/ColliderBit/analyses/AnalysisMacros.hpp)
defines a small DSL so that analyses read declaratively. The important ones:

### Signal regions and cutflows

| Macro | Effect |
|---|---|
| `DEFINE_SIGNAL_REGION(name, "cut1", ...)` | creates `_counters[name]` + a cutflow `Preselection → cuts → Final` |
| `DEFINE_SIGNAL_REGIONS(base, N, ...)` | N numbered SRs `base1…baseN` |
| `*_NOCUTS` variants | same without named cut steps |
| `BEGIN_PRESELECTION` / `END_PRESELECTION` | fill cutflow init/preselection entries in `run()` |
| `LOG_CUT("SRa", "SRb", ...)` | record passing the *next* cut for the listed SRs (up to 10) |
| `LOG_CUTS(cuts, "SRa", ...)` / `LOG_CUT_N(base, N)` | bulk variants |
| `FILL_SIGNAL_REGION(name)` | event passed all cuts: fill cutflow final + `_counters[name].add_event(event)` |
| `COMMIT_SIGNAL_REGION(name, obs, bkg, bkg_err)` | in `collect_results()`: `add_result(SignalRegionData(...))` |
| `COMMIT_COVARIANCE_MATRIX(cov)` | `set_covariance(cov)` |
| `COMMIT_CUTFLOWS` | export `_cutflows` |

Cutflow filling is compiled in only with `-DCUTFLOW=ON` (`CHECK_CUTFLOW`) and switched at
runtime via the YAML key `check_cutflow` (static gate `Cutflow::set_check_cutflow`).

### Object selection

`BASELINE_PARTICLES/JETS/BJETS(src, name, [minPT, minEta, [maxPT, maxEta, [eff]]])` build
filtered vectors; `SIGNAL_*` variants additionally pT-sort. Efficiency maps live in
[ATLASEfficiencies.hpp](../../../ColliderBit/include/gambit/ColliderBit/ATLASEfficiencies.hpp) /
`CMSEfficiencies.hpp` (`ATLAS::eff1DEl`, `ATLAS::eff2DMu`, `applyEfficiency(...)`, `has_tag(...)`).
Many analyses use plain loops instead of these macros — both styles are accepted; match
the style of the paper you copy from.

### Histograms (in-house, YODA-free)

| Macro | Effect |
|---|---|
| `DEFINE_HISTOGRAM_1D(name, edges, [xlabel])` / `_1D_UNIFORM(name, n, lo, hi, ...)` | declare in ctor |
| `DEFINE_HISTOGRAM_SR_1D(name, edges, obs_vec, bkg_vec, bkgerr_vec, ...)` | **histogram-backed SRs**: one SR per bin |
| `DEFINE_HISTOGRAM_2D[_UNIFORM](...)` | 2D variants |
| `FILL_HISTOGRAM_1D(name, value)` / `_2D(name, x, y)` | fill in `run()` (no-op unless `check_histogram: true`) |
| `COMMIT_HISTOGRAMS` | export histograms to results/JSON |
| `COMMIT_HISTOGRAM_SRS(name)` | convert each bin of an SR-histogram into a `SignalRegionData` |

Design background: [P.Zhu/Histogram_SR_Design.md](../../Histogram_SR_Design.md) and
[P.Zhu/YODA_to_Histogram_Migration.md](../../YODA_to_Histogram_Migration.md).

## Registration (compile-time factory)

[AnalysisContainer.cpp:51](../../../ColliderBit/src/analyses/AnalysisContainer.cpp) holds
four X-macro lists; adding `F(MyAnalysis)` to one list generates the forward declaration,
the `mkAnalysis()` string-dispatch entry, and the `getDetector()` entry:

| List | Condition |
|---|---|
| `MAP_ANALYSES` | always compiled |
| `MAP_ANALYSES_WITH_ROOT` | only if ROOT enabled (`#ifndef EXCLUDE_ROOT`) |
| `MAP_ANALYSES_WITH_ROOT_RESTFRAMES` | ROOT + RestFrames |
| `MAP_ANALYSES_WITH_ONNX` | ONNXRuntime |

One `.cpp` may define several registered variants (e.g. an inclusive + binned version, or
per-channel subsets) as derived classes overriding `collect_results()`; each variant needs
its own `DEFINE_ANALYSIS_FACTORY(...)` and registry entry —
see `Analysis_CMS_SUS_16_039.cpp` or `Analysis_ATLAS_SUSY_2018_08.cpp` for the pattern.

## The `.info` metadata file

Each `Analysis_X.cpp` has a YAML sibling `Analysis_X.info`:

```yaml
Summary: <one-line description>
InspireID: 1750597          # -1 if not yet assigned
ExptRun: ATLAS-R2           # EXPT-R1/R2/R3
Lumi_ifb: 139.0
Ecm_TeV: 13.0
Signatures: ['=2L + OSSF + >=2J + MET + MT2']   # SR mini-language
Keywords: []
Authors: []
OldName: ATLAS_13TeV_...    # if renamed from the legacy naming scheme
```

The `Signatures` mini-language (object counts, MET/MT2 flags, etc.) is specified in
[ColliderBit/src/analyses/README.md](../../../ColliderBit/src/analyses/README.md) —
read that before inventing syntax.

## Special analyses

| Name | Purpose |
|---|---|
| `Analysis_Minimum` | smallest valid analysis; teaching template |
| `Analysis_Covariance` | demo of SR covariance |
| `Analysis_Dummy` | no-op placeholder |
| `Analysis_Baselines` | baseline-object validation/efficiency studies |

## Catalogue

The generated [analyses/catalogue.md](../analyses/catalogue.md) lists every source file
with detector, √s, lumi, SR count, covariance/FullLikes flags, techniques, and registered
variants. Refresh with `python3 P.Zhu/docs/analyses/harvest_analyses.py`.
