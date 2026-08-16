# Variable-R jets in ColliderBit

Baseline `9c955e3a7` &rarr; head `65aca0890d`.

## Dependency

`fastjet::contrib::VariableRPlugin`, a FastJet *plugin* from fjcontrib. That is why
the build had to link `fastjetplugins`, `siscone` and `siscone_spherical` before any
of this could compile.

## Pipeline files

| File | Role | Lines |
|---|---|---|
| `Utils.hpp` | YAML schema, validation, VR key list | +95 / -5 |
| `Py8EventConversions.hpp` | clustering and flavour tagging | +192 / -82 |
| `Event.h` | named cluster-sequence storage | +5 / -5 |
| `BuckFast.hpp` | no-smear list | +6 / -0 |
| `BuckFast.cpp` | skips VR when smearing | +4 / -0 |
| `getBuckFast.cpp` | fills the no-smear list | +31 / -5 |
| `lhef2heputils.cpp` | declines VR at LHE level | +1 / -0 |
| **total** | 7 files | **+334 / -97** |

Plus 1337 lines across 3 new analyses.

## Numbered additions

1. **A jet collection became a named, typed thing** &mdash; `Utils.hpp`
2. **The YAML is validated, not trusted** &mdash; `Utils.hpp`
3. **Clustering through the fjcontrib plugin** &mdash; `Py8EventConversions.hpp`
4. **Flavour tagging by the jet's own radius** &mdash; `Py8EventConversions.hpp`
5. **The event stores cluster sequences by name** &mdash; `Event.h`
6. **VR collections opt out of detector smearing** &mdash; `BuckFast.cpp`
7. **Two readers decline VR outright** &mdash; `lhef2heputils.cpp`

## Where VR stops

Parton-level conversion and the LHEF reader skip VR collections outright; BuckFast
skips them for jet smearing and for the |eta| > 2.5 b-tag clearing pass.

`Analysis_ATLAS_SUSY_2018_07` does not use the pipeline: it constructs its own
`VariableRPlugin` with hard-coded rho/Rmin/Rmax, so YAML cannot reach it.

No build or run was performed for this document.
