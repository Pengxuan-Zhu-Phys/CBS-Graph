# ColliderBit-Solo 开发总结与汇报底稿

> 用途：作为下周一开发汇报的底稿。内容按“任务—背景—问题—改进—框架影响—完成状态”组织，后续可以直接拆分为 slide 和正式 report。

## 1. 一句话总结

本阶段的核心工作，是把 ColliderBit 从依赖完整 GAMBIT 工作流的分析代码，逐步整理成可以独立运行的 ColliderBit-Solo（CBS）：统一分析接口和 cutflow，加入可复用的直方图与 signal-region 输出，支持单文件、多文件及多 process 样本，接通 variable-R jet 处理链，并补齐多个 ATLAS/CMS 分析和可重复的 JSON/plot 工作流。

需要在汇报中区分两类成果：

1. 已经形成可复用框架能力的工程任务，例如 JSON 输出、batch 合并、cutflow、histogram、CLI 和 VR jet。
2. 具体物理分析的实现。部分分析已经完成并做过验证；CMS B2G-18-003 的部分 shape 区域以及 ATLAS EXOT-2018-60 仍然属于“框架已接入、物理选择尚未完全实现”的状态，不能表述为完整复现。

## 2. 范围与证据口径

- 统计范围：当前分支 ColliderBit_solo_development 中，从共同基线到当前 HEAD 的个人提交；master 合并提交只作为上游依赖背景，不计入独立任务。
- 代码范围：ColliderBit/examples/solo_*、ColliderBit/include、ColliderBit/src、ColliderBit/analyses、CBS_yaml、CMake 和相关脚本。
- 时间范围：2024 年底的分析基础工作，到 2026 年 8 月的 CBS CLI/分析注册工作。
- 证据来源：git 提交历史、当前源代码、分析注册表、YAML 模板和更新说明文档。
- 验证口径：本次只做静态代码和历史核对，没有重新编译或运行 GAMBIT/CBS。按照 ColliderBit review 工作流，避免因环境依赖造成无关改动。

## 3. 总体架构变化

当前 CBS 的数据流可以概括为：

YAML/命令行参数
→ solo_cli 解析与校验
→ solo_input 读取 event file 或 processes
→ 单文件执行，或 solo_batch 拆分并行子任务
→ HepMC 转换、BuckFast、jet/VR jet 构造
→ ATLAS/CMS analysis、cutflow、histogram
→ signal-region 统计量、协方差和 likelihood
→ solo_output 输出屏幕摘要与 JSON
→ plot_cbs_histograms.py 生成图

这个变化的意义是：分析代码仍然复用 ColliderBit 的 Analysis、AnalysisContainer、HEPUtils、FastJet、Pythia/BuckFast 和 likelihood 模块，但运行入口、输入、批处理、结果序列化和可视化已经由 CBS 独立承担。

## 4. 时间线与任务分组

| 阶段 | 主要工作 | 汇报定位 |
|---|---|---|
| 2024-11 至 2025-01 | event tracking、RJR、ATLAS SUSY-2018-012/007 基础分析 | 物理分析和对象重建基础 |
| 2025-01 至 2025-04 | Topness、EXOT-2016-013、EXOT-2016-017、EXOT-2019-007、EXOT-2021-035 等 | 扩充可用分析库 |
| 2025-11 至 2026-02 | EXOT-2019-04、cutflow 迁移、JSON 输出、VR jet、CBS 首个 release | 从分析代码走向独立框架 |
| 2026-03 至 2026-06 | CMS B2G-18-003、histogram system、SR plotting、batch/OpenMP 修复 | 形状分析和批量统计能力 |
| 2026-07 至 2026-08 | VLQ 分析 metadata 对齐、EXOT-2018-60 注册、CBS CLI | 工具链和分析注册收尾 |

## 5. 具体任务总结

### 5.1 建立 ColliderBit-Solo 独立运行入口

**背景**

原来的 ColliderBit 分析通常通过完整 GAMBIT 配置启动，需要外部模块提供 event generation、likelihood、扫描参数和输出管理。对已经存在的 HepMC 样本进行快速复现、调试或批量统计时，启动路径较重，也不利于把 CBS 当成独立工具交给分析人员使用。

**原来的问题**

- 没有一个稳定、轻量的独立命令行入口。
- 输入 event file、cross section、analysis 选项和输出位置分散在不同配置层。
- 小错误可能在较深的框架初始化后才暴露，定位成本高。

**完成内容**

- 增加 ColliderBit/examples/solo.cpp 作为独立入口。
- 增加 solo_cli.hpp/cpp：支持 -h/--help、YAML 路径校验、未知参数拒绝、缺少参数报错和 getopt 状态重置。
- 统一初始化 Nulike、可选 Rivet/Contur/FullLikes，并设置运行时 cutflow/histogram 开关。
- 将单文件执行、batch 执行、输出和采样建议分别拆到 solo_input、solo_batch、solo_output 模块。
- 增加启动 banner 抑制和更清晰的屏幕摘要。

**基于的原有 module**

ColliderBit standalone_module、ColliderBit rollcall、AnalysisContainer、HEPUtils event converter、BuckFast、Nulike 和原有 likelihood 计算。

**对框架的影响**

入口层与物理分析层解耦。后续新增分析只需要注册到 AnalysisContainer 并在 YAML 中选择，不必重复实现输入解析、批处理和输出逻辑。

**完成状态**

已完成。当前 CLI 提交为 ef4107bcf1；CBS release 和 YAML 模板已形成稳定使用方式。

### 5.2 统一 cutflow，并修复多线程/批处理聚合

**背景**

各分析原先有不同的 cutflow 写法，有些分析在 standalone 模式下没有统一输出，有些依赖编译宏。OpenMP 多线程和每文件 batch 运行时，还容易出现计数重复、漏加或结果对象不一致。

**原来的问题**

- cutflow 是否启用由编译方式和分析内部实现共同决定，用户不容易判断。
- 多线程时每个线程的当前 cut index 和计数聚合容易出错。
- 多个 event file 合并后，不能直接把未经校验的 cutflow 拼接。

**完成内容**

- 将 cutflow 逻辑集中到 ColliderBit/include/gambit/ColliderBit/Cutflow.hpp。
- 增加 settings.check_cutflow 运行时开关；保留 CMake 的 CUTFLOW 选项作为编译能力检查。
- 统一分析中的 fillinit、fill、commit 和结果收集方式。
- 修复 OpenMP cutflow aggregation，保证 per-file batch 结果能正确合并。
- 在 batch 合并阶段检查 cutflow 结构是否一致，随后进行加权合并。

**基于的原有 module**

原有 Cutflow class、AnalysisData、AnalysisMacros 和 OpenMP 事件循环。

**对框架的影响**

cutflow 从“每个分析自己处理”变成了 CBS 的统一观测接口。它既服务于物理分析调试，也进入 JSON 结果，方便回归测试和 slide 展示。

**完成状态**

已完成。主要提交包括 0e08060bf5、ed8bda983a、637ea90acc、06b5de7a16、7acb603f74、10018eb86d 和 3599c668e1。

### 5.3 新增 JSON 输出、schema 和结果可追溯性

**背景**

原来分析结果主要通过终端或框架内部对象查看，不利于脚本读取、跨文件合并和后处理绘图。正式汇报需要同时展示 analysis metadata、signal regions、cutflow、histogram 和 likelihood。

**原来的问题**

- 输出格式不统一，难以被外部工具消费。
- signal-region 数值、MC 统计误差、background covariance 和组合规则缺少固定结构。
- 批处理完成后，没有一个可审计的最终结果文件。

**完成内容**

- 增加 ColliderBit/examples/solo_output.hpp/cpp。
- 规定 JSON schema_version 为 cbs-solo-loglike-v1。
- 输出运行信息：事件数、是否启用 Contur、analysis metadata、luminosity、signal-region 数值、cutflows、histograms、covariance、likelihood 组合和 predefined sets。
- 输出 n_sig_MC、n_sig_MC_stat、n_sig_scaled、n_sig_scaled_err、loglike 等统计字段。
- 统一屏幕摘要和文件输出，支持 batch 的 sampling_advice。

**基于的原有 module**

AnalysisData、AnalysisContainer、Nulike/common likelihood、Cutflow 和 Histogram system。

**对框架的影响**

CBS 结果不再依赖 C++ 内部对象生命周期，能够被 Python plot 脚本、批处理工具和后续 report 直接消费；schema 也为不同分析之间的结果比较提供了稳定契约。

**完成状态**

已完成。主要提交为 061b425740、9a1262ed95 和 92fbd960f8。

### 5.4 支持多文件、多 process 和可合并的 batch 执行

**背景**

实际生产样本通常被拆成多个 HepMC 文件，甚至按不同 process 分开生成。原来的单文件接口无法自动维护每个样本的截面、事件数和 MC 统计误差。

**原来的问题**

- 用户需要手动逐文件运行，再自己合并 SR 和 likelihood。
- 同一 process 的不同文件不应重复使用完整截面；不同 process 又必须分别使用各自截面。
- 直接相加每个文件的 log-likelihood 在统计上不正确。

**完成内容**

- solo_input 支持 settings.processes；每个 process 包含 name、cross_section_fb、cross_section_uncert_fb 和多个 event_file。
- 支持 fb/pb 单位及绝对/相对截面不确定度，校验非负值和文件存在性。
- 明确禁止把 generated_events 当成输入事件数；实际事件数从文件读取。
- solo_batch 将每个物理文件拆成子任务，子任务保留完整 process 截面；同一 process 内按事件数加权合并。
- 合并 n_sig_scaled 和 MC 误差，校验 luminosity、background、SR 标签顺序及 histogram 结构。
- 合并完成后重新计算总 signal 和 likelihood，而不是简单相加 per-file loglike。
- 增加 sampling_advice：目标相对误差、有效事件数和建议补充事件数。

**基于的原有 module**

solo.cpp 单文件循环、solo_output JSON、Nulike/common likelihood、临时 YAML 生成、fork/exec 和 OpenMP。

**对框架的影响**

CBS 从“单个输入文件 runner”升级为可用于生产样本的 batch runner。合并规则被固化在框架层，减少分析人员手工合并带来的统计错误。

**完成状态**

已完成，核心提交为 8749e3e8e4、bdb31483ee、03d5a9e959 和后续 batch 修复。

### 5.5 引入通用 Histogram 和 histogram-backed signal regions

**背景**

cut-and-count 只能提供离散 SR 数值，无法表达发布结果中常见的质量分布、shape fit 或 bin-by-bin comparison。为了支持 CMS/ATLAS 的公开图表和更直观的验证，需要在分析中保存 histogram。

**原来的问题**

- 分析只提交 cutflow/SR，无法保存加权分布。
- 没有统一处理 underflow、overflow、sumw2、background uncertainty 和 signal-region 转换。
- 不同分析如果各自保存直方图，会产生重复数据结构和合并规则。

**完成内容**

- 新增 ColliderBit/include/gambit/ColliderBit/Histogram.hpp。
- 提供 Histogram1D/Histogram2D、加权 fill、sumw2、underflow/overflow、scale、combine、obs/bkg/bkg_err 以及 to_signal_regions。
- 在 AnalysisData 中增加 histograms，并让 Analysis::scale、reset 同步处理 histogram。
- 在 AnalysisMacros 中增加 DEFINE_HISTOGRAM_1D、DEFINE_HISTOGRAM_SR_1D、二维 histogram、FILL_HISTOGRAM 和 commit 宏。
- solo_output 将直方图写入 JSON；solo_batch 对多个文件进行结构检查和加权合并。
- 增加 ColliderBit/scripts/plot_cbs_histograms.py，支持 1D/2D、SR 图、background uncertainty、data、signal 和 ratio。

**基于的原有 module**

AnalysisData、AnalysisMacros、YODA histogram 习惯、HEPUtils event loop 和现有 SR/likelihood 输出。

**对框架的影响**

Histogram 成为分析结果的一等公民；同一份 event loop 可以同时产出 cutflow、cut-and-count SR 和 shape histogram，后处理无需再次读取 HepMC。

**完成状态**

框架已完成。具体分析的 digitisation 完成度不同，必须按分析单独说明。

### 5.6 接通 variable-R jet 处理链

**背景**

部分 ATLAS 分析需要 variable-R track jet，而原有 jet pipeline 主要覆盖固定半径 anti-kT jet。若只在分析文件里临时构造对象，CBS 与完整 ColliderBit 的行为会不一致。

**原来的问题**

- YAML 无法声明 VR jet collection。
- event conversion、BuckFast、Pythia 后端和 analysis 之间没有统一传递 VR jet。
- batch 子任务可能丢失 VR 设置。

**完成内容**

- YAML 增加 VRJet_collections/VRTrackJets 配置。
- 在 Utils.hpp、BaseCollider、getPy8Collider、Py8EventConversions、getHepMCEvent 等环节传递并构造 variable-R jet。
- 在 CBS batch 临时配置中保留 VR 设置。
- CMake/FastJetContrib 接入 VariableR 和 EnergyCorrelator。
- 在 ATLAS EXOT-2019-04、EXOT-2019-07 中使用 VRTrackJets。

**基于的原有 module**

FastJet、FastJetContrib、Py8EventConversions、HEPUtils Jet、BuckFast 和 ColliderBit jet collection 接口。

**对框架的影响**

VR jet 从分析私有实现提升为框架级输入对象；新分析只需在 YAML 声明 collection，即可复用同一套事件转换和批处理逻辑。

**完成状态**

已完成，细节记录在 CBS_yaml/VRjet_update.md；需注意当前 Pythia wrapper 的某些 VR overload 仍有限制，分析应使用实际可用的 YAML collection。

### 5.7 ATLAS SUSY-2018-012 RJR 分析

**背景**

ATLAS Stop 0L 分析使用 Recursive Jigsaw Reconstruction，需要 LAB/CM/S/ISR/V/I 等 RestFrames frame、Jigsaw rule 和质量/角度变量。

**原来的问题**

- RJR 对象构造复杂，依赖 RestFrames，不能简单套用普通 cut-and-count 模板。
- 需要同时维护 ISR/VIS/INV 系统和多个 SRC signal region。

**完成内容**

- 增加 Analysis_ATLAS_SUSY_2018_12_RJR.cpp。
- 用 unique_ptr 管理 RestFrames LAB、CM、S、ISR、V、I frame 及对应 Jigsaw。
- 实现 INV/VIS 重建、MET significance、SRC signal regions 和 cutflow。
- 在 AnalysisContainer 中通过 MAP_ANALYSES_WITH_ROOT_RESTFRAMES 注册。

**基于的原有 module**

RestFrames、HEPUtils Event/Jet、METSignificance、Cutflow、AnalysisContainer ROOT/RestFrames 分组。

**对框架的影响**

证明 CBS 不只支持轻量 cut-and-count，也能承载带外部重建库的复杂分析；同时将 ROOT/RestFrames 依赖隔离到相应分析映射。

**完成状态**

已完成并经过 validation 提交记录。

### 5.8 ATLAS SUSY-2018-007：soft-b、Topness 和 VR jet 基础

**背景**

Stop 搜索需要区分 soft-b、bWN、diagonal 和 dark-matter-like 区域，并使用 Topness 等事件变量。

**原来的问题**

- soft-b jet 不是普通固定半径 b-jet，容易与常规 b-tag 逻辑混淆。
- Topness 公式和对象组合需要与文献定义一致。
- 分析内部的 VR jet 与通用事件对象衔接不稳定。

**完成内容**

- 扩展 Analysis_ATLAS_SUSY_2018_07.cpp 的多个 signal region。
- 加入 soft-b、bWN、bffN、DM 和 diagonal region 组织。
- 接入 Topness 计算及相关 bug fix。
- 将 variable-R jet 作为后续通用 jet pipeline 的需求来源之一。

**基于的原有 module**

HEPUtils Jet、b-tag proxy、Topness utility、VariableRPlugin、Cutflow 和分析注册表。

**对框架的影响**

扩充了复杂对象选择的可复用模式，为之后的 VR jet 和大型 VLQ 分析提供了对象处理经验。

**完成状态**

分析实现和历史验证已完成；个别物理对象仍应在 slide 中说明为分析特定近似。

### 5.9 ATLAS EXOT-2016-013 和 EXOT-2016-017

**背景**

这两项分析分别覆盖多 b/多 jet 的 0L/1L 搜索，以及单 lepton 的 vector-like T/Y 搜索，需要大半径 jet、b-tag、前向 jet 和 ΔR/Δφ 变量。

**原来的问题**

- 原有分析模板不能直接覆盖 0L/1L 分支和 forward-jet 条件。
- 诊断 histogram、cutflow 和最终 SR 提交没有统一。
- EXOT-2016-013 的诊断输出曾被不合适地编译条件门控。

**完成内容**

- 新增或完善 Analysis_ATLAS_EXOT_2016_013.cpp：0L/1L、多 b SR、大半径 jet trimming 和诊断分布。
- 新增或完善 Analysis_ATLAS_EXOT_2016_017.cpp：one-lepton、Wb 单 T/Y、anti-kT R04 中心/前向 jet、b-tag、forward jet、ΔR/Δφ。
- 迁移 cutflow，统一 collect_results。
- 通过 f95c0ffabf 将 EXOT-2016-013 diagnostics 的 gate 改为与 histogram/cutflow 语义一致。

**基于的原有 module**

HEPUtils/FastJet、b-tag、large-R jet、AnalysisMacros、Cutflow 和 AnalysisContainer。

**对框架的影响**

增加了 0L/1L 和 forward-jet 分析模板，验证统一 cutflow/histogram 接口能覆盖不同拓扑。

**完成状态**

已完成，分析已经进入正常注册和输出流程。

### 5.10 ATLAS EXOT-2019-007 和 EXOT-2021-035

**背景**

EXOT-2019-007 使用大半径 jet、top/H tagging 和形状变量；EXOT-2021-035 是相关的公开分析更新。两者都需要将 object-level 选择转成稳定的 cutflow/SR 输出。

**原来的问题**

- 旧实现中存在重复对象处理和较分散的结果收集。
- YODA/自定义 histogram 迁移前，结果不容易与新 JSON schema 对接。

**完成内容**

- 增加并维护 Analysis_ATLAS_EXOT_2019_07.cpp 和 2021-035 相关实现。
- 完成 large-R/VR jet、H/top tag 和 mJJ 等分布的结果收集。
- 迁移到统一 YODA Histo1D/Histogram-backed 结果路径。
- 将 cutflow、histogram 和 SR 统一提交到 AnalysisData。

**基于的原有 module**

FastJet、HEPUtils、YODA、AnalysisData、AnalysisMacros 和 solo_output。

**对框架的影响**

证明同一套输出结构可以覆盖连续形状变量和传统 SR；为 plot_cbs_histograms.py 提供真实分析样例。

**完成状态**

已完成并纳入当前分析注册表。

### 5.11 ATLAS EXOT-2019-04：VLQ 分析和 VRTrackJets

**背景**

EXOT-2019-04 是当前 CBS 中较能体现“分析 + 框架”结合的 VLQ 示例，包含大半径 jet、VRTrackJets、H2T2B/VLB 候选和质量分布。

**原来的问题**

- 需要同时处理 fixed-R large-R jet 和 variable-R track jet。
- 结果既有 cutflow/SR，又需要对 m_VLB 做 histogram-backed SR。
- 早期分析 metadata、对象命名和框架输出约定不完全统一。

**完成内容**

- 新增并验证 Analysis_ATLAS_EXOT_2019_04.cpp。
- 使用 anti-kT R04/R10、large-R trimming、VRTrackJets、H2T2B 和 VLB candidate。
- 增加 m_VLB histogram，提供 bin edges、data、background 和 uncertainty。
- collect_results 同时提交 signal regions、cutflow、histograms 和 histogram SR。
- 在 VLQ metadata 对齐提交中统一分析名称、作者和描述。

**基于的原有 module**

VR jet pipeline、FastJet/FJContrib、HEPUtils、Histogram、AnalysisData 和 solo_output。

**对框架的影响**

这是 CBS 形状输出、VR jet 和 VLQ 分析的综合示例；后续分析可以按同样模式增加 histogram-backed SR。

**完成状态**

已完成，当前源代码和 YAML 模板均可识别；仍需把“物理验证结果”与“代码注册成功”分开汇报。

### 5.12 CMS B2G-18-003：低质量 histogram SR 与高质量近似

**背景**

CMS B2G-18-003 同时包含低质量的多类别形状区域和高质量区域。它是检验 CBS 是否能承载 CMS histogram-backed SR 的关键案例。

**原来的问题**

- 原有框架更偏 ATLAS cut-and-count，缺少 CMS 形状区域的统一表达。
- 五 jet mass 等分布需要 histogram，而不是简单事件计数。
- 公开数据 digitisation 不完整时，不能把空的 obs/bkg 数组误认为完整复现。

**完成内容**

- 新增 Analysis_CMS_B2G_18_003.cpp 并注册到 AnalysisContainer。
- 实现 low-mass 类别选择、FastJet SoftDrop/pruning、N-subjettiness 和 b-tag proxy。
- 为 3M、3T、2M1L 等类别加入 histogram-backed signal-region scaffold。
- 对高质量区提供 public cut-and-count approximation。
- 在 .info 中明确：3M 使用五 jet mass histogram；3T/2M1L 的 obs/bkg 仍待 digitisation；高质量区尚未实现 CMS 完整 shape fit。

**基于的原有 module**

CMS Analysis 模板、FastJet、Histogram/Histogram_SR、AnalysisData、solo_output 和 plot 脚本。

**对框架的影响**

展示了 CBS 对 CMS 风格 shape 分析的扩展路径，同时明确了“框架能力已具备”和“外部公开数据尚未 digitise”的边界。

**完成状态**

部分完成。框架、选择逻辑和输出 scaffold 已接入；完整 shape fit 和所有 obs/bkg 数值仍是后续工作。

### 5.13 ATLAS EXOT-2018-60 注册：必须标记为 skeleton

**背景**

为了让分析清单和新一批 EXOT/VLQ 任务保持一致，需要把 ATLAS EXOT-2018-60 加入分析注册表和 metadata。

**原来的问题**

如果只看注册表或 YAML 能否加载，很容易把“可以被框架识别”误报成“物理选择已经实现”。

**完成内容**

- 增加 Analysis_ATLAS_EXOT_2018_60.cpp。
- 在 AnalysisContainer.cpp 中注册分析，并增加对应 .info metadata。
- 设置 analysis name 和 140 fb−1 luminosity 的基础信息。

**当前限制**

run() 仍保留 TODO，collect_results/reset 尚未实现 published selection 和 SR yields。因此当前成果是框架注册和开发骨架，不是完整分析复现。

**对框架的影响**

验证了新增分析的最小注册流程，但也提醒后续需要在 metadata 中增加更明确的 implementation status。

**完成状态**

仅完成注册/skeleton。汇报时应明确说“analysis entry 已加入，物理 selection 尚未完成”。

## 6. 工程质量、依赖和构建维护

### 6.1 FastJet/FastJetContrib 复用

CBS standalone 复用了 contrib 中的 FastJet 3.4.2 和 FastJetContrib 1.049。构建逻辑优先复用已有 fastjet/fjcontrib target，避免重复构建；如果外部 target 不存在，则回退到正常 backend 路径。Rivet 在复用模式下也指向相同 FastJet 目录。

这个改动的价值是降低 standalone 与完整框架的 ABI/版本差异，并让 VariableR、EnergyCorrelator 等插件可用。

### 6.2 YODA 和警告清理

在 2026-06 的维护提交中，完成了部分 YODA Histo1D 迁移，移除 2018-07、2019-07、2016-017 中的 dead YODA code，并修复若干编译器警告和未定义行为风险，包括：

- 修正 ATLAS_EXOT_2016_014 的括号问题。
- 修正 ATLAS_SUSY_2019_22 中 samesign 初始化和阈值判断。
- 迁移 deprecated FastJet JetDefinition 用法。
- 调整 CMake flags 和 script mode。

这些不是新物理功能，但提升了 CBS 在不同编译器和 macOS 环境下的可维护性。

### 6.3 分析注册和 metadata 对齐

新增分析需要同时修改分析源文件、AnalysisContainer.cpp、ColliderBit/CMakeLists.txt 和 .info metadata。2026-07 的 VLQ metadata 对齐工作统一了分析名称、作者、luminosity 和描述，减少了“源码存在但框架找不到”或“输出名称不一致”的问题。

## 7. 对框架的总体影响

| 框架层 | 新增/改进 | 直接收益 |
|---|---|---|
| 输入层 | solo_cli、solo_input、processes、多文件和截面校验 | 可复现、可批处理 |
| 事件层 | HepMC 转换、BuckFast、fixed-R 与 variable-R jet 统一 | 分析可复用同一对象链 |
| 分析层 | 多个 ATLAS/CMS 分析、RJR、VLQ、CMS shape scaffold | 覆盖更多拓扑和实验风格 |
| 结果层 | Cutflow、Histogram、JSON schema、sampling advice | 输出可审计、可绘图、可合并 |
| 统计层 | SR 合并、MC 误差传播、重新计算 likelihood | 避免手工统计错误 |
| 构建层 | FastJet/FJContrib 复用、YODA/警告维护 | 减少依赖冲突和编译噪声 |

最重要的架构变化不是“增加了多少个分析文件”，而是把分析运行流程的共性部分提取为稳定模块，使新分析的新增成本主要集中在物理选择和公开结果 digitisation。

## 8. 建议的 slide 结构

### Slide 1：目标与动机

- ColliderBit-Solo 的目标：对已有 HepMC 样本提供轻量、可复现、可批量的 ColliderBit 分析入口。
- 原来的痛点：完整 GAMBIT 启动重、输入/输出不统一、手工合并困难。

### Slide 2：总体架构

- 展示 YAML/CLI → event conversion/jet → analysis → cutflow/histogram → JSON/likelihood/plot 的流水线。
- 强调“复用 ColliderBit 物理模块，新增 CBS 工具层”。

### Slide 3：框架化能力

- 统一 cutflow。
- JSON schema 和结果 metadata。
- 多文件、多 process batch。
- Histogram 与 histogram-backed SR。
- VR jet pipeline。

### Slide 4：分析成果

- ATLAS SUSY-2018-012 RJR。
- SUSY-2018-007 soft-b/Topness。
- EXOT-2016-013/017、EXOT-2019-007/035、EXOT-2019-04。
- CMS B2G-18-003。

### Slide 5：一个端到端示例

- 以 ATLAS EXOT-2019-04 为例：YAML 声明 VRTrackJets → 事件转换 → VLB 候选 → m_VLB histogram → SR/JSON/plot。
- 可放一张 histogram 和一段 JSON 结构截图。

### Slide 6：完成边界与下一步

- 已完成：CBS runner、cutflow、JSON、batch、histogram、VR pipeline 和多项分析。
- 部分完成：CMS B2G digitisation/shape fit。
- 待完成：ATLAS EXOT-2018-60 published selection。
- 下一步：补齐公开数据、增加回归测试、完善 schema/versioning 和物理验证。

## 9. 汇报时可直接使用的结论

本阶段完成了 ColliderBit-Solo 从“能运行单个分析文件”到“具备独立输入、统一结果、批量合并和形状输出能力”的工程化升级。核心框架现在可以处理单文件和多 process HepMC 样本，统一输出 cutflow、signal region、histogram、MC 统计误差和 likelihood，并通过 JSON 和 Python 脚本形成可追溯的后处理链。

在物理分析方面，已经覆盖 RJR、soft-b、VLQ、大半径 jet、variable-R jet、CMS 多类别等场景。需要准确表述的是：ATLAS EXOT-2019-04 等分析已经接入并验证；CMS B2G-18-003 的部分区域是 histogram scaffold/近似实现；ATLAS EXOT-2018-60 当前只是注册骨架，published selection 仍待实现。

## 10. 证据索引

- 独立入口与 CLI：ColliderBit/examples/solo.cpp、solo_cli.cpp。
- 输入与 batch：ColliderBit/examples/solo_input.cpp、solo_batch.cpp、CBS_yaml/CBS_update.md。
- JSON 输出：ColliderBit/examples/solo_output.cpp。
- Cutflow：ColliderBit/include/gambit/ColliderBit/Cutflow.hpp。
- Histogram：ColliderBit/include/gambit/ColliderBit/Histogram.hpp、ColliderBit/scripts/plot_cbs_histograms.py。
- VR jet：CBS_yaml/VRjet_update.md、Utils.hpp、BaseCollider、Py8EventConversions。
- 分析注册：ColliderBit/src/AnalysisContainer.cpp、ColliderBit/analyses/*.info。
- 典型分析：Analysis_ATLAS_EXOT_2019_04.cpp、Analysis_CMS_B2G_18_003.cpp、Analysis_ATLAS_SUSY_2018_12_RJR.cpp、Analysis_ATLAS_EXOT_2018_60.cpp。
- 重要提交：8749e3e8e4、061b425740、10018eb86d、de5e879b74、e39afa6ce1、03d5a9e959、ca959103fc、1585caf95b、b581f7130a、ef4107bcf1。

## 11. 需要避免的表述

- 不要把“已注册到 AnalysisContainer”说成“物理分析已完成”。
- 不要把 CMS B2G 的空 obs/bkg 数组说成已完成公开结果复现。
- 不要把 batch 的 per-file loglike 直接相加；当前实现是合并 signal/background 后重新计算组合 likelihood。
- 不要把 master 合并提交计入个人新增功能；应以个人提交和当前代码证据为准。
