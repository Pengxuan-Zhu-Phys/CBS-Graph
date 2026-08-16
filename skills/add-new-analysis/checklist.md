# New-Analysis Review Checklist

Walk this before committing / opening a PR. Every box must be checkable or explicitly
waived with a reason.

## Files

- [ ] `ColliderBit/src/analyses/Analysis_<NAME>.cpp` exists, class named `Analysis_<NAME>`
- [ ] `ColliderBit/src/analyses/Analysis_<NAME>.info` exists with Summary, InspireID,
      ExptRun, Lumi_ifb, Ecm_TeV, Signatures
- [ ] `DEFINE_ANALYSIS_FACTORY(<NAME>)` present (one per variant)
- [ ] Registered in the correct `MAP_ANALYSES*` list in `AnalysisContainer.cpp`
- [ ] Author header block with name/date added to the `.cpp`

## Code correctness

- [ ] `set_analysis_name` matches the registered name exactly
- [ ] `set_luminosity` matches the paper
- [ ] `detector` static member is `"ATLAS"` / `"CMS"` (matches the experiment)
- [ ] Every SR label is identical across `DEFINE_SIGNAL_REGION`, `LOG_CUT`,
      `FILL_SIGNAL_REGION`, `COMMIT_SIGNAL_REGION` (grep each label)
- [ ] All committed `n_obs` / `n_bkg` / `n_bkg_err` traceable to the paper or HEPData
- [ ] Covariance (if any): square, dimension = number of committed SRs, order matches
- [ ] FullLikes JSON (if any): file present under `ColliderBit/data/analyses_json_files/`,
      SR labels match pyhf channel names
- [ ] No `static` mutable state in the analysis class; no globals
- [ ] `analysis_specific_reset()` resets all counters (and any custom state)
- [ ] Jet collections used (`event->jets("...")`, `event->vrjets("...")`) documented
- [ ] `|η|` cuts use `fabs`/`std::abs` on the *double* (no integer `abs` truncation —
      this exact bug existed in ATLAS_EXOT_2016_014)
- [ ] Comparison chains reviewed for `>` vs `>=` off-by-one against the paper

## Build & run

- [ ] `make CBS` compiles with no new warnings
- [ ] Smoke run with only the new analysis completes; SR table shows paper numbers
- [ ] `check_cutflow: true` produces a sensible cutflow (no empty Preselection)
- [ ] If ROOT/RestFrames/ONNX gated: build also tested (or reasoned) with the dependency
      excluded — analysis must silently disappear, not break the build

## Validation

- [ ] Cutflow comparison against the paper's benchmark documented
- [ ] Final-yield comparison against paper benchmark documented
- [ ] Validation note stored (PR description or `P.Zhu/docs/analyses/validation/<NAME>.md`)

## Bookkeeping

- [ ] `python3 P.Zhu/docs/analyses/harvest_analyses.py` re-run; catalogue diff committed
- [ ] If new YAML keys / schema fields were introduced: `P.Zhu/docs/architecture/05`/`06` updated
