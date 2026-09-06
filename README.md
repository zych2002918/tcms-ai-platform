# TCMS × AI 测试平台（tcms-ai-platform）

> 把「AI 测试工程师能干活、能自证、看得见」的 TCMS 列车控制软件测试平台，
> 做成**本地 Web 应用**。数据全部派生自真实上游资产，AI 能力离线可用。

![UI](docs/dashboard-preview.png)

更多页面截图：本地运行 `node e2e/preview-shots.mjs` 生成（见 docs/preview/）。

## 新人 3 步跑起来（不用配任何 key）

```bash
# 1. clone
git clone https://github.com/zych2002918/tcms-ai-platform.git
cd tcms-ai-platform

# 2. 启动（Windows）
start.bat

# 2'. 或 macOS / Linux
bash start.sh
```

脚本会自动：建虚拟环境 → 装依赖 → 启动服务 → 自动打开浏览器。
**首次较慢（装依赖），之后秒开。**

### 手动启动（可选）

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows；Linux/macOS: source .venv/bin/activate
pip install -e .                  # 或 pip install -e ".[upstream]" 带引擎
python -m tcms_ai_platform.server.app   # → http://127.0.0.1:8000
```

## 回答你的几个"为什么"

### 为什么要一个端口 / 这是不是要部署到服务器？
**不需要服务器。** 平台是**本地 Web 应用**：Python 起一个本地服务（默认
`http://127.0.0.1:8000`），浏览器访问——跟你打开 VS Code 一样，是跑在你
自己机器上的程序，不对外网开放。端口只是本机内部通信的"门牌"。

### 下载后别人怎么运行？
见上方"新人 3 步"。关键设计：
- **平台自带资产快照**（DBC/故障字典/13 场景/RTM 随包分发），clone 单仓库即可加载全部资产；
- 启动脚本自动建 venv、装依赖，无需手工配环境；
- 可选的 TCMS 引擎（`.[upstream]`）用于场景执行/Agent，不装则资产浏览与知识图谱仍完整可用；
- `start.bat` / `start.sh` 是唯二需要用户执行的命令。

### 新人要不要填自己的 API？
**当前不用。** Agent 默认走**离线 Mock 后端**——检索知识、选场景、真实执行、
给评分报告这条链路**不花一分钱、不需要任何 key**。只有将来启用"真 LLM
写测试/自由规划"这类功能才需要 key（`pip install -e ".[llm]"` + 配
`.env` 的 key），且是可选增强而非前提。

## 界面与功能

- **总览** — 系统状态 + 从这里开始（跑场景 / 问图谱 / 指挥 Agent）
- **测试资产** — 报文 · 信号（枚举）· 故障（FMEA 详情）· 安全需求（RTM），可筛选
- **场景执行** — 在真实 TCMS 引擎上运行故障场景，逐步流程 + 断言证据
- **知识图谱** — 大白话检索 TCMS 领域知识，结果分类 + 附小白解释 + 关系图谱
- **AI Agent 工作台** — 给 Agent 真实任务，看它检索→执行→汇报（轨迹可审计）

## 启动前自检

```bash
python -m tcms_ai_platform.cli      # 或: tcms-platform-doctor
```
逐项检查：Python / 依赖 / 资产源 / TCMS 引擎 / LLM key / 端口。

## 配置（.env，全部可选）

见 `.env.example`。核心变量：
- `PORT` — 端口，默认 8000
- `TCMS_UPSTREAM_DIR` — 用活的上游 tcms-can-test 目录（可选，默认内置快照）
- `DASH_API_KEY` / `DEEPSEEK_API_KEY` / `LLM_API_KEY` — 未来真 LLM 用（可选）

## 架构

```
真实资产(tcms-can-test) ──loader──▶ L1 资产模型 ──FastAPI──▶ Web UI (/)
        (内置快照/活上游/兄弟目录 三级解析)
        ├──▶ 知识底座：图谱(106节点) + 向量(101文档) + GraphRAG
        └──▶ Agent Harness：任务库 → 检索 → 真实执行 → 验证 → 评分
```

## 测试 / 门禁

```bash
python -m pytest tests -q            # 43 tests（含真实资产冒烟）
python -m ruff check src tests
python -m pytest tests -q --cov=tcms_ai_platform --cov-fail-under=80
```

> 红线：展示数字全部由真实资产派生；功能表/任务库锚定真实 RTM/故障字典，漂移即失败。
