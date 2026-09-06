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


def create_app(asset_model: AssetModel | None = None, upstream: str | Path | None = None) -> FastAPI:
    """应用工厂。asset_model 缺省时按 upstream 加载；都缺省 → 默认上游。"""
    global _app_model, _app_upstream

    if asset_model is None:
        if upstream is None:
            upstream = Path(__file__).resolve().parents[4] / "tcms-can-test"
        asset_model = load_asset_model(upstream)
    _app_model = asset_model
    _app_upstream = Path(str(asset_model.source_upstream))

    # 知识底座（P2）：图谱 + 向量 + 混合检索（同一 app 实例内单例）
    graph = build_knowledge_graph(asset_model)
    store = VectorStore()
    store.add_many(build_docs_from_asset(asset_model))
    retriever = HybridRetriever(store, graph)
    sink = GraphSink(graph)
    _run_counter = {"n": 0}

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
        return {"graph": graph.stats(), "vector": store.stats()}

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

        # 动态导入上游引擎（与本平台 venv 同依赖，探针已验证可导入）
        import sys

        upstream = str(_app_upstream)
        if upstream not in sys.path:
            sys.path.insert(0, upstream)
        try:
            import tcms.scenarios as sc  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover - 环境缺失时给明确错误
            raise HTTPException(
                500, f"上游引擎不可导入（需 tcms-can-test 在 PYTHONPATH）: {e}"
            ) from None

        try:
            rep = sc.run_yaml(str(_app_upstream / "scenarios" / req.scenario))
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
        import sys

        upstream = str(_app_upstream)
        if upstream not in sys.path:
            sys.path.insert(0, upstream)
        try:
            import tcms.scenarios as sc  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise HTTPException(
                500, f"上游引擎不可导入: {e}"
            ) from None

        results = []
        total_pass = total_fail = 0
        for file in asset_model.scenarios:
            rep = sc.run_yaml(str(_app_upstream / "scenarios" / file))
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

    # ---- 前端静态托管（P3）：生产构建 dist/ 挂到根路径 ----
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
    """uvicorn 启动入口（python -m tcms_ai_platform.server.app）。"""
    import uvicorn

    uvicorn.run("tcms_ai_platform.server.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
