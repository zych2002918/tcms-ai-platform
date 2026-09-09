"""compose_seq（时序连锁原子化）门禁：先A后B随后C最后D → 逐原子故障 + 诚实未锚定。"""

from __future__ import annotations

from pathlib import Path

import pytest

UPSTREAM = Path(__file__).resolve().parents[2] / "tcms-can-test"
NEEDS_UPSTREAM = pytest.mark.skipif(
    not UPSTREAM.is_dir(), reason=f"上游 tcms-can-test 不存在: {UPSTREAM}"
)


@NEEDS_UPSTREAM
def _model():
    from tcms_ai_platform.core import load_asset_model

    return load_asset_model(UPSTREAM)


@NEEDS_UPSTREAM
def test_sequential_cascade_parses_atoms_and_honest_unresolved():
    """『先车门故障，后空调失效，随后牵引失效，最后紧急制动』：
    车门故障被锚定；空调/牵引子句未锚定时给域候选(不自动发明)；末句收尾期望=emergency_brake。"""
    from tcms_ai_platform.agent.composer import plan_compose_seq

    m = _model()
    s = plan_compose_seq(m, "先车门故障，后空调失效，随后牵引失效，最后紧急制动")
    assert s["keys"] == ["door_fault"]
    assert s["final_action"] == "emergency_brake"
    clauses = [u["clause"] for u in s["unresolved"]]
    assert len(clauses) >= 2, "空调/牵引子句应作为未锚定候选返回，而不是静默丢弃"
    for u in s["unresolved"]:
        dc = u.get("domain_candidates")
        assert dc is not None and dc.get("faults"), f"未锚定子句应带域候选: {u['clause']}"
        for f in dc["faults"]:
            assert f["key"] in m.faults_by_key, "域候选必须是真实故障键"


@NEEDS_UPSTREAM
def test_two_matched_faults_preserve_order():
    """两个都能锚定时按句序保留，且无未锚定项。"""
    from tcms_ai_platform.agent.composer import plan_compose_seq

    m = _model()
    s = plan_compose_seq(m, "车门故障，随后超速")
    assert s["keys"] == ["door_fault", "overspeed"]
    assert s["unresolved"] == []
    assert s["final_action"] is None


@NEEDS_UPSTREAM
def test_no_fault_raises_honest_error():
    from tcms_ai_platform.agent.composer import ComposeError, plan_compose_seq

    m = _model()
    with pytest.raises(ComposeError):
        plan_compose_seq(m, "今天天气不错")
