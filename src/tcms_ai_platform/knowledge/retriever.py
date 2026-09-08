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

import re
from dataclasses import dataclass

from .graph import KnowledgeGraph
from .vector import DOMAIN_ZH, VectorStore, system_domain

# 域路由词表：查询里的中文/英文域信号 → 分区（13 域与 domain_systems.json 同口径）
_DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "network": ("网络", "心跳", "VCU", "总线", "报文", "CRC", "看门狗", "重启", "网关", "司控", "主控", "network", "bus"),
    "brake": ("制动", "brake", "刹车", "缸压", "防滑", "闸瓦", "紧急制动", "EB", "制动缸"),
    "traction": ("牵引", "traction", "超速", "限速", "逆变", "变流器", "母线", "手柄", "overspeed", "ATP"),
    "door": ("车门", "door", "门控", "联锁门", "站台门", "门气源", "门开", "后车门"),
    "pantograph": ("受电弓", "弓", "网压", "高压", "拉弧", "升弓", "pantograph"),
    "battery": ("电池", "SOC", "储能", "绝缘", "单体", "充放电", "bms", "battery", "均衡"),
    "aux": ("辅助", "aux", "低压母线", "辅助变流", "接触器", "过载", "辅逆"),
    "hvac": ("空调", "暖通", "压缩机", "客室", "制冷", "制热", "新风", "滤网", "加热器", "舒适度", "hvac"),
    "pis": ("PIS", "乘客信息", "显示屏", "对讲", "播报", "到站", "pis", "display"),
    "light": ("照明", "应急灯", "灯光", "light", "lamp"),
    "fire": ("烟火", "烟雾", "灭火", "探测器", "火警", "疏散", "fire", "smoke"),
    "bogie": ("走行部", "轴温", "轴箱", "轴承", "振动", "转向架", "bogie"),
    "signal": ("信号", "传感器", "漂移", "卡死", "表决", "超范围", "signal", "sensor"),
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


def _shared_cjk(query: str, text: str) -> int:
    """查询与文本共享的中文字符数（图谱路由的"词元重合"闸门）。"""
    qs = set(re.findall(r"[\u4e00-\u9fff]", query or ""))
    ts = set(re.findall(r"[\u4e00-\u9fff]", text or ""))
    return len(qs & ts)


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

    def _route_via_graph(self, query: str, probe: int = 3) -> list[str]:
        """图谱先定位域：查询无显式域词时，用全局 top-k 命中经 belongs_to 边
        反查所属系统 → 得到 1 个分区域（Q4"先图谱定位系统再域内 topk"兜底）。

        只采信图谱 belongs_to 边（enrich_graph 注入的 system 节点），且查询与
        候选文档须共享 ≥3 个中文字符（词元重合闸门）——防止无域查询被哈希噪声
        文档误路由。未 enrich 的图没有系统边 → 返回 []（走全局检索，诚实降级）。
        """
        if not self.graph.nodes:
            return []
        qchars = set(re.findall(r"[\u4e00-\u9fff]", query or ""))
        probe_hits = self.store.search(query, k=probe, domains=None)
        votes: dict[str, int] = {}
        for h in probe_hits:
            nid = h["doc_id"]
            if nid not in self.graph.nodes:
                continue
            dom = ""
            for nb, via in self.graph.neighbors(nid):
                if via == "belongs_to" and nb.startswith("system:"):
                    dom = system_domain(nb.split(":", 1)[1])
                    break
            if not dom:
                continue
            # 词元重合闸门：查询须与候选文档有实质字符重合（防哈希噪声误路由）
            shared = len(qchars & set(re.findall(r"[\u4e00-\u9fff]", h.get("text") or "")))
            if shared >= 3:
                votes[dom] = votes.get(dom, 0) + 1
        if not votes:
            return []
        # 多数一致 → 采纳；唯一命中也可采纳（域内召回不足由 mixed 回退保底）
        best = max(votes.items(), key=lambda kv: kv[1])
        return [best[0]]

    def retrieve(self, query: str, k: int = 5, neighbor_limit: int = 6) -> dict:
        route_source = ""
        routed = _route_domains(query)
        if routed:
            route_source = "terms"
        else:
            routed = self._route_via_graph(query)
            if routed:
                route_source = "graph"
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
        # 分区路由命中率：最终 top-k 命中里属于路由分区的比例（bounded 时应 =1.0）
        rset = set(routed)
        surfaced = enriched[:k]
        route_precision = (
            round(
                sum(1 for h in surfaced if (h["domain"] or "") in rset) / len(surfaced),
                3,
            )
            if surfaced and rset
            else None
        )
        return {
            "query": query,
            "routed_domains": routed,
            "routed_zh": [DOMAIN_ZH.get(d, d) for d in routed],
            "route_source": route_source,  # terms=词表路由 / graph=图谱定位域 / ''=全局
            "route_precision": route_precision,  # 分区命中率（域内召回质量）
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
