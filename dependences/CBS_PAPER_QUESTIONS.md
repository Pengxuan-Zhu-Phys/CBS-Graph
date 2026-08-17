# Open questions for the CBS paper

Refs: `9c955e3a78` -> `65aca0890d`, master `gambit/master`.

The questions are editorial. Every figure beside them is read from the tree or from the other pages' generated JSON at build time.

## What the numbers depend on

Settings and modelling choices that move the yields. If the paper does not pin these down, two people running the same input file get two different likelihoods and neither is wrong.

### 1. Which check_histogram setting produced the published numbers?  _[changes published numbers]_

check_histogram defaults to false. Turned on, the 2 signal-region histogram analyses commit 23 additional signal regions that are simply absent otherwise. That is not a verbosity flag — it changes the number of likelihood terms in the output.

- read with getValueOrDef, default false — `solo.cpp:179`
- 2 of 3 histogram analyses run in signal-region mode, contributing 23 extra signal regions when the flag is on — `cbs-histograms.json · consumers`
- only 2 of 9 histogram macros guard themselves (FILL_HISTOGRAM_1D, FILL_HISTOGRAM_2D); the rest rely on the caller checking — `AnalysisMacros.hpp`

**If unanswered:** A reader who copies the example YAML gets fewer signal regions than the paper reports, with no warning and no error. The paper needs the setting stated next to the results, and ideally the flag’s value echoed into the output JSON.

### 2. Are variable-R jets smeared, and is that the intended physics?  _[changes published numbers]_

Variable-R collections are named into a no-smear list and skipped by the detector simulation, so VR jets carry no jet energy resolution smearing while every fixed-R collection does. The code says what happens; nothing says whether it is right.

- jetcollections_no_smear declared on the smearing object — `BuckFast.hpp:49`
- 2 continue sites drop those collections out of the smearing loop — `BuckFast.cpp:48, BuckFast.cpp:56`
- the list is filled from the VR settings at 3 wiring sites, so membership is automatic — a collection is excluded by being variable-R, not by anyone choosing to exclude it — `getBuckFast.cpp:85, getBuckFast.cpp:101, getBuckFast.cpp:113`
- 2 analyses consume VR jets and inherit the choice: ATLAS_EXOT_2019_04, ATLAS_EXOT_2019_07 — `ColliderBit/src/analyses/`

**If unanswered:** Either it is deliberate — because the experimental VR calibration is applied upstream and smearing twice would be wrong — in which case say so in one sentence and the objection dies. Or it is a gap, in which case it is an unquantified systematic on every analysis that uses VR jets (2 of them), and the paper is silent about it. Right now a referee cannot tell which.

### 3. Which of the twelve new analyses are validated, and against what?  _[changes published numbers]_

The deck says twelve analyses were added. It does not say which of them reproduce the published cutflows. 5 of 12 carry no Cutflow instrumentation at all, and 3 say in their own source comments that they are not finished.

- no cutflow instrumentation: ATLAS_EXOT_2016_013, ATLAS_EXOT_2018_60, ATLAS_EXOT_2019_04, ATLAS_EXOT_2021_35, CMS_SUS_16_039 — `ColliderBit/src/analyses/`
- ATLAS_EXOT_2018_60 — “TODO: Implement the published selection and signal-region yields.” — `Analysis_ATLAS_EXOT_2018_60.cpp:23`
- ATLAS_SUSY_2018_07 — “Not validated, still in progress” — `Analysis_ATLAS_SUSY_2018_07.cpp:41`
- CMS_B2G_18_003 — “vectors are still TODO (their histograms commit no SRs until the data are supplied, but” — `Analysis_CMS_B2G_18_003.cpp:20`
- ATLAS_EXOT_2018_60 is tracked as skeleton — run() carries a TODO; collect_results() is empty. Registered only. — `change ledger`
- CMS_B2G_18_003 is tracked as partial — 3M histogram SRs digitised; 3T/2M1L obs/bkg pending; high-mass is a cut-and-count approximation, not the CMS shape fit. — `change ledger`

**If unanswered:** A validation table is the single most-requested thing in a recast paper. Without one, every yield in the paper is taken on trust, and the two analyses already tracked as skeleton and partial will be read as finished.

## What a reader needs to rerun it

A reader with the repository and the paper should be able to reproduce a run. Each of these is something they would need and cannot currently get from either.

### 4. Where does a reader get the default settings?  _[blocks an independent rerun]_

The three-layer merge — global defaults, per-analysis card, user file — is the headline simplification of the new configuration. The defaults file at the bottom of it is not in the repository: the whole CBS_yaml/ directory is gitignored, and a missing defaults file is a silent fallback rather than an error.

- CBS_yaml/CBS_defaults.yaml exists in the worktree, 22 lines of settings, tracked: False — `cbs-yaml-config.json · defaults`
- CBS_yaml/* ignored — `.gitignore:50`
- absent defaults return silently rather than failing, so the run proceeds on whatever the compiled-in values happen to be — `solo_input.cpp`

**If unanswered:** Every number in the paper was produced under a set of defaults that ships with nobody. Either commit the file and cite it, or print the resolved settings into the output JSON so a run is self-describing. The second is cheaper and also fixes the previous question.

### 5. Which settings does CBS overrule, and which do nothing at all?  _[needs a paragraph]_

3 keys are overwritten in solo.cpp after the user file is read, so setting them in YAML has no effect. A further 3 keys are read by no source file at either ref. Both kinds look exactly like working settings in an example file.

- min_nEvents forced to (long long)(1000) — `solo.cpp:383`
- max_nEvents forced to (long long)(std::numeric_limits<int>::max()) — `solo.cpp:384`
- run_convergence_checks forced to false — CBS policy: always process all events provided by the user (no convergence-based early stop). — `solo.cpp:386`
- of the 14 keys in the original example file, only 3 are still genuinely the user’s to set — 7 are defaulted by the program, 1 is conditional, and 3 are read by nothing — `cbs-yaml-config.json · counts`

**If unanswered:** run_convergence_checks being forced to false makes the whole convergence block inert — a reader tuning those thresholds is tuning nothing. A configuration table in the paper that lists dead keys as options is worse than no table.

### 6. Which backend versions is the paper claiming?  _[needs a decision, not text]_

A software paper carries a version table. At HEAD the tree does not agree with itself about at least one entry: cmake and the frontend name different Contur versions, and the patch cmake points at does not exist.

- master: cmake says 2.1.1; patch patch_contur_2.1.1.dif present; self-consistent: yes — `cmake/backends.cmake:2236`
- base: cmake says 3.0.0; no patch line (deliberately absent); self-consistent: yes — `cmake/backends.cmake:2244`
- sr2: cmake says 3.0.0; no patch line (deliberately absent); self-consistent: yes — `cmake/backends.cmake:2244`
- head: cmake says 2.1.1; patch patch_contur_2.1.1.dif missing; self-consistent: no — `cmake/backends.cmake:2185`

**If unanswered:** HEAD is the only ref of the four that is internally inconsistent here. Fix it before the version table is written, or the table records a configuration that cannot be built.

## What existing users walk into

CBS is not a new tool for new users only. Anyone with a working GAMBIT ColliderBit setup has files that CBS will now reject, and the paper is where they will look first.

### 7. What happens to an existing user’s YAML?  _[needs a decision, not text]_

123 registered analysis names were retired. Any input file naming one of them now fails. The migration is documented in the source as per-file comments, which is the one place a user with a broken YAML will not look.

- 123 names retired, 132 introduced, 128 → 137 registered overall — `cbs-rename-migration.json`
- 80 renames documented across 75 git-detected file moves, including 18 consolidations absorbing 56 files — `per-file provenance comments`
- PX_SUSYRun2_stop.yaml in this tree still names 48 retired analyses — `yaml debt`

**If unanswered:** Decide whether CBS accepts old names with a deprecation warning or breaks cleanly. Either is defensible; silence is not. If it breaks, the paper needs the mapping as an appendix or a cited machine-readable file — not a comment in a .cpp.

## What downstream code may rely on

The JSON output is already being consumed by scripts. The paper decides whether that is a promise or an accident.

### 8. Is the output JSON a specified interface, or an implementation detail?  _[needs a decision, not text]_

The output carries schema_version (cbs-solo-loglike-v1), which is a promise. But the field layout is defined only by the code that writes it, and the term_id grammar — the thing every downstream consumer parses — is documented nowhere.

- 8 top-level keys, 16 nested object types — `cbs-json-output.json`
- <analysis>::<sr|combined>::<variant>, e.g. ATLAS_EXOT_2019_04::combined::nominal — `term_id grammar`
- 7 in-tree consumers already parse it, with their own guards for fields they expect — `reader-side guards`

**If unanswered:** If it is an interface, the paper should carry the schema and the grammar, and schema_version should have a documented bump policy. If it is not, say so, and downstream users know to pin a commit rather than trust the version string.

## How anyone gets it at all

Covered at length on slide 14. Restated here because a paper with no followable installation route is a paper nobody reproduces.

### 9. What installation route does the paper tell a reader to take?  _[needs a decision, not text]_

CBS declares one module and 2 dependencies (hepmc, pybind11). The build system in front of it declares 69 backends, and 29 of 71 download URLs (41%) point at a single host. Nothing tells a reader which of the two numbers applies to them.

- add_standalone(CBS … MODULES ColliderBit DEPENDENCIES hepmc pybind11) — `cmake/standalones.cmake:36`
- 69 backends declared; 29/71 downloads on hepforge.org — `cmake/backends.cmake`
- mitigation already exists and is undocumented: safe_dl.sh, copy_tarballs.sh, restore_tarballs.sh — `cmake/scripts/`
- GAMBIT_USE_LLD_FOR_CBS exists because linking CBS was worth an option — `cmake/standalones.cmake:38`

**If unanswered:** The cheapest fix is a paragraph: name the minimal dependency set, and point at the tarball-mirror scripts that are already in the tree. The real fix is a container or conda recipe, so that most readers never build at all.

## What the paper is even about

The one question that has to be answered first, because it silently sets the answer to several of the others.

### 10. What does “CBS” name, and against which baseline?  _[needs a decision, not text]_

This whole project is scoped to what changed on this branch, so it is baselined at the merge-base. A paper is scoped to what CBS is, which is the delta against released GAMBIT. Those are different sets, and the gap is not small: capabilities that predate the branch point are invisible here but are squarely part of what the paper describes.

- ONNX — master 0 files, merge-base 5, HEAD 5 — predates the branch point; absent from master — `ColliderBit tree`
- BDT — master 3 files, merge-base 15, HEAD 17 — grew on this branch — `ColliderBit tree`
- METSignificance — master 0 files, merge-base 5, HEAD 7 — predates the branch point; absent from master — `ColliderBit tree`
- FullLikes — master 10 files, merge-base 12, HEAD 15 — grew on this branch — `ColliderBit tree`
- 2 of 4 probed capabilities are absent from master entirely, and this deck mentions none of them — `scope gap`

**If unanswered:** Answer this first. It decides whether the paper’s change list starts at the merge-base (in which case ONNX and MET-significance belong to somebody else’s paper) or at master (in which case they are CBS features that are currently undocumented in every artefact here).

---

Static read of the worktree and of the other pages' JSON. Nothing was built or run. Generated by `scripts/build-paper-questions-page.py`.
