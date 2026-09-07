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
    assert s["nodes"] == 121  # 24 场景
    assert s["edges"] >= 150
    assert s["by_kind"]["fault"] == 26
    assert s["by_kind"]["signal"] == 36
    assert s["by_kind"]["scenario"] == 24
    assert s["by_kind"]["function"] == 4


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
    assert s["docs"] == 116  # 资产文档(含4新故障+2新场景)
    assert s["by_kind"]["fault"] == 26
    assert s["by_kind"]["requirement"] == 18


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
    """enrich 后 system 节点存在，且 22 条故障全部 belongs_to 某系统。"""
    from tcms_ai_platform.core import load_asset_model
    from tcms_ai_platform.domain import enrich_graph
    from tcms_ai_platform.knowledge import VectorStore, build_knowledge_graph

    m = load_asset_model(UPSTREAM)
    g = build_knowledge_graph(m)
    vs = VectorStore()
    enrich_graph(g, vs)
    systems = {n.id for n in g.nodes.values() if n.kind == "system"}
    assert len(systems) >= 6  # SYS-TRAIN/BRAKE/TRACTION/DOOR/POWER/SENSING
    linked = {e.src for e in g.edges if e.kind == "belongs_to" and e.src.startswith("fault:")}
    assert len(linked) == 26  # 全部故障归属系统


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
