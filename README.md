<div align="center">

# TCMS × AI 列车软件测试平台

> **让 AI 测试工程师能干活、能自证、看得见** —— 面向列车控制软件（TCMS）的
> 本地测试平台：真实资产 → 知识底座 → Agent 自证 → 动画/图谱可视化，全部离线可跑。

![Python](https://img.shields.io/badge/Python-3.11+-2dd4a0)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_UI-4ca6ff)
![React](https://img.shields.io/badge/React-18+-8b7cf6)
![pytest](https://img.shields.io/badge/pytest-164%20passed-2dd4a0)
![license](https://img.shields.io/badge/license-MIT-8ca0c0)

**黑夜 / 白天双主题 · 图谱 2D 缩放平移 + 3D 俯瞰 · 一键本地启动**

</div>

---

## 这是什么

本仓库是把两条独立能力线**合二为一**的 TCMS（列车网络控制系统）AI 测试工程：

| 组件 | 一句话 | 位置 | 状态 |
|---|---|---|---|
| **平台**（tcms-ai-platform） | 本地 Web 应用：资产模型 + 知识图谱 + Agent Harness + 故障动画演示 | 仓库根 + `web/` + `src/tcms_ai_platform/` | ✅ 完整可运行 |
| **AI 测试生成器**（原 tcms-ai-testgen） | LLM 生成测试用例的受约束 DSL 流水线 + 变异杀毒/反思自愈评测 | `ai-testgen/` | ✅ 完整可运行 |

> 背景：作者先在 `tcms-can-test` 手写了 802 个 pytest（98% 覆盖），再把
> 「AI 写测试并自证好坏」做成流水线（`ai-testgen`），最后把整套东西收进一个
> 带界面的本地平台（`tcms-ai-platform`）——**三个仓库一个叙事**：
> 真实核心 → AI 生成 → 平台化可视。上游引擎 `tcms-can-test` 作为依赖存在。

---

## 快速开始（2 条命令，不用配任何 key）

```bash
git clone https://github.com/zych2002918/tcms-ai-platform.git
cd tcms-ai-platform

# Windows：
start.bat
# macOS / Linux：
bash start.sh
```

脚本自动建 venv → 装依赖 → 起服务 → 开浏览器（`http://127.0.0.1:8000`）。
**全部功能离线可用**：Agent 默认离线 Mock 后端，检索 / 执行 / 评分一分钱不花。

> 免 Python 版：Windows 现场可用 `dist/tcms-ai-platform/` 下的 exe（见
> `packaging/README.md`）。

---

## 一屏看懂：平台里有什么

```
┌─────────────────────────── 总览 ───────────────────────────┐
│ 引擎/资产源/AI 后端状态 · 六大资产卡（报文/信号/故障/场景/需求/功能）│
├──────────────┬───────────────┬───────────────┬─────────────┤
│  场景执行      │  故障演示       │  知识图谱       │  AI Agent    │
│  真实引擎跑场景 │  故障动画可溯源   │  2D 缩放/3D 俯瞰 │  检索→执行→自证 │
│  手动编排      │  注入→检测→处置  │  大白话问 TCMS  │  自由目标/任务库 │
│  AI 编排顾问   │  →恢复 逐帧溯源  │  向量+图谱双通道  │  8 真实故障锚定  │
└──────────────┴───────────────┴───────────────┴─────────────┘
```

### 核心亮点

- **知识图谱工作台**：语义检索 + 关系图谱。图谱画布支持**滚轮缩放、拖拽平移、
  双击/按钮一键适配**，并可切换 **3D 俯瞰**（拖拽旋转 / 自动缓转）——不同深度
  （1/2/3 跳）扩缩关联范围，节点可点开看属性与邻居。
- **图谱默认骨架图**：打开图谱页**无需先搜索**即展示“基础关联图谱”（13 系统域 + 11 功能 +
  每功能代表故障，`/api/kb/overview` 56 节点/65 边）；2D/3D 节点**单击看详情、双击以其为中心跳转**，
  3D 支持滚轮缩放与一键适配，停转后 3 秒自动恢复待机自转。
- **混合检索（P1-1）**：`/api/kb/search` 由 **向量 + BM25 词法（RRF 融合）**双通道驱动（兼顾语义近义与字面精确）；配 **golden 检索评测集**（14 条真实期望 id）作防回退门禁（混合 14/14、纯向量 ≥13/14）。
- **场景名 = 简短中文释义**：全部 103 个内置场景均带简短中文名（唯一、无批量模板残留）与故障序列 `desc`；
  列表/下拉/执行结果标题都优先显示中文名（文件名为次级标识）。
- **FaultLab 高亮 = 具体异常可点**：列车动画高亮点与下方 chip 直接显示具体故障（不再笼统“系统异常”），
  并带「【13 系统域 · 子系统】」定位前缀；**点击高亮点/chip 查看异常说明**（等级/现象/检测语义），悬停也有提示。
- **症状/无码故障诊断卡片**：Agent 页输入“仪表盘闪烁但无故障码”等无码症状 → 症状资产 + 图谱因果链候选卡
  （derived 显式标注、复现场景一键直达），全离线确定性、不编造故障码（`POST /api/agent/diagnose`）。
- **症状多跳诊断**：输入「仪表盘闪烁但无故障码」这类**无码症状描述** → kb 检索
  症状资产（12 条）→ 图谱沿因果边（indicates 41 / causes 13，共 54 条，每条带
  依据）≤3 跳取候选链 → 给出诊断步骤建议（验证哪条真实故障/查哪个报文信号/
  用什么场景复现）+ 置信度 + 逐条溯源；derived 示意候选显式标注，证据不足时
  诚实输出“不确定/需补充”，**绝不编造故障码**（`POST /api/agent/diagnose`）。
- **故障演示（FaultLab）**：真实场景 → 可播放动画。列车/驾驶台 SVG + 故障部位
  高亮脉冲 + 速度/制动缸压曲线，随进度条逐帧推进；每个事件都可溯源到
  「场景 YAML / 故障字典 / 引擎断言 / 示意模型」四级数据来源。
- **AI Agent 工作台**：内置 8 类真实故障任务（紧急制动/超速/心跳/总线/CRC/
  重启风暴…），Agent 检索知识底座 → 真实执行 → 6 维语义评审 → 轨迹可审计；
  也支持**自由目标**：输入「车门故障了还能发车吗」，Agent 理解后查证。
- **手动编排 + AI 编排顾问**：在场景执行页自己编排「何时注入什么故障 → 期望
  什么处置」并真实执行；旁边 AI 顾问可多轮对话，给出可一键采纳的编排建议。
- **黑夜 / 白天双主题**：右上角一键切换，跟随系统/手动/持久化到本机设置。

---

## ai-testgen：AI 写测试并证明它写得好

`ai-testgen/` 是独立可运行的 Python 包（原 `tcms-ai-testgen` 仓库整体并入）。
它回答行业难题：**LLM 生成的测试用例怎么证明是"好的"**。

```
真实资产(DBC 8报文/38信号 + 25场景YAML) ──> 生成器(mock/真LLM) ──> execution DSL
──> 编译为真实 pytest ──> 在上游 tcms-can-test 执行 ──> 量化报告
        解析率 / 编译率 / 执行通过率 / 变异杀毒 kill_rate / 反思自愈 / 双 judge
```

### 独立运行

```bash
cd ai-testgen
pip install -e ".[test]"          # 30 秒自检：python scripts/selfcheck.py
python examples/demo_full_loop.py --num 40 --mutation   # 全链路演示
python -m tcms_ai_testgen.cli --llm --target "TCMS 超速防护"   # 真 LLM（需 key）
```

### 量化证据（数字全部有报告 JSON 可复现，见 `ai-testgen/docs/reports/`）

| 证据 | 结果 | 复现 |
|---|---|---|
| 真实执行通过率 | mock 生成 34 条 → 真实 pytest **34/34 passed**（compile 100%） | `demo_full_loop.py --num 40` |
| 变异杀毒 | 3 个被选中行为翻转**全被杀**（kill_rate 1.0，按相关用例分母） | 同上 `--mutation` |
| 真 LLM 可执行 | deepseek-v3.2 compile 100%；幻觉（AlarmLevel=-1）被真实执行器当场拦截 | `run_llm_arm.py` |
| AI 自我修复 | 反思闭环：22 条 5 失败 2 自愈（self-heal 0.40，diff 门禁防作弊） | `run_reflect_demo.py` |
| 多模型对比 | v4-flash/v3.2/r1 × 3 批正式对比（质量差异被量化） | `run_multi_model.py` |
| 生成源可区分 | 规则基线 vs mock 变异覆盖 1/3 vs 3/3 —— 只有 pass_rate 会误判 | `run_p3_comparison.py` |

---

## 目录速览

```
tcms-ai-platform/
├── src/tcms_ai_platform/      平台 Python 包
│   ├── core/                  L1 资产模型 + loader + 三级资产源
│   ├── knowledge/             知识底座：图谱(基础517/含enrich 651节点 · 13系统域) + 向量(506/640文档) + 因果遍历(≤3跳) + GraphRAG + 沉淀
│   ├── agent/                 Agent Harness：8任务/自由目标/advisor/reviewer/diagnoser(症状诊断)/LLM后端
│   ├── faultlab.py            故障演示数据重建器（事件时间线 + 通道曲线）
│   ├── domain/                领域知识注入 JSON（EBM/网络/安全/13 系统域）+ 症状资产与因果表(12 症状/54 因果边)
│   └── server/app.py          FastAPI（单端口托管前端 dist）
├── web/                       React + Vite + Tailwind v4 前端（双主题）
├── ai-testgen/                独立包：LLM 测试生成流水线（原 tcms-ai-testgen）
├── e2e/                       浏览器走查脚本（playwright + Edge）
├── docs/                      设计 / 截图 / 研究；**PROJECT_ARC.md = 开发路径复盘+方法论**
└── packaging/                 PyInstaller 打包说明
```

---

## 配置（全部可选，新人零配置）

环境变量 > 本机设置文件（`~/.tcms-ai-platform/settings.json`，设置页写入）> 内置默认。

| 变量 | 作用 | 默认 |
|---|---|---|
| `PORT` | Web 端口 | 8000 |
| `TCMS_UPSTREAM_DIR` | 指向活的上游 tcms-can-test（资产+引擎） | 自动：兄弟目录 → 内置快照 |
| `TCMS_AI_HOME` | 本机设置目录 | `~/.tcms-ai-platform` |
| `DASH_API_KEY` / `DEEPSEEK_API_KEY` | 真 LLM（可选，离线 Mock 已够演示） | 未设置走 Mock |

**新人在设置页的「环境变量键值表」可实时看到每个变量当前取值与解析状态**，
无遗留本地绝对路径——仓库源码不含任何 `D:\` 字面量（唯一 `C:\` 在注释里说明
本机设置文件位置）。

---

## 测试 / 门禁

```bash
# 平台
python -m pytest tests -q                 # 164 passed（含真实资产冒烟 + 症状诊断回归 + API 契约）
python -m ruff check src tests            # clean
# 前端纯逻辑单测（播放器状态机等）
cd web && pnpm test                       # vitest（src/lib/*.test.ts）
# 浏览器 e2e 主流程（需服务运行且 dist 已构建）
cd e2e && npm run smoke                   # playwright-core + 缓存 chromium，主流程 5 断言
# ai-testgen（独立包，需 PYTHONPATH=src 或先 pip install -e）
cd ai-testgen && python -m pytest tests -q
```

红线（继承 tcms-can-test 纪律）：展示数字全部由真实资产派生、任务库锚定真实
RTM/故障字典（漂移即失败）、API key 永不入库/不入响应、LLM 决策可落回离线 Mock。

---

## 关系：与上下游仓库

| 仓库 | 关系 | 说明 |
|---|---|---|
| `tcms-can-test` | **上游引擎** | 958 用例（957 passed + 1 skip）/ 98% 覆盖 / 202 FMEA（13 系统域）/ 103 场景 / 22 报文·116 信号的领域核心；平台以 `pip install -e ".[upstream]"` 依赖 |
| `tcms-ai-platform` | **本仓库** | 平台 + 生成器（ai-testgen）合体，一个叙事 |
| ~~tcms-ai-testgen~~ | 已并入 | 作为 `ai-testgen/` 保留独立包结构 |

## License

MIT —— 平台与生成器均 MIT；上游 tcms-can-test 亦 MIT。
