# ColliderBit-Solo 汇报逐页逐字稿

适用材料：

- 主汇报页：`dependences/cbs-change-ledger.html`
- 对应技术说明：`dependences/cbs-yaml-config.html`、`cbs-json-output.html`、`cbs-histograms.html`、`cbs-vr-jets.html`、`cbs-fastjet-cmake.html`、`cbs-rename-migration.html`、`cbs-solo-comparison.html`

以下内容按 14 页排列，可以直接照读。代码名、分支名和提交号保留英文原文。

## 第 1 页：What CBS changed

大家好，我是 Pengxuan Zhu。今天在 ColliderBit-Solo Meeting 里，我想汇报一下 ColliderBit-Solo，也就是 CBS，相对于 SUSYRun2 原型分支到底改变了什么。

这次汇报不是简单展示一个文件 diff，而是建立一份可以核对的变更台账。比较的对象是当前的 `ColliderBit_solo_development`，以及它发展出来的源分支 `private-SUSYRun2`。同时，我把已经从 `gambit/master` 合并进来的上游工作单独分离出来，不把它们全部算成 CBS 本地工作。

从整体数字看，共有 416 个文件发生变化。其中 147 个文件只由本地工作触及，75 个分析文件发生了重命名，另外新增了 12 个分析。12 个新增分析里，10 个已经实现，1 个是部分实现，1 个目前只是 skeleton。

这页下面给出了几个重要的版本锚点：当前分支是 `ColliderBit_solo_development`，基线是 `private-SUSYRun2`，共同祖先是 `9c955e3a7`，而 `gambit/master` 已经完全合入当前分支。

所以今天的核心问题不是“代码增加了多少行”，而是三个问题：哪些是 CBS 真正新增的能力，哪些是继承来的上游工作，以及当前新增能力中哪些已经完成、哪些还需要继续验证。

## 第 2 页：What counts as “my change”

第二页先说明统计方法，因为如果不先说明归属，后面的数字很容易被误读。

当前分支相对于 master 多出了 606 个提交，但其中只有 226 个提交是由本地开发者完成的。因此，我没有简单地把整个分支的所有变化都叫作“我的修改”，而是按照文件级别的提交历史做归属。

这里分成三类。第一类是 local，共 147 个文件：从共同祖先开始，触及这些文件的提交全部来自本地工作。第二类是 mixed，共 87 个文件：文件同时被本地工作、合作者或者上游提交修改，需要逐行讨论，不能整体认领。第三类是 upstream，共 174 个文件：它们只是通过 master merge 进入当前分支，所以在汇报中列出，但不算作 CBS 本地工作。

这里还要解释为什么本页旁边的 branch-comparison 图不能直接作为最终统计。普通的树状 diff 没有 rename detection，所以 75 个重命名分析会被看成左边删除 75 个、右边新增 75 个，表面上凭空增加大约 150 个文件。这个台账使用 Git 的 `-M` 重命名检测，因此一个重命名只计作一个移动文件。

最后强调证据边界：这些数字来自 Git 历史和当前源码文本。这次没有重新编译，也没有重新运行 CBS，所以它说明的是“代码改了什么、谁改的”，不是“物理输出已经改变了多少”。

## 第 3 页：From a GAMBIT module to a standalone runner

第三页看整体架构变化。

左边是 SUSYRun2 原型。它依赖完整的 GAMBIT scan configuration，包括 scanner、priors、printers 和 dependency resolver。ColliderBit 的物理层位于整个 GAMBIT 工作流里面，最后由 GAMBIT printers 输出结果。

右边是当前的 ColliderBit-Solo。CBS 增加了自己的 `solo_cli` 和 `solo_input`，负责命令行校验、YAML 读取、process 和截面处理；增加了 `solo_batch`，把多个 HepMC 文件拆成独立子任务；最后由 `solo_output` 生成统一的屏幕摘要和 JSON 文件。

这里最重要的一点是，绿色的物理层仍然是复用的 ColliderBit 物理框架：HepMC 转换成 HEPUtils event，经过 BuckFast 和 jet 处理，进入 `AnalysisContainer::analyze()`，最后连接到 signal regions 和 `LHC_likelihoods`。CBS 的主要变化集中在物理层外面，也就是入口、输入、批处理、结果合并和序列化。

因此，CBS 的定位不是重新实现一套物理分析，而是把原来必须依赖完整 GAMBIT 启动的 ColliderBit 分析，包装成一个可以独立运行、可以批处理、可以输出固定数据契约的工具。

## 第 4 页：Where the changes landed

第四页把改动按功能区域展开。

首先是 CBS standalone runner。这里有 8 个 local 文件、2 个 mixed 文件，增加了大约 2,978 行，且没有 upstream contribution。这部分包括 `solo_cli`、`solo_input`、`solo_batch` 和 `solo_output`，是当前分支最主要的结构性新增。

第二部分是 event 和 jet pipeline，有 10 个 local 文件和 4 个 mixed 文件，增加大约 1,098 行，也没有 upstream contribution。variable-R jet 就是在这条路径上被接入的。

第三部分是 result framework，包括 Cutflow、Histogram 和相关宏。这里有 local、mixed 和 upstream 混合贡献。需要特别注意的是，原始 diff 中的 26,653 行不能直接当作手写框架工作量，因为其中 25,510 行是 vendored 的 `nlohmann/json.hpp`。真正手写的结果框架大约是 1,143 行。

分析层共有 109 个 local、53 个 mixed 和 17 个 upstream 文件，包含 12 个新增分析、75 个重命名、3 个修改和 3 个删除。最后，YAML、scripts、build、backends 和 configuration 这些区域的贡献相对混合，尤其是 build 部分主要是协作完成的。

所以读这张表时，应该优先看“功能区域”和“归属”，而不是只看某一行的 raw line count。

## 第 5 页：The standalone runner

第五页进入 CBS runner 的内部结构。

程序首先经过 `solo_cli`。它负责解析 `argv`，处理 `--help`，拒绝未知参数，并在多次调用或批处理场景中正确重置 `getopt` 状态。

然后是 `solo_input`。它把 YAML 转换成统一的 `PreparedInput`，检查分析名称、事件文件是否存在、process 配置是否完整，并处理 fb 或 pb 单位的截面和不确定度。

之后分成两条执行路径。如果是单文件模式，就直接使用 `settings.event_file`；如果是 batch 模式，就进入 `solo_batch`，把每一个物理 HepMC 文件变成一个 subprocess。这里的“一个文件一个子进程”不是把所有文件同时塞进同一个 event loop，而是先逐文件执行，再在 CBS 层做结构化合并。不同文件仍然保留所属 process 的完整截面信息。

合并时，CBS 会验证 luminosity、background、signal-region 标签顺序以及 histogram 结构。相同 process 的结果按事件数加权；不同 process 的贡献按照相应的统计和不确定度规则合并。最后重新计算 combined likelihood，而不是直接把每个文件的 log-likelihood 相加。

输出阶段由 `solo_output` 负责，生成屏幕摘要和 `cbs-solo-loglike-v1` JSON。batch 结果还会给出有效事件数、目标误差以及建议补充多少事件。

这说明 CBS 已经从“单个 HepMC 文件的 runner”变成了可以处理生产样本的 batch runner。

## 第 6 页：The user YAML, and what left it

第六页看用户真正需要写的 YAML，以及哪些设置已经不再由用户决定。

先看数量：原始配置里有 29 行有效 settings，当前示例是 17 行。这个数字不代表所有功能都被删除了，而是很多控制项转移到了程序默认值、默认卡或者 CBS 自己的运行策略中。

这里有一个 jet 配置的口径需要特别说明。历史 standalone 示例的最小文件里没有把 `jet_collections` 写出来，但旧版 `solo.cpp` 实际上通过 `getValue` 要求这个配置存在。因此，在对应的 YAML HTML 页面里，我把旧 standalone 所需的 `jet_collections` 和 `jet_collection_taus` 直接放进同一个 before 示例块，并给出了 `antikt_R04` 的完整例子。换句话说，它不是 dead key，也不是旧版完全不支持 jet；旧版是要求用户显式写，当前 CBS 则可以由 `CBS_defaults.yaml` 代为提供。

第一类是仍然由用户提供的内容，主要是 event source 和 cross-section。第二类是 optional program defaults，也就是 `getValueOrDef` 读取的可选标量；如果 YAML 没写，就使用代码或 default card 的值，但这不会把真正必需的输入变成可选。

第三类是 CBS policy。`solo.cpp` 会把下面三个值直接写入运行选项：`min_nEvents` 设为 1000，`max_nEvents` 设为 `INT_MAX`，`run_convergence_checks` 设为 false，也就是把用户提供的事件全部处理完。这里的 convergence 相关设置可能仍然能够解析，但已经不能改变 CBS 的停止行为。

另外三个 dead keys 是 `covariance_marg_convthres_abs`、`covariance_marg_convthres_rel` 和 `covariance_nsamples_start`。当前 C++ 源码里没有 reader，所以它们不是“被 CBS 强制覆盖”，而是根本没有代码读取。

最后要提醒的是，`CBS_defaults.yaml` 本身不在仓库里，`CBS_yaml/*` 被 `.gitignore` 忽略。新 clone 如果没有这张 default card，默认合并会静默失败，之后在 `Utils.hpp:96` 读取 `jet_collections` 时才报错。因此 required jet configuration 在最终合并设置中仍然必须存在。

## 第 7 页：Results became a data contract

第七页讲结果框架。

在原来的结构里，cutflow、histogram 和 signal region 更多是各个分析内部的 C++ 对象和约定。CBS 把它们抽成共享类型，并通过一个有版本号的 JSON schema 输出。

事件循环中，分析可以同时产生 cutflow、histogram 和 signal regions。`Cutflow.hpp` 统一了 `fillinit`、`fill` 和 `commit` 的生命周期；`Histogram.hpp` 支持加权填充、`sumw2`、underflow、overflow、scale 和 combine；如果 histogram 同时带有 `obs`、`bkg` 和 `bkg_err`，还可以通过 `to_signal_regions()` 直接把每个 bin 转换成一个 signal region。

这些结果进入 `AnalysisData`，并且一起执行 scale 和 reset。最后 `solo_output` 写出 `cbs-solo-loglike-v1`，其中包含 metadata、luminosity、signal-region yields、MC 统计误差、covariance 和 log-likelihood。

实际效果是，一次 event pass 可以同时生成 cutflow、cut-and-count signal regions 和 shape histograms，后处理绘图不需要重新读取 HepMC。

这里的 JSON 不只是日志，而是一个数据契约。它让 batch merge、Python 绘图和后续报告都可以消费同一份结构化结果；而 SUSYRun2 原型没有对应的 JSON 输出体系。

## 第 8 页：Twelve new analyses

第八页进入具体物理分析层。

当前分支新增了 12 个分析，其中 10 个已经实现并注册，1 个是 partial recast，1 个是 skeleton。这里我不逐行朗读表格，而是强调这三个状态不能混为一谈。

已经完成的分析覆盖了三轻子电弱过程、multilepton、boosted boson、Recursive Jigsaw、large-R jet、VLQ、variable-R track jet 和 shape variables。例如 `ATLAS_EXOT_2019_04` 使用 VLQ 选择、`VRTrackJets` 和 `m_VLB` histogram signal regions；`ATLAS_SUSY_2018_12_RJR` 使用 RestFrames 和 Recursive Jigsaw；`CMS_B2G_18_003` 则接入了 SoftDrop、N-subjettiness 和部分 shape signal regions。

分析注册本身也发生了变化。`AnalysisContainer.cpp` 增加了新的 factory 注册，另外有 3 个旧分析被重命名或被新的等价实现替代。

这里还要区分上游带来的大文件，例如 `Analysis_Baselines.cpp`。它虽然会影响总行数，但并不是当前 CBS 分支本地新增的物理工作。

所以这页的结论是：分析数量增加说明框架覆盖面扩大了，但“已经注册”不等于“已经完整复现论文结果”。下一页和第 13 页会继续拆开这个区别。

## 第 9 页：Histograms, and histogram signal regions

第九页是一个非常关键的框架变化：同一个 Histogram 类有两种用途。

第一种是普通 histogram。此时 `obs` 为空，它保存 bins、weights、underflow 和 overflow，会写进 JSON，也会被绘图脚本读取，但 `is_signal_region()` 为 false，所以它不会进入 likelihood。`ATLAS_EXOT_2021_35` 就使用这种模式，把 `mVLQlep` 分布作为诊断信息，同时保留原来的 cut-and-count signal regions。

第二种是 histogram signal region。此时同时提供 `obs`、`bkg` 和 `bkg_err`，`to_signal_regions()` 会把每个 bin 变成一个 `SignalRegionData`，名字是 `<hist>_bin<i>`。每个 bin 有自己的 observed count、signal 内容、发表的 background 和 MC 统计误差。

这个机制让 `ATLAS_EXOT_2019_04` 的 `m_VLB` 从 1 个基础 SR 扩展为 8 个 SR，让 `ATLAS_EXOT_2019_07` 的 `m_JJ` 从 1 个扩展为 17 个 SR，总共增加 23 个 histogram-derived signal regions，也替换了原来手写的 16 行 per-bin `add_result`。

需要特别说清楚 `check_histogram`。它在 `solo.cpp:179` 读取，默认值是 false，而且同时控制 booking、filling 和 committing。因此对这两个分析来说，它不只是“要不要画图”的诊断开关，而是决定 likelihood 中有多少个 signal regions。打开和关闭这个 flag 的两次运行，物理输出不能直接比较。

## 第 10 页：The naming migration

第十页讲分析命名迁移。

分析名称从描述“它看什么”转向使用论文的 publication report number。Git 检测到的是 75 个文件重命名，但 YAML 真正写入的是 `DEFINE_ANALYSIS_FACTORY` 注册出来的字符串；一个文件可以注册多个分析，因此注册名称层面的数字是 128 个旧名称、137 个当前名称，其中 123 个旧名称已经退休。

75 个文件和 123 个名称同时正确，原因是有 18 个 consolidation：一个新文件吸收了多个旧分析，涉及 56 个旧文件。Git 会把 survivor 视为 modified，把其他文件视为 deleted，但这并不等于物理分析丢失；它们仍然作为不同 sub-region 注册在新的 report-number 文件里。

有一个分析保留了旧名字：`ATLAS_8TeV_1LEPbb_20invfb`。源码明确写着找不到原始实验报告，所以没有强行重命名。这种例外是有证据的，而不是遗漏。

迁移的实际代价是旧配置。比如 `yaml_files/PX_SUSYRun2_stop.yaml` 仍然引用 48 个已经不存在的分析名称，今天配置时会失败。这里需要合作者决定：是否接受 report-number 命名，是否需要一个过渡期 alias table，让旧 YAML 至少还能工作一个 release。

## 第 11 页：Variable-R jets, threaded end to end

第十一页讲 variable-R jet。

以前 variable-R jet 更像是某些分析内部自己构造的对象；现在它可以从 YAML 声明，并沿着和 fixed-R jet 相同的转换路径传递。数据流是：YAML 中的 `VRJet_collections` 或 `VRTrackJets`，进入 `Utils.hpp` 的 collection registry，再进入 `Py8EventConversions` 的 `VariableRPlugin` clustering，经过 BuckFast，最后作为命名的 HEPUtils jet collection 提供给分析。

这部分大约增加 1,098 行，并且没有 upstream contribution。batch 模式还会把 VR 配置传递到每个 per-file YAML，避免子进程丢失 collection。

构建侧也有变化：FastJet 和 fjcontrib 不再由仓库自动下载和构建，而是在 configure 阶段探测预装版本，然后链接对应的 FastJet 和 fjcontrib 库。

这里要说清楚一个 caveat：部分 Pythia wrapper 的 VR overload 仍然有限，所以分析应该使用 YAML 声明的 collection，而不要在分析内部重新构造一套不受框架管理的 VR jet。`ATLAS_EXOT_2019_04` 和 `ATLAS_EXOT_2019_07` 是沿着公共 pipeline 使用的例子。

## 第 12 页：Which packages moved, and who moved them

第十二页检查 backend 和 package 依赖。

这里同时查看四个来源：CMake 声明、frontend header、BOSS wrapper tree 和 patch directory。大多数 package 在不同来源之间是相互一致的，但 Contur 暴露出一个需要行动的问题。

Rivet 从 master 的 3.1.5 变成 4.1.0，这个升级已经在 SUSYRun2 完成，当前 CBS 只是继承。Pythia 版本一直是 8.312，但 wrapper 和 patch 有不同来源的修改。FastJet 和 fjcontrib 不再在 `backends.cmake` 中声明为下载型 backend，而是由 `contrib.cmake` 探测机器上预装的 3.4.2 和 1.049。

Contur 的问题是当前 HEAD 不自洽：CMake 在 `backends.cmake:2185` 里仍然声明 2.1.1，并且指向不存在的 2.1.1 patch 文件；但树里实际只有 3.0.0 patch directory，frontend 也是 `Contur_3_0_0.hpp`。因此这不是一个单纯的版本说明，而是一个需要修复的 build blocker。

另外，CBS 新增了 vendored 的 `nlohmann/json.hpp`，约 25,500 行。汇报时要把它单独说出来，避免合作者把这部分第三方 header 误认为物理代码。

## 第 13 页：What is not finished

第十三页专门划出完成边界。

第一，`ATLAS_EXOT_2018_60` 目前只有 38 行，`run()` 仍然是 TODO，`collect_results()` 为空。它已经完成了注册和 metadata，但还没有 published selection 和 signal-region yields，所以只能叫 skeleton。

第二，`CMS_B2G_18_003` 是 partial。3M 区域已经使用从 Fig. 4(c,d) digitise 的 five-jet-mass histogram signal regions，但 3T 和 2M1L 仍然有空的 `obs` 和 `bkg` vectors。高质量区域目前是公开的 cut-and-count approximation，不是完整的 CMS shape fit。

第三，B2G 中的 soft-drop subjet b-tag 使用了 AK4-associated proxy subjets。这是一个 documented public-recast approximation，应该明确称为近似，而不是说已经复现了实验内部的 b-tagging。

因此在汇报中不要把“已经注册到 `AnalysisContainer`”说成“分析已经完成”，不要把空的 histogram arrays 说成完整 reproduction，也不要把相对于 master 的 313,000 行直接当作物理工作量，因为其中主要是 background JSON 和 vendored header。

还要再次强调，这次检查没有重新编译或运行。对于已有分析，CBS 主要改变调用方式；但对于新分析，“代码已经存在”和“结果已经与论文一致”是两个不同的命题，目前这里只证明了前者的一部分。

## 第 14 页：Where this goes

最后一页总结后续方向，并把需要合作者决定的事项和已知工作分开。

第一项需要协作决定的是命名迁移。我们是否希望 upstream 接受 report-number naming？如果接受，是否需要 alias table，让旧 YAML 在一个过渡 release 中继续工作？第二项是 CBS runner 本身：`solo_*` 应该提交回 master，还是暂时作为 ColliderBit 的独立分支工具？

已知工作包括完成 `ATLAS_EXOT_2018_60` 的 published selection，补齐 B2G-18-003 的 3T 和 2M1L digitisation，增加 JSON schema 的 regression tests，并在 `.info` metadata 中显式区分“registered”和“validated”。

这条分支没有重写已有 ColliderBit 物理分析。CBS 改变的是调用方式：增加独立 runner、独立输入和独立输出。最能说明这一点的是 fixed-R jet conversion：前后都是 336 个 token，99.4% 保持一致；variable-R 是沿着这条已有路径接入的，而不是另建一条物理流水线。

所以最后给合作者留下的问题不是“旧结果是不是因为 CBS 被改写了”，而是“新增能力本身是否正确”：12 个新增分析、variable-R jet、histogram signal regions 和 batch merge 是否都经过充分验证。第十三页已经把目前还没有建立的部分明确列出来。

我的汇报到这里。谢谢大家，下面我可以按文件、函数或者某一个分析的 HTML 证据页继续展开。

## 备用转场句

- 从统计方法进入架构：`“前面说明了这些数字如何归属，下面看这些修改在程序结构中具体落在哪里。”`
- 从架构进入 runner：`“绿色部分仍然是 ColliderBit 物理层，下面只展开右侧新增的 CBS 外壳。”`
- 从 runner 进入 YAML：`“有了新的入口以后，最直接的问题就是用户现在到底需要写哪些配置。”`
- 从结果框架进入分析：`“框架已经能输出统一结果，下面看这些接口被哪些具体分析使用。”`
- 从完成内容进入边界：`“前面讲的是已经建立的能力，下一页专门说明哪些地方还不能称为完成。”`
- 结束：`“因此这是一套已经可以运行和审计的框架，但物理复现完成度仍然需要按分析逐项确认。”`
