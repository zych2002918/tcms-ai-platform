"""P2 混合检索（GraphRAG）+ 有界分层路由 + 沉淀闭环。

`HybridRetriever.retrieve(query)`（Q4 升级：图谱路由 → 域内语义 topk，不迷失）：
1. **路由**：从查询里提取域线索（子系统词/域别名/图谱 fault 邻接），映射到 1~2 个分区；
2. **有界域内检索**：只在路由到的分区做向量 topk（候选池有界，不再全库线性扫）；
   路由失败则回退全库 topk（诚实降级，保召回）；
3. **证据富化**：对每个命中取其图谱 neighbors 作证据路径（结构化邻接）；
4. 返回 {query, routed_domains, bounded, hits} —— 路由信息供 UI 展示「检索走向」。

`GraphSink.record_run(result)`：执行结果 → run 节点 + 关联（组织记忆，L2 运行层）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph import KnowledgeGraph
from .vector import DOMAIN_ZH, VectorStore

# 域路由词表：查询里的中文/英文域信号 → 分区（故障名/子系统外显词）
_DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "traction": ("牵引", "traction", "电机", "逆变", "手柄", "超速", "overspeed", "限速"),
    "brake": ("制动", "brake", "刹车", "缸压", "制动力", "紧急制动", "EB", "闸瓦"),
    "door": ("车门", "door", "门", "联锁门", "站台门", "门控"),
    "power": ("能源", "电池", "SOC", "储能", "电", "power", "bms"),
    "pantograph": ("受电弓", "弓", "高压", "pantograph", "网压"),
    "network": ("网络", "心跳", "VCU", "总线", "报文", "CRC", "看门狗", "重启", "network", "bus"),
    "signal": ("信号", "传感器", "漂移", "卡死", "signal", "sensor"),
}


def _route_domains(query: str) -> list[str]:
    """从查询文本提取域信号 → 命中的分区域（按命中词数降序，最多 2 个）。"""
    q = (query or "").lower()
    scored: list[tuple[int, str]] = []
    for dom, terms in _DOMAIN_TERMS.items():
        hit = sum(1 for t in terms if t.lower() in q)
        if hit:
            scored.append((hit, dom))
    scored.sort(reverse=True)
    return [d for _, d in scored[:2]]


@dataclass
class RetrievalHit:
    doc_id: str
    kind: str
    text: str
    score: float
    graph_neighbors: list[dict]  # [{id, kind, label, via}]


class HybridRetriever:
    """图谱路由 + 有界域内语义检索 + 图谱邻接证据（GraphRAG 混合）。"""

    def __init__(self, store: VectorStore, graph: KnowledgeGraph) -> None:
        self.store = store
        self.graph = graph

    def retrieve(self, query: str, k: int = 5, neighbor_limit: int = 6) -> dict:
        routed = _route_domains(query)
        hits = self.store.search(query, k=max(k * 2, 8), domains=routed if routed else None)
        # 域内候选可能不足 k → 诚实回退全库补召回（标注 mixed=true）
        mixed = len(hits) < k and bool(routed)
        if mixed:
            extra = self.store.search(query, k=k, domains=None)
            seen = {h["doc_id"] for h in hits}
            hits.extend(h for h in extra if h["doc_id"] not in seen)
        enriched = []
        for h in hits[: max(k, 8)]:
            nid = h["doc_id"]  # 向量 doc_id 与图节点 id 对齐（fault:x / req:x ...）
            neighbors = []
            if nid in self.graph.nodes:
                nbs = self.graph.neighbors(nid)
                for nb_id, via in nbs[:neighbor_limit]:
                    nb = self.graph.nodes.get(nb_id)
                    if nb:
                        neighbors.append({"id": nb.id, "kind": nb.kind, "label": nb.label, "via": via})
            enriched.append(
                {
                    "doc_id": h["doc_id"],
                    "kind": h["kind"],
                    "text": h["text"],
                    "score": h["score"],
                    "domain": (h.get("meta") or {}).get("domain", ""),
                    "graph_neighbors": neighbors,
                }
            )
        return {
            "query": query,
            "routed_domains": routed,
            "routed_zh": [DOMAIN_ZH.get(d, d) for d in routed],
            "bounded": bool(routed),
            "mixed_fallback": mixed,
            "hits": enriched,
        }

    def subgraph(self, seed_id: str, depth: int = 2) -> dict:
        """图谱子图（供可视化 / 前端图谱工作台）。"""
        if seed_id not in self.graph.nodes:
            return {"seed": seed_id, "nodes": [], "edges": [], "node_count": 0}
        return self.graph.subgraph(seed_id, depth)


class GraphSink:
    """沉淀闭环：执行结果 → 知识库 run 节点（组织记忆雏形）。"""

    def __init__(self, graph: KnowledgeGraph) -> None:
        self.graph = graph
        self.runs: list[dict] = []

    def record_run(self, run_id: str, scenario_file: str, result: dict) -> None:
        """记录一次真实执行。result 含 passed/failed/assertions。"""
        passed = result.get("passed", 0)
        failed = result.get("failed", 0)
        node_id = self.graph.add_node(
            "run",
            run_id,
            f"run:{run_id}",
            {
                "scenario": scenario_file,
                "passed": passed,
                "failed": failed,
                "all_passed": result.get("all_passed"),
            },
        )
        # 关联到场景节点
        scen_id = f"scenario:{scenario_file}"
        if scen_id in self.graph.nodes:
            self.graph.add_edge("run", run_id, "scenario", scenario_file, "executed")
        self.runs.append(
            {"run_id": run_id, "node_id": node_id, "scenario": scenario_file, "result": result}
        )
