# FastJet and fjcontrib build integration

Refs: master `gambit/master` &middot; baseline `9c955e3a7` &middot; head `65aca0890d`

Three-way, because two-way hides that the development branch restores upstream
`master`'s fjcore path rather than inventing a new one.

| | master | SUSYRun2 | solo_development |
|---|---|---|---|
| FastJet | absent | downloaded + built | detected if present |
| fjcontrib | absent | built, 1 library | detected, 4 libraries |
| fjcore | always | commented out | always, namespace switched |

## Numbered changes

| # | Change | Target |
|---:|---|---|
| 1 | The gate | `cmake/contrib.cmake` |
| 2 | Download and build | `ExternalProject_Add(fastjet) / (fjcontrib)` |
| 3 | FastJet link surface | `fastjet_LDFLAGS` |
| 4 | fjcontrib link surface | `fjcontrib_LDFLAGS` |
| 5 | fjcore as fallback | `FJNS / FJCORE` |
| 6 | Nsubjettiness compiled in-tree | `add_gambit_library(fjcontrib_nsubjettiness)` |
| 7 | Contrib headers on the include path | `include_directories` |
| 8 | LDFLAGS as list elements | `quoting, across every contrib` |

## Link surfaces

FastJet before: `-lfastjet -lfastjettools`

FastJet after: `-lfastjettools -lfastjet -lfastjetplugins -lsiscone_spherical -lsiscone`

fjcontrib before: `-lRecursiveTools`

fjcontrib after: `-lfastjetcontribfragile -lRecursiveTools -lEnergyCorrelator -lVariableR`

## Provisioning

Tracked files: fastjet 0, fjcontrib 0, fjcore 7.

Neither FastJet nor fjcontrib is tracked, and CMake no longer downloads them.
On a fresh clone the probe fails, fjcore takes over silently and Rivet is ditched.

No build was run to produce this document.
