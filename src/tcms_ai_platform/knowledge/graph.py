"""P2 知识图谱：从 L1 AssetModel 派生的实体/关系图（GraphRAG 结构通道）。

节点类型（对齐北极星 schema：信号→报文→设备→功能→需求→故障→场景）：
    signal / message / device / function / requirement / fault / scenario

关系（direction-aware，全部从真实资产派生，无手编）：
    signal -in-> message
    message -sent_by-> device
    device -involved_in-> function       (经功能表的报文/信号/故障键)
    function -covers_requirement-> requirement
    fault -detected_by_module-> module   (module 作为 value 节点：detect 文本提取)
    scenario -injects_fault-> fault
    scenario -runs_on-> device/node

查询：neighbors(node) / shortest_path / subgraph(seed, depth)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import AssetModel

# 节点类型全集
NODE_TYPES = {
    "signal",
    "message",
    "device",
    "function",
    "requirement",
    "fault",
    "scenario",
}

# 关系类型（展示标签）
EDGE_LABELS = {
    ("signal", "message"): "in",
    ("message", "device"): "sent_by",
    ("message", "function"): "used_in",
    ("signal", "function"): "used_in",
    ("function", "requirement"): "covers",
    ("fault", "function"): "triggers",
    ("scenario", "fault"): "injects",
    ("scenario", "device"): "runs_on",
    ("fault", "device"): "affects",
}


@dataclass(frozen=True)
class Node:
    kind: str  # NODE_TYPES
    id: str  # 规范 id（如 signal:Door1State / req:SR-01）
    label: str  # 展示名
    props: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    src: str  # node id
    dst: str  # node id
    kind: str  # EDGE_LABELS value


def node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


class KnowledgeGraph:
    """内存图：邻接表 + 节点/边集合（P2 阶段足够；后续可换图库）。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._adj: dict[str, list[str]] = {}

    def add_node(self, kind: str, key: str, label: str, props: dict | None = None) -> str:
        nid = node_id(kind, key)
        if nid not in self.nodes:
            self.nodes[nid] = Node(kind=kind, id=nid, label=label, props=props or {})
            self._adj.setdefault(nid, [])
        return nid

    def add_edge(self, src_kind: str, src_key: str, dst_kind: str, dst_key: str, kind: str) -> None:
        src = node_id(src_kind, src_key)
        dst = node_id(dst_kind, dst_key)
        if src not in self.nodes:
            raise KeyError(f"边起点不存在: {src}")
        if dst not in self.nodes:
            raise KeyError(f"边终点不存在: {dst}")
        if dst not in self._adj[src]:
            self._adj[src].append(dst)
        if src not in self._adj[dst]:
            self._adj[dst].append(src)
        self.edges.append(Edge(src=src, dst=dst, kind=kind))

    # ---- 查询 ----

    def neighbors(self, nid: str) -> list[tuple[str, str]]:
        """返回 [(邻居 node_id, 边 kind)]，双向。"""
        out = []
        for e in self.edges:
            if e.src == nid:
                out.append((e.dst, e.kind))
            elif e.dst == nid:
                out.append((e.src, e.kind))
        return out

    def subgraph(self, seed_id: str, depth: int = 2) -> dict:
        """以 seed 为中心提取子图（BFS），用于可视化/检索上下文。"""
        visited: set[str] = set()
        frontier = [seed_id]
        for _ in range(depth):
            nxt = []
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                for nb, _kind in self.neighbors(nid):
                    if nb not in visited and nb not in nxt:
                        nxt.append(nb)
            frontier = nxt
        # 子图边（两端都在 visited 内）
        sub_edges = []
        seen = set()
        for e in self.edges:
            if e.src in visited and e.dst in visited:
                key = (e.src, e.dst, e.kind)
                if key not in seen:
                    seen.add(key)
                    sub_edges.append({"src": e.src, "dst": e.dst, "kind": e.kind})
        return {
            "seed": seed_id,
            "depth": depth,
            "nodes": [
                {"id": n.id, "kind": n.kind, "label": n.label}
                for n in self.nodes.values()
                if n.id in visited
            ],
            "edges": sub_edges,
            "node_count": len(visited),
        }

    def stats(self) -> dict:
        by_kind: dict[str, int] = {}
        for n in self.nodes.values():
            by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
        return {"nodes": len(self.nodes), "edges": len(self.edges), "by_kind": by_kind}


# ---------------------------------------------------------------------------
# 构建器：从 AssetModel 派生
# ---------------------------------------------------------------------------


def build_knowledge_graph(m: AssetModel) -> KnowledgeGraph:
    """从 L1 AssetModel 构建完整图谱（全部关系机器派生）。"""
    g = KnowledgeGraph()

    # 设备
    for dev in m.devices.values():
        g.add_node("device", dev.name, dev.name, {"role": dev.role})

    # 报文 / 信号
    for msg in m.messages.values():
        g.add_node("message", msg.name, msg.name, {"cycle_ms": msg.cycle_ms})
        if msg.node in m.devices:
            g.add_edge("message", msg.name, "device", msg.node, "sent_by")
    for sig in m.signals.values():
        g.add_node("signal", sig.name, sig.name, {"unit": sig.unit})
        if sig.message in m.messages:
            g.add_edge("signal", sig.name, "message", sig.message, "in")

    # 故障
    for f in m.faults_by_key.values():
        g.add_node(
            "fault",
            f.key,
            f"{f.name} ({f.fid})",
            {"level": f.level, "action": f.action, "sil": f.sil, "subsystem": f.subsystem},
        )

    # 场景
    for s in m.scenarios.values():
        g.add_node("scenario", s.file, s.name, {"steps": len(s.steps)})
        for fk in s.fault_keys:
            if fk in m.faults_by_key:
                g.add_edge("scenario", s.file, "fault", fk, "injects")
        for n in s.nodes:
            dev = n.upper() if n != "bus" else "TCMS"
            if dev in m.devices:
                g.add_edge("scenario", s.file, "device", dev, "runs_on")

    # 需求
    for req_id, reqs in m.requirements.items():
        g.add_node(
            "requirement",
            req_id,
            req_id,
            {"verifies": " | ".join(r.verifies for r in reqs)},
        )

    # 被测功能（聚合层，锚定真实）
    for fn in m.functions.values():
        g.add_node("function", fn.fid, fn.name, {"description": fn.description})
        for msg in fn.messages:
            if msg in m.messages:
                g.add_edge("function", fn.fid, "message", msg, "used_in")
        for sig in fn.signals:
            if sig in m.signals:
                g.add_edge("function", fn.fid, "signal", sig, "used_in")
        for fk in fn.fault_keys:
            if fk in m.faults_by_key:
                g.add_edge("fault", fk, "function", fn.fid, "triggers")
        for req in fn.requirements:
            if req in m.requirements:
                g.add_edge("function", fn.fid, "requirement", req, "covers")

    # 故障 → 设备（经子系统近邻）
    _SUB_DEV = {
        "VCU": "VCU",
        "车门": "BOGIE",
        "能源": "BMS",
        "牵引": "VCU",
        "受电弓": "BCU",
        "制动": "BCU",
        "网络": "TCMS",
    }
    for f in m.faults_by_key.values():
        dev = _SUB_DEV.get(f.subsystem)
        if dev and dev in m.devices:
            g.add_edge("fault", f.key, "device", dev, "affects")

    return g
