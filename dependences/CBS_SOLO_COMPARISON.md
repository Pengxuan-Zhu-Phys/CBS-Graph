# Focused CBS source comparison

File: `ColliderBit/examples/solo.cpp`
Old: `SUSYRun2` (`5989e2d27a`)
New: `ColliderBit_solo_development` (`65aca0890d`)

- Lines: +291 / -139 (34 hunks)
- Functions: 1 changed of 2
- Changed includes: 10
- Changed source relations: 10
- Changed build relations: 0

Focused static source evidence for one file; comparison direction is SUSYRun2 (old) → ColliderBit_solo_development (new). The two flowcharts are grouped source paths, not a runtime trace or a complete C++ AST.

## Module total

The counts above are file-scoped and therefore cannot show an extraction refactor. Across the whole `ColliderBit/examples/solo*` family the change is **+2978 / -153** over 10 files, 8 of them new on `ColliderBit_solo_development`.

| File | Status | Added | Removed |
|---|---|---:|---:|
| `solo.cpp` | modified | +291 | -139 |
| `solo_batch.cpp` | added | +1171 | -0 |
| `solo_batch.hpp` | added | +85 | -0 |
| `solo_cli.cpp` | added | +83 | -0 |
| `solo_cli.hpp` | added | +43 | -0 |
| `solo_example.yaml` | modified | +24 | -14 |
| `solo_input.cpp` | added | +458 | -0 |
| `solo_input.hpp` | added | +56 | -0 |
| `solo_output.cpp` | added | +689 | -0 |
| `solo_output.hpp` | added | +78 | -0 |

## Logic flow

The generated HTML contains two grouped static flowcharts: the old main-owned SUSYRun2 path and the new helper-oriented ColliderBit_solo_development path.

| Concern | Old · SUSYRun2 owner | New · ColliderBit_solo_development owner | Observed change |
|---|---|---|---|
| CLI / help / argument errors | `main: argc check + argv[1]` | `SoloCLI::parse_command_line · solo_cli.cpp` | CLI ownership extracted |
| YAML, analyses, settings, event inputs | `main: YAML::LoadFile + Options(settings)` | `SoloInput::parse_and_prepare_input · solo_input.cpp` | input normalization extracted |
| multi-process / multi-file execution | `no batch branch; one settings.event_file` | `SoloBatch::run_and_merge + build_sampling_advice` | batch abstraction added |
| likelihood implementation choice | `calc_LHC_LogLikes_full is hard-wired` | `use_FullLikes selects calc_LHC_LogLikes(_full)` | upstream TODO implemented |
| cutflow / histogram policy | `CollectAnalyses.setOption(print_cutflows, true)` | `Cutflow::set_check_cutflow + Histogram1D::set_check_histogram` | runtime switches introduced |
| output contract | `summary_line + cout in main` | `OutputConfig + validate_output_config + emit_outputs` | structured screen/JSON output added |
| Rivet / Contur wiring | `main configures and prints pool details inline` | `main configures and output helper emits maps` | Rivet/Contur output extracted |

## SUSYRun2 (OLD) detail

The HTML page contains the full YAML/default table and dependency table. The reset chain is summarized here:

| Step | Container | Contents | Source |
|---|---|---|---|
| `operateLHCLoop.reset_and_calculate()` | `MCLoopInfo` | event loop state; event_count["CBS"] | `solo.cpp:372,385` |
| `CollectAnalyses.reset_and_calculate()` | `AnalysisDataPointers` | vector<AnalysisData*>; ATLAS + CMS + Identity | `solo.cpp:373; ColliderBit_eventloop.cpp:336` |
| `calc_LHC_LogLikes_full.reset_and_calculate()` | `map_str_AnalysisLogLikes` | AnalysisLogLikes per analysis / SR | `solo.cpp:374; LHC_likelihoods.cpp:1335` |
| `get_LHC_LogLike_per_analysis.reset_and_calculate()` | `map_str_dbl` | analysis → combination_loglike; alt keys appended | `solo.cpp:375; LHC_likelihoods.cpp:1386` |
| `calc_combined_LHC_LogLike.reset_and_calculate()` | `double` | combined ATLAS+CMS log-likelihood | `solo.cpp:376; LHC_likelihoods.cpp:1503` |
| `Contur_LHC_measurements_LogLike.reset_and_calculate()` | `double` | total Contur LLR | `solo.cpp:379,414; ColliderBit_measurements.cpp:454` |
| `Contur_LHC_measurements_LogLike_perPool.reset_and_calculate()` | `map_str_dbl` | pool → LLR | `solo.cpp:380,415; ColliderBit_measurements.cpp:495` |
| `Contur_LHC_measurements_histotags_perPool.reset_and_calculate()` | `map_str_str` | pool → dominant measurement tag | `solo.cpp:381,416; ColliderBit_measurements.cpp:533` |
| `inline summary aggregation` | `stringstream summary_line` | analysis → SR → observed/background/signal/loglike | `solo.cpp:384–431` |

## Functions

| Status | Function | Old | New | Diff |
|---|---|---:|---:|---:|
| unchanged | `apply_setting_if_present` | 48–56 | 61–69 | +0 / -0 |
| modified | `main` | 59–445 | 71–598 | +272 / -131 |
