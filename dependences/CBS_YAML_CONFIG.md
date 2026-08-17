# The user YAML, before and after

Baseline `9c955e3a78` &rarr; head `65aca0890d`.

## Where the original settings went

| Setting | Original value | Who decides now |
|---|---|---|
| `debug` | `true` | program default |
| `seed` | `-1` | program default |
| `event_file` | `susy10.hepmc` | still yours |
| `cross_section_pb` | `1.0` | still yours |
| `cross_section_fractional_uncert` | `0.2` | still yours |
| `use_lognormal_distribution_for_1d_systematic` | `true` | program default |
| `events_between_convergence_checks` | `5000` | program default |
| `target_fractional_uncert` | `0.3` | conditional |
| `halt_when_systematic_dominated` | `true` | program default |
| `all_analyses_must_converge` | `false` | program default |
| `all_SR_must_converge` | `false` | program default |
| `covariance_marg_convthres_abs` | `0.05` | dead key |
| `covariance_marg_convthres_rel` | `0.05` | dead key |
| `covariance_nsamples_start` | `100000` | dead key |

3 still the user's, 7 now defaulted inside the program, 0 decided by CBS regardless of the YAML, 3 read by nothing at all.

## What CBS decides for you

| Key | Value | solo.cpp |
|---|---|---|
| `min_nEvents` | `(long long)(1000)` | 383 |
| `max_nEvents` | `(long long)(std::numeric_limits<int>::max())` | 384 |
| `run_convergence_checks` | `false` | 386 |

No build or run was performed for this document.
