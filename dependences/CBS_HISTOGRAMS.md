# Histograms in ColliderBit

Baseline `9c955e3a78` &rarr; head `65aca0890d`.

## One class, two jobs

`Histogram1D` is a plain histogram when its `obs` vector is empty and a
signal-region histogram when it is not. That single test at
`Histogram.hpp:213` is the whole distinction.

A plain histogram reaches the JSON output and the plotter and stops there.
A signal-region histogram additionally turns every bin into a `SignalRegionData`
named `<hist>_bin<i>` (`Histogram.hpp:236`), which", enters the likelihood.

## Consumers

| Analysis | Mode | Histogram | Bins | Signal regions |
|---|---|---|---|---|
| `ATLAS_EXOT_2019_04` | signal region | `m_VLB` | 7 | 1 -> 8 |
| `ATLAS_EXOT_2019_07` | signal region | `m_JJ` | 16 | 1 -> 17 |
| `ATLAS_EXOT_2021_35` | plain | `mVLQlep_sr1, mVLQlep_sr2` | - | 2 |

## The flag

`check_histogram` is read from YAML at `solo.cpp:179`
and **defaults to false**. It gates booking, filling and committing.

On the two signal-region analyses it therefore changes how many signal regions
reach the likelihood, which is more than a diagnostic switch normally does.

No build or run was performed for this document.
