"""P1 测试：资产模型加载 + FastAPI 服务层（真实上游资产冒烟）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tcms_ai_platform.core import AssetLoadError, load_asset_model
from tcms_ai_platform.server.app import create_app

# 上游根（与本仓库同级的兄弟目录）
UPSTREAM = Path(__file__).resolve().parents[2] / "tcms-can-test"
NEEDS_UPSTREAM = pytest.mark.skipif(
    not UPSTREAM.is_dir(), reason=f"上游 tcms-can-test 不存在: {UPSTREAM}"
)


@NEEDS_UPSTREAM
def test_load_real_assets_counts():
    """真实资产加载计数（派生自文件，非手抄）。"""
    m = load_asset_model(UPSTREAM)
    s = m.stats()
    assert s["messages"] == 8
    assert s["signals"] == 36
    assert s["faults"] == 22
    assert s["scenarios"] == 13
    assert s["req_ids"] == 18
    assert s["functions"] == 4
    assert s["devices"] == 5
    assert m.load_stats["bad"] == []


@NEEDS_UPSTREAM
def test_real_message_signal_choices():
    """真实 DBC 报文/信号（含枚举表）解析正确。"""
    m = load_asset_model(UPSTREAM)
    door = m.message("DoorControl")
    assert door.frame_id == 0x400
    assert door.cycle_ms == 100
    assert door.send_type == "cyclic"
    # 枚举
    d1 = m.signal("Door1State")
    assert d1.choices == {0: "Closed", 1: "Open", 2: "Fault", 3: "Unknown"}
    # 带缩放/单位
    spd = m.signal("SpeedKmh")
    assert spd.scale == 0.1
    assert spd.unit == "km/h"
    assert spd.maximum == 200.0


@NEEDS_UPSTREAM
def test_real_fault_and_function_anchor():
    """故障字段与功能表 RTM 锚定。"""
    m = load_asset_model(UPSTREAM)
    eb = m.fault("eb_failure")
    assert eb.fid == "F-TCMS-011"
    assert eb.level == "critical"
    assert eb.action == "emergency_brake"
    assert eb.sil == "4"
    # 功能表每个 req 都在 RTM（loader 内部已校验，这里再断言查询面）
    f = m.function("F-EBM")
    assert f.name == "紧急制动管理（EBM）"
    assert all(r in m.requirements for r in f.requirements)


@NEEDS_UPSTREAM
def test_real_scenario_steps():
    """真实场景步骤解析（事件式与 inject/recover）。"""
    m = load_asset_model(UPSTREAM)
    dc = m.scenario("door_cascade.yaml")
    assert dc.name == "车门故障级联"
    assert len(dc.steps) == 4
    injects = [st for st in dc.steps if st.action == "inject"]
    assert {st.fault for st in injects} == {"door_fault", "overspeed"}
    recovers = [st for st in dc.steps if st.action == "recover"]
    assert len(recovers) == 2


@NEEDS_UPSTREAM
def test_load_error_missing_dir():
    with pytest.raises(AssetLoadError):
        load_asset_model(Path("Z:/no/such/upstream"))


# ---- 服务层 ----


@pytest.fixture(scope="module")
def client():
    """真实上游加载的 app 测试客户端。"""
    if not UPSTREAM.is_dir():
        pytest.skip(f"上游不存在: {UPSTREAM}")
    app = create_app(upstream=UPSTREAM)
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_stats_endpoint(client):
    s = client.get("/api/stats").json()
    assert s["messages"] == 8
    assert s["functions"] == 4


def test_messages_endpoint(client):
    msgs = client.get("/api/messages").json()
    assert len(msgs) == 8
    names = {m["name"] for m in msgs}
    assert "DoorControl" in names and "TCMS_Heartbeat" in names


def test_get_message_with_signals(client):
    d = client.get("/api/messages/DoorControl").json()
    assert d["frame_id"] == "0x400"
    sigs = {s["name"] for s in d["signals"]}
    assert "Door1State" in sigs
    door1 = next(s for s in d["signals"] if s["name"] == "Door1State")
    assert door1["choices"] == [
        {"value": 0, "label": "Closed"},
        {"value": 1, "label": "Open"},
        {"value": 2, "label": "Fault"},
        {"value": 3, "label": "Unknown"},
    ]


def test_get_message_404(client):
    assert client.get("/api/messages/Nope").status_code == 404


def test_devices_endpoint(client):
    devs = client.get("/api/devices").json()
    assert {d["name"] for d in devs} >= {"VCU", "BCU", "BMS"}


def test_faults_endpoint(client):
    faults = client.get("/api/faults").json()
    assert len(faults) == 22
    eb = next(f for f in faults if f["key"] == "eb_failure")
    assert eb["action"] == "emergency_brake"


def test_fault_detail(client):
    f = client.get("/api/faults/overspeed").json()
    assert f["fid"] == "F-TCMS-007"
    assert "recovery" in f


def test_scenarios_endpoint(client):
    scs = client.get("/api/scenarios").json()
    assert len(scs) == 13
    assert any(s["file"] == "door_cascade.yaml" for s in scs)


def test_requirements_endpoint(client):
    reqs = client.get("/api/requirements").json()
    ids = {r["req_id"] for r in reqs}
    assert "SR-01" in ids and "SR-16" in ids


def test_functions_endpoint(client):
    funcs = client.get("/api/functions").json()
    assert len(funcs) == 4
    f = next(f for f in funcs if f["fid"] == "F-EBM")
    assert "SR-01" in f["requirements"]


def test_run_scenario_endpoint(client):
    """真实上游引擎执行单场景（离线确定性）。"""
    r = client.post("/api/run/scenario", json={"scenario": "door_cascade.yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["all_passed"] is True
    assert body["passed"] == 2
    assert body["engine_version"]  # 上游引擎版本自证


def test_run_scenario_404(client):
    r = client.post("/api/run/scenario", json={"scenario": "nope.yaml"})
    assert r.status_code == 404
    assert "场景不存在" in r.json()["detail"]


def test_run_scenarios_all(client):
    """批量执行全部 13 场景全部通过（真实引擎）。"""
    r = client.post("/api/run/scenarios", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_count"] == 13
    assert body["all_passed"] is True
    assert body["total_fail"] == 0
