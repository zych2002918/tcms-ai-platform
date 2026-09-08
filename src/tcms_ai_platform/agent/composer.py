"""Q3 原子组合器（Composer）：一句话多故障意图 → 原子化可执行计划 + 逐条溯源。

与 freeform（单故障）互补：freeform 解决"验证/处置一个故障"，composer 解决
"把这些故障组合成一个可执行场景"——同一套规则打分（锚定真实故障字典）提取
用户点名的一组故障，按序错峰编排注入/恢复，期望取字典默认 action
（真实引擎可判），并为每一步给出三栏式溯源（源资产 / 图谱系统 / Agent 建议）。

产品红线与 freeform 一致：组合只允许使用规则命中的**真实故障键**，
绝不发明故障；无任何命中 → ComposeError（调用方转 200 + ok=False 引导）。
"""

from __future__ import annotations

from ..knowledge.vector import DOMAIN_ZH, subsystem_domain
from .advisor import _compose_steps

# 组合上限：一次编排最多组装 6 个故障（保持可读/可执行/可审计）
COMPOSE_CAP = 6
# 规则命中强度门槛：与 freeform 明确命中一致（name/key 3.0 起）
MIN_SCORE = 3.0


class ComposeError(ValueError):
    """组合目标里找不到任何真实故障（调用方转 200 + ok=False，不硬 422）。"""


def _mention_keys(m, goal: str) -> list[str]:
    """从目标文本提取规则命中的真实故障键（score≥3.0，候选已按得分/长度排序）。"""
    from .freeform import _score_candidates  # noqa: PLC0415 函数级避免循环

    cands = [h for h in _score_candidates(goal, list(m.faults_by_key.values())) if h["score"] >= MIN_SCORE]
    keys: list[str] = []
    for h in cands:
        if h["key"] not in keys:
            keys.append(h["key"])
    return keys


def build_plan(m, keys: list[str], goal: str = "") -> dict:
    """把一组真实故障键组装成可执行计划（steps 兼容 /api/run/custom）。

    溯源：每个故障给出 source_asset（字典字段）/ source_system（13 域标签）/
    source_agent（规则组合规划说明）/ example_scenarios（库内相似模板 ≤2）。
    """
    steps = _compose_steps(m, keys)
    provenance: list[dict] = []
    systems: set[str] = set()
    for fk in keys:
        fd = m.faults_by_key[fk]
        dom = subsystem_domain(fd.subsystem)
        systems.add(DOMAIN_ZH.get(dom, dom) if dom else "通用")
        examples = [
            s.name for s in m.scenarios.values()
            if fk in s.fault_keys
        ][:2]
        provenance.append(
            {
                "fault": fk,
                "name": fd.name,
                "subsystem": fd.subsystem,
                "system_zh": DOMAIN_ZH.get(dom, dom) if dom else "通用",
                "source_asset": {
                    "action": fd.action, "level": fd.level, "sil": fd.sil,
                    "desc": fd.desc, "detect": fd.detect,
                },
                "source_system": {"domain": dom or None, "zh": DOMAIN_ZH.get(dom, "通用") if dom else "通用"},
                "source_agent": "规则组合规划：按目标点名顺序错峰注入，期望=字典默认 action，恢复在全部注入后依次执行",
                "example_scenarios": examples,
            }
        )
    actions = sorted({m.faults_by_key[k].action for k in keys})
    return {
        "goal": goal,
        "faults": keys,
        "steps": steps,
        "provenance": provenance,
        "summary": {
            "fault_count": len(keys),
            "systems": sorted(systems),
            "actions": actions,
            "recover_after_inject": True,
        },
    }


def plan_compose(m, goal: str, max_faults: int = COMPOSE_CAP) -> dict:
    """一句话多故障意图 → 可执行组合计划。

    未识别到任何真实故障时抛 ComposeError（诚实引导，不猜不造）。
    """
    goal = (goal or "").strip()
    if not goal:
        raise ComposeError("目标不能为空：请一句话点名要组合的故障（如「车门故障加超速级联」）。")
    keys = _mention_keys(m, goal)[:max_faults]
    if not keys:
        raise ComposeError(
            f"目标里未识别出任何真实故障（可用 {len(m.faults_by_key)} 条均未命中）：{goal!r}。"
            "请直接点名故障名（如：车门故障 / 超速 / 烟火报警）并用「组合/级联/编排」说明意图。"
        )
    return build_plan(m, keys, goal)
