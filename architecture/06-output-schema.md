# CBS JSON Output Schema (`cbs-solo-loglike-v1`)

Emitter: [solo_output.cpp](../../../ColliderBit/examples/solo_output.cpp)
(`SoloOutput::emit_outputs`). Enabled by `settings.output: <path>`; the human-readable
screen summary is independent (`settings.screen_output`).

## Top-level structure

```jsonc
{
  "schema_version": "cbs-solo-loglike-v1",
  "run": { "n_events": ..., "with_contur": false, "enabled_variants": [...] },
  "analyses": {
    "<analysis_name>": {
      "n_signal_regions": ...,
      "luminosity": ...,
      "bkgjson_path": "...",            // when FullLikes JSON registered
      "covariance": [[...], ...],       // when provided by the analysis
      "combination": {
        "selected_sr_label": "...",
        "selected_sr_index": ...,
        "nominal_loglike": ...,
        "alternatives": { "<variant>": ... }
      },
      "signal_regions": {
        "<sr_label>": {
          "n_obs": ..., "n_bkg": ..., "n_bkg_err": ...,
          "n_sig_MC": ..., "n_sig_MC_stat": ..., "n_sig_MC_sys": ...,
          "n_sig_scaled": ..., "n_sig_scaled_err": ...,
          "loglike": ..., "alt_loglikes": { ... }
        }
      },
      "cutflows": [ ... ],              // when check_cutflow
      "histograms": { "1d": [...], "2d": [...] }   // when check_histogram
    }
  },
  "terms": [ ... ],                     // flat composable loglike terms
  "predefined_sets": { "default_total": ["<term_id>", ...] },
  "summary": { "n_analyses": ..., "combined_loglike": ... },
  "sampling_advice": { ... },           // batch mode only
  "contur": { ... }                     // when Contur active
}
```

## The `terms` array

Designed for downstream combination tools. Each term:

```jsonc
{
  "term_id": "...",
  "component": "analysis_combination" | ...,
  "variant": "nominal" | "expected" | ...,
  "exclusive_group": "...",      // sum at most one term per group
  "selected_in_default": true
}
```

`predefined_sets.default_total` lists the term ids whose sum reproduces
`summary.combined_loglike`.

## Histogram entries

```jsonc
{ "name": "m_HC", "x_label": "...", "edges": [...], "nbins": 30,
  "bins": [ {"bin_index": 0, "x_low": ..., "x_high": ..., "count": ..., "error": ..., "sumw2": ...} ],
  "underflow": ..., "overflow": ..., "underflow_error": ..., "overflow_error": ...,
  "integral": ... }
```

`count` is luminosity×σ-scaled; `sumw2` is kept so batch mode can merge histograms
losslessly across subprocess JSONs. SR-backed histograms additionally carry per-bin
`obs/bkg/bkg_err`.

## Sampling advice (batch mode)

Per analysis → selected SR → list of targets:

```jsonc
{ "analysis_name": "...", "sr_label": "...", "sr_index": ...,
  "n_sig_scaled": ..., "n_sig_scaled_err": ..., "fractional_uncert": ...,
  "effective_events": ...,
  "targets": [ { "target_fractional_uncert": 0.10, "need_more_mc": true,
                 "current_fractional_uncert": ..., "scale_factor": ...,
                 "current_total_events": ..., "recommended_total_events": ...,
                 "recommended_additional_events": ...,
                 "process_recommendations": [
                   { "process_name": "...", "cross_section_fb": ...,
                     "processed_events": ..., "recommended_additional_events": ... } ] } ] }
```

## Consumers

- [ColliderBit/scripts/plot_cbs_histograms.py](../../../ColliderBit/scripts/plot_cbs_histograms.py)
  — plots `histograms` blocks (`--list`, `--analysis`, `--outdir`).
- `solo_batch.cpp` — round-trips this schema when merging per-file subprocess results,
  so **schema changes must keep the batch parser in sync** (`parse_*` helpers there).

## Compatibility policy

Additions are backwards-compatible (new optional keys). Renames/removals require bumping
`schema_version` and updating: `solo_output.cpp`, the batch parser in `solo_batch.cpp`,
the plotting script, and this document.
