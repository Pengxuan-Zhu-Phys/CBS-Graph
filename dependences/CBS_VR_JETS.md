# Variable-R jets in ColliderBit

Baseline `9c955e3a7` &rarr; head `65aca0890d`.

## Dependency

`fastjet::contrib::VariableRPlugin`, a FastJet *plugin* from fjcontrib. That is why
the build had to link `fastjetplugins`, `siscone` and `siscone_spherical` before any
of this could compile.

## Fixed-R vs variable-R, stage by stage

One loop over the collection list (`Py8EventConversions.hpp` L218-398). One test at L220 opens the VR branch; a `continue` at L301 closes it.

| Stage | Fixed-R | Variable-R | Verdict |
|---|---|---|---|
| settings read | L304 | L222 | differs |
| jet definition | L308 | L228 | differs |
| cluster sequence | L312 | L230 | same call |
| jet list / pT floor | L314 | L231 | differs |
| per-jet momentum | L321 | L235 | identical |
| b-tag match | L326 | L241 | differs |
| c-tag match | L336 | L251 | differs |
| tau-tag match | L347 | L261 | differs |
| W/Z/h match | L358 | L271 | identical |
| tau promoted to particle | L387 | absent | one-sided |
| tag map | L395 | L298 | differs |
| emit into event | L396 | L299 | identical |

Of 12 stages, 4 agree and 7 differ. Four of the differing rows are the flavour-tagging
radii, which differ because a VR jet has no single radius to match against.

The pre-existing fixed-R body is unchanged by this work: 336 tokens at the baseline, 336 now, 99.40% in common.
The only drift is on L308, a two-argument reorder from `bb641a5d1e` (a separate commit that fixed a deprecated FastJet
call signature). Tokens rather than lines, because a clang-format pass swept the file.

Both lanes end on a byte-identical `result.add_jet(new HEPUtils::Jet(pj, tags),
jetcollection.key)`: no new jet type, no separate container, nothing downstream can
tell which lane produced a jet.

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
