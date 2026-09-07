"""P4 扩展测试：自由 Agent 目标解析（/api/agent/free 后端逻辑）。

规则优先 + LLM 仲裁（无 key 落回规则）：
    - 确定性命中：规则解析把一句话目标映射到真实故障字典条目
    - LLM 仲裁：仅当规则歧义且注入 chat 时触发（测试用替身）
    - 无命中 → NoFaultMatch（API 层转 422）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tcms_ai_platform.agent.freeform import NoFaultMatch, parse_free_goal
from tcms_ai_platform.core import load_asset_model

UPSTREAM = Path(__file__).resolve().parents[2] / "tcms-can-test"
NEEDS_UPSTREAM = pytest.mark.skipif(
    not UPSTREAM.is_dir(), reason=f"上游 tcms-can-test 不存在: {UPSTREAM}"
)


@pytest.fixture(scope="module")
def model():
    return load_asset_model(UPSTREAM)


@NEEDS_UPSTREAM
def test_parse_free_goal_door(model):
    """「验证车门故障不能发车」→ 确定性命中 door_fault / derate。"""
    p = parse_free_goal(model, "验证车门故障不能发车", use_llm=False)
    assert p.fault == "door_fault"
    assert p.expected == "derate"
    assert p.resolver == "rule"
    assert p.confidence >= 0.9
    assert p.fault_name == "车门故障（按未关处理）"


@NEEDS_UPSTREAM
def test_parse_free_goal_explicit_action_terms(model):
    """显式处置词应被正确提取（而不只是字典默认）。"""
    p = parse_free_goal(model, "超速需要紧急制动", use_llm=False)
    assert p.fault == "overspeed"
    assert p.expected == "emergency_brake"  # 用户显式说紧急制动，覆盖字典默认 derate


@NEEDS_UPSTREAM
def test_parse_free_goal_latin_name(model):
    """英文前缀中文名（VCU 心跳丢失）应能命中（剥拉丁 + 中文主体匹配）。"""
    p = parse_free_goal(model, "VCU心跳丢失时应该降级", use_llm=False)
    assert p.fault == "heartbeat_loss_vcu"
    assert p.expected == "derate"


@NEEDS_UPSTREAM
def test_parse_free_goal_bigram_order(model):
    """乱序名称（CRC报文校验错误）命中（bigram 覆盖）。"""
    p = parse_free_goal(model, "CRC报文校验错误应告警", use_llm=False)
    assert p.fault == "crc_error_frame"
    assert p.expected == "warning"


@NEEDS_UPSTREAM
def test_parse_free_goal_no_match_raises(model):
    """无关目标 → NoFaultMatch（诚实不猜，API 转 422）。"""
    with pytest.raises(NoFaultMatch):
        parse_free_goal(model, "今天天气不错", use_llm=False)


@NEEDS_UPSTREAM
def test_parse_free_goal_zero_candidate_rejects_even_with_llm(model):
    """产品红线：规则零候选（目标无任何真实故障语义）→ 即使 LLM 仲裁可用、
    注入 chat 返回真实键，也必须 NoFaultMatch（LLM 不允许自由发明故障）。"""
    with pytest.raises(NoFaultMatch):
        parse_free_goal(
            model,
            "今天天气不错",
            use_llm=True,
            llm_chat=lambda s, u: '{"fault": "overspeed", "expected": "derate"}',
        )


@NEEDS_UPSTREAM
def test_parse_free_goal_llm_disambiguates(model):
    """规则多候选歧义（车门故障 vs 超速同分）→ LLM 从候选里消歧选一个。"""
    p = parse_free_goal(
        model,
        "车门故障和超速都要处置",
        use_llm=True,
        llm_chat=lambda s, u: '{"fault": "overspeed", "expected": "derate"}',
    )
    assert p.fault == "overspeed"
    assert p.expected == "derate"
    assert p.resolver == "llm"
    assert p.confidence == 1.0


@NEEDS_UPSTREAM
def test_parse_free_goal_llm_outside_candidates_rejected(model):
    """LLM 输出非候选真实键（候选只有 door_fault/overspeed 却回 eb_failure）→ 拒绝，
    落回规则兜底（resolver=rule），不许 LLM 跳到规则没命中的故障。"""
    p = parse_free_goal(
        model,
        "车门故障和超速都要处置",
        use_llm=True,
        llm_chat=lambda s, u: '{"fault": "eb_failure", "expected": "emergency_brake"}',
    )
    assert p.fault in {"door_fault", "overspeed"}  # 规则候选之一（eb_failure 被拒）
    assert p.resolver == "rule"


@NEEDS_UPSTREAM
def test_parse_free_goal_llm_abstain_falls_back(model):
    """LLM 返回 {fault: null}（无法识别）→ 落回规则兜底，不抛。"""
    p = parse_free_goal(
        model,
        "车门故障怎么处理",
        use_llm=True,
        llm_chat=lambda s, u: '{"fault": null}',
    )
    assert p.fault == "door_fault"
    assert p.resolver == "rule"


@NEEDS_UPSTREAM
def test_parse_free_goal_no_key_falls_back(model, monkeypatch):
    """无 key 且规则未命中 → 不做 LLM 调用，仍抛 NoFaultMatch（离线可复现）。"""
    for k in ("DASH_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DSH_CREDENTIALS_FILE", str(Path("Z:/no-cred.yaml")))
    with pytest.raises(NoFaultMatch):
        parse_free_goal(model, "报文CRC错误要给出告警提示", use_llm=True)


@NEEDS_UPSTREAM
def test_parse_free_goal_task_id_seq(model):
    """解析结果打包为 T-FREE-{n} 临时任务（Harness 可执行契约）。"""
    p = parse_free_goal(model, "验证车门故障不能发车", use_llm=False, seq=3)
    t = p.to_task("验证车门故障不能发车", seq=3)
    assert t.task_id == "T-FREE-3"
    assert t.target_fault == "door_fault"
    assert t.expected_action == "derate"
    assert t.kb_query  # 整句作 RAG 检索
