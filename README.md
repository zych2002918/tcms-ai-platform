# TCMS × AI 测试平台（tcms-ai-platform）

> 北极星规划的落地仓库：把「AI 测试工程师能干活、能自证、看得见」的
> TCMS 列车控制软件测试平台做成**本地 Web 应用**。
> 裁判文档：[`TCMS-AI_北极星规划.md`](../TCMS-AI_北极星规划.md)。

## 这是什么

站在**列车视角**（而非单总线视角）组织 TCMS 测试资产，提供稳定 API 与
**本地 Web 界面**。数据全部派生自真实上游资产（数字机器自证），AI 能力
嵌入真实执行与知识底座，不依赖任何 LLM API 即可完整跑通（离线优先）。

```
真实资产(tcms-can-test) ──loader──▶ L1 资产模型 ──FastAPI──▶ Web UI (/)
  DBC 8报文/36信号 · 22 FMEA · 13 场景 · RTM SR-01~18 · 4 被测功能
        │
        ├──▶ 知识底座：图谱(106节点) + 向量(101文档) + GraphRAG 混合检索
        └──▶ Agent Harness：任务库 → 检索证据 → 真实执行 → 验证 → 反思 → 评分
```

## 快速开始（一键本地 Web 应用）

```bash
cd D:\DSHworkplace\objects\tcms-ai-platform
.venv\Scripts\python -m tcms_ai_platform.server.app   # → http://127.0.0.1:8000
```

上游 `tcms-can-test` 需在同级目录（默认 `../tcms-can-test`）。
打开浏览器即得完整应用：总览 / 知识图谱 / 测试资产 / 场景执行 / AI Agent 工作台。
前端构建产物已入库（`web/dist`），无需 node 工具链。

## 里程碑状态（北极星 P1–P5）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| P1 | L1 资产模型 + FastAPI 服务层（真实资产 → 列车视角 schema + API） | ✅ |
| P2 | 知识底座：图谱 + 向量 + GraphRAG 混合检索 + 沉淀闭环 | ✅ |
| P3 | 前端 MVP：React Web 应用（图谱可视化是招牌），FastAPI 单端口托管 | ✅ |
| P4 | Agent 工作流 + Harness：任务库→检索→真实执行→反思→双轨评分 | ✅ |
| P5 | Agent 前端工作台 + 打磨叙事 | ✅（本阶段） |

## 实测证据（机器自证）

| 能力 | 实测 |
|---|---|
| 资产加载 | 8 报文 / 36 信号 / 22 故障 / 13 场景 / 18 需求(23行) / 5 设备 / 4 功能，bad=0 |
| 真实执行 | 13 场景 23 断言全部通过（上游 tcms-can-test v1.9.1 引擎） |
| GraphRAG | "紧急制动执行失败"→fault:eb_failure；"车门故障不能发车"→SR-04/F-DOOR/door_fault 带证据链 |
| Agent Harness | 4 任务全达成（success_rate 1.0），每任务检索证据+真实执行+轨迹+评分 90 |
| 门禁 | 43 tests passed / ruff clean / cov 93.5% |

## API 一览（交互文档：/docs）

- 资产：`/api/stats` `messages` `signals` `faults` `scenarios` `requirements` `functions` `devices`
- 执行：`POST /api/run/scenario`（单场景）`/api/run/scenarios`（全 13 场景，真实引擎）
- 知识底座：`POST /api/kb/search`（GraphRAG）`/api/kb/subgraph` `nodes` `node/{id}` `stats`
- Agent：`GET /api/agent/tasks` `POST /api/agent/run`（单任务/全跑，含轨迹+评分）

## 路线（backlog，北极星之外）

- [ ] LLM 后端接入（AgentBackend 接口已就绪，接 key 即用；离线 mock 已可复现）
- [ ] 图谱 schema 扩展（需求→用例→运行历史全联通，组织记忆随跑测增长）
- [ ] 向量 embedding 升级（可插拔 Embedder，接 BGE/sentence-transformers）
- [ ] 前端打磨（真实列车网络拓扑可视化、报告趋势图）
- [ ] 推 GitHub + 演示故事线打磨

## 测试 / 门禁

```bash
.venv\Scripts\python -m pytest tests -q          # 43 tests（真实资产冒烟）
.venv\Scripts\python -m ruff check src tests     # lint
.venv\Scripts\python -m pytest tests -q --cov=tcms_ai_platform --cov-fail-under=80
```

> 红线条款：展示数字全部由加载结果派生（loader 不做美化）；功能表/任务库
> 锚定真实 RTM / DBC / 故障字典，需求漂移即加载失败；Agent 能力挂 Harness 评测。
