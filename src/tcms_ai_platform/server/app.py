"""FastAPI 应用工厂 + 资产/执行端点。

设计：
- 单例 AssetModel 在启动时加载（可注入上游路径，测试用 override）。
- 资产端点只读查询（机器自证：计数派生自加载结果）。
- 执行端点调上游 tcms 引擎真实跑场景（离线、确定性、无 LLM 依赖）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .._version import __version__
from ..core import AssetModel, load_asset_model
from ..core.sources import (
    ensure_engine_importable,
    resolve_asset_source,
)
from ..knowledge import (
    GraphSink,
    HybridRetriever,
    VectorStore,
    build_docs_from_asset,
    build_knowledge_graph,
)

# 供 uvicorn 直接 import 的默认实例（app:main 兼容）
_app_model: AssetModel | None = None
_app_upstream: Path | None = None


class RunScenarioRequest(BaseModel):
    """单场景执行请求。

    必须定义在模块级：本文件启用 `from __future__ import annotations`，
    函数内定义的模型无法被 FastAPI 在模块全局解析前向引用，会被误判为
    query 参数（422: missing query req）。
    """

    scenario: str  # 场景文件名（含 .yaml）


class RunScenariosRequest(BaseModel):
    """批量执行请求（当前无参数，占位便于扩展）。"""

    pass


class SearchRequest(BaseModel):
    """GraphRAG 混合检索请求（模块级：同上 FastAPI 前向引用约束）。"""

    query: str
    k: int = 5


class SubgraphRequest(BaseModel):
    """图谱子图请求（seed 为 node id，如 fault:overspeed）。"""

    seed: str
    depth: int = 2


class AgentRunRequest(BaseModel):
    """Agent 任务执行请求（模块级：FastAPI 前向引用约束）。"""

    task_id: str | None = None  # None = 全跑


class FaultLabRequest(BaseModel):
    """FaultLab 演示请求：选一个真实场景。"""

    scenario: str  # 场景文件名（含 .yaml）


class AgentFreeRequest(BaseModel):
    """自由 Agent 目标请求：一句自然语言 → 自动解析为可执行任务。

    模块级（FastAPI 前向引用约束，同 RunScenarioRequest）。
    """

    goal: str  # 自然语言目标（如「验证车门故障不能发车」）


class CustomStepRequest(BaseModel):
    """自定义场景单步（模块级：FastAPI 前向引用约束）。

    与内置场景 YAML 步骤同构：at 为注入时刻；action ∈ inject/recover。
    fault 必填（inject 用）；node/level 仅 inject 有意义。
    """

    at: float
    action: str  # inject / recover
    fault: str | None = None
    node: str | None = None
    level: str | None = None
    expect: str | None = None
    impact: str | None = None


class CustomScenarioRequest(BaseModel):
    """自定义场景请求：一组手动编排的步骤（真实引擎执行，不落盘）。"""

    name: str = "custom"
    steps: list[CustomStepRequest]


class SettingsUpdateRequest(BaseModel):
    """设置保存请求（前端「设置/引导」页写入；key 只落本机文件）。"""

    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None  # 允许空串 = 清除
    asset_dir: str | None = None  # 空串 = 清空(回到自动)
    onboarding_done: bool | None = None


def create_app(asset_model: AssetModel | None = None, upstream: str | Path | None = None) -> FastAPI:
    """应用工厂。

    资产源解析（新人友好，无需配置）：
    - upstream 显式传入 → 用它（测试/开发）
    - 否则按环境解析：TCMS_UPSTREAM_DIR → 兄弟目录 → 平台内置快照
    """
    global _app_model, _app_upstream

    # 场景目录（真实引擎从这里读场景 YAML；bundled 模式用平台快照）
    scenario_dir: Path
    if asset_model is None:
        if upstream is not None:
            asset_model = load_asset_model(upstream)
            scenario_dir = Path(upstream) / "scenarios"
            # 显式上游（开发/测试）：把其根加入 sys.path 使 tcms 引擎可 import
            import sys as _sys

            root = Path(upstream)
            if str(root) not in _sys.path:
                _sys.path.insert(0, str(root))
        else:
            source = resolve_asset_source()
            from ..core.loader import load_from_source

            asset_model = load_from_source(source)
            ensure_engine_importable(source)
            scenario_dir = source.scenarios_dir
    else:
        # 显式传入 asset_model（测试）：场景目录取上游根，无则退回内置
        src_root = Path(str(asset_model.source_upstream))
        candidate = src_root / "scenarios"
        scenario_dir = candidate if candidate.is_dir() else Path(__file__).resolve().parents[2] / "_assets" / "scenarios"
    _app_model = asset_model
    _app_upstream = scenario_dir

    # 引擎可用性探测（启动时一次；供 /api/system/status 与前端引导）
    def _probe_engine() -> dict:
        try:
            import importlib.util

            if importlib.util.find_spec("tcms") is None:
                return {"ok": False, "reason": "not_installed"}
            import tcms  # noqa: F401

            return {"ok": True, "version": getattr(tcms, "__version__", "?")}
        except ImportError as e:
            return {"ok": False, "reason": f"import_failed:{e}"}

    _engine_status = _probe_engine()

    # 知识底座（P2）：图谱 + 向量 + 混合检索（同一 app 实例内单例）
    graph = build_knowledge_graph(asset_model)
    store = VectorStore()
    store.add_many(build_docs_from_asset(asset_model))
    # 领域知识注入（P6）：真实列车领域知识(驾驶模式/联锁/阈值/标准/危害/概念)扩图谱
    from ..domain import enrich_graph as _enrich

    _enrich_report = _enrich(graph, store)
    retriever = HybridRetriever(store, graph)
    sink = GraphSink(graph)
    _run_counter = {"n": 0}

    # Agent Harness：后端可插拔——有 LLM key(env / 本地设置 / 凭据文件)
    # 用 LLM 决策(失败自动落回 Mock)，否则 Mock 确定性（离线可复现）。
    # 注意：设置页可在运行期改 key/provider → 用闭包每次现取（懒构建）。
    from ..agent import (
        AgentHarness,
        LLMAgentBackend,
        MockAgentBackend,
        default_tasks,
        llm_available,
    )

    def _current_backend_mode() -> str:
        return "llm" if llm_available() else "mock"

    def _make_harness() -> AgentHarness:
        if _current_backend_mode() == "llm":
            return AgentHarness(
                asset_model, retriever, _app_upstream, backend=LLMAgentBackend()
            )
        return AgentHarness(
            asset_model, retriever, _app_upstream, backend=MockAgentBackend()
        )

    app = FastAPI(
        title="TCMS × AI 测试平台",
        version=__version__,
        description="列车控制软件测试平台（L1 资产模型 + 真实引擎执行）",
    )

    # ---- 元信息 ----

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": asset_model.version}

    @app.get("/api/stats")
    def stats() -> dict:
        return asset_model.stats()

    @app.get("/api/source")
    def source() -> dict:
        return {"upstream": asset_model.source_upstream, "load": asset_model.load_stats}

    @app.get("/api/system/status")
    def system_status() -> dict:
        """环境状态（供前端引导）：引擎 / LLM key / 资产源 / 可用能力。"""
        from ..agent import llm_available

        has_key = llm_available()
        eng = _probe_engine()
        return {
            "engine": eng,
            "llm_key": has_key,
            "agent_backend": _current_backend_mode(),  # mock(离线) / llm(已配 key)
            "asset_mode": asset_model.source_upstream,
            "capabilities": {
                "browse_assets": True,
                "knowledge_graph": True,
                "run_scenario": eng["ok"],
                "agent": eng["ok"],
                "llm_generation": has_key,  # 真 LLM 写测试（可选增强）
            },
            "fix_hints": {
                "engine": (
                    []
                    if eng["ok"]
                    else [
                        "pip install -e \".[upstream]\"  # 从 GitHub 安装 tcms-can-test 引擎",
                        "或设置环境变量 TCMS_UPSTREAM_DIR 指向 tcms-can-test 目录后重启",
                    ]
                ),
                "llm": (
                    []
                    if has_key
                    else [
                        "当前 Agent 使用离线 Mock 后端，无需 key 即可演示全流程。",
                        "如需真 LLM 生成/规划，到「设置」页配置 API（阿里云/DeepSeek/OpenAI 兼容），或设 DASH_API_KEY（见 .env.example）",
                    ]
                ),
            },
        }

    # ---- 设置（外部可配置接口：新手引导页读写本地 settings，key 永不外泄）----

    @app.get("/api/settings")
    def settings_get() -> dict:
        """读取非敏感设置（含 provider 预设与当前状态，绝不含 api_key）。"""
        from ..core import settings as _settings

        view = _settings.public_view()
        view["providers"] = _settings.PROVIDER_PRESETS
        return view

    @app.post("/api/settings")
    def settings_update(req: SettingsUpdateRequest) -> dict:
        """保存设置（写入 ~/.tcms-ai-platform/settings.json；key 只落本机文件）。"""
        from ..core import settings as _settings

        patch: dict = {}
        if req.llm_provider is not None:
            patch.setdefault("llm", {})["provider"] = req.llm_provider
        if req.llm_base_url is not None:
            patch.setdefault("llm", {})["base_url"] = req.llm_base_url.strip()
        if req.llm_model is not None:
            patch.setdefault("llm", {})["model"] = req.llm_model.strip()
        if req.llm_api_key is not None:
            patch.setdefault("llm", {})["api_key"] = req.llm_api_key.strip()
        if req.asset_dir is not None:
            patch["asset_dir"] = req.asset_dir.strip()
        if req.onboarding_done is not None:
            patch["onboarding_done"] = bool(req.onboarding_done)
        if not patch:
            raise HTTPException(400, "无有效设置字段")
        try:
            _settings.save(patch)
        except RuntimeError as e:
            raise HTTPException(500, str(e)) from e
        return _settings.public_view()

    @app.post("/api/settings/clear-api-key")
    def settings_clear_api_key() -> dict:
        """清除已保存的 API key（不留本机文件）。"""
        from ..core import settings as _settings

        try:
            _settings.save({"llm": {"api_key": ""}})
        except RuntimeError as e:
            raise HTTPException(500, str(e)) from e
        return _settings.public_view()

    # ---- 知识底座（P2）----

    @app.post("/api/kb/search")
    def kb_search(req: SearchRequest) -> dict:
        """GraphRAG 混合检索：语义命中 + 图谱邻接证据。"""
        return retriever.retrieve(req.query, k=req.k)

    @app.post("/api/kb/subgraph")
    def kb_subgraph(req: SubgraphRequest) -> dict:
        """以某实体为中心的子图（图谱工作台数据源）。"""
        return retriever.subgraph(req.seed, req.depth)

    @app.get("/api/kb/stats")
    def kb_stats() -> dict:
        return {
            "graph": graph.stats(),
            "vector": store.stats(),
            "domain_enrichment": _enrich_report["files"],
        }

    @app.get("/api/kb/nodes")
    def kb_nodes(kind: str | None = None, q: str | None = None) -> list[dict]:
        """节点浏览/搜索（前端下拉、图谱定位用）。kind ∈ graph.NODE_TYPES。"""
        out = []
        for n in graph.nodes.values():
            if kind and n.kind != kind:
                continue
            if q and q.lower() not in n.label.lower() and q.lower() not in n.id.lower():
                continue
            out.append({"id": n.id, "kind": n.kind, "label": n.label})
            if len(out) >= 200:
                break
        return out

    @app.get("/api/kb/node/{node_id}")
    def kb_node(node_id: str) -> dict:
        """单个节点 + 其直接邻接（图谱漫游）。"""
        if node_id not in graph.nodes:
            raise HTTPException(404, f"节点不存在: {node_id}")
        n = graph.nodes[node_id]
        return {
            "id": n.id,
            "kind": n.kind,
            "label": n.label,
            "props": n.props,
            "neighbors": [
                {"id": nb, "label": graph.nodes[nb].label, "kind": graph.nodes[nb].kind}
                for nb, _ in graph.neighbors(node_id)
            ],
        }

    # ---- 资产：协议 ----

    @app.get("/api/messages")
    def list_messages() -> list[dict]:
        return [
            {
                "name": m.name,
                "frame_id": hex(m.frame_id),
                "node": m.node,
                "cycle_ms": m.cycle_ms,
                "send_type": m.send_type,
                "signals": list(m.signal_names),
            }
            for m in asset_model.messages.values()
        ]

    @app.get("/api/messages/{name}")
    def get_message(name: str) -> dict:
        try:
            m = asset_model.message(name)
        except KeyError:
            raise HTTPException(404, f"报文不存在: {name}") from None
        return {
            "name": m.name,
            "frame_id": hex(m.frame_id),
            "node": m.node,
            "length": m.length,
            "cycle_ms": m.cycle_ms,
            "send_type": m.send_type,
            "signals": [
                {
                    "name": s.name,
                    "bit_length": s.bit_length,
                    "scale": s.scale,
                    "offset": s.offset,
                    "range": [s.minimum, s.maximum],
                    "unit": s.unit,
                    # 枚举表序列化为有序 [{value,label}]（JSON 键恒为字符串，
                    # 用 list 避免 int/str 键歧义）
                    "choices": [
                        {"value": k, "label": v}
                        for k, v in sorted(s.choices.items())
                    ],
                    "receivers": list(s.receivers),
                }
                for s in (asset_model.signals[n] for n in m.signal_names)
            ],
        }

    @app.get("/api/signals")
    def list_signals() -> list[dict]:
        return [
            {
                "name": s.name,
                "message": s.message,
                "unit": s.unit,
                "choices": [
                    {"value": k, "label": v} for k, v in sorted(s.choices.items())
                ],
            }
            for s in asset_model.signals.values()
        ]

    # ---- 资产：列车结构 ----

    @app.get("/api/devices")
    def list_devices() -> list[dict]:
        return [
            {
                "name": d.name,
                "role": d.role,
                "messages": list(d.messages),
                "faults": list(d.faults),
            }
            for d in asset_model.devices.values()
        ]

    # ---- 资产：故障/场景 ----

    @app.get("/api/faults")
    def list_faults() -> list[dict]:
        return [
            {
                "fid": f.fid,
                "key": f.key,
                "name": f.name,
                "subsystem": f.subsystem,
                "layer": f.layer,
                "level": f.level,
                "action": f.action,
                "sil": f.sil,
            }
            for f in asset_model.faults_by_key.values()
        ]

    @app.get("/api/faults/{key}")
    def get_fault(key: str) -> dict:
        try:
            f = asset_model.fault(key)
        except KeyError:
            raise HTTPException(404, f"故障不存在: {key}") from None
        return {
            "fid": f.fid,
            "key": f.key,
            "name": f.name,
            "subsystem": f.subsystem,
            "layer": f.layer,
            "level": f.level,
            "action": f.action,
            "sil": f.sil,
            "desc": f.desc,
            "detect": f.detect,
            "inject": f.inject,
            "recovery": f.recovery,
        }

    @app.get("/api/scenarios")
    def list_scenarios() -> list[dict]:
        return [
            {
                "file": s.file,
                "name": s.name,
                "steps": len(s.steps),
                "fault_keys": sorted(s.fault_keys),
                "nodes": sorted(s.nodes),
            }
            for s in asset_model.scenarios.values()
        ]

    @app.get("/api/scenarios/{file}")
    def get_scenario(file: str) -> dict:
        try:
            s = asset_model.scenario(file)
        except KeyError:
            raise HTTPException(404, f"场景不存在: {file}") from None
        return {
            "file": s.file,
            "name": s.name,
            "steps": [
                {
                    "at": st.at,
                    "action": st.action,
                    "node": st.node,
                    "fault": st.fault,
                    "level": st.level,
                    "expect": st.expect,
                    "impact": st.impact,
                }
                for st in s.steps
            ],
        }

    # ---- FaultLab：故障演示（真实场景 + 事件时间线 + 通道曲线）----

    @app.get("/api/faultlab/scenarios")
    def faultlab_scenarios() -> list[dict]:
        """可演示的场景清单（全部真实资产场景）。"""
        return [
            {
                "file": s.file,
                "name": s.name,
                "steps": len(s.steps),
                "fault_keys": sorted(s.fault_keys),
                "duration_hint": max((st.at for st in s.steps), default=0) + 4,
            }
            for s in asset_model.scenarios.values()
        ]

    @app.post("/api/faultlab/demo")
    def faultlab_demo(req: FaultLabRequest) -> dict:
        """重建一个场景的演示时间线（事件 + 曲线一次返回）。

        引擎可用时先真实执行该场景，用真实断言作为处置来源；
        引擎不可用时退化为故障字典 action（诚实标注 derived）。
        """
        try:
            asset_model.scenario(req.scenario)
        except KeyError:
            raise HTTPException(404, f"场景不存在: {req.scenario}") from None

        from ..faultlab import build_curve, build_demo

        run_result: dict | None = None
        engine_ok = _probe_engine()["ok"]
        if engine_ok:
            try:
                import tcms.scenarios as sc  # noqa: PLC0415

                run_result = sc.run_yaml(str(_app_upstream / req.scenario))
                # 真实引擎 run_yaml 报告不带版本 → 补 engine_version，供
                # faultlab._engine_block 填 demo.engine.version（不臆造 None）。
                if run_result is not None:
                    run_result = dict(run_result)
                    run_result["engine_version"] = __import__("tcms").__version__
            except Exception:  # noqa: BLE001 - 引擎失败退化为字典来源（诚实标注）
                run_result = None

        demo = build_demo(asset_model, req.scenario, run_result)
        curve = build_curve(asset_model, demo)
        return {
            "demo": demo,
            "curve": curve,
            "engine_asserted": run_result is not None,
            "honesty_note": demo["honesty"],
        }

    # ---- 资产：需求 / 功能 ----

    @app.get("/api/requirements")
    def list_requirements() -> list[dict]:
        out = []
        for req_id, reqs in asset_model.requirements.items():
            out.append(
                {
                    "req_id": req_id,
                    "rows": [
                        {"module": r.module, "test_file": r.test_file, "verifies": r.verifies}
                        for r in reqs
                    ],
                }
            )
        return out

    @app.get("/api/functions")
    def list_functions() -> list[dict]:
        return [
            {
                "fid": f.fid,
                "name": f.name,
                "description": f.description,
                "messages": list(f.messages),
                "signals": list(f.signals),
                "fault_keys": list(f.fault_keys),
                "requirements": list(f.requirements),
            }
            for f in asset_model.functions.values()
        ]

    # ---- 执行：真实场景 ----

    @app.post("/api/run/scenario")
    def run_scenario(req: RunScenarioRequest) -> dict:
        """在真实上游 tcms 引擎上执行一个场景（离线确定性）。"""
        try:
            asset_model.scenario(req.scenario)  # 校验存在
        except KeyError:
            raise HTTPException(404, f"场景不存在: {req.scenario}") from None

        # 引擎已在 create_app 中 ensure_engine_importable（活上游入 path 或已安装）
        try:
            import tcms.scenarios as sc  # noqa: PLC0415
        except ImportError as e:  # 引擎缺失 → 明确引导（新人可读）
            raise HTTPException(
                503,
                f"TCMS 引擎不可用：场景执行需要 tcms-can-test。请 pip install tcms-can-test，"
                f"或设置 TCMS_UPSTREAM_DIR 指向其目录。({e})",
            ) from None

        try:
            rep = sc.run_yaml(str(_app_upstream / req.scenario))
        except Exception as e:  # 上游引擎异常 → 500 含信息
            raise HTTPException(500, f"场景执行失败: {e}") from None
        # 沉淀闭环：执行结果写回知识库（组织记忆）
        _run_counter["n"] += 1
        sink.record_run(
            f"run-{_run_counter['n']:03d}",
            req.scenario,
            {"passed": rep.get("passed"), "failed": rep.get("failed"), "all_passed": rep.get("all_passed")},
        )
        return {
            "scenario": rep.get("scenario"),
            "steps": rep.get("steps"),
            "assertions": rep.get("assertions"),
            "passed": rep.get("passed"),
            "failed": rep.get("failed"),
            "all_passed": rep.get("all_passed"),
            "engine_version": __import__("tcms").__version__,
            "run_id": f"run-{_run_counter['n']:03d}",
        }

    @app.post("/api/run/scenarios")
    def run_scenarios(req: RunScenariosRequest) -> dict:
        """批量执行全部 13 场景（真实引擎，逐场景独立台账）。"""
        try:
            import tcms.scenarios as sc  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover - 引擎缺失引导
            raise HTTPException(
                503, f"TCMS 引擎不可用：请 pip install tcms-can-test 或设置 TCMS_UPSTREAM_DIR。({e})"
            ) from None

        results = []
        total_pass = total_fail = 0
        for file in asset_model.scenarios:
            rep = sc.run_yaml(str(_app_upstream / file))
            total_pass += rep.get("passed", 0)
            total_fail += rep.get("failed", 0)
            results.append(
                {
                    "scenario": file,
                    "name": asset_model.scenario(file).name,
                    "passed": rep.get("passed"),
                    "failed": rep.get("failed"),
                    "all_passed": rep.get("all_passed"),
                }
            )
        return {
            "engine_version": __import__("tcms").__version__,
            "scenario_count": len(results),
            "total_pass": total_pass,
            "total_fail": total_fail,
            "all_passed": total_fail == 0,
            "results": results,
        }

    # ---- Agent Harness（P4）----

    @app.get("/api/agent/tasks")
    def agent_tasks() -> list[dict]:
        """任务库（锚定真实故障字典）。"""
        return [
            {
                "task_id": t.task_id,
                "title": t.title,
                "goal": t.goal,
                "target_fault": t.target_fault,
                "expected_action": t.expected_action,
            }
            for t in default_tasks(asset_model)
        ]

    @app.post("/api/agent/run")
    def agent_run(req: AgentRunRequest) -> dict:
        """跑 Agent 任务（真实引擎执行 + 轨迹 + 评分）。"""
        tasks = default_tasks(asset_model)
        if req.task_id:
            tasks = [t for t in tasks if t.task_id == req.task_id]
            if not tasks:
                raise HTTPException(404, f"任务不存在: {req.task_id}")
        # 每次现取后端（设置页改 key/provider 后无需重启即生效）
        return _make_harness().run_tasks(tasks)

    @app.post("/api/agent/free")
    def agent_free(req: AgentFreeRequest) -> dict:
        """自由 Agent 目标：自然语言 → 解析(规则+LLM仲裁) → 真实执行。

        像 DSH Harness 一样自由：不给任务 id，只给一句话目标。
        返回解析结果（命中故障/期望处置/置信度）+ 与 /api/agent/run 同构的执行报告。
        """
        from ..agent.freeform import NoFaultMatch, parse_free_goal
        from ..agent.llm_backend import llm_available as _llm_ok

        try:
            parsed = parse_free_goal(
                asset_model, req.goal, seq=1, use_llm=_llm_ok()
            )
        except NoFaultMatch as e:
            raise HTTPException(422, str(e)) from None
        task = parsed.to_task(req.goal, seq=1)
        resp = _make_harness().run_tasks([task])
        return {
            "goal": req.goal,
            "parsed": {
                "fault": parsed.fault,
                "fault_name": parsed.fault_name,
                "expected": parsed.expected,
                "expected_zh": parsed.expected_zh,
                "confidence": parsed.confidence,
                "resolver": parsed.resolver,
                "matched_on": parsed.matched_on,
            },
            "matched_task_id": task.task_id,  # T-FREE-1（自由任务由解析动态生成）
            **resp,
        }

    @app.post("/api/run/custom")
    def run_custom(req: CustomScenarioRequest) -> dict:
        """手动编排的自定义故障场景 → 真实引擎执行（不落盘）。

        与 /api/run/scenario 同构：校验 → 组装 YAML → parse_scenario →
        VirtualClock(virtual) + FaultLedger 执行 → 同构报告。
        """
        # 校验引擎（缺失引导文案与 run_scenario 一致）
        try:
            import tcms.scenarios as sc  # noqa: PLC0415
            import tcms.timebase as _tb  # noqa: PLC0415
        except ImportError as e:
            raise HTTPException(
                503,
                f"TCMS 引擎不可用：自定义场景执行需要 tcms-can-test。请 pip install tcms-can-test，"
                f"或设置 TCMS_UPSTREAM_DIR 指向其目录。({e})",
            ) from None
        if not req.steps:
            raise HTTPException(422, "自定义场景至少需要一个步骤")

        # 校验故障键存在（在真实故障字典内，防拼写错误静默通过）
        for st in req.steps:
            if st.action == "inject":
                if not st.fault:
                    raise HTTPException(422, f"at={st.at} 的 inject 步骤缺少 fault")
                if st.fault not in asset_model.faults_by_key:
                    raise HTTPException(
                        422,
                        f"未知故障键: {st.fault}（可用故障见 /api/faults，共 {len(asset_model.faults_by_key)} 个）",
                    )
            elif st.action != "recover":
                raise HTTPException(422, f"at={st.at} 的未知动作: {st.action!r}（仅支持 inject/recover）")
            elif not st.fault:
                raise HTTPException(422, f"at={st.at} 的 recover 步骤缺少 fault")

        # 组装 YAML（显式 inject/recover 写法；level/impact/expect 缺省由引擎字典兜底）
        lines = [f"name: {req.name or 'custom'}", "steps:"]
        for st in sorted(req.steps, key=lambda s: s.at):
            if st.action == "inject":
                lines.append(f"  - at: {st.at}")
                lines.append("    inject:")
                lines.append(f"      fault: {st.fault}")
                if st.node:
                    lines.append(f"      node: {st.node}")
                if st.level:
                    lines.append(f"      level: {st.level}")
                if st.impact:
                    lines.append(f"      impact: {st.impact}")
                if st.expect:
                    lines.append(f"      expect: {st.expect}")
            else:
                lines.append(f"  - at: {st.at}")
                lines.append(f"    recover: {st.fault}")
        yaml_text = "\n".join(lines)

        try:
            scenario = sc.parse_scenario(yaml_text, name=req.name or "custom")
            clock = _tb.VirtualClock(mode="virtual")
            from tcms.faultlife import FaultLedger, ScenarioRunner  # noqa: PLC0415

            rep = ScenarioRunner(FaultLedger(clock), scenario, clock).run()
        except Exception as e:  # 组装/执行异常 → 500 含信息
            raise HTTPException(500, f"自定义场景执行失败: {e}") from None
        _run_counter["n"] += 1
        sink.record_run(
            f"run-{_run_counter['n']:03d}",
            req.name or "custom",
            {"passed": rep.get("passed"), "failed": rep.get("failed"), "all_passed": rep.get("all_passed")},
        )
        return {
            "scenario": rep.get("scenario"),
            "steps": rep.get("steps"),
            "assertions": rep.get("assertions"),
            "passed": rep.get("passed"),
            "failed": rep.get("failed"),
            "all_passed": rep.get("all_passed"),
            "engine_version": __import__("tcms").__version__,
            "run_id": f"run-{_run_counter['n']:03d}",
            "custom": True,
        }

    # ---- 前端静态托管（P3）：生产构建 dist/ 挂到根路径 ----
    # 路径解析：PyInstaller 打包(frozen)时静态资源在 sys._MEIPASS/web/dist；
    # 源码运行时在仓库 web/dist。
    import sys as _sys

    if getattr(_sys, "frozen", False):
        _bundle = Path(getattr(_sys, "_MEIPASS", Path(__file__).resolve().parent))
        _web_dist = _bundle / "web" / "dist"
    else:
        _web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if _web_dist.is_dir():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        # 静态资源（/assets/...）
        app.mount("/assets", StaticFiles(directory=_web_dist / "assets"), name="assets")

        # SPA fallback：非 /api 的未知路径回 index.html（前端路由）
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            f = _web_dist / full_path
            if full_path and f.is_file():
                return FileResponse(f)
            return FileResponse(_web_dist / "index.html")

    return app


app = create_app()


def main() -> None:
    """启动入口：python -m tcms_ai_platform.server.app / tcms-platform / 打包后的 exe。"""
    import os
    import sys as _sys
    import threading

    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    # 延迟自动开浏览器（仅本地非 headless 环境；exe 内也开）
    def _open_browser() -> None:
        import time

        time.sleep(1.6)
        try:
            import webbrowser

            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:  # noqa: BLE001 - 开浏览器失败不影响服务
            pass

    if not os.environ.get("DSH_NO_BROWSER"):
        threading.Thread(target=_open_browser, daemon=True).start()

    if getattr(_sys, "frozen", False):
        # 打包态：直接跑已构建的 app 对象，避免按 import 字符串二次解析
        uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
    else:
        uvicorn.run("tcms_ai_platform.server.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
