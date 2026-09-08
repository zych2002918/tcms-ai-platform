# Q2-Q4 路线图验收台账（ACCEPTANCE LEDGER）

> 对应 `docs/ROADMAP_Q2Q4.md`；每个可自动验证的门禁给出**实测证据**与提交点。
> 结论先行：**步骤 ①-④ 与 ⑤ 的自动化部分全部完成且双侧测试全绿**；
> ⑤-c/d（fresume 式产品化打磨与浏览器 e2e）为 UI/环境类**迭代清单**，不属自动测试门禁，
> 范围与理由见文末「遗留范围」。

## ① 收尾提交 + ai-testgen 回归 ✅

| 验收 | 证据 |
|---|---|
| 上游原子提交 | `d5205a5 feat` + `dddbc02 docs`（main；后随 ③/④ 多笔推进至 v1.12.0） |
| 平台原子提交 | `d3b7f7b feat` + `1018899 docs`（master；后随多笔至 v0.4.0） |
| ai-testgen 独立 venv 回归 | `ai-testgen/.venv`：**136 passed / 28 skipped**（引擎多网段改动后复测仍绿） |
| 版本链 | `/api/health` version=0.4.0 · asset=0.4.0 · engine=1.12.0（loader 默认 platform_version 单一真源 _version） |

## ② Q4 分层有界检索 ✅

| 验收 | 证据 |
|---|---|
| 13 域分区铺全 | domain_systems.json 每 system 增 `domain`；故障 202/202、报文 22/22、信号 116/116、场景 103/103、功能 11/11 全分区（空域仅 10 个基础设施类 SR，断言=精确集合） |
| 检索链路 | 词表路由(13 域) → 图谱定位域兜底（belongs_to 系统边 + 中文字符重合闸门）→ 域内 topk → 无域/不足回退全局（mixed 标注） |
| 指标 | `route_source`(terms/graph/'') + `route_precision`（域查询 =1.0，测试锁定） |
| HTTP 实测 | `空调压缩机过流→routed=[hvac] prec=1.0`；`今天天气不错→unbounded` |
| 测试 | `tests/test_knowledge.py`（含分区/路由/图谱兜底单元） |

## ③ Q2-P-A 第二增量扩库（全部 ✅，v1.12.0 / v0.4.0）

| 子项 | 实测 |
|---|---|
| ③-a FMEA | **66 → 202**（13 系统域全覆盖；12 字段/SIL≥3 detect/inject 完整性断言通过） |
| ③-b 场景 | **25 → 103**（全部可执行、无孤儿故障不变量） |
| ③-c 多网段 | DBC `GenMsgSegment` 单一真源：vehicle 13 / comfort 7 / backbone 1；网段级可调度 vehicle 9.40% / comfort 1.08% / backbone 0.11% **全部可调度** |
| ③-d 四向追溯 | `docs/rtm_4way.md`（52 SR↔场景/模块↔测试↔故障；机器生成 `scripts/gen_trace_4way.py`） |
| ③-e 终扫 | 覆盖率口径 98.00%（2651/55）实测刷新；双仓陈旧数字残留清零 |
| 用例 | 上游 **958 collected（957 passed + 1 skip）** |

## ④ Q3 原子组合器（全部 ✅）

| 子项 | 实测 |
|---|---|
| 组合规划 | `agent/composer.py`：规则点名提取（score≥3.0，≤6，绝不发明）→ steps 兼容 `/api/run/custom` |
| 组合→执行 | `POST /api/agent/composer{run:true}` 真实引擎；测试端到端 all_passed（车门+超速+烟火报警，3/3） |
| 三栏溯源 | provenance：source_asset（字典）/source_system（13 域）/source_agent（规则说明）+ example_scenarios |
| ④-d 多轮 | history 续编（指代式"刚才那个也加上"经前文点名解析；直接点名优先） |
| 诚实边界 | 空目标/无故障 → ok:false 引导（不 422 死路） |

## ⑤ 动画原子化（自动化部分 ✅；⑤-c/d 见遗留范围）

| 子项 | 实测 |
|---|---|
| ⑤-a 域特征演示档 | `faultlab._domain_alarm`：**202/202 故障**均可生成结构化告警（名·子系统域/层·期望处置，诚实标注"示意/巡航基线"） |
| ⑤-b 通道级示例档案 | 8 个 Wave A/B/C 域代表故障 curated（door_open_moving→EB 施加等，语义保守映射）；190+ 由域文案兜底 |
| FaultLab 冒烟 | door_open_moving_eb → emergency_brake；aux_converter_fault_derate → derate（事件时间线完整） |

## 最终门禁（2026-09-08 实测）

| 侧 | 结果 |
|---|---|
| 上游 tcms-can-test v1.12.0 | pytest：**957 passed + 1 skipped（958 collected）**；ruff clean |
| 平台 tcms-ai-platform v0.4.0 | pytest：**134 passed**；ruff clean（src/tests/ai-testgen） |
| ai-testgen | **136 passed / 28 skipped**（独立 venv） |

## 遗留范围（迭代清单，非自动门禁）

- **⑤-c** fresume 式产品化打磨（采纳才应用/版本不落地/截图+粘贴双入口）—— 属前端交互流程，需 UI 人力；自动层已具备三栏溯源/四维雷达等数据基础。
- **⑤-d** 浏览器 e2e 走查 —— 需前端构建 + Playwright 环境，超出本自动回归轮范围；API 级等价冒烟（compose/run、kb route、faultlab demo）已在测试与手动 HTTP 验证覆盖。
- **全 13 域通道级逐条扩谱**：演示叙事已由域特征文案 + 8 个示例档案承载；按需逐域精修属于内容打磨迭代。
