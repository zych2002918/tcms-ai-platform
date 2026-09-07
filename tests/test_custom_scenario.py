"""P1 扩展测试：自定义场景手动编排（/api/run/custom，真实引擎不落盘）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tcms_ai_platform.server.app import create_app

UPSTREAM = Path(__file__).resolve().parents[2] / "tcms-can-test"
NEEDS_UPSTREAM = pytest.mark.skipif(
    not UPSTREAM.is_dir(), reason=f"上游 tcms-can-test 不存在: {UPSTREAM}"
)


@pytest.fixture(scope="module")
def client():
    if not UPSTREAM.is_dir():
        pytest.skip(f"上游不存在: {UPSTREAM}")
    app = create_app(upstream=UPSTREAM)
    from fastapi.testclient import TestClient

    return TestClient(app)


@NEEDS_UPSTREAM
def test_run_custom_overspeed_passes(client):
    """合法 overspeed 步骤 → 真实引擎执行全部通过（报告与 run/scenario 同构）。"""
    r = client.post(
        "/api/run/custom",
        json={
            "name": "自定义超速",
            "steps": [
                {
                    "at": 1.0,
                    "action": "inject",
                    "fault": "overspeed",
                    "node": "vcu",
                    "level": "major",
                    "expect": "derate",
                    "impact": "速度超限",
                },
                {"at": 2.0, "action": "recover", "fault": "overspeed"},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["all_passed"] is True
    assert body["passed"] == 1
    assert body["failed"] == 0
    assert body["scenario"] == "自定义超速"
    assert body["engine_version"]
    assert body["custom"] is True
    # 断言里 actual 来自真实引擎处置判定（derate 命中）
    assert body["assertions"][0]["actual"] == "derate"
    assert body["assertions"][0]["expected"] == "derate"


@NEEDS_UPSTREAM
def test_run_custom_event_style(client):
    """事件式写法（action: inject）同样支持。"""
    r = client.post(
        "/api/run/custom",
        json={
            "steps": [
                {"at": 0.5, "action": "inject", "fault": "eb_failure", "expect": "emergency_brake"},
                {"at": 1.5, "action": "recover", "fault": "eb_failure"},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["all_passed"] is True
    assert body["assertions"][0]["actual"] == "emergency_brake"


@NEEDS_UPSTREAM
def test_run_custom_unknown_fault_422(client):
    """未知故障键 → 422 中文提示（防拼写错误静默通过）。"""
    r = client.post(
        "/api/run/custom",
        json={"steps": [{"at": 1.0, "action": "inject", "fault": "no_such_fault"}]},
    )
    assert r.status_code == 422
    assert "未知故障键" in r.json()["detail"]


@NEEDS_UPSTREAM
def test_run_custom_empty_422(client):
    """空步骤 → 422。"""
    r = client.post("/api/run/custom", json={"name": "空", "steps": []})
    assert r.status_code == 422


@NEEDS_UPSTREAM
def test_run_custom_bad_action_422(client):
    """未知动作 → 422。"""
    r = client.post(
        "/api/run/custom",
        json={"steps": [{"at": 1.0, "action": "explode", "fault": "overspeed"}]},
    )
    assert r.status_code == 422


# ---- 自由 Agent 目标端点（HTTP 面）----


@NEEDS_UPSTREAM
def test_agent_free_endpoint_door(client):
    """POST /api/agent/free「验证车门故障不能发车」→ 200 命中 door_fault 并真实达成。"""
    r = client.post("/api/agent/free", json={"goal": "验证车门故障不能发车"})
    assert r.status_code == 200
    body = r.json()
    assert body["goal"] == "验证车门故障不能发车"
    assert body["parsed"]["fault"] == "door_fault"
    assert body["parsed"]["expected"] == "derate"
    assert body["parsed"]["confidence"] >= 0.9
    assert body["matched_task_id"] == "T-FREE-1"
    # 与 /api/agent/run 同构的执行报告
    assert body["total"] == 1
    assert body["runs"][0]["achieved"] is True
    assert body["runs"][0]["task_id"] == "T-FREE-1"
    assert "trace" in body["runs"][0]


@NEEDS_UPSTREAM
def test_agent_free_endpoint_no_match_422(client, monkeypatch):
    """目标不含任何故障 → 422 中文提示（与 LLM key 有无无关：
    规则零候选在触发 LLM 仲裁前即拒绝，LLM 不允许自由发明故障）。"""
    # 显式无 LLM key：即使本机配了 live key，也锁死走「无仲裁」确定性路径
    for k in ("DASH_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DSH_CREDENTIALS_FILE", str(Path("Z:/no-cred.yaml")))
    r = client.post("/api/agent/free", json={"goal": "今天天气不错"})
    assert r.status_code == 422
    assert "故障" in r.json()["detail"]


@NEEDS_UPSTREAM
def test_agent_free_endpoint_no_match_422_even_with_llm(client, monkeypatch):
    """产品红线（HTTP 面）：即便 LLM 仲裁「可用且会猜一个真实键」，
    规则零候选目标仍必须 422（防 LLM 硬猜返回 200 的回归）。
    模拟本机有 live key：patch _api_key 返回假 key + _chat 防真实联网。"""
    import tcms_ai_platform.agent.llm_backend as lb

    monkeypatch.setattr(lb, "_api_key", lambda: "sk-fake-for-test")
    monkeypatch.setattr(
        lb.LLMAgentBackend,
        "_chat",
        lambda self, s, u: '{"fault": "overspeed", "expected": "derate"}',
    )
    r = client.post("/api/agent/free", json={"goal": "今天天气不错"})
    assert r.status_code == 422  # 修复：零候选直接拒绝，LLM 猜键不再放行
    assert "故障" in r.json()["detail"]
