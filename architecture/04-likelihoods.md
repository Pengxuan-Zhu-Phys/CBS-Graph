# Likelihood Machinery

Implementation: [ColliderBit/src/LHC_likelihoods.cpp](../../../ColliderBit/src/LHC_likelihoods.cpp).
Inputs: the merged, luminosity-scaled `AnalysisData` of each analysis (from `CollectAnalyses`).
Outputs: `map_str_AnalysisLogLikes` (per analysis) and a combined scalar loglike.

## Entry points

| Function | Line | Role |
|---|---|---|
| `calc_LHC_LogLikes` | `LHC_likelihoods.cpp:1373` | per-analysis loglikes, simplified-likelihood path |
| `calc_LHC_LogLikes_full` | `:1333` | same, but ATLAS FullLikes (pyhf) where a bkg JSON is registered |
| `get_LHC_LogLike_per_analysis` | `:1410` | flatten to `map<str,double>` |
| `calc_combined_LHC_LogLike` | `:1527` | sum over analyses (with `skip_analyses`, capping options) |

CBS selects `calc_LHC_LogLikes` vs `calc_LHC_LogLikes_full` via YAML `use_FullLikes`.

## Per-analysis logic

For each analysis the result is an `AnalysisLogLikes`
([AnalysisLogLikes.hpp:36](../../../ColliderBit/include/gambit/ColliderBit/analyses/AnalysisLogLikes.hpp)):
per-SR loglikes (`sr_loglikes`), the **combination** value (`combination_loglike`), the SR
chosen for it (`combination_sr_label/index`), and optional alternative variants
(`alt_*`: expected, no-error, scaled-signal — switched on by `calc_*_loglikes` YAML keys).

Decision tree per analysis:

1. **FullLikes path** (only in `calc_LHC_LogLikes_full`): if the analysis registered a
   background-only pyhf JSON (`set_bkgjson`) and `ATLAS_FullLikes` works, evaluate the full
   likelihood with all SRs (`fill_analysis_loglikes_full`, `:645`). The backend caches the
   loaded workspace per analysis name.
2. **Covariance path**: if the analysis provides an SR covariance matrix and
   `use_covariances: true` (default), build the simplified likelihood over all SRs with
   correlated background nuisances, then either
   - **profile** the nuisances (`profile_loglike_cov`, `:328`, multimin simplex), or
   - **marginalise** (`marg_loglike_cov`, `:453`, MC sampling; controlled by
     `use_marginalising`; convergence knobs `nuisance_marg_*`).
3. **No-covariance path**: each SR evaluated independently with nulike's 1D
   marginalised Poisson (`nulike_lnpin`, or lognormal `nulike_lnpiln` when
   `use_lognormal_distribution_for_1d_systematic: true`); the analysis loglike is taken
   from the SR with the **best expected sensitivity** (most constraining expected limit),
   *not* the best observed — unless `combine_SRs_without_covariances: true`, which sums
   SRs as if independent.

Nuisance-profiling knobs (`nuisance_prof_*`) and marginalisation knobs (`nuisance_marg_*`)
are forwarded from the CBS YAML by `apply_setting_if_present` in `solo.cpp`.

## Combined likelihood

`calc_combined_LHC_LogLike` sums the per-analysis combination loglikes, honouring:

- `skip_analyses: [name, ...]` — exclude from the sum (still reported individually)
- `cap_loglike_individual_analyses: true` — cap each analysis at 0 (no positive evidence)
- `cap_loglike: true` — cap the total at 0
- `alt_loglike: <variant>` — use an alternative variant for the combination (batch mode)

## Batch-mode merge

In multi-process batch mode (`solo_batch.cpp`), per-file JSON results are merged at SR
level **before** the likelihood is computed once on the merged `AnalysisData` via
`calc_LHC_LogLikes_common`. Merge rules:

- same process, several files → treated as statistical chunks of one sample
  (signal sums, MC stat errors combined via summed `sumw2`)
- different processes → independent contributions: `n_sig_scaled` summed, errors in quadrature
- cutflows and histograms are added bin-wise (histogram edges must match exactly)

## Statistical conventions

- `n_sig_MC_stat = sqrt(n_sig_MC)` (raw MC count), `n_sig_MC_sys` from the analysis
- `n_sig_scaled = scalefactor × n_sig_MC` where scalefactor = lumi × σ / N_MC
- SR fractional uncertainty used by sampling advice = `n_sig_scaled_err / n_sig_scaled`
  of the combination SR; advice allocates new events ∝ process cross-sections
  (`SoloBatch::build_sampling_advice`).
