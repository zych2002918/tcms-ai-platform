# TCMS × AI 测试平台（tcms-ai-platform）

> 北极星规划的落地仓库：把「AI 测试工程师能干活、能自证、看得见」的
> TCMS 列车控制软件测试平台做成**本地 Web 应用**。
> 裁判文档：[`TCMS-AI_北极星规划.md`](../TCMS-AI_北极星规划.md)（P1 起逐步实现）。

## 这是什么

站在**列车视角**（而非单总线视角）组织 TCMS 测试资产，提供稳定 API 供
前端 / 知识底座 / Agent 层消费。当前为 **P1：资产模型 + 服务层**。

```
真实资产(tcms-can-test) ──loader──▶ L1 资产模型 ──FastAPI──▶ /api/*
  DBC 8报文/36信号 · 22 故障 FMEA · 13 场景 · RTM SR-01~18 · 4 被测功能
```

## P1 已交付（实测数字，全部机器派生）

| 资产 | 计数 | 来源 |
|---|---|---|
| 报文 | 8 | tcms.dbc（周期/发送类型/枚举解析） |
| 信号 | 36 | tcms.dbc（含 DoorState/ChargeState 等 VAL_ 枚举表） |
| 故障 | 22 | faults.yaml（F-TCMS-001~022，FMEA 全字段） |
| 场景 | 13 | scenarios/*.yaml（事件式步骤解析） |
| 需求 | 18 req / 23 行 | tests/rtm.csv（SR-01~18 追溯矩阵） |
| 被测功能 | 4 | curated（F-EBM/ATP/DOOR/NET，锚定真实 RTM，漂移即失败） |
| 设备 | 5 | DBC 发送节点 + 故障子系统派生 |

## 快速开始

```bash
cd D:\DSHworkplace\objects\tcms-ai-platform
.venv\Scripts\activate
python -m tcms_ai_platform.server.app    # → http://127.0.0.1:8000/docs
```

上游 `tcms-can-test` 需位于同级目录（默认定位 `../tcms-can-test`）。

## API 一览

- `GET /api/health` `stats` `source` — 元信息（数字机器自证）
- `GET /api/messages[/{name}]` `signals` — 协议资产（含枚举/周期）
- `GET /api/devices` — 列车设备（发送报文 / 关联故障）
- `GET /api/faults[/{key}]` `scenarios[/{file}]` — 故障字典 / 场景
- `GET /api/requirements` `functions` — RTM / 被测功能
- `POST /api/run/scenario` `run/scenarios` — 真实上游引擎执行场景
  （离线确定性，无 LLM 依赖；`door_cascade` 实测 2 断言全过）

## 测试 / 门禁

```bash
.venv\Scripts\python -m pytest tests -q          # 真实资产冒烟 + API
.venv\Scripts\python -m ruff check src tests     # lint
```

> 红线条款：展示数字全部由加载结果派生（loader 不做美化）；功能表锚定
> 真实 RTM / DBC / 故障字典，需求漂移即加载失败。

## 路线（北极星）

P1 资产模型+服务层（本阶段）→ P2 知识底座（向量+图谱）→ P3 前端 MVP →
P4 Agent 工作流 + Harness → P5 打磨叙事。
