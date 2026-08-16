# CBS YAML Configuration Reference

Authoritative parsing code: [solo_input.cpp](../../../ColliderBit/examples/solo_input.cpp)
(input modes, cross-sections) and [solo.cpp](../../../ColliderBit/examples/solo.cpp)
(all `settings.*` keys). Annotated template:
[CBS_yaml/CBS_complete_template.yaml](../../../CBS_yaml/CBS_complete_template.yaml).

```yaml
analyses:            # required: list of registered ColliderBit analysis names
  - ATLAS_SUSY_2018_05
settings:            # required: everything below lives here
  ...
rivet-settings:      # optional (must appear together with contur-settings)
  analyses: [...]
contur-settings: []  # optional list of contur CLI options
```

## Input modes (exactly one)

**Mode A — multi-process batch** (recommended for production):

```yaml
settings:
  processes:
    - name: EWino
      cross_section_fb: 1841.0
      cross_section_uncert_fb: 3.46
      files: [/path/a_01.hepmc, /path/a_02.hepmc]
    - name: slepton
      cross_section_pb: 0.07549
      cross_section_fractional_uncert: 0.0013
      files: [/path/b.hepmc]
```

**Mode B — single file** (legacy):

```yaml
settings:
  event_file: /path/to/sample.hepmc
  cross_section_fb: 10.0
  cross_section_uncert_fb: 1.0
```

Cross-sections accept four equivalent spellings:
`cross_section_fb + cross_section_uncert_fb`, `cross_section_fb + cross_section_fractional_uncert`,
`cross_section_pb + cross_section_uncert_pb`, `cross_section_pb + cross_section_fractional_uncert`.
Accepted file extensions: `.hepmc`, `.hepmc2`, `.hepmc3`. Event counts are read from the
files; CBS always processes **all** events (no convergence early-stop).

## General settings

| Key | Type | Default | Meaning |
|---|---|---|---|
| `debug` | bool | false | verbose output, per-step logging |
| `seed` | int | -1 | RNG seed (-1 = hardware entropy) |
| `suppress_fastjet_banner` | bool | false | silence FastJet banner |
| `screen_output` | bool | true | human-readable summary on stdout |
| `output` | str | (off) | JSON output path; presence enables file output |
| `check_cutflow` | bool | false | fill/print cutflows (binary must be built with `-DCUTFLOW=ON`) |
| `check_histogram` | bool | false | fill histograms + include in JSON |
| `jet_pt_min` | double | 10.0 | minimum jet pT (GeV) at clustering |
| `jet_collections` | map | **required** | FastJet definitions, see below |
| `jet_collection_taus` | str | `antikt_R04` | collection used for hadronic-tau association |
| `VRJet_collections` | map | (off) | variable-R jet definitions (only if an analysis needs `vrjets`) |

```yaml
  jet_collections:
    antikt_R04: {algorithm: antikt, R: 0.4, recombination_scheme: E_scheme, strategy: Best}
    antikt_R10: {algorithm: antikt, R: 1.0, recombination_scheme: E_scheme, strategy: Best}
  VRJet_collections:
    VRTrackJets: {rho: 30.0, Rmin: 0.02, Rmax: 0.40, pt_min: 5.0}
```

Declare **every** collection the selected analyses request via `event->jets("<name>")` /
`event->vrjets("<name>")`, or the run aborts.

## Likelihood settings

| Key | Default | Meaning |
|---|---|---|
| `use_FullLikes` | false | use ATLAS pyhf full likelihoods where available |
| `use_lognormal_distribution_for_1d_systematic` | false | nulike lognormal instead of Gaussian systematic |
| `use_covariances` | true | use SR covariance (simplified likelihood) when provided |
| `use_marginalising` | false | marginalise instead of profile nuisances |
| `combine_SRs_without_covariances` | false | sum SRs as independent when no covariance |
| `nuisance_prof_initstep/convtol/maxsteps/convacc/simplexsize/method` | 0.1/0.01/10000/0.01/1e-5/6 | profiler controls |
| `nuisance_marg_convthres_abs/rel`, `nuisance_marg_nsamples_start`, `nuisance_marg_nulike1sr` | 0.05/0.05/1e6/true | marginaliser controls |
| `calc_noerr_loglikes`, `calc_expected_loglikes`, `calc_expected_noerr_loglikes`, `calc_scaledsignal_loglikes` | false | emit alternative loglike variants |
| `signal_scalefactor` | 1.0 | scale factor for the scaled-signal variant |

## Combination / batch settings

| Key | Default | Meaning |
|---|---|---|
| `target_fractional_uncert` | 0.30 | headline target for sampling advice |
| `sampling_advice_targets` | [target, 0.10, 0.05] | full list of advice targets |
| `keep_batch_tmp` | false | keep per-file tmp YAML/JSON from batch runs |
| `alt_loglike` | "" | use an alternative variant in the combined loglike |
| `skip_analyses` | [] | exclude analyses from the combined loglike |
| `cap_loglike_individual_analyses` | false | cap each analysis loglike at 0 |
| `cap_loglike` | false | cap the combined loglike at 0 |

## Rivet / Contur (single-file mode only)

```yaml
rivet-settings:
  analyses: [ATLAS_2019_I1725190]
  exclude_analyses: []
  drop_YODA_file: true
contur-settings: []        # contur CLI options as strings
```

Both blocks must be present together; batch mode rejects them.

## Environment variables

| Variable | Effect |
|---|---|
| `CBS_SUPPRESS_BANNER=1` | suppress CBS startup banner (used for subprocess runs) |
| `GAMBIT_SUPPRESS_BANNER=1` | suppress the GAMBIT banner |
