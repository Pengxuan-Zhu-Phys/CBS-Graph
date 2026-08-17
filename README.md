# CBS-Graph

Static dependency and C++ call graphs for ColliderBit Solo (CBS).

在线页面：<https://pengxuan-zhu-phys.github.io/CBS-Graph/>

## 项目范围

本仓库保留两类互补的图：

1. **GAMBIT runtime dependency graph** — GAMBIT dependency resolver 在一次具体运行中产生的 `GAMBIT_active_functor_graph.gv`，用于说明实际激活的 functor 依赖。
2. **Meta Glean C++ graph** — C++ 源码级的声明和引用关系，用于追踪 CBS functor 链背后的实现。

Glean 不是运行时图的替代品：Glean 描述源码符号和引用，而 GAMBIT 才知道某次具体运行中哪些 functor 依赖被激活。

仓库中已迁移的 CBS 静态文档和页面包括：

- `index.html`：站点首页
- `dependences/cbs-change-ledger.html`：**变更台账 slide**——`ColliderBit_solo_development` 相对 `private-SUSYRun2` 源分支做了什么，逐文件标注作者归属
- `dependences/cbs-full-execution-flow.html`：CBS 从启动到最终输出的完整流程
- `dependences/main-change-tree.html`：SUSYRun2 原型与当前 CBS 框架的 `main()` 对照
- `dependences/three-analysis-dependency-graphs.html`：三个 ColliderBit 分析的局部依赖图
- `architecture/`、`analyses/`、`build/`、`skills/`：CBS 架构、分析目录、构建记录和开发指南

每个分析尽量同时保留 JSON 和 Mermaid 源文件，便于后续重新生成或扩展可视化。当前页面是基于源码、Clang AST 摘要和 Git 历史整理的静态证据图，不是 profiling，也不是完整 AST 展开。

## 目录结构

```text
config/gambit.env.example       本地路径和数据库配置模板
queries/cxx-declaration-targets.angle
scripts/index-gambit.sh          创建 Glean DB 并导出查询结果
scripts/build-site.py             渲染 .gv 和 Glean 结果到 site/
site/                             GitHub Pages 发布目录
.github/workflows/deploy-pages.yml
```

## 本地 Glean 配置

Glean 上游构建主要在 Linux 上测试。安装 CLI：

```bash
cabal install glean
```

C++ indexer 不是独立的 Hackage 包；从 Glean 源码构建：

```bash
git clone https://github.com/facebookincubator/Glean.git ~/src/Glean
cd ~/src/Glean
make glean-clang
```

复制配置并编辑本地 GAMBIT 路径：

```bash
cp config/gambit.env.example config/gambit.env
${EDITOR:-vi} config/gambit.env
```

至少设置：

```bash
GAMBIT_SOURCE_DIR=/absolute/path/to/gambit
GAMBIT_BUILD_DIR=/absolute/path/to/gambit/build
```

如果 `compile_commands.json` 不存在，辅助脚本会对已有构建目录重新运行 CMake：

```bash
cmake -S "$GAMBIT_SOURCE_DIR" -B "$GAMBIT_BUILD_DIR" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

然后建立索引并导出 C++ 声明目标：

```bash
./scripts/index-gambit.sh config/gambit.env
```

该命令只在本地生成被忽略的 `.glean/` 内容，不会上传源码或 Glean 数据库。

## macOS 分支比较图

如果只需要比较两个 CBS worktree，不必安装 Glean。`scripts/compare-cbs-branches.py` 使用 Git 快照、局部 `#include`、分析注册宏、CMake 源文件引用和可识别的 C++ 函数调用生成静态关系图，适合直接在 macOS 上运行。

例如比较 ColliderBit Solo development 和 SUSYRun2：

```bash
python3 scripts/compare-cbs-branches.py \
  --baseline /Users/P.Zhu/Gambit-Workshop/gambit \
  --comparison /Users/P.Zhu/Gambit-Workshop/worktree/SUSYRun2 \
  --baseline-label ColliderBit_solo_development \
  --comparison-label SUSYRun2
```

默认生成：

- `dependences/cbs-branch-comparison.json`：完整机器可读图和差异数据；
- `dependences/cbs-branch-comparison.html`：源码目录中的对比页面；
- `dependences/CBS_BRANCH_COMPARISON.md`：变更摘要；
- `site/cbs-branch-comparison.html`：可直接交给 GitHub Pages 的自包含页面。

### 聚焦单个源文件

对于 1000+ 节点的大分支差异，使用聚焦比较器只展开一个源文件、它的直接 include 表面和函数级变化。当前的 `solo.cpp` 页面由下面的命令生成，之后可以替换 `--focus-file` 比较其他文件：

```bash
python3 scripts/compare-cbs-focus.py \
  --baseline /Users/P.Zhu/Gambit-Workshop/gambit \
  --comparison /Users/P.Zhu/Gambit-Workshop/worktree/SUSYRun2 \
  --focus-file ColliderBit/examples/solo.cpp \
  --baseline-label ColliderBit_solo_development \
  --comparison-label SUSYRun2
```

输出包括：

- `dependences/cbs-solo-comparison.html`：聚焦的 diagram-design 页面；
- `dependences/cbs-solo-comparison.json`：函数、include、模块和 unified diff 数据；
- `dependences/CBS_SOLO_COMPARISON.md`：文本摘要；
- `site/cbs-solo-comparison.html`：GitHub Pages 页面。

图是静态源码证据，不是运行时 trace，也不是完整 C++ AST；CBS 的运行时 functor 图仍应使用 GAMBIT 运行生成的 `.gv` 文件。

### JSON 输出契约

`private-SUSYRun2` 完全没有 JSON 输出（连 `Utils/include/gambit/Utils/json.hpp` 都不存在，`solo.cpp` 里 `json` 出现 0 次），所以这一页不是对比，而是**只介绍新的**输出编排：

```bash
python3 scripts/build-json-output-page.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

页面上的每个 key、字段、行号都是生成时从 `solo_output.cpp` 和 `solo_batch.cpp` 里抽取的，不是手写的，因此不会随源码改动而悄悄失效。脚本还会算出一件手写文档算不出来的事：**batch 合并到底读回了哪些字段**——因为 batch 模式下 per-file JSON 就是子进程回传结果的唯一通道，被读回的字段改名会直接弄坏 batch，而不只是弄坏下游画图脚本。

生成：

- `dependences/cbs-json-output.html`：输出契约页面；
- `dependences/cbs-json-output.json`：抽取出来的字段表、读回集合、合并守卫；
- `dependences/CBS_JSON_OUTPUT.md`：文本摘要；
- `site/cbs-json-output.html`：GitHub Pages 页面。

### FastJet / fjcontrib 构建集成

这一页是**三方对比**，不是两方：上游 `master` 只有 fjcore，`private-SUSYRun2` 用下载编译的 FastJet 把它替换掉，本分支两个都留、在 configure 时选。只跟 SUSYRun2 比的话，"恢复 fjcore"会看起来像新功能，其实是回到 master 的行为。

```bash
python3 scripts/build-fastjet-cmake-page.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成：

- `dependences/cbs-fastjet-cmake.html`：8 个编号改动，每个带两侧真实源码摘录；
- `dependences/cbs-fastjet-cmake.json`：link flag、gate 条件、消费点、符号用量、提交历史；
- `dependences/CBS_FASTJET_CMAKE.md`：文本摘要；
- `site/cbs-fastjet-cmake.html`：镜像页面。

该区块是**重写**而不是逐行修改，所以 unified diff 会塌成一个 hunk、分不开任何东西；因此编号卡片展开的是两侧源码摘录，完整 region diff 仍放在页面最后一节。

页面点名了一个要对合作者讲清楚的事：CMake 不再下载 FastJet，而 `.gitignore` 里 `contrib/fastjet-*/`、`contrib/fjcontrib-*/` 的规则还在，两者都是 0 个文件入库。**新 clone 上探测失败，`else()` 分支不打印任何东西**，构建静默退回 fjcore，第一个可见症状是 Rivet 宣布自己被排除。

### Variable-R jet 流水线

VR jet 是怎么被穿进 ColliderBit 的：依赖什么、经过哪 7 个文件、每一站填了什么、以及**哪四个地方故意不做**。

```bash
python3 scripts/build-vrjet-page.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成 `dependences/cbs-vr-jets.{html,json}`、`CBS_VR_JETS.md` 和 `site/cbs-vr-jets.html`。

一条 VR collection 从 YAML 出发，要活着穿过解析、聚类、味标定、存储、探测器模型和分析 API。7 个文件全是**就地修改**（+334 / −97），没有一个新文件——因为固定 R 的行为每一步都得继续正常工作。

页面里几个值得注意的点：

- **两条 jet 路径并排对比**（§02）：同一个 collection 循环，12 个阶段逐行对照，判定是算出来的不是写死的——`identical` / `same call` / `differs`。结论：分叉只有一个入口（`L220` 的 `is_vr_algorithm`）和一个出口（`L301` 的 `continue`），原有固定 R 那一支在 token 层面 **336 → 336，99.4% 相同**，唯一的差异是 `L308` 两个实参换序，来自一个**无关的 commit**（修 FastJet 弃用签名）。用 token 而不是行来比，是因为这个文件被 clang-format 扫过，行 diff 会报几百处毫无意义的改动。两支最后落在**逐字节相同**的 `result.add_jet(...)` 上：没有新类型、没有新容器，下游分不出一个 jet 来自哪一支。
- **依赖只有一个类**：`fastjet::contrib::VariableRPlugin`。它是 FastJet *plugin*，所以链接面必须先长出 `-lfastjetplugins` 和两个 siscone——这就是[构建那一页](#fastjet--fjcontrib-构建集成)必须先发生的原因。
- **味标定用的是 jet 自己的有效半径** `effectiveR = min(Rmax, max(Rmin, rho/pT))`，不是固定锥。
- **四处故意跳过 VR**：parton 级转换、LHEF reader（都没有 track 可聚）、BuckFast 的动量涂抹、以及 BuckFast 清除 |η|>2.5 b-tag 的那一遍。最后一条有后果：VR jet 在任意 η 都保留 b-tag，两个流水线分析自己切了 `abseta() < 2.5` 所以没事，但忘了切的分析会继承本该被探测器模型抹掉的 tag。
- **一个分析绕过了流水线**：`Analysis_ATLAS_SUSY_2018_07` 在分析体内自建 `VariableRPlugin`，rho/Rmin/Rmax 硬编码，YAML 够不着它，也不在任何 opt-out 名单里（no-smear 按 collection 名匹配，而它那个 collection 没有名字）。

## 变更台账（汇报用 slide）

`compare-cbs-branches.py` 把两个 worktree 当成普通文件树来 diff，因此**无法识别重命名**：75 个改名的分析会被报成"左边删除 75 个 + 右边新增 75 个"，凭空放大约 150 个文件的改动量。

`scripts/build-change-ledger.py` 改为直接向 Git 提问，用 `-M` 让 Git 自己做重命名检测，并按文件统计作者归属，避免把从 `master` 合并进来的上游工作算成本地工作：

```bash
python3 scripts/build-change-ledger.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成：

- `dependences/cbs-change-ledger.json`：逐文件的改动量、提交数、作者列表和归属分类（`own` / `mixed` / `upstream`）；
- `dependences/cbs-change-ledger.html`：14 页自包含 slide，内联 SVG 流程图，不依赖任何 CDN；按 `P` 展开全部页面以便打印成 PDF。

基线是 `private-SUSYRun2` 与开发分支的共同祖先，而不是 `gambit/master`——因为要回答的问题是"相对合作者手上的源分支我改了什么"。`gambit/master` 已完全合入，分支落后 0 个提交。

### Histogram 与 Histogram SR（slide 9 + 专页）

```bash
python3 scripts/build-histogram-page.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成 `dependences/cbs-histograms.{html,json}`、`CBS_HISTOGRAMS.md` 和 `site/cbs-histograms.html`。

新增一个头文件 `Histogram.hpp`（678 行），**一个类干两件事**，分界就是一个 vector 空不空：

- **纯 Histogram**（`obs` 为空）：bins / counts / sumw2 / under-overflow。走到 run JSON 和绘图脚本为止，`is_signal_region()` 为 false，下游不会当物理读。`ATLAS_EXOT_2021_35` 用这个。
- **Histogram SR**（带 `obs` / `bkg` / `bkg_err`）：`to_signal_regions()` 把每个 bin 变成一个 `SignalRegionData`，名字 `<hist>_bin<i>`，带该 bin 的观测数、自身内容作为信号、发表的本底，以及 `sqrt(sumw2)` 作为 MC 统计误差。`ATLAS_EXOT_2019_04`（m_VLB，7 bins）和 `ATLAS_EXOT_2019_07`（m_JJ，16 bins）用这个。

**要当面讲的一条**：`check_histogram` 从 YAML 读进来（`solo.cpp:179`），**默认 false**，而且同时管着 booking、filling 和 committing。所以在上面两个分析里它决定的不是"出不出图"，而是**有几个 signal region**——一共 23 个额外区域。名字像诊断开关，实际动的是 likelihood；同一份 YAML 翻转这个 flag 的两次运行不可比。

另外，`ATLAS_EXOT_2019_07` 里还留着 **16 行注释掉的手写 per-bin `add_result`**（L313–328），观测数和本底都是硬编码字面量——那就是这套机制替换掉的东西，before/after 在同一个文件里看得见。

### 命名迁移（slide 10 + 专页）

分析从"描述看什么"的名字迁移到论文报告号。

```bash
python3 scripts/build-rename-migration-page.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成 `dependences/cbs-rename-migration.{html,json}` 和 `CBS_RENAME_MIGRATION.md`。

**关键：文件数低估了这次迁移。** 两个层级的数不一样，而且只有一个是用户会踩到的：

| 层级 | 数 |
|---|---|
| git 认定的重命名 | 75 |
| 带 `// Renamed from:` 记录的文件 | 80 |
| 其中 1:1 | 62 |
| 其中合并（N:1） | 18 个文件吸收了 56 个旧文件 |
| 注册分析名（baseline → head） | 128 → 137 |
| **退役的名字** | **123** |

**注册名才是 YAML 里写的东西**（`DEFINE_ANALYSIS_FACTORY` 发出来的），一个文件可以注册多个——所以差距在那 18 个合并文件上：合并不是重命名，git 会把幸存者报成 modified、其余报成 deleted。**没有分析丢失**，每个子区域仍然独立注册，只是搬进了报告号文件里。

另外两条：

- `ATLAS_8TeV_1LEPbb_20invfb` 是唯一保留旧名的物理分析，文件里写了原因：`:D unrenamed, can not find original exp report`。留例外就该这么留——下一个人不用猜是漏了还是故意的。
- `yaml_files/PX_SUSYRun2_stop.yaml` 里还有 **48 个已经不存在的分析名**，今天跑会在 configure 阶段就挂。这是仓库内部的证据，说明仓库外每一份按名字选分析的配置都有同样的问题、而且没有任何警告。

### 用户 YAML：默认卡片（slide 6）

以前一个文件写全部设置，每次运行都要重复 `jet_collections`（`ATLAS_EXOT_2019_04` 光 jet 配置就 **22 行**，三个 collection）。现在三层合并，**用户永远覆盖**：

1. `CBS_defaults.yaml → settings:`（全局）
2. `CBS_defaults.yaml → analysis_defaults: <分析名>:`（**每个分析一张默认卡**，按 YAML 里分析出现的顺序合并）
3. 用户输入文件

`merge_yaml_nodes`（`solo_input.cpp:62`）对 map 递归下去，但**标量和序列是整体替换**——覆盖列表可以，往列表里追加不行。

结果：`CBS_yaml/ATLAS_EXOT_2019_04.yaml` 里 jet 配置 **22 → 0 行**，连分析依赖的那个 VR collection 都不用写。

**但默认文件本身没进仓库。** `.gitignore:50` 忽略 `CBS_yaml/*`，`git ls-files CBS_yaml/` 是空的。新 clone 上五个查找位置全落空，`apply_default_settings` **静默**原样返回用户设置（`solo_input.cpp:130`），最后死在 `Utils.hpp:96`：*"Could not find jet_collections option. Please provide this in the YAML file"*——**把用户指向他自己的文件，而不是缺失的默认文件**。和 FastJet 探测那条是同一个形状。

### 依赖矩阵（slide 12）

哪些程序包相对 `gambit/master` 和 `private-SUSYRun2` 有更新：

```bash
python3 scripts/build-package-matrix.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成 `dependences/cbs-package-matrix.json`。脚本**分别读四个声明源**，因为它们可能互相矛盾：`cmake/backends.cmake`（实际下载哪个版本）、frontend 头文件名（GAMBIT 声称能对话的版本）、`backend_types/<name>_<ver>/`（BOSS 生成的封装树）、`Backends/patches/<name>/<ver>/`（构建必须存在的补丁目录）。

归属判定不靠人工判断：一个路径**相对 master 非零、相对 merge-base 恰好为零**，就说明这活是 SUSYRun2 干的、我们原封不动继承。

结论：

- **Rivet 3.1.5 → 4.1.0** 是唯一一次真正的版本升级，BOSS 封装重新生成（14 文件 +1,045/−803），继承自 SUSYRun2。
- **Pythia 8.312 三边一致**——版本没动，动的是 patch 和 frontend（SUSYRun2 的），以及 BOSS 封装（相对两边都是 +14/−14，这是我们的）。
- **FastJet / fjcontrib 从 `backends.cmake` 里整个删掉**，改由 `contrib.cmake` 探测预装的 3.4.2 / 1.049。
- **Contur 在 HEAD 是坏的**：`backends.cmake:2185` 写 `2.1.1` 并指向一个**树里不存在**的补丁文件，而 frontend 是 `Contur_3_0_0.hpp`、patch 目录只有 `3.0.0/`。`git log -L` 定位到 `3d9ebcb490 "Fixing very minor merge conflicts"`——合并时这一块取了 master 的一侧，frontend 和 patch 树留在 SUSYRun2 一侧。master、merge-base、SUSYRun2 tip 三边各自都自洽，只有 HEAD 是劈开的。

台账只反映**代码变化**，不反映**物理结果变化**：过程中没有重新编译或运行 CBS。

## 生成 GitHub Pages 页面

先使用目标 CBS 配置运行 GAMBIT，使其生成 `GAMBIT_active_functor_graph.gv`，再渲染两层图：

```bash
python3 scripts/build-site.py \
  --gambit-root "$GAMBIT_SOURCE_DIR" \
  --glean-json .glean/cxx-declaration-targets.json \
  --source-ref "$(git -C "$GAMBIT_SOURCE_DIR" rev-parse --short HEAD)"
```

脚本会自动搜索 `scratch/run_time/` 下的 runtime graph，也可以用 `--graphviz-file` 指定文件。生成的 `site/` 是 GitHub Pages 的发布内容；提交前请检查其中是否包含不应公开的本地路径或符号名。

本地预览：

```bash
python3 -m http.server --directory site 8000
```

## GitHub Pages 发布

1. 在仓库 Settings → Pages 中选择 **GitHub Actions**。
2. 将审核后的 `site/` 内容提交并推送到 `main`。
3. `.github/workflows/deploy-pages.yml` 会发布 `site/`。

工作流不会在 GitHub 上重新运行 Glean 或编译完整 GAMBIT；索引数据库和完整构建属于本地/CI 输入，公开仓库只发布轻量的图形展示文件。

## 方法边界

- runtime `.gv` 是解释一次运行中实际 functor 依赖的主要依据。
- Glean 图是静态 C++ 声明/引用视图，不是运行时数据溯源图。
- 当前版本发布 SVG 和少量 JSON 摘要，不发布 Glean 数据库本身。
- 进行 before/after 比较时，应使用相同 CBS 输入分别生成两套 artifact，再增加差异图层。

上游参考：[Glean](https://github.com/facebookincubator/Glean)、[C++ indexer](https://glean.software/docs/indexer/cxx/)、[Glean CLI](https://glean.software/docs/cli/) 和 [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-actions)。
