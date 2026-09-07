"""P2 向量索引：轻量、离线优先、可插拔 embedder。

设计（红线：知识底座不依赖任何 LLM API 即可跑通）：
- `Embedder` 抽象：`embed(text) -> np.ndarray`。默认 `HashedEmbedder`：
  确定性 token 哈希 → 归一化向量（中文按字符 + 英文按词切分，无需分词库），
  保证离线可用且对"故障/信号名/枚举"这类短结构化文本有效。
- 可插拔：将来接真 embedding 模型（如 BGE/sentence-transformers）只需实现
  同一接口并注入 store，检索代码零改动。
- `VectorStore`：add(document) / search(query, k) → 带 score 的命中。
  score = cosine；命中带 doc_id / kind / text / meta，供 GraphRAG 混合。

语料来源（P2 种子，全部真实）：
    FMEA 故障条目（desc/detect/inject/recovery）、场景描述、RTM verifies、
    被测功能描述 —— 由 store 构建器从 AssetModel 派生。
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Doc:
    doc_id: str  # 全局唯一（如 fault:overspeed / req:SR-01）
    kind: str  # fault / requirement / function / scenario
    text: str  # 检索文本
    meta: dict = field(default_factory=dict)


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> np.ndarray: ...


def _tokens(text: str) -> list[str]:
    """轻量切分：中文按字 + 英文按词 + 数字。无需分词库。"""
    # 英文/数字词
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text)
    # 中文字符（去空白）
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    out = [w.lower() for w in words]
    out.extend(chars)
    return out


class HashedEmbedder(Embedder):
    """确定性 token 哈希向量（离线，维度 DIM）。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec


class VectorStore:
    """内存向量库（可分片有界）：add / search（余弦）。

    有界分层设计（Q4）：
    - 每个 doc 可带 domain 分区标签（meta["domain"]），search 可按 domains 过滤 →
      检索先路由到域、再域内语义 topk（不会在庞大库中迷失）。
    - 分区容量上限：add 时可传 partition_caps {domain: max_docs}；超限自动拒绝
      （fail-loud 防静默溢出），由调用方做淘汰/归档。
    - 无 domain 的 doc 归 "" 分区（全局兼容，原行为不变）。
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        partition_caps: dict[str, int] | None = None,
    ) -> None:
        self.embedder = embedder or HashedEmbedder()
        self.docs: list[Doc] = []
        self._vectors: list[np.ndarray] = []
        self.partition_caps = dict(partition_caps or {})

    def _domain_of(self, doc: Doc) -> str:
        return str(doc.meta.get("domain", "") or "")

    def add(self, doc: Doc) -> bool:
        """加文档；返回是否成功（超分区上限时拒绝并返回 False，不静默溢出）。"""
        dom = self._domain_of(doc)
        cap = self.partition_caps.get(dom)
        if cap is not None:
            cur = sum(1 for d in self.docs if self._domain_of(d) == dom)
            if cur >= cap:
                return False
        self.docs.append(doc)
        self._vectors.append(self.embedder.embed(doc.text))
        return True

    def add_many(self, docs: list[Doc]) -> int:
        accepted = 0
        for d in docs:
            if self.add(d):
                accepted += 1
        return accepted

    def partition_stats(self) -> dict:
        """各分区文档数（供 UI/自检展示「有界索引」）。"""
        out: dict[str, int] = {}
        for d in self.docs:
            dom = self._domain_of(d)
            out[dom] = out.get(dom, 0) + 1
        return out

    def search(self, query: str, k: int = 8, domains: list[str] | None = None) -> list[dict]:
        """余弦 topk；domains 非空时只在该分区内检索（图谱路由后调用）。"""
        if not self.docs:
            return []
        idx = list(range(len(self.docs)))
        if domains is not None:
            dset = {d for d in domains if d != ""} | (set() if "" in (domains or []) else set())
            if dset or "" in (domains or []):
                idx = [
                    i
                    for i in idx
                    if (self._domain_of(self.docs[i]) in dset)
                    or (self._domain_of(self.docs[i]) == "" and "" in (domains or []))
                ]
                if not idx:
                    return []
        qv = self.embedder.embed(query)
        scores = []
        for i in idx:
            s = float(np.dot(qv, self._vectors[i]))
            scores.append((s, i))
        scores.sort(key=lambda t: t[0], reverse=True)
        out = []
        for s, i in scores[:k]:
            d = self.docs[i]
            out.append(
                {
                    "doc_id": d.doc_id,
                    "kind": d.kind,
                    "text": d.text,
                    "meta": d.meta,
                    "score": round(s, 4),
                }
            )
        return out

    def stats(self) -> dict:
        by_kind: dict[str, int] = {}
        for d in self.docs:
            by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
        return {"docs": len(self.docs), "by_kind": by_kind, "by_domain": self.partition_stats()}


# ---------------------------------------------------------------------------
# 语料构建：从 AssetModel 派生真实语料
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 域分区（Q4 有界分层：检索先路由到域，再域内语义 topk）
# ---------------------------------------------------------------------------
# 域标签沿用上游 faults.yaml 的 subsystem 归属；真实列车按 13 系统分类法
# (S1000D 01-13) 组织，当前资产子集已覆盖：牵引/制动/车门/能源/受电弓/网络/
# VCU/信号。域常量同时被图谱路由 (retriever) 与向量分区消费。

# 子系统 → 归一化域（别名收拢，避免"网络/VCU/信号"三处分片过碎）
SUB_DOMAIN: dict[str, str] = {
    "牵引": "traction",
    "制动": "brake",
    "车门": "door",
    "能源": "power",
    "受电弓": "pantograph",
    "网络": "network",
    "VCU": "network",  # VCU 心跳/健康属网络完整性域
    "信号": "signal",
}
DOMAIN_ZH: dict[str, str] = {
    "traction": "牵引",
    "brake": "制动",
    "door": "车门",
    "power": "能源/电池",
    "pantograph": "受电弓/高压",
    "network": "网络/VCU",
    "signal": "信号/传感",
    "": "通用",
}
DOMAINS: list[str] = ["traction", "brake", "door", "power", "pantograph", "network", "signal", ""]


def subsystem_domain(subsystem: str) -> str:
    """故障子系统 → 分区域（未收录归 网络 域，避免丢失可检索性）。"""
    return SUB_DOMAIN.get(subsystem or "", "network")


def build_docs_from_asset(m) -> list[Doc]:
    """从 L1 AssetModel 派生检索语料（全真实，无手编），并打 domain 分区标签。"""
    docs: list[Doc] = []

    # 故障：desc + detect + inject + recovery（分区 = 子系统域）
    for f in m.faults_by_key.values():
        dom = subsystem_domain(f.subsystem)
        docs.append(
            Doc(
                doc_id=f"fault:{f.key}",
                kind="fault",
                text=(
                    f"{f.name} {f.desc} 检测:{f.detect} 注入:{f.inject} "
                    f"恢复:{f.recovery} 等级:{f.level} 处置:{f.action} SIL:{f.sil}"
                ),
                meta={
                    "fid": f.fid,
                    "key": f.key,
                    "level": f.level,
                    "action": f.action,
                    "subsystem": f.subsystem,
                    "domain": dom,
                },
            )
        )

    # 需求 verifies（分区 = 覆盖它的功能主域；无覆盖归 ""）
    def _fault_domain(key: str) -> str:
        f = m.faults_by_key.get(key)
        return subsystem_domain(f.subsystem) if f else ""

    _REQ_DOMAIN: dict[str, str] = {}
    for fn in m.functions.values():
        dom = _fault_domain(fn.fault_keys[0]) if fn.fault_keys else ""
        for rid in fn.requirements:
            _REQ_DOMAIN.setdefault(rid, dom)
    for req_id, reqs in m.requirements.items():
        docs.append(
            Doc(
                doc_id=f"req:{req_id}",
                kind="requirement",
                text=f"{req_id} " + " ".join(r.verifies for r in reqs),
                meta={"req_id": req_id, "rows": len(reqs), "domain": _REQ_DOMAIN.get(req_id, "")},
            )
        )

    # 被测功能（分区 = 其 fault_keys 主域）

    for fn in m.functions.values():
        dom = _fault_domain(fn.fault_keys[0]) if fn.fault_keys else ""
        docs.append(
            Doc(
                doc_id=f"function:{fn.fid}",
                kind="function",
                text=f"{fn.name} {fn.description}",
                meta={"fid": fn.fid, "requirements": list(fn.requirements), "domain": dom},
            )
        )

    # 场景（分区 = 注入故障主域；多域场景归第一域）
    for s in m.scenarios.values():
        steps_txt = []
        for st in s.steps:
            if st.action == "inject":
                steps_txt.append(
                    f"在{st.at}s注入{st.fault}(节点{st.node})期望{st.expect}"
                )
            else:
                steps_txt.append(f"在{st.at}s恢复{st.fault}")
        dom = _fault_domain(next(iter(s.fault_keys), "")) if s.fault_keys else ""
        docs.append(
            Doc(
                doc_id=f"scenario:{s.file}",
                kind="scenario",
                text=f"{s.name} {' '.join(steps_txt)}",
                meta={"file": s.file, "domain": dom},
            )
        )

    # 报文/信号元（让检索能命中"心跳/门/速度"等）；分区 = 发送设备域
    _DEV_DOMAIN = {"BCU": "brake", "VCU": "network", "BMS": "power", "TCMS": "network", "BOGIE": "door"}
    for msg in m.messages.values():
        dom = _DEV_DOMAIN.get(msg.node, "")
        docs.append(
            Doc(
                doc_id=f"message:{msg.name}",
                kind="message",
                text=(
                    f"报文 {msg.name} 发送节点{msg.node} 周期{msg.cycle_ms}ms "
                    f"类型{msg.send_type} 信号:" + ",".join(msg.signal_names)
                ),
                meta={"name": msg.name, "cycle_ms": msg.cycle_ms, "domain": dom},
            )
        )
    for sig in m.signals.values():
        unit = f"单位{sig.unit}" if sig.unit else ""
        choices = " 取值:" + ",".join(f"{k}={v}" for k, v in sig.choices.items()) if sig.choices else ""
        docs.append(
            Doc(
                doc_id=f"signal:{sig.name}",
                kind="signal",
                text=f"信号 {sig.name} 属于报文{sig.message} {unit} 范围{sig.minimum}~{sig.maximum}{choices}",
                meta={"name": sig.name, "message": sig.message},
            )
        )

    return docs
