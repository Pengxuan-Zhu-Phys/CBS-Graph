# SKILL: Add a New LHC Analysis to ColliderBit

Follow these steps **in order**. Every step has a verification. An agent executing this
skill should not skip steps or invent values — anything taken from the experimental paper
(cuts, SR definitions, observed/background counts) must be traceable to the paper,
HEPData record, or auxiliary material.

Prerequisites: read [architecture/03-analysis-framework.md](../../architecture/03-analysis-framework.md)
once per session. Templates: [templates/](templates/). Final gate: [checklist.md](checklist.md).

---

## Step 0 — Gather inputs

Collect before writing code:

- [ ] Paper reference: arXiv ID, InspireID, ATLAS/CMS analysis code (e.g. `SUSY-2018-05`, `SUS-19-006`)
- [ ] √s (TeV), integrated luminosity (fb⁻¹), detector (ATLAS/CMS)
- [ ] Signal region definitions: object selections, overlap removal, all cuts, SR binning
- [ ] Observed event counts and background expectations (± error) per SR — usually from
      the paper's results table or HEPData
- [ ] Covariance matrix of backgrounds, if published (CMS simplified likelihood, HEPData)
- [ ] ATLAS full-likelihood pyhf JSON, if published (HEPData "Likelihood" resource)
- [ ] Cutflow tables from the paper/auxiliary material (for validation)
- [ ] Special reconstruction needs: large-R jets, VR jets, MT2, MET significance,
      RestFrames/RJR, BDT/ONNX models

**Naming**: `<EXPT>_<GROUP>_<YYYY>_<NN>` from the experiment's analysis code, e.g.
`ATLAS_SUSY_2018_05`, `CMS_SUS_19_006`, `ATLAS_EXOT_2019_04`, `ATLAS_CONF_2019_008`
(CONF notes use the CONF number). The class is `Analysis_<NAME>`, files
`Analysis_<NAME>.cpp/.info`.

## Step 1 — Pick a donor analysis

Do not start from a blank file. Query the catalogue for the closest existing analysis
(same final state, same techniques):

```bash
python3 - <<'EOF'
import json
d = json.load(open('P.Zhu/docs/analyses/catalogue.json'))
for e in d['analyses']:
    if 'MT2' in e['techniques']:        # adapt filter: detector, techniques, SR count...
        print(e['stem'], e['techniques'], e['n_signal_regions'])
EOF
```

Copy the donor `.cpp` and `.info` to the new names, or use
[templates/Analysis_TEMPLATE.cpp](templates/Analysis_TEMPLATE.cpp) for a clean start.
Good donors: `Analysis_ATLAS_SUSY_2018_05` (modern ATLAS EW, MET-significance, cutflows),
`Analysis_CMS_SUS_16_039` (multi-variant + covariance), `Analysis_ATLAS_EXOT_2019_04`
(large-R/VR jets, histogram-backed SRs), `Analysis_Minimum` (bare minimum).

## Step 2 — Write the constructor

```cpp
set_analysis_name("<NAME>");          // exactly the registered name, no Analysis_ prefix
set_luminosity(<L_fb>);
set_bkgjson("ColliderBit/data/analyses_json_files/<NAME>_bkgonly.json");  // only if pyhf JSON exists
DEFINE_SIGNAL_REGION("SR-A", "cut 1 description", "cut 2 description", ...)
// ... one per SR; or DEFINE_SIGNAL_REGIONS("SRbin", N, ...) for numbered bins
// histograms (optional):
// DEFINE_HISTOGRAM_1D_UNIFORM("met", 20, 0., 1000., "E_T^{miss} [GeV]")
// histogram-backed SR sets (optional, one SR per bin):
// DEFINE_HISTOGRAM_SR_1D("mll", edges, obs_vec, bkg_vec, bkgerr_vec, "m_{ll} [GeV]")
```

SR labels must match the paper's names where possible — they appear in output JSON and
in FullLikes channel mapping (for FullLikes the labels **must** match the pyhf channel
names, check the JSON).

## Step 3 — Implement `run(const HEPUtils::Event* event)`

Standard shape (follow the paper's object definitions section):

1. **Baseline objects**: loop `event->electrons()/muons()/taus()/photons()/jets("<collection>")`,
   apply pT/η cuts. Apply ID efficiencies via `applyEfficiency(vec, ATLAS::eff1DEl.at("..."))`
   or `CMS::...` maps, or the `BASELINE_*` macros.
2. **Overlap removal**: replicate the paper's ΔR-based removal order (copy from donor —
   `removeOverlap(...)` helpers in `Utils.hpp` / donor code).
3. **Signal objects**: tighter cuts, pT-sorted; b-tagging via `jet->btag()` plus the
   tagger efficiency map for the stated working point.
4. **Event variables**: `event->met()`, `event->missingmom()`, MT2 (`mt2_bisect.h`),
   MET significance (`METSignificance.hpp`), etc.
5. **Cutflow + SR filling**:

```cpp
BEGIN_PRESELECTION;
...
END_PRESELECTION;
if (cut1) { LOG_CUT("SR-A", "SR-B") } else return;
...
if (passes_SR_A) FILL_SIGNAL_REGION("SR-A");
FILL_HISTOGRAM_1D("met", met);
```

Rules:
- jets come from named collections — every collection used must exist in the run YAML;
  note which ones the analysis needs in the `.info` Summary or a code comment.
- no `static` mutable state (OpenMP; see [02-event-loop.md](../../architecture/02-event-loop.md)).
- use `event->weight()` only through the macros (they handle it).

## Step 4 — Implement `collect_results()`

```cpp
virtual void collect_results()
{
  COMMIT_SIGNAL_REGION("SR-A", <n_obs>, <n_bkg>, <n_bkg_err>)   // numbers from the paper
  ...
  // COMMIT_HISTOGRAM_SRS("mll")          // for histogram-backed SR sets
  // COMMIT_COVARIANCE_MATRIX({{...},{...}})  // row-major, SR order = commit order
  COMMIT_CUTFLOWS
  // COMMIT_HISTOGRAMS
}
```

The covariance matrix dimension and ordering must match the committed SR sequence exactly.

Also implement the boilerplate `analysis_specific_reset()` (reset `_counters`; donors show
the pattern) and end the file with `DEFINE_ANALYSIS_FACTORY(<NAME>)`.

**Variants** (inclusive/exclusive, per-channel): derive from the main class, override
`collect_results()` to commit a subset / different combination, give each variant
`DEFINE_ANALYSIS_FACTORY(<NAME>_<variant>)`. Donor: `Analysis_CMS_SUS_16_039.cpp`.

## Step 5 — Write the `.info` file

Copy [templates/Analysis_TEMPLATE.info](templates/Analysis_TEMPLATE.info); fill `Summary`,
`InspireID` (use `-1` if not yet in Inspire), `ExptRun` (`ATLAS-R2`, `CMS-R2`, ...),
`Lumi_ifb`, `Ecm_TeV`, and `Signatures` using the mini-language specified in
[ColliderBit/src/analyses/README.md](../../../../ColliderBit/src/analyses/README.md).

## Step 6 — Register

In [ColliderBit/src/analyses/AnalysisContainer.cpp](../../../../ColliderBit/src/analyses/AnalysisContainer.cpp),
add one `F(<NAME>)` line (and one per variant) to the correct list:

- plain C++ → `MAP_ANALYSES`
- needs ROOT → `MAP_ANALYSES_WITH_ROOT`
- needs ROOT + RestFrames → `MAP_ANALYSES_WITH_ROOT_RESTFRAMES`
- needs ONNXRuntime → `MAP_ANALYSES_WITH_ONNX`

Keep the trailing backslash continuation format of neighbouring lines.

## Step 7 — Build

```bash
cd build && make CBS -j8 2>&1 | tail -20
```

Must compile warning-clean (`-Wall -Wextra` are on). Common failures: missing trailing
backslash in the registration macro; SR label typos between `DEFINE_SIGNAL_REGION` /
`FILL_SIGNAL_REGION` / `COMMIT_SIGNAL_REGION` (label mismatch throws `std::out_of_range`
at **runtime**, not compile time — grep your labels for consistency).

## Step 8 — Smoke run

Create a minimal YAML (donor: `CBS_yaml/CBS_defaults.yaml`) selecting only the new
analysis, with a small HepMC file and all needed `jet_collections` declared:

```bash
./CBS my_test.yaml
```

Verify: analysis appears in output; SR table shows the paper's `n_obs`/`n_bkg`; with
`check_cutflow: true` the cutflow prints; loglike is finite.

## Step 9 — Validate against the paper

This is the physics gate — an implementation that compiles is not done:

1. Generate (or obtain) the benchmark signal sample the paper quotes cutflows for.
2. Run with `check_cutflow: true` and compare each cutflow line with the paper's
   (target: agreement within ~20–30% per line, better at early cuts; MC and smearing
   differences accumulate downstream).
3. Compare final SR yields against the paper's signal benchmarks.
4. Record the comparison in the PR / in `P.Zhu/docs/analyses/validation/<NAME>.md`.

## Step 10 — Refresh the catalogue and finish

```bash
python3 P.Zhu/docs/analyses/harvest_analyses.py
git diff --stat   # should show catalogue.{md,json} + your new/edited files
```

Then walk [checklist.md](checklist.md) before committing.
