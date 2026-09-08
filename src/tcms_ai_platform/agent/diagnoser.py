"""症状多跳诊断规划器（C 步：harness/RAG 层的"无码症状→诊断步骤建议"）。

输入：一句症状类描述（无故障码，如「仪表盘闪烁但无故障码」）。
管线：
    1. kb 检索症状资产（RAG）：在向量库中找 kind=symptom 的命中（词元重合闸门，
       防噪声/防错域）；无命中 → 诚实 no_match + 需补充引导，绝不编造故障码；
    2. 图谱多跳：沿因果边取候选链 —— 症状 -indicates-> 怀疑故障（depth1），
       再沿 fault -causes-> fault 反查疑似根因（depth2+，见 graph.causal_chain）；
    3. 诊断建议：对每个候选给出"验证哪个真实故障 / 查哪个报文信号（detect）/
       用哪个现成场景复现"，置信度按 跳数×依据类型 确定性计算；
    4. 溯源：每条建议带 因果边 basis/note + 命中文档，derived 候选明确标注
       "仅示意，不可当已确认故障码"。

诚实纪律：
    - 只输出真实故障字典键（faults.yaml 202 条）/ 真实系统域；
    - 证据不足 → uncertain=true + 明确"需补充 X"；
    - LLM（可选）只在候选集内做排序/文案，不得自由发明故障（默认离线规则）。
"""

from __future__ import annotations

import re

from ..core.models import AssetModel
from ..domain.causal import symptoms as _catalog_symptoms
from ..knowledge import HybridRetriever

# 与 retriever._route_via_graph 同款"通用/诊断中性字"（防止仅因"故障/检测/报警"
# 等词重合而误判语义命中）
_GENERIC_CJK = frozenset(
    "故障检测处置注入恢复系统等级动作期望监控告警报警方法分析流程事件影响信息"
)

# 确定性置信度（跳数 × 依据类型；0~1 可解释单调）
_CONF = {
    (1, "real_mechanism"): 0.85,  # 症状直接指向的真实机制候选
    (1, "derived"): 0.5,  # 症状直接指向的示意候选
    (2, "real_mechanism"): 0.7,  # 一级嫌疑的真实根因（causes 反查）
    (2, "derived"): 0.4,
    (3, "real_mechanism"): 0.6,
    (3, "derived"): 0.35,
}
_SYMPTOM_MIN_ABS_SCORE = 0.05  # hashed 余弦绝对下限（防噪声）
_SYMPTOM_MIN_SHARED_CJK = 2  # 查询与症状文档共享的（非通用）中文字数下限


def _non_generic_cjk(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]", text or "")) - _GENERIC_CJK


def _zh_domain_zh(domain: str) -> str:
    from ..knowledge.vector import DOMAIN_ZH

    return DOMAIN_ZH.get(domain, domain)


def _fault_domain_of(m: AssetModel, fault_key: str) -> str:
    """故障键 → 13 域分区标签（domain_systems.json 单一真源派生）。"""
    from ..knowledge.vector import subsystem_domain

    fd = m.faults_by_key.get(fault_key)
    return subsystem_domain(fd.subsystem) if fd else ""


def _confidence(hop: int, basis: str) -> float:
    return _CONF.get((min(hop, 3), basis), 0.3)


def _scenario_files(m: AssetModel, fault_key: str) -> list[str]:
    return sorted(s.file for s in m.scenarios.values() if fault_key in s.fault_keys)


def _detect_summary(m: AssetModel, fault_key: str) -> str:
    fd = m.faults_by_key.get(fault_key)
    if fd is None:
        return ""
    return f"查 {fd.detect}" if fd.detect else fd.desc


# ---------------------------------------------------------------------------
# 匹配：检索症状资产（RAG）
# ---------------------------------------------------------------------------


def match_symptom(
    m: AssetModel,
    retriever: HybridRetriever,
    text: str,
    k: int = 8,
) -> dict | None:
    """在 kb 中找症状资产命中 → {key,name,...,score,doc_text} | None。

    只采信 kind=symptom 的文档；噪声闸门：绝对分 + 非通用中文字符重合数。
    """
    if not text.strip():
        return None
    # 症状资产跨 13 域分布：若按域词路由，用户口语里的域词（如“客室”）可能把
    # 症状文档隔在另一分区外（客室→hvac，而“客室灯组频闪”症状属 light）。
    # 故症状匹配走**全局检索**（不分区），再按 kind/噪声闸门过滤 —— 只影响召回面，
    # 不做错域路由。
    hits = retriever.store.search(text, k=max(k * 2, 16), domains=None)
    qchars = _non_generic_cjk(text)
    best: dict | None = None
    for h in hits:
        if h.get("kind") != "symptom":
            continue
        score = float(h.get("score", 0.0))
        if score < _SYMPTOM_MIN_ABS_SCORE:
            continue
        tchars = _non_generic_cjk(str(h.get("text", "")))
        if len(qchars & tchars) < _SYMPTOM_MIN_SHARED_CJK:
            continue
        if best is None or score > best["score"]:
            doc_id = str(h.get("doc_id", ""))
            key = doc_id.split(":", 1)[1] if doc_id.startswith("symptom:") else ""
            entry = {
                "key": key,
                "name": (h.get("meta") or {}).get("name", key),
                "score": round(score, 4),
                "doc_text": str(h.get("text", ""))[:400],
                "annotation": (h.get("meta") or {}).get("annotation", ""),
            }
            for s in _catalog_symptoms():
                if s.get("key") == key:
                    entry.update(
                        {
                            "description": s.get("description", ""),
                            "domains": s.get("domains", []),
                            "evidence": s.get("evidence", ""),
                        }
                    )
                    break
            best = entry
    return best


# ---------------------------------------------------------------------------
# 诊断主流程
# ---------------------------------------------------------------------------


def diagnose_symptom(
    m: AssetModel,
    graph,
    retriever: HybridRetriever,
    text: str,
    depth: int = 3,
    max_candidates: int = 8,
    use_llm: bool = False,
    llm_chat=None,  # noqa: ARG001 - 预留 LLM 候选内仲裁；默认规则路径
) -> dict:
    """症状文本 → 多跳诊断结果（结构化；绝不编造故障码）。"""
    text = (text or "").strip()
    if not text:
        return _no_match(text, "输入为空 —— 请描述你观察到的异常现象（部位/工况）。")

    sym = match_symptom(m, retriever, text)
    if sym is None:
        return _no_match(
            text,
            "未在症状资产中找到匹配 —— 需要补充：① 哪个部位/设备；② 什么工况下发生；"
            "③ 是否伴随其它现象或告警。我不会把没把握的描述硬说成某个故障。",
        )

    sym_id = f"symptom:{sym['key']}"
    walk = graph.causal_chain(sym_id, depth=depth) if sym_id in graph.nodes else {
        "seed": sym_id, "depth": depth, "chains": [], "node_count": 0,
    }

    # 合并候选：同一 fault 保留最浅跳 + 更强依据；chains 汇总溯源
    cand_by_key: dict[str, dict] = {}
    for hops in walk.get("chains", []):
        path_keys: list[str] = []
        path_names: list[str] = []
        for h in hops:
            to_id = h["to"]
            kind, key = (to_id.split(":", 1) + [""])[:2]
            if kind == "fault":
                cand = cand_by_key.setdefault(
                    key,
                    {
                        "fault": key,
                        "name": "",
                        "domain": "",
                        "domain_zh": "",
                        "level": "",
                        "action": "",
                        "sil": "",
                        "detect": "",
                        "scenarios": [],
                        "chains": [],
                        "best_hop": 99,
                        "basis": "derived",
                    },
                )
                hop_no = len(path_keys) + 1
                basis = h.get("basis") or "derived"
                if hop_no < cand["best_hop"] or (
                    hop_no == cand["best_hop"] and basis == "real_mechanism" and cand["basis"] != "real_mechanism"
                ):
                    cand["best_hop"] = hop_no
                    cand["basis"] = basis
                if h.get("note"):
                    cand.setdefault("notes", []).append(h["note"])
                cand["chains"].append(
                    {
                        "path": list(path_names),
                        "hop": hop_no,
                        "rel": h.get("rel", ""),
                        "basis": basis,
                        "note": h.get("note", ""),
                    }
                )
                fd = m.faults_by_key.get(key)
                if fd is not None:
                    cand["name"] = fd.name
                    cand["level"] = fd.level
                    cand["action"] = fd.action
                    cand["sil"] = fd.sil
                    cand["detect"] = fd.detect
                    cand["domain"] = _fault_domain_of(m, key)
                    cand["domain_zh"] = _zh_domain_zh(cand["domain"])
                    if not cand["scenarios"]:
                        cand["scenarios"] = _scenario_files(m, key)[:4]
            elif kind == "system":
                pass  # system 域级怀疑保留在 notes（当前因果表未用，前瞻兼容）
            path_keys.append(kind + ":" + key if kind else "")
            path_names.append(_graph_label(graph, to_id))

    candidates = []
    for key, c in cand_by_key.items():
        fd = m.faults_by_key.get(key)
        if fd is None:
            continue  # 诚实：只输出真实故障
        candidates.append(
            {
                "fault": key,
                "name": fd.name,
                "domain": c["domain"],
                "domain_zh": c["domain_zh"] or "通用",
                "hop": c["best_hop"],
                "basis": c["basis"],
                "confidence": round(_confidence(c["best_hop"], c["basis"]), 3),
                "level": fd.level,
                "action": fd.action,
                "sil": fd.sil,
                "check": _detect_summary(m, key),
                "scenarios": c["scenarios"],
                "notes": list(dict.fromkeys(c.get("notes", [])))[:3],
                "chains": c["chains"][:2],
                "derived": c["basis"] == "derived",
            }
        )
    candidates.sort(
        key=lambda c: (-c["confidence"], c["hop"], 0 if c["basis"] == "real_mechanism" else 1)
    )
    candidates = candidates[:max_candidates]

    # —— 可选：LLM 只在候选内仲裁（重排，禁止引入新故障键）——
    llm_used = False
    if use_llm and candidates:
        chat = llm_chat
        if chat is None:
            try:
                from .llm_backend import LLMAgentBackend, _api_key

                if _api_key() is not None:
                    chat = LLMAgentBackend()._chat
            except Exception:  # noqa: BLE001 - LLM 不可用则保持规则排序
                chat = None
        if chat is not None:
            order = _llm_arbitrate_candidates(candidates, sym, text, chat)
            if order:
                rank = {k: i for i, k in enumerate(order)}
                candidates.sort(key=lambda c: rank.get(c["fault"], len(rank)))
                llm_used = True

    plan = _build_plan(candidates)
    reply = _rule_reply(text, sym, candidates, plan)
    if llm_used:
        reply += "\n（LLM 已在候选内重排诊断顺序 —— 未引入候选之外的任何故障键。）"
    evidence = {
        "symptom_hit": {
            "doc_id": f"symptom:{sym['key']}",
            "kind": "symptom",
            "score": sym["score"],
            "text": sym["doc_text"],
        },
        "causal_edges_real": sum(1 for c in candidates if not c["derived"]),
        "causal_edges_derived": sum(1 for c in candidates if c["derived"]),
    }
    return {
        "query": text,
        "matched": True,
        "no_match": False,
        "symptom": sym,
        "uncertain": not candidates,
        "reply": reply,
        "candidates": candidates,
        "plan": plan,
        "evidence": evidence,
        "no_fault_code_invented": True,
        "llm_generated": llm_used,
    }


def _graph_label(graph, node_id: str) -> str:
    n = graph.nodes.get(node_id)
    if n is None:
        return node_id
    # fault label "名字 (F-TCMS-xxx)" → 名字
    label = n.label
    if " (" in label:
        return label.split(" (", 1)[0]
    return label


def _llm_arbitrate_candidates(candidates: list[dict], sym: dict, query: str, chat) -> list[str] | None:
    """LLM 候选内仲裁：只允许在给定 fault 键内重排/挑序；返回顺序或 None（失败/非法）。

    纪律（红线）：提示词明令禁止输出候选之外的故障键；返回列表经“有效集”过滤，
    非候选键一律丢弃，绝不进入结果 —— LLM 无法自由发明故障。
    """
    import json
    import re

    keys = [c["fault"] for c in candidates]
    # 只仲裁规则排序最靠前的前 4 个（候选已按置信度排好；模型长中文提示易空返回，故极简化）
    sel = candidates[:4]
    user_text = (
        f"症状：{query[:40]}\n"
        f"候选（只能原样使用这些英文键）：{', '.join(c['fault'] for c in sel)}\n"
        "请挑 1-3 个你认为最可能的：先逐行列出所选英文键，再给一句理由。"
    )
    system = (
        "你是 TCMS 症状诊断候选仲裁器。你只能原样使用用户给出的候选故障英文键，挑选并排序；"
        "严禁编造或使用候选之外的任何故障键。"
    )
    try:
        raw = chat(system, user_text)
    except Exception:  # noqa: BLE001 - LLM 失败 = 规则排序保底
        return None
    if not raw or not str(raw).strip():
        return None
    raw_s = str(raw)
    order = None
    m = re.search(r"\[[^\]]*\]", raw_s, flags=re.S)
    if m:
        try:
            order = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            order = None
    if not isinstance(order, list):
        order = None
    if order is None:
        # 兜底：LLM 未给纯 JSON 数组时，按候选键在回复文本中的首次出现顺序取序（只认候选键）
        found = sorted((raw_s.find(k), k) for k in keys if raw_s.find(k) >= 0)
        if found:
            order = [k for _, k in found]
    if not isinstance(order, list) or not order:
        return None
    valid = set(keys)
    picked = [str(k) for k in order if str(k) in valid]
    rest = [k for k in keys if k not in picked]
    if not picked:
        return None
    return picked + rest


def _build_plan(candidates: list[dict]) -> list[dict]:
    """候选 → 诊断步骤建议（验证哪条故障/查哪个报文信号/用什么场景复现）。"""
    plan = []
    for i, c in enumerate(candidates, start=1):
        verify = f"检查真实故障 {c['fault']}（{c['name']}，{c['level']}/{c['action']}）"
        if c["check"]:
            verify += f"：{c['check']}"
        step = {
            "step": i,
            "phase": "verify_fault",
            "fault": c["fault"],
            "name": c["name"],
            "domain": c["domain"],
            "domain_zh": c["domain_zh"],
            "hop": c["hop"],
            "basis": c["basis"],
            "confidence": c["confidence"],
            "description": verify[:220],
            "scenarios": c["scenarios"],
            "note": c["notes"][0] if c["notes"] else "",
            "derived": c["derived"],
        }
        plan.append(step)
    return plan


def _basis_zh(basis: str) -> str:
    return "真实机制" if basis == "real_mechanism" else "示意(derived)"


def _rule_reply(text: str, sym: dict, candidates: list[dict], plan: list[dict]) -> str:
    lines: list[str] = []
    if not candidates:
        lines.append(
            f"按症状描述「{text}」命中了症状资产「{sym.get('name', sym.get('key', ''))}」，"
            "但图谱上没有可审计的因果链候选 —— 说明该症状资产还没被因果表覆盖，"
            "我不能凭猜给出故障结论。需补充更具体的现象（部位/工况/伴随告警）。"
        )
        return "\n".join(lines)
    lines.append(
        f"按症状描述「{text}」，匹配到症状资产「{sym.get('name', '')}」"
        f"（涉及域：{'、'.join(sym.get('domains', []))}；诚实标注：{sym.get('annotation', '')}）。"
    )
    lines.append("图谱沿因果边给出的诊断候选（按置信度排序，逐条可溯源）：")
    for i, c in enumerate(candidates[:6], start=1):
        lines.append(
            f"{i}. {c['name']}（{c['fault']}，域 {c['domain_zh']}，"
            f"第{c['hop']}跳 · {_basis_zh(c['basis'])} · 置信 {c['confidence']:.2f}）"
            f"{('：' + c['notes'][0]) if c['notes'] else ''}"
        )
    if any(c["derived"] for c in candidates):
        lines.append(
            "标注：上表中 marked derived 的候选仅为示意提示（证据较弱），"
            "不能当成已确认故障码 —— 需按「检查」动作逐条验证后再下结论。"
        )
    if plan:
        first = plan[0]
        lines.append(
            f"建议先验证：{first['description']}"
            + (f"；可用现成场景复现：{', '.join(first['scenarios'][:3])}" if first["scenarios"] else "")
        )
    else:
        lines.append("当前候选不足以构成验证计划 —— 需补充现象细节。")
    lines.append("以上全部故障键均来自真实故障字典（不编造故障码）。")
    return "\n".join(lines)


def _no_match(query: str, reason: str) -> dict:
    return {
        "query": query,
        "matched": False,
        "no_match": True,
        "symptom": None,
        "uncertain": True,
        "reply": reason,
        "candidates": [],
        "plan": [],
        "evidence": {},
        "no_fault_code_invented": True,
        "llm_generated": False,
    }
