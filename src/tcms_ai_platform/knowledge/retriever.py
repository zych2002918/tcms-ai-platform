"""P2 混合检索（GraphRAG）+ 沉淀闭环。

`HybridRetriever.retrieve(query)`：
1. 向量检索顶层命中（语义）
2. 对每个命中，取其 doc_id 对应图谱节点的 neighbors（结构近邻）作证据路径
3. 合并 → 返回 {answer 候选, evidence: [源doc + 图谱路径]}
   让"问答/诊断"能同时给出 语义命中 + 结构化邻接 两层证据。

`GraphSink.record_run(result)`：场景/执行结果沉淀回知识库
- 把一次真实执行的 断言/通过/失败 写为一条 run 记录节点（kind=run），
  关联到 fault / scenario —— 组织记忆雏形。
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph import KnowledgeGraph
from .vector import VectorStore


@dataclass
class RetrievalHit:
    doc_id: str
    kind: str
    text: str
    score: float
    graph_neighbors: list[dict]  # [{id, kind, label, via}]


class HybridRetriever:
    """语义(向量) + 结构(图谱) 双通道检索。"""

    def __init__(self, store: VectorStore, graph: KnowledgeGraph) -> None:
        self.store = store
        self.graph = graph

    def retrieve(self, query: str, k: int = 5, neighbor_limit: int = 6) -> dict:
        hits = self.store.search(query, k=k)
        enriched = []
        for h in hits:
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
                    "graph_neighbors": neighbors,
                }
            )
        return {"query": query, "hits": enriched}

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
