# CBS JSON output contract

Schema: `cbs-solo-loglike-v1` (`ColliderBit/examples/solo_output.cpp:36`)
Writer: `ColliderBit/examples/solo_output.cpp` &middot; indent 2 &middot; nlohmann::json 3.11.3

`private-SUSYRun2` has no JSON output at all, so this document describes the new
contract only; there is no before/after to compare.

## Top-level keys

| # | Key | Gate | Emitted at |
|---:|---|---|---|
| 1 | `schema_version` | always | `ColliderBit/examples/solo_output.cpp:407` |
| 2 | `run` | always | `ColliderBit/examples/solo_output.cpp:408` |
| 3 | `analyses` | always | `ColliderBit/examples/solo_output.cpp:566` |
| 4 | `terms` | always | `ColliderBit/examples/solo_output.cpp:567` |
| 5 | `summary` | always | `ColliderBit/examples/solo_output.cpp:573` |
| 6 | `sampling_advice` | only when the batch path produced advice entries | `ColliderBit/examples/solo_output.cpp:621` |
| 7 | `predefined_sets` | always | `ColliderBit/examples/solo_output.cpp:626` |
| 8 | `contur` | only when Contur ran | `ColliderBit/examples/solo_output.cpp:682` |

## Object shapes

| Path | Fields | Read back by batch merge |
|---|---:|---:|
| `analyses["<ANALYSIS_NAME>"]` | 8 | 6 |
| `analyses["<A>"].combination` | 4 | 0 |
| `analyses["<A>"].signal_regions["<SR_LABEL>"]` | 10 | 6 |
| `analyses["<A>"].cutflows[]` | 2 | 2 |
| `analyses["<A>"].cutflows[].cuts[]` | 5 | 2 |
| `analyses["<A>"].histograms["1d"][]` | 14 | 12 |
| `analyses["<A>"].histograms["1d"][].bins[]` | 10 | 5 |
| `analyses["<A>"].histograms["2d"][]` | 12 | 8 |
| `terms[]` | 9 | 0 |
| `summary` | 3 | 0 |
| `sampling_advice` | 2 | 0 |
| `sampling_advice.analyses[]` | 8 | 0 |
| `sampling_advice.analyses[].targets[]` | 8 | 0 |
| `sampling_advice.analyses[].targets[].process_recommendations[]` | 4 | 0 |
| `contur` | 2 | 0 |
| `contur.pools["<POOL>"]` | 2 | 0 |

## Likelihood terms

| Component | Variant | safe_to_sum | selected_in_default |
|---|---|---|---|
| `signal_region` | `"nominal"` | `false` | `false` |
| `signal_region` | `alt_key` | `false` | `false` |
| `analysis_combined` | `"nominal"` | `true` | `true` |
| `analysis_combined` | `alt_pair.first` | `true` | `false` |
| `contur_pool` | `"nominal"` | `false` | `false` |
| `contur_total` | `"nominal"` | `true` | `true` |

## Batch round trip

The same schema is the batch wire format: the parent forces the child's
`output` path (`ColliderBit/examples/solo_batch.cpp:238`) and silences its
screen output (`ColliderBit/examples/solo_batch.cpp:237`), then reads the
per-file documents back and merges them.

41 of 106 emitted fields are
read back by the merge, guarded by 19 explicit consistency checks.

No CBS build or run was performed to produce this document.
