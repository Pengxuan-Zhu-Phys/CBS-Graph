# The analysis naming migration

Baseline `9c955e3a78` &rarr; head `65aca0890d`.

## Two levels, two numbers

| Level | Count |
|---|---|
| Files git sees as renames | 75 |
| Files carrying a `// Renamed from:` block | 80 |
| &nbsp;&nbsp;of those, 1:1 | 62 |
| &nbsp;&nbsp;of those, consolidations | 18 (absorbing 56 old files) |
| Registered analysis names, baseline | 128 |
| Registered analysis names, head | 137 |
| **Retired names** | **123** |
| Introduced names | 132 |
| Survived | 5 (1 physics, 4 test/utility) |

The registered name is what a YAML selects by, so it is the number that
describes breakage: **123 names no longer resolve**.

## Scheme

Old: `<EXPERIMENT>_<beam energy>_<final state>_<luminosity>` -- what the analysis looked at.

New: `<EXPERIMENT>_<report type>_<year>_<number>` -- how the paper is cited.

| Report type | Count |
|---|---|
| `SUSY` | 41 |
| `SUS` | 27 |
| `CONF` | 6 |
| `B2G` | 2 |
| `EXO` | 2 |
| `unparsed` | 1 |
| `EXOT` | 1 |

## What did not move

- `ATLAS_8TeV_1LEPbb_20invfb` -- :D unrenamed, can not find original exp report
- 4 test/utility stubs (`Baselines`, `Covariance`, `Dummy`, `Minimum`)

## Outstanding

- `yaml_files/PX_SUSYRun2_stop.yaml` still names 48 analyses that no longer exist.

No build or run was performed for this document.
