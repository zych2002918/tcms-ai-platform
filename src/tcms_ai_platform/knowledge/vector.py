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
    """内存向量库：add / search（余弦）。"""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashedEmbedder()
        self.docs: list[Doc] = []
        self._vectors: list[np.ndarray] = []

    def add(self, doc: Doc) -> None:
        self.docs.append(doc)
        self._vectors.append(self.embedder.embed(doc.text))

    def add_many(self, docs: list[Doc]) -> int:
        for d in docs:
            self.add(d)
        return len(docs)

    def search(self, query: str, k: int = 8) -> list[dict]:
        if not self.docs:
            return []
        qv = self.embedder.embed(query)
        scores = []
        for i, vec in enumerate(self._vectors):
            # 余弦（向量已归一化）
            s = float(np.dot(qv, vec))
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
        return {"docs": len(self.docs), "by_kind": by_kind}


# ---------------------------------------------------------------------------
# 语料构建：从 AssetModel 派生真实语料
# ---------------------------------------------------------------------------


def build_docs_from_asset(m) -> list[Doc]:
    """从 L1 AssetModel 派生检索语料（全真实，无手编）。"""
    docs: list[Doc] = []

    # 故障：desc + detect + inject + recovery
    for f in m.faults_by_key.values():
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
                },
            )
        )

    # 需求 verifies
    for req_id, reqs in m.requirements.items():
        docs.append(
            Doc(
                doc_id=f"req:{req_id}",
                kind="requirement",
                text=f"{req_id} " + " ".join(r.verifies for r in reqs),
                meta={"req_id": req_id, "rows": len(reqs)},
            )
        )

    # 被测功能
    for fn in m.functions.values():
        docs.append(
            Doc(
                doc_id=f"function:{fn.fid}",
                kind="function",
                text=f"{fn.name} {fn.description}",
                meta={"fid": fn.fid, "requirements": list(fn.requirements)},
            )
        )

    # 场景（含步骤语义）
    for s in m.scenarios.values():
        steps_txt = []
        for st in s.steps:
            if st.action == "inject":
                steps_txt.append(
                    f"在{st.at}s注入{st.fault}(节点{st.node})期望{st.expect}"
                )
            else:
                steps_txt.append(f"在{st.at}s恢复{st.fault}")
        docs.append(
            Doc(
                doc_id=f"scenario:{s.file}",
                kind="scenario",
                text=f"{s.name} {' '.join(steps_txt)}",
                meta={"file": s.file},
            )
        )

    # 报文/信号元（让检索能命中"心跳/门/速度"等）
    for msg in m.messages.values():
        docs.append(
            Doc(
                doc_id=f"message:{msg.name}",
                kind="message",
                text=(
                    f"报文 {msg.name} 发送节点{msg.node} 周期{msg.cycle_ms}ms "
                    f"类型{msg.send_type} 信号:" + ",".join(msg.signal_names)
                ),
                meta={"name": msg.name, "cycle_ms": msg.cycle_ms},
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
