# Analysis Catalogue

Two generated artefacts describe every analysis in `ColliderBit/src/analyses/`:

- [catalogue.md](catalogue.md) — human-readable tables (ATLAS / CMS / Special), with
  detector, √s, luminosity, SR count, covariance & FullLikes flags, detected techniques,
  registered variants and InspireID.
- [catalogue.json](catalogue.json) — same data machine-readable, one entry per source
  file, including the class list, registration group, `.info` metadata and the list of
  *unregistered* factories (a factory defined in a `.cpp` but missing from
  `AnalysisContainer.cpp` — these are dormant bugs).

## Regenerating

```bash
python3 P.Zhu/docs/analyses/harvest_analyses.py
```

No dependencies beyond the standard library. The script:

1. parses the four `MAP_ANALYSES*` registration macros in `AnalysisContainer.cpp`;
2. scans each `Analysis_*.cpp` for classes, factories, detector, luminosity, SR
   definitions, covariance/FullLikes/cutflow/histogram usage, and technique fingerprints
   (MT2, RestFrames, ONNX, BDT, VR jets, large-R jets, MET significance, …);
3. merges the `.info` metadata;
4. cross-checks registration (orphan registrations are reported as warnings in the header).

Run it after **every** analysis addition, rename, or registration change; commit the
refreshed catalogue together with the code change.

## Useful queries (agents)

```python
import json
d = json.load(open('P.Zhu/docs/analyses/catalogue.json'))

# Analyses with covariance matrices
[e['stem'] for e in d['analyses'] if e['covariance']]

# Analyses supporting ATLAS FullLikes
[e['stem'] for e in d['analyses'] if e['fulllikes_bkgjson']]

# Unregistered factories (should normally be empty!)
[(e['stem'], e['unregistered_factories']) for e in d['analyses'] if e['unregistered_factories']]

# Donor candidates for a new large-R-jet analysis
[e['stem'] for e in d['analyses'] if 'Large-R jets' in e['techniques']]
```

## Known state (2026-06-21)

- `CMS_B2G_18_003` is live and registered in `MAP_ANALYSES`. Its low-mass resolved 3M
  tH/tZ regions use histogram-backed five-jet-mass SRs; 3T and 2M1L histograms are
  scaffolded but carry empty obs/bkg vectors until the remaining Fig. 4 rows are
  digitised. The high-mass merged regions are implemented as public cut-and-count
  approximations without the CMS shape fit.
- Several legacy `.info` files exist without a matching `.cpp` (Run-1 analyses whose code
  was retired); the harvester only reports files that have a `.cpp`.
