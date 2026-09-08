"""P2 测试：知识图谱 + 向量索引 + GraphRAG 混合检索 + 沉淀闭环。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tcms_ai_platform.core import load_asset_model
from tcms_ai_platform.knowledge import (
    GraphSink,
    HashedEmbedder,
    HybridRetriever,
    VectorStore,
    build_docs_from_asset,
    build_knowledge_graph,
)

UPSTREAM = Path(__file__).resolve().parents[2] / "tcms-can-test"
NEEDS_UPSTREAM = pytest.mark.skipif(
    not UPSTREAM.is_dir(), reason=f"上游不存在: {UPSTREAM}"
)


@pytest.fixture(scope="module")
def kb():
    m = load_asset_model(UPSTREAM)
    g = build_knowledge_graph(m)
    store = VectorStore()
    store.add_many(build_docs_from_asset(m))
    return {"model": m, "graph": g, "store": store, "retriever": HybridRetriever(store, g)}


# ---- 图谱 ----


@NEEDS_UPSTREAM
def test_graph_stats(kb):
    s = kb["graph"].stats()
    assert s["nodes"] == 337  # 22 报文/116 信号/66 故障/59 场景/52 需求/11 功能/11 设备
    assert s["edges"] >= 300
    assert s["by_kind"]["fault"] == 66
    assert s["by_kind"]["signal"] == 116
    assert s["by_kind"]["scenario"] == 59
    assert s["by_kind"]["function"] == 11


@NEEDS_UPSTREAM
def test_graph_function_anchors(kb):
    """功能节点必须联通知 报文/信号/需求/故障（可漫游）。"""
    g = kb["graph"]
    fn = "function:F-DOOR"
    nbs = {nid for nid, _ in g.neighbors(fn)}
    assert "message:DoorControl" in nbs
    assert "signal:Door1State" in nbs
    assert "fault:door_fault" in nbs
    assert "requirement:SR-04" in nbs


@NEEDS_UPSTREAM
def test_graph_subgraph_overspeed(kb):
    sub = kb["retriever"].subgraph("fault:overspeed", 2)
    assert sub["node_count"] >= 5
    kinds = {n["kind"] for n in sub["nodes"]}
    assert "function" in kinds and "scenario" in kinds


# ---- 向量 ----


@NEEDS_UPSTREAM
def test_vector_store_stats(kb):
    s = kb["store"].stats()
    assert s["docs"] == 326  # 资产文档：66 故障/116 信号/59 场景/52 需求/11 功能/22 报文
    assert s["by_kind"]["fault"] == 66
    assert s["by_kind"]["requirement"] == 52


@NEEDS_UPSTREAM
def test_vector_search_door(kb):
    hits = kb["store"].search("车门故障 不能发车", k=3)
    ids = {h["doc_id"] for h in hits}
    assert any("door" in i or "DOOR" in i for i in ids)


@NEEDS_UPSTREAM
def test_hashed_embedder_deterministic():
    emb = HashedEmbedder(dim=128)
    v1 = emb.embed("超速 160km/h 紧急制动")
    v2 = emb.embed("超速 160km/h 紧急制动")
    assert (v1 == v2).all()
    assert abs(float(v1 @ v1) - 1.0) < 1e-3  # 归一化


# ---- 混合检索 ----


@NEEDS_UPSTREAM
def test_hybrid_retrieve_evidence(kb):
    r = kb["retriever"].retrieve("紧急制动 执行失败", k=3)
    assert r["hits"]
    top = r["hits"][0]
    assert "doc_id" in top and "graph_neighbors" in top
    # 顶层命中应带结构邻接（证据链）
    assert top["graph_neighbors"] is not None


@NEEDS_UPSTREAM
def test_hybrid_door_has_graph_neighbors(kb):
    r = kb["retriever"].retrieve("车门故障 不能发车", k=5)
    door_hit = next((h for h in r["hits"] if h["doc_id"] == "fault:door_fault"), None)
    assert door_hit is not None
    nids = {n["id"] for n in door_hit["graph_neighbors"]}
    assert "scenario:door_cascade.yaml" in nids
    assert "function:F-DOOR" in nids


# ---- 沉淀闭环 ----


@NEEDS_UPSTREAM
def test_graph_sink_records_run(kb):
    g = kb["graph"]
    sink = GraphSink(g)
    before = len(g.nodes)
    sink.record_run(
        "run-test-001",
        "door_cascade.yaml",
        {"passed": 2, "failed": 0, "all_passed": True},
    )
    assert len(g.nodes) == before + 1
    assert len(sink.runs) == 1
    run_id = "run:run-test-001"
    assert run_id in g.nodes


# ---- Q4：有界分层检索（域路由 → 域内语义 topk） ----


@NEEDS_UPSTREAM
def test_partition_stats_domain_tagged(kb):
    """资产文档已按子系统打域标（有界索引的分区基础）。"""
    by = kb["store"].partition_stats()
    # 资产文档已按子系统打域标；验证域集合非空且可路由
    assert "door" in by and "network" in by and "brake" in by
    assert by.get("network", 0) >= 9  # 网络子系统 9 故障 + 相关报文/场景


@NEEDS_UPSTREAM
def test_asset_docs_all_partitioned(kb):
    """Q4 域标签铺全：故障/报文/信号/场景/功能文档必须全部分区（无空域）；
    需求仅"基础设施类 SR"允许空域（不被任何功能覆盖，属全局层）。"""
    from tcms_ai_platform.knowledge import build_docs_from_asset

    m = kb["model"]
    docs = build_docs_from_asset(m)
    kinds = {}
    for d in docs:
        kinds.setdefault(d.kind, []).append(d)

    # 每类中带非空 domain 的数量
    def nonempty(kind: str) -> int:
        return sum(1 for d in kinds.get(kind, []) if (d.meta.get("domain") or ""))

    assert nonempty("fault") == len(m.faults_by_key) == 66
    assert nonempty("message") == len(m.messages) == 22
    assert nonempty("signal") == len(m.signals) == 116
    assert nonempty("scenario") == len(m.scenarios) == 59
    assert nonempty("function") == len(m.functions) == 11
    # 需求：只有不被任何功能追溯的 SR 才允许空域（基础设施类，如 recorder/replay/rtm）
    covered = {rid for fn in m.functions.values() for rid in fn.requirements}
    infra = {rid for rid in m.requirements if rid not in covered}
    empty_reqs = {d.meta["req_id"] for d in kinds.get("requirement", []) if not (d.meta.get("domain") or "")}
    assert empty_reqs == infra, (f"需求空域 ≠ 基础设施集: {empty_reqs - infra} / {infra - empty_reqs}")


@NEEDS_UPSTREAM
def test_route_hvac_domain_precision_one(kb):
    """新域（HVAC）查询：词表路由到 hvac 分区，域内 topk 命中率=1.0。"""
    r = kb["retriever"].retrieve("空调压缩机过流保护 制冷降级", k=3)
    assert r["bounded"] is True
    assert r["route_source"] == "terms"
    assert "hvac" in r["routed_domains"]
    assert r["route_precision"] == 1.0
    ids = {h["doc_id"] for h in r["hits"]}
    assert "fault:hvac_compressor_overcurrent" in ids


@NEEDS_UPSTREAM
def test_route_via_graph_only_counts_system_edges(kb):
    """图谱定位域兜底：只采信 belongs_to system 边且需词元重合；
    无域词但语义贴近的查询 → 图谱路由到 bogie；纯噪声查询（无字符重合）→ 回退全局。"""
    from tcms_ai_platform.knowledge import Doc, HybridRetriever, VectorStore
    from tcms_ai_platform.knowledge.graph import KnowledgeGraph

    g = KnowledgeGraph()
    g.add_node("fault", "zz_fake", "假故障", {"subsystem": "走行部"})
    g.add_node("system", "SYS-BOGIE", "走行部", {})
    g.add_edge_raw("fault:zz_fake", "system:SYS-BOGIE", "belongs_to")
    vs = VectorStore()
    vs.add(Doc(doc_id="fault:zz_fake", kind="fault",
               text="该转动件高温异常处置流程", meta={"domain": "bogie"}))
    # 无域词、但与文档共享 ≥3 中文字符 → 图谱路由到 bogie
    r = HybridRetriever(vs, g).retrieve("那个转动件高温咋办", k=3)
    assert r["bounded"] is True
    assert r["route_source"] == "graph"
    assert r["routed_domains"] == ["bogie"]
    # 纯噪声（无中文字符重合）→ 图谱兜底不采信 → 回退全局
    r2 = HybridRetriever(vs, g).retrieve("zzzz qwerty 12345", k=3)
    assert r2["bounded"] is False
    assert r2["route_source"] == ""


@NEEDS_UPSTREAM
def test_route_domain_door(kb):
    r = kb["retriever"].retrieve("车门故障 不能发车", k=3)
    assert r["bounded"] is True
    assert "door" in r["routed_domains"]
    # 域内 top1 应命中 door 域资产
    top = r["hits"][0]
    assert top.get("domain") in ("door", "")


@NEEDS_UPSTREAM
def test_route_domain_heartbeat(kb):
    r = kb["retriever"].retrieve("VCU 心跳丢失 降级", k=3)
    assert "network" in r["routed_domains"]
    ids = {h["doc_id"] for h in r["hits"]}
    assert "fault:heartbeat_loss_vcu" in ids


@NEEDS_UPSTREAM
def test_unrouted_query_falls_back_global(kb):
    """无域信号查询（天气/通用）→ 不全域硬路由，退回全局检索保召回。"""
    r = kb["retriever"].retrieve("今天天气不错", k=3)
    assert r["bounded"] is False
    assert r["hits"]  # 仍返回（虽有噪，但诚实不空）


# ---- Q2 语义层：列车系统分类框架（system 节点 + 故障隶属 + 系统视角路由） ----


@NEEDS_UPSTREAM
def test_systems_injected_and_all_faults_linked():
    """enrich 后 system 节点存在（13 系统域），且 66 条故障全部 belongs_to 某系统。"""
    from tcms_ai_platform.core import load_asset_model
    from tcms_ai_platform.domain import enrich_graph
    from tcms_ai_platform.knowledge import VectorStore, build_knowledge_graph

    m = load_asset_model(UPSTREAM)
    g = build_knowledge_graph(m)
    vs = VectorStore()
    enrich_graph(g, vs)
    systems = {n.id for n in g.nodes.values() if n.kind == "system"}
    assert len(systems) == 13  # SYS-TRAIN/BRAKE/TRACTION/DOOR/PANTO/BATT/AUX/HVAC/PIS/LIGHT/FIRE/BOGIE/SENSING
    linked = {e.src for e in g.edges if e.kind == "belongs_to" and e.src.startswith("fault:")}
    assert len(linked) == 66  # 全部故障归属系统（_SUB_TO_SYS 覆盖 16 个子系统名）


@NEEDS_UPSTREAM
def test_system_view_routing_returns_system():
    """系统视角查询（"制动系统有哪些故障"）→ 路由到域且顶层命中 system 节点。"""
    from tcms_ai_platform.core import load_asset_model
    from tcms_ai_platform.domain import enrich_graph
    from tcms_ai_platform.knowledge import (
        HybridRetriever,
        VectorStore,
        build_docs_from_asset,
        build_knowledge_graph,
    )

    m = load_asset_model(UPSTREAM)
    g = build_knowledge_graph(m)
    vs = VectorStore()
    vs.add_many(build_docs_from_asset(m))
    enrich_graph(g, vs)
    hr = HybridRetriever(vs, g)
    r = hr.retrieve("制动系统有哪些故障", k=4)
    assert "brake" in r["routed_domains"]
    ids = [h["doc_id"] for h in r["hits"]]
    assert "system:SYS-BRAKE" in ids  # 先给出系统视角答案
