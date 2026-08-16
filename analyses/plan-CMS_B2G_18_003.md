# Plan & status — Analysis_CMS_B2G_18_003 (histogram-backed low-mass SRs)

_Last updated: 2026-06-22_

## Context

CMS search for EW vector-like T production, fully hadronic (arXiv:1909.04721, 35.9 fb⁻¹).
The analysis was previously dormant (`#if 0`, unregistered, no `.info`, did not compile under
`CHECK_CUTFLOW`, and its 50 per-bin low-mass SRs were defined-but-never-filled). This work
rebuilt the low-mass search on the histogram-backed SR system (`Histogram1D` +
`DEFINE_HISTOGRAM_SR_1D` / `COMMIT_HISTOGRAM_SRS`), so every five-jet-mass bin becomes a
`SignalRegionData` in the likelihood, and activated the analysis.

Locked decisions:
- **Overflow:** default *discard-overflow*. Last m5j bin ends at 1.3 TeV; events above are
  dropped (no clip, no class change). Acceptable because the low-mass search targets 0.6–1.2 TeV.
- **Scope:** scaffold all 6 low-mass regions (3T / 3M / 2M1L × tH / tZ); 3M filled with digitised
  data, 3T/2M1L wired with empty obs/bkg (commit no SRs until digitised).
- **Activation:** live now (removed `#if 0`, registered, `.info` added, README updated).
- **High-mass:** keep the 8 cut-and-count SRs (bug-fixed only); no T-mass shape fit.

## Done (verified)

- **Low-mass histogram SRs**: 6 `DEFINE_HISTOGRAM_SR_1D` on a shared 25-bin edge vector
  (300–1300 GeV, 40 GeV bins); 3M tH/tZ carry obs/bkg/bkg_err digitised from Fig. 4(c,d);
  3T/2M1L carry empty vectors. `run()` computes the five-jet (T-candidate) mass and
  `FILL_HISTOGRAM_1D`s the matching channel×category histogram; `collect_results()` does
  `COMMIT_HISTOGRAMS` + `COMMIT_HISTOGRAM_SRS` for all 6.
  → `ColliderBit/src/analyses/Analysis_CMS_B2G_18_003.cpp`
- **b-tag categories**: DeepCSV loose/medium/tight collections + mutually-exclusive 3T / 3M /
  2M1L classification; χ²/candidate/m5j reconstruction refactored into one
  `reconstruct_lowmass(bjets, nonbjets, HT)` helper (removes the old tH/tZ copy-paste).
- **Bug fixes** (were blocking / wrong in the dormant version): `CFHM` declared+registered+wired;
  ΔR(jj)/ΔR(b,W) copy-paste self-comparisons fixed in both channels; tZ rest-jet now uses the Z
  indices; scalar-pT-sum > 850 GeV cut now actually gates the high-mass path; removed the unused
  `mTcorr` block and the trailing `Bar0…Bar22` digitisation scratch.
- **reset() safety**: all SRs/histograms/cutflows booked in `book_regions()`, called from the
  constructor **and** `analysis_specific_reset()` — base `reset()` wipes `_histograms`/`_cutflows`,
  so re-booking is required (the EXOT_2019_04 pattern misses this).
- **Activation**: `F(CMS_B2G_18_003)` added to `MAP_ANALYSES` in `AnalysisContainer.cpp`;
  `Analysis_CMS_B2G_18_003.info` created; README "Known state" updated.
- **Build**: `make CBS` recompiles the TU and relinks cleanly (object newer than source; symbols
  `create_Analysis_CMS_B2G_18_003`, `book_regions`, `reconstruct_lowmass` present). The
  `-DCHECK_CUTFLOW` path syntax-checks clean (original blocker resolved).

## Remaining work

1. **b-tag WP non-nesting (correctness, from review — not yet applied).** The three DeepCSV
   `BASELINE_BJETS` draws are independent, so loose⊇medium⊇tight is not guaranteed; the category
   logic and the 2M1L bset assume nesting, biasing the (currently live) 3M yields. Suggested fix —
   enforce nesting after the draws:
   ```cpp
   for (auto j : deepcsv_tight)  if (!in(deepcsv_medium,j)) deepcsv_medium.push_back(j);
   for (auto j : deepcsv_medium) if (!in(deepcsv_loose,j))  deepcsv_loose.push_back(j);
   ```
   (Inherent ColliderBit limitation — high-mass `csvv2_*` has the same pattern — but the explicit
   threshold-nested categories make it worth fixing here.)
2. **3T / 2M1L per-bin obs/bkg/bkg_err**: digitise the 3T and 2M1L rows of Fig. 4 and fill the
   four empty vectors in `book_regions()`. Until then those histograms commit no SRs (safe); the
   filled distributions are still available for plotting.
3. **Refresh the catalogue**: `python3 P.Zhu/docs/analyses/harvest_analyses.py` — it still flags
   `CMS_B2G_18_003` as an unregistered factory (registration changed after the last harvest).
4. **Verify `InspireID: 1753679`** maps to arXiv:1909.04721 in the `.info`.
5. **Optional**: runtime `mkAnalysis("CMS_B2G_18_003")` smoke-test on a sample; a full build with
   `CHECK_CUTFLOW` actually enabled (only syntax-checked so far).

## Known approximations (by design, not bugs)

- High-mass is cut-and-count (no dijet-AK8 T-mass shape fit); subjet b-tags are AK4-proxy.
- Per-bin backgrounds treated as independent (no transfer-function correlation); `set_covariance`
  is available if a faithful covariance is added later.
- `.info` `Signatures`/`Notes`/`Authors` are not read by the harvester (only `Summary`,
  `InspireID`, `ExptRun`, `Lumi_ifb`, `Ecm_TeV`, `OldName`) — cosmetic only.
- Overflow > 1.3 TeV dropped while the digitised last bin includes it; negligible for ≤1.2 TeV.

## Files

- `ColliderBit/src/analyses/Analysis_CMS_B2G_18_003.cpp` — analysis
- `ColliderBit/src/analyses/AnalysisContainer.cpp` — `MAP_ANALYSES` registration
- `ColliderBit/src/analyses/Analysis_CMS_B2G_18_003.info` — metadata
- `P.Zhu/docs/analyses/README.md` — "Known state"
- `P.Zhu/docs/analyses/catalogue.{md,json}` — regenerated by the harvester
