# CBS Graph

静态展示 GAMBIT ColliderBit Solo（CBS）依赖关系、执行流程和源码修改范围的独立项目。

## 在线页面

GitHub Pages：<https://pengxuan-zhu-phys.github.io/CBS-Graph/>

主要入口：

- `index.html`：站点首页
- `dependences/cbs-full-execution-flow.html`：CBS 从启动到最终输出的完整流程
- `dependences/main-change-tree.html`：SUSYRun2 原型与当前 CBS 框架的 `main()` 原子级对照
- `dependences/three-analysis-dependency-graphs.html`：三个 ColliderBit 分析的局部依赖图

## 迁移的 CBS 文档

`architecture/`、`analyses/`、`build/`、`skills/` 以及根目录中的旧版调用关系和汇报底稿，来自原 Gambit 工作区的 `gambit/P.Zhu/docs/`。`GAMBIT_DOCS_AGENTS.md` 是原文档库的 agent 说明副本，不作为本图形仓库的活动规则文件。

## 数据文件

每个分析同时保留 JSON 和 Mermaid 源文件，便于后续重新生成或扩展可视化：

- `dependences/CBS_full_execution_dependency.json` / `.mmd`
- `dependences/ATLAS_EXOT_2019_04_dependency.json` / `.mmd`
- `dependences/ATLAS_SUSY_2018_05_dependency.json` / `.mmd`
- `dependences/CMS_B2G_18_003_dependency.json` / `.mmd`

## 方法边界

这些图是基于源码、Clang AST 摘要和 Git 历史整理的静态证据图，不是运行时 profiling，也不是完整 AST 展开。CBS 不需要在这个项目中重新编译；图页面可以独立发布到 GitHub Pages。

原始工作来自 GAMBIT 工作区中的 `gambit/P.Zhu/docs/dependences/`，当前项目用于独立维护和发布图形文档。
