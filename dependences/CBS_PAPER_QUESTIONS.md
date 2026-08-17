# Open questions for the CBS paper

Refs: `9c955e3a78` -> `65aca0890d`, master `gambit/master`.

The questions are editorial. Every figure beside them is read from the tree or from the other pages' generated JSON at build time.

## What the paper is

Not a code question, and the only one that cannot be settled by editing a file. Everything below inherits its answer from here: the results worth showing, the tools worth comparing against, and how much GAMBIT a reader is assumed to already know.

### 1. What is the paper claiming CBS is?  _[decides what the paper is]_

The whole tree says this about CBS’s purpose, once, in a file header: “ColliderBit Solo: an event-based LHC recast tool using the GAMBIT ColliderBit module”. That is a description, not a claim. At least four papers could be written from the same branch, and they do not share results, comparisons, or readers: (a) a standalone recast tool; (b) an interface that makes ColliderBit usable without a GAMBIT scan; (c) a new analysis library plus a variable-R jet capability; (d) a reproducible results contract for recasting. Pick one as the thesis and the rest become supporting sections.

- the only statement of purpose in the tree, and there is no second one — `solo.cpp:4`
- the runner itself is small: 10 files, +2,978 lines — `ledger · cbs-runner`
- the analysis work is not: 162 files, +11,073/−7,437, against a library of 137 registered names — `ledger · analyses`
- the jet pipeline sits between them: 14 files, +1,098 — `ledger · event-pipeline`
- and the subject is wider than this deck: ONNX (5 files), METSignificance (7 files) are absent from released GAMBIT entirely but predate the branch point, so they appear nowhere here — correct for a changelog, wrong for a paper — `ColliderBit tree vs master`

**If unanswered:** Reading (a) invites the comparison CBS is weakest on — it does not simulate detectors better than anyone else. Reading (b) or (d) is defensible and nearly unclaimed. Reading (c) makes the validation question the whole paper. Choosing late means writing three half-papers and picking the least bad.

### 2. Who is the reader, and how much GAMBIT do they already have?  _[decides what the paper is]_

Three plausible readers want incompatible papers. A GAMBIT user wants the delta: what CBS adds to a module they already build. Someone who has never built GAMBIT wants a self-contained tool description — and for them the 69-backend build system is the first thing on the page, not an appendix. Someone building their own pipeline wants the output contract and little else.

- CBS asks for 2 dependencies but sits behind 69 declared backends — the gap only matters to reader two — `cmake/standalones.cmake:36`
- 123 retired analysis names only matter to reader one, who has YAML already written — `cbs-rename-migration.json`
- the JSON contract, 8 top-level keys with 7 in-tree consumers, only matters to reader three — `cbs-json-output.json`

**If unanswered:** Written for reader one, the paper reads as a changelog and no new user can follow it. Written for reader two, half of it is build instructions. The choice also sets how much of ColliderBit has to be re-explained, which is most of the page budget.

### 3. What is CBS measured against?  _[decides what the paper is]_

A recast-tool paper is read beside the tools a referee already uses. Nothing in the tree compares CBS to any of them, on any axis — no benchmark, no cross-check against another framework’s yields, no statement of what it does differently. That comparison has to be constructed, and it decides which numbers are worth producing.

- no file in the tree names a comparison framework or benchmarks against one — `searched at HEAD`
- what CBS actually inherits and exposes is the ColliderBit likelihood machinery and a 137-analysis library — not event generation or detector simulation, which are Pythia’s and BuckFast’s — `ledger · themes`
- the histogram signal regions are the one mechanism with no obvious equivalent elsewhere: a binned distribution becoming per-bin likelihood terms — `cbs-histograms.json`

**If unanswered:** Compared on event throughput or detector fidelity, CBS loses to tools built for it. Compared on what you can do with the result — correlated likelihoods, per-bin signal regions, a machine-readable contract — the comparison is favourable and mostly unoccupied. Choosing the axis is the same act as choosing the thesis above.

## What the numbers depend on

Given a thesis, these are the settings and modelling choices that decide whether the numbers supporting it are reproducible. Two people running the same input file currently get two different likelihoods, and neither is wrong.

### 4. Which check_histogram setting produced the published numbers?  _[changes published numbers]_

check_histogram defaults to false. Turned on, the 2 signal-region histogram analyses commit 23 additional signal regions that are simply absent otherwise. That is not a verbosity flag — it changes the number of likelihood terms in the output.

- read with getValueOrDef, default false — `solo.cpp:179`
- 2 of 3 histogram analyses run in signal-region mode, contributing 23 extra signal regions when the flag is on — `cbs-histograms.json · consumers`
- only 2 of 9 histogram macros guard themselves (FILL_HISTOGRAM_1D, FILL_HISTOGRAM_2D); the rest rely on the caller checking — `AnalysisMacros.hpp`

**If unanswered:** A reader who copies the example YAML gets fewer signal regions than the paper reports, with no warning and no error. The paper needs the setting stated next to the results, and ideally the flag’s value echoed into the output JSON.

### 5. Are variable-R jets smeared, and is that the intended physics?  _[changes published numbers]_

Variable-R collections are named into a no-smear list and skipped by the detector simulation, so VR jets carry no jet energy resolution smearing while every fixed-R collection does. The code says what happens; nothing says whether it is right.

- jetcollections_no_smear declared on the smearing object — `BuckFast.hpp:49`
- 2 continue sites drop those collections out of the smearing loop — `BuckFast.cpp:48, BuckFast.cpp:56`
- the list is filled from the VR settings at 3 wiring sites, so membership is automatic — a collection is excluded by being variable-R, not by anyone choosing to exclude it — `getBuckFast.cpp:85, getBuckFast.cpp:101, getBuckFast.cpp:113`
- 2 analyses consume VR jets and inherit the choice: ATLAS_EXOT_2019_04, ATLAS_EXOT_2019_07 — `ColliderBit/src/analyses/`

**If unanswered:** Either it is deliberate — because the experimental VR calibration is applied upstream and smearing twice would be wrong — in which case say so in one sentence and the objection dies. Or it is a gap, in which case it is an unquantified systematic on every analysis that uses VR jets (2 of them), and the paper is silent about it. Right now a referee cannot tell which.

### 6. Which of the twelve new analyses are validated, and against what?  _[changes published numbers]_

The deck says twelve analyses were added. It does not say which of them reproduce the published cutflows. 5 of 12 carry no Cutflow instrumentation at all, and 3 say in their own source comments that they are not finished.

- no cutflow instrumentation: ATLAS_EXOT_2016_013, ATLAS_EXOT_2018_60, ATLAS_EXOT_2019_04, ATLAS_EXOT_2021_35, CMS_SUS_16_039 — `ColliderBit/src/analyses/`
- ATLAS_EXOT_2018_60 — “TODO: Implement the published selection and signal-region yields.” — `Analysis_ATLAS_EXOT_2018_60.cpp:23`
- ATLAS_SUSY_2018_07 — “Not validated, still in progress” — `Analysis_ATLAS_SUSY_2018_07.cpp:41`
- CMS_B2G_18_003 — “vectors are still TODO (their histograms commit no SRs until the data are supplied, but” — `Analysis_CMS_B2G_18_003.cpp:20`
- ATLAS_EXOT_2018_60 is tracked as skeleton — run() carries a TODO; collect_results() is empty. Registered only. — `change ledger`
- CMS_B2G_18_003 is tracked as partial — 3M histogram SRs digitised; 3T/2M1L obs/bkg pending; high-mass is a cut-and-count approximation, not the CMS shape fit. — `change ledger`

**If unanswered:** A validation table is the single most-requested thing in a recast paper. Without one, every yield in the paper is taken on trust, and the two analyses already tracked as skeleton and partial will be read as finished.

## What goes in the paper, and what goes in the manual

Each of these has to be written down somewhere. The question is not whether, but where -- and a paper that documents all of it is a manual, while one that documents none of it is unusable.

### 7. What does the configuration section actually document?  _[paper, appendix, or manual]_

Every tool paper has a settings table, and CBS’s is not a list of keys. 3 keys are overwritten in solo.cpp after the user file is read, so setting them in YAML has no effect; a further 3 are read by no source file at all. A table that lists them as options is worse than no table.

- min_nEvents forced to (long long)(1000) — `solo.cpp:383`
- max_nEvents forced to (long long)(std::numeric_limits<int>::max()) — `solo.cpp:384`
- run_convergence_checks forced to false — CBS policy: always process all events provided by the user (no convergence-based early stop). — `solo.cpp:386`
- of the 14 keys in the original example file, only 3 are still genuinely the user’s to set — 7 are defaulted by the program, 1 is conditional, and 3 are read by nothing — `cbs-yaml-config.json · counts`

**If unanswered:** The interesting row is run_convergence_checks, forced to false as deliberate CBS policy: the whole convergence block is inert, so a reader tuning those thresholds is tuning nothing. Whatever the paper says about configuration has to distinguish yours, defaulted, overruled and dead — four categories, not one list.

### 8. Where does the old-to-new name mapping live?  _[paper, appendix, or manual]_

123 registered analysis names were retired, so any input file naming one of them now fails. Today the mapping exists only as per-file comments in the source — the one place a user with a broken YAML will not look. It is too long for the body and too load-bearing to omit.

- 123 names retired, 132 introduced, 128 → 137 registered overall — `cbs-rename-migration.json`
- 80 renames documented across 75 git-detected file moves, including 18 consolidations absorbing 56 files — `per-file provenance comments`
- PX_SUSYRun2_stop.yaml in this tree still names 48 retired analyses — `yaml debt`

**If unanswered:** Three options and they are not equivalent: an appendix table, a cited machine-readable file, or aliases in the code so old names keep working with a deprecation warning. The third makes the other two optional and is the only one that helps a user who does not read the paper at all.

### 9. Is the output JSON a specified interface, or an implementation detail?  _[paper, appendix, or manual]_

The output carries schema_version (cbs-solo-loglike-v1), which is a promise. But the field layout is defined only by the code that writes it, and the term_id grammar — the thing every downstream consumer parses — is documented nowhere.

- 8 top-level keys, 16 nested object types — `cbs-json-output.json`
- <analysis>::<sr|combined>::<variant>, e.g. ATLAS_EXOT_2019_04::combined::nominal — `term_id grammar`
- 7 in-tree consumers already parse it, with their own guards for fields they expect — `reader-side guards`

**If unanswered:** If it is an interface, the paper should carry the schema and the grammar, and schema_version should have a documented bump policy. If it is not, say so, and downstream users know to pin a commit rather than trust the version string.

## The release checklist

Listed so they are not mistaken for open questions. These are code and packaging tasks with obvious fixes, several of which a release does automatically. They are here only because each one is currently load-bearing for a claim above, so the claim is unsafe until the task is done.

### 10. Ship the default cards, and make a run self-describing  _[a task, not a question]_

The three-layer merge — global defaults, per-analysis card, user file — is the headline simplification of the new configuration, and the cards go into the release. The task is not the packaging. It is that a missing defaults file is a silent fallback rather than an error, so a run whose cards did not load looks exactly like one whose cards did.

- CBS_yaml/CBS_defaults.yaml, 22 lines of settings, currently ignored by git — a packaging step, not a question — `.gitignore:50`
- absent defaults return silently rather than failing, so the run proceeds on whatever the compiled-in values happen to be — `solo_input.cpp`

**If unanswered:** Two cheap fixes, and the second is the one that matters: fail loudly when the cards are missing, and write the resolved settings into the output JSON so every run states the configuration it actually ran under. That also settles the check_histogram question above without anyone having to remember to write the flag down.

### 11. Make the Contur version agree with itself  _[a task, not a question]_

A tool paper carries a version table, and one row cannot currently be written truthfully. At HEAD, 4 declaration sites name 2 different Contur versions, and the patch cmake points at does not exist in the tree. Purely a merge artefact: HEAD is the only one of four refs that disagrees with itself.

- cmake says 2.1.1, pointing at patch_contur_2.1.1.dif — missing — `cmake/backends.cmake:2185`
- solo.cpp says 3.0.0 — `solo.cpp:45`
- frontends/Contur_3_0_0.hpp says 3.0.0 — `frontends/Contur_3_0_0.hpp`
- patches/contur/3.0.0/ says 3.0.0 — `patches/contur/3.0.0/`
- the other three refs are each self-consistent: master 2.1.1, base 3.0.0, sr2 3.0.0 — `cbs-package-matrix.json`

**If unanswered:** Pick a version, delete the other declarations, and the row writes itself. Left alone, the version table records a configuration that cannot be built.

### 12. Give the installation route a name, and take HepForge off the critical path  _[a task, not a question]_

CBS declares one module and 2 dependencies (hepmc, pybind11). The build system in front of it declares 69 backends, and 29 of 71 download URLs (41%) point at a single host. Nothing tells a reader which of the two numbers applies to them. Slide 14 has the full argument; the checklist part is small.

- add_standalone(CBS … MODULES ColliderBit DEPENDENCIES hepmc pybind11) — `cmake/standalones.cmake:36`
- 69 backends declared; 29/71 downloads on hepforge.org — `cmake/backends.cmake`
- mitigation already exists and is undocumented: safe_dl.sh, copy_tarballs.sh, restore_tarballs.sh — `cmake/scripts/`
- GAMBIT_USE_LLD_FOR_CBS exists because linking CBS was worth an option — `cmake/standalones.cmake:38`

**If unanswered:** Two paragraphs and a preset: name the minimal dependency set, and point at the tarball-mirror scripts that are already in the tree and already undocumented. The larger move — a container or conda recipe, so most readers never build at all — is a real decision and it is on slide 14, not here.

---

Static read of the worktree and of the other pages' JSON. Nothing was built or run. Generated by `scripts/build-paper-questions-page.py`.
