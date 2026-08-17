# Focused CBS source comparison

File: `ColliderBit/examples/solo.cpp`
Old: `ColliderBit_solo_development` (`65aca0890d`)
New: `SUSYRun2` (`5989e2d27a`)

- Lines: +139 / -291 (34 hunks)
- Functions: 1 changed of 2
- Changed includes: 10
- Changed source relations: 10
- Changed build relations: 0

Focused static source evidence for one file; comparison direction is SUSYRun2 (old) → ColliderBit_solo_development (new). The two flowcharts are grouped source paths, not a runtime trace or a complete C++ AST.

## Module total

The counts above are file-scoped and therefore cannot show an extraction refactor. Across the whole `ColliderBit/examples/solo*` family the change is **+153 / -2978** over 10 files, 0 of them new on `SUSYRun2`.

| File | Status | Added | Removed |
|---|---|---:|---:|
| `solo.cpp` | modified | +139 | -291 |
| `solo_batch.cpp` | removed | +0 | -1171 |
| `solo_batch.hpp` | removed | +0 | -85 |
| `solo_cli.cpp` | removed | +0 | -83 |
| `solo_cli.hpp` | removed | +0 | -43 |
| `solo_example.yaml` | modified | +14 | -24 |
| `solo_input.cpp` | removed | +0 | -458 |
| `solo_input.hpp` | removed | +0 | -56 |
| `solo_output.cpp` | removed | +0 | -689 |
| `solo_output.hpp` | removed | +0 | -78 |

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
| `inline summary aggregation` | `stringstream summary_line` | analysis → SR → observed/background/signal/loglike | `solo.cpp:386–427` |

## Functions

| Status | Function | Old | New | Diff |
|---|---|---:|---:|---:|
| unchanged | `apply_setting_if_present` | 61–69 | 48–56 | +0 / -0 |
| modified | `main` | 71–598 | 59–445 | +131 / -272 |
