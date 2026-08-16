# ColliderBit analysis dependency comparison

本目录先放入三张分析的 analysis-local 依赖图：

| 分析 | 节点 | 边 | 主要结构 |
|---|---:|---:|---|
| `ATLAS_EXOT_2019_04` | 12 | 13 | 多个对象输入汇聚到 H2T2B/VLB 候选 |
| `ATLAS_SUSY_2018_05` | 15 | 17 | 对象清理链之后并行计算 MET significance 与 mT2 |
| `CMS_B2G_18_003` | 16 | 16 | 低质量 resolved 与高质量 merged 两条主分支 |

## 图和数据

- `three-analysis-dependency-graphs.html`：三张图的集中展示页
- `ATLAS_EXOT_2019_04_dependency.json` / `.mmd`
- `ATLAS_SUSY_2018_05_dependency.json` / `.mmd`
- `CMS_B2G_18_003_dependency.json` / `.mmd`

## 结构观察

### ATLAS_EXOT_2019_04

这张图的核心是一个明显的汇聚结构：

```text
large-R trimming
generateBTagsMap()
VR_Reff()
        ↓
H2T2B / VLB candidate
        ↓
m_VLB histogram + SR counter
```

`run()` 的出边最多，说明它同时负责对象构建、排序、b-tag、VR 半径、结果收集和 reset 生命周期。候选节点有三个物理输入，是整个分析的主要 fan-in 点。

### ATLAS_SUSY_2018_05

这张图的前半段更长：

```text
baseline e/μ/γ + jets
        ↓
efficiency / overlap removal
        ↓
signal objects → sort()
        ↓
2-lepton preselection
        ├── calcMETSignificance()
        └── mt2_bisect::mt2::get_mt2()
                    ↓
              signal regions
```

它的特点是对象清理和分析变量计算比较重，signal-region 数量也较多。与 EXOT 分析相比，它不是“一个候选构造器”主导，而是“预选 + 多变量切分”主导。

### CMS_B2G_18_003

CMS B2G 图最明显的是两个相对独立的物理分支：

- 低质量分支：AK4/AK8 → 3T/3M/2M1L → `reconstruct_lowmass()` → 五喷注质量 histogram
- 高质量分支：AK4/AK8 → SoftDrop/pruning → N-subjettiness + proxy b-tag → 8 个 cut-and-count SR

因此这张图的结构更接近双通道 pipeline，而不是单一线性流程。它还同时使用 histogram-backed SR 和普通 cut-and-count SR 两种结果提交机制。

## 证据和限制

- 三个分析的 `run()`、`collect_results()` 和 `analysis_specific_reset()` 均作为 AST 确认的成员函数记录。
- 普通函数调用使用 Clang AST 证据；`BASELINE_*`、`SIGNAL_*`、`FILL_*`、`COMMIT_*` 使用源码语义证据。
- `CMS_B2G_18_003` 的 AST 解析额外需要 `contrib/fastjet-3.4.2/local/include/fastjet/contrib`，因为源码直接 include `SoftDrop.hh`。
- 这些 JSON 是可读的 analysis-local 摘要图，不是每一个 STL、FastJet 或宏展开节点的完整 AST 图。
- 尚未加入 CBS 共享主干：`operateLHCLoop → runATLASAnalyses/runCMSAnalyses → AnalysisContainer → CollectAnalyses → calc_LHC_LogLikes`。

## 下一步合并方式

下一步可以把三张图统一接到共享节点：

```text
runATLASAnalyses / runCMSAnalyses
        ↓ dynamic_dispatch
AnalysisContainer::mkAnalysis(name)
        ↓
各分析 ::run()
        ↓
各分析 collect_results()
        ↓
CollectAnalyses → calc_LHC_LogLikes → CBS_result.json
```

合并时，分析内部节点使用 `analysis:<name>:<node>` 命名，共享节点使用 `shared:<qualified-name>` 命名，避免多个分析重复生成 `CollectAnalyses`、`calc_LHC_LogLikes` 等公共节点。
