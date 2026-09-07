# Changelog — tcms-ai-platform

版本单一真源在 `src/tcms_ai_platform/_version.py`；本文件记录用户可见变更。

## 0.2.0 (2026-09)

- **版本语义拆分**：`/api/health` 现在返回双段版本——`version`(平台自身) / `engine_version`(上游 tcms 引擎)；总览不再把平台版本误标为引擎版本。
- **总览状态条**："平台运行中 · v0.2.0 · 引擎 vX / 引擎未接入"，区分平台与上游引擎。
- 从 0.1.0 bump（前 29 commits 未动版本号）。

### 0.1.0 里程碑回顾（前 29 commits，版本号当时未演进）

- P1–P5：资产模型/知识底座/前端 MVP/Agent Harness/打磨（详见 git 历史与 docs/PLAN 系）。
- r2/r3：手动编排、AI 编排顾问、动画资产化、双主题、图谱 2D/3D、ai-testgen 并入、RAG 无匹配建议。
