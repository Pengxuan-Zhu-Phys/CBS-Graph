# FastJet and fjcontrib build integration

Refs: master `gambit/master` &middot; baseline `9c955e3a7` &middot; head `65aca0890d`

Three-way, because two-way hides that the development branch restores upstream
`master`'s fjcore path rather than inventing a new one.

| | master | SUSYRun2 | solo_development |
|---|---|---|---|
| FastJet | absent | downloaded + built | detected if present |
| fjcontrib | absent | built, 1 library | detected, 4 libraries |
| fjcore | always | commented out | always, namespace switched |

## Why fjcore is still here

Not because another module needs it. Counting every file that names a jet type
(`PseudoJet`, `ClusterSequence` or `FJNS`):

| Directory | Files |
|---|---:|
| `ColliderBit/` | 21 |
| `contrib/` | 9 |
| `cmake/` | 1 |

No GAMBIT module outside ColliderBit clusters jets at all. fjcore stays because
it is upstream `master`'s only jet backend, because it is the floor when FastJet
is not provisioned, and because it costs almost nothing to keep: `fjcore.hh:173` hard-codes `namespace gambit { namespace fjcore {`,
disjoint from `fastjet`, so both compile into one binary.

The remaining fjcore references are inside ColliderBit: 6 analyses carry an
`#ifndef FJCORE` branch, of which 1 is self-consistent. The other
5 mix `FJNS::` with literal `fastjet::` in one jet-trimming idiom.

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
