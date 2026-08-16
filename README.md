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

图是静态源码证据，不是运行时 trace，也不是完整 C++ AST；CBS 的运行时 functor 图仍应使用 GAMBIT 运行生成的 `.gv` 文件。

## 变更台账（汇报用 slide）

`compare-cbs-branches.py` 把两个 worktree 当成普通文件树来 diff，因此**无法识别重命名**：75 个改名的分析会被报成"左边删除 75 个 + 右边新增 75 个"，凭空放大约 150 个文件的改动量。

`scripts/build-change-ledger.py` 改为直接向 Git 提问，用 `-M` 让 Git 自己做重命名检测，并按文件统计作者归属，避免把从 `master` 合并进来的上游工作算成本地工作：

```bash
python3 scripts/build-change-ledger.py \
  --gambit-root ~/Gambit-Workshop/gambit
```

生成：

- `dependences/cbs-change-ledger.json`：逐文件的改动量、提交数、作者列表和归属分类（`own` / `mixed` / `upstream`）；
- `dependences/cbs-change-ledger.html`：11 页自包含 slide，内联 SVG 流程图，不依赖任何 CDN；按 `P` 展开全部页面以便打印成 PDF。

基线是 `private-SUSYRun2` 与开发分支的共同祖先，而不是 `gambit/master`——因为要回答的问题是"相对合作者手上的源分支我改了什么"。`gambit/master` 已完全合入，分支落后 0 个提交。

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
