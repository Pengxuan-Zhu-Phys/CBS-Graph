# Focused CBS source comparison

File: `ColliderBit/examples/solo.cpp`
Baseline: `ColliderBit_solo_development` (`65aca0890`)
Comparison: `SUSYRun2` (`5989e2d27`)

- Lines: +139 / -291 (34 hunks)
- Functions: 1 changed of 2
- Changed includes: 10
- Changed source relations: 10
- Changed build relations: 0

Focused static source evidence for one file; the two flowcharts are grouped source paths, not a runtime trace or a complete C++ AST.

## Logic flow

The generated HTML contains two grouped static flowcharts: one for the helper-oriented baseline and one for the main-owned SUSYRun2 path.

| Concern | Baseline owner | SUSYRun2 owner | Observed change |
|---|---|---|---|
| CLI / help / argument errors | `SoloCLI::parse_command_line · solo_cli.cpp` | `main: argc check + argv[1]` | helper boundary removed |
| YAML, analyses, settings, event inputs | `SoloInput::parse_and_prepare_input · solo_input.cpp` | `main: YAML::LoadFile + Options(settings)` | input normalization moved inline |
| multi-process / multi-file execution | `SoloBatch::run_and_merge + build_sampling_advice` | `no batch branch; one settings.event_file` | batch abstraction removed |
| likelihood implementation choice | `use_FullLikes selects calc_LHC_LogLikes(_full)` | `calc_LHC_LogLikes_full is hard-wired` | runtime selector simplified |
| cutflow / histogram policy | `Cutflow::set_check_cutflow + Histogram1D::set_check_histogram` | `CollectAnalyses.setOption(print_cutflows, true)` | runtime switches simplified |
| output contract | `OutputConfig + validate_output_config + emit_outputs` | `summary_line + cout in main` | structured screen/JSON output removed |
| Rivet / Contur wiring | `main configures and output helper emits maps` | `main configures and prints pool details inline` | ownership remains inline; output path changed |

## Functions

| Status | Function | Baseline | Comparison | Diff |
|---|---|---:|---:|---:|
| unchanged | `apply_setting_if_present` | 61–69 | 48–56 | +0 / -0 |
| modified | `main` | 71–598 | 59–445 | +131 / -272 |
