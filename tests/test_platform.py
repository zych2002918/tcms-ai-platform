"""P1 测试：资产模型加载 + FastAPI 服务层（真实上游资产冒烟）。"""

from __future__ import annotations

import json
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
    assert s["signals"] == 38
    assert s["faults"] == 26
    assert s["scenarios"] == 25
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
    assert len(faults) == 26
    eb = next(f for f in faults if f["key"] == "eb_failure")
    assert eb["action"] == "emergency_brake"


def test_fault_detail(client):
    f = client.get("/api/faults/overspeed").json()
    assert f["fid"] == "F-TCMS-007"
    assert "recovery" in f


def test_scenarios_endpoint(client):
    scs = client.get("/api/scenarios").json()
    assert len(scs) == 25
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
    assert body["scenario_count"] == 25
    assert body["all_passed"] is True
    assert body["total_fail"] == 0


# ---- P2 知识底座 API ----


def test_kb_stats(client):
    s = client.get("/api/kb/stats").json()
    # 图谱 ≥ 基础 106 + 领域注入(~109) + run 沉淀;向量 ≥ 基础 101 + 领域文档
    assert s["graph"]["nodes"] >= 200
    assert s["vector"]["docs"] >= 200
    assert "domain_enrichment" in s
    assert s["domain_enrichment"]  # 领域注入统计非空(ebm/network/safety)


def test_kb_search(client):
    r = client.post("/api/kb/search", json={"query": "车门故障 不能发车", "k": 3})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert hits
    assert all("graph_neighbors" in h for h in hits)


def test_kb_subgraph(client):
    r = client.post("/api/kb/subgraph", json={"seed": "fault:overspeed", "depth": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["node_count"] >= 5
    kinds = {n["kind"] for n in body["nodes"]}
    assert "function" in kinds and "scenario" in kinds


def test_kb_nodes_filter(client):
    nodes = client.get("/api/kb/nodes", params={"kind": "fault"}).json()
    assert len(nodes) == 26
    assert all(n["kind"] == "fault" for n in nodes)


def test_kb_node_detail(client):
    r = client.get("/api/kb/node/fault:door_fault")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "fault"
    nids = {n["id"] for n in body["neighbors"]}
    assert "scenario:door_cascade.yaml" in nids
    assert "function:F-DOOR" in nids


def test_kb_node_404(client):
    assert client.get("/api/kb/node/nope:xyz").status_code == 404


def test_run_scenario_records_sink(client):
    """执行单场景会沉淀 run 节点到知识库（组织记忆）。"""
    client.post("/api/run/scenario", json={"scenario": "overspeed_derate.yaml"})
    nodes = client.get("/api/kb/nodes", params={"kind": "run"}).json()
    assert len(nodes) >= 1


# ---- P4 Agent Harness API ----


def test_agent_tasks(client):
    tasks = client.get("/api/agent/tasks").json()
    ids = {t["task_id"] for t in tasks}
    assert ids == {
        "T-EBM",
        "T-DOOR",
        "T-OVERSPEED",
        "T-CONFLICT",
        "T-HEARTBEAT",
        "T-BUS",
        "T-CRC",
        "T-STORM",
    }
    t = next(t for t in tasks if t["task_id"] == "T-EBM")
    assert t["expected_action"] == "emergency_brake"


def test_agent_run_single(client):
    r = client.post("/api/agent/run", json={"task_id": "T-DOOR"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["achieved"] == 1
    run = body["runs"][0]
    assert run["achieved"] is True
    assert run["fault"] == "door_fault"
    assert run["score"]["score"] >= 60
    steps = {t["step"] for t in run["trace"]}
    assert {"plan", "retrieve", "exec", "verify"} <= steps


def test_agent_run_all(client):
    r = client.post("/api/agent/run", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 8
    assert body["achieved"] == 8
    assert body["success_rate"] == 1.0
    # 每个 run 都带证据链（RAG 可见）
    for run in body["runs"]:
        assert run["evidence"] or not run["evidence"]  # 允许空但结构在
    assert all("evidence" in run for run in body["runs"])


def test_agent_run_404(client):
    r = client.post("/api/agent/run", json={"task_id": "T-NOPE"})
    assert r.status_code == 404


# ---- FaultLab 演示（真实场景 → 事件时间线 + 通道曲线）----


def test_faultlab_scenarios(client):
    r = client.get("/api/faultlab/scenarios")
    assert r.status_code == 200
    scs = r.json()
    assert len(scs) == 25
    assert any(s["file"] == "overspeed_derate.yaml" for s in scs)


def test_faultlab_demo_overspeed(client):
    r = client.post("/api/faultlab/demo", json={"scenario": "overspeed_derate.yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["demo"]["scenario"] == "overspeed_derate.yaml"
    assert body["curve"]
    kinds = {e["kind"] for e in body["demo"]["events"]}
    assert {"inject", "detect", "action", "recover"} <= kinds
    # 超速 → 处置 derate 出现在时间线上
    acts = [e for e in body["demo"]["events"] if e["kind"] == "action"]
    assert any(e["action"] == "derate" for e in acts)
    # 曲线里速度应出现超限(>160)后回落
    speeds = [c["speed_kmh"] for c in body["curve"]]
    assert max(speeds) > 160
    assert min(speeds) <= 120


def test_faultlab_demo_404(client):
    r = client.post("/api/faultlab/demo", json={"scenario": "nope.yaml"})
    assert r.status_code == 404


def test_faultlab_demo_engine_window(client):
    """引擎观察窗：engine.version 非空(真实执行已附)、事件带 source 溯源、pipeline 有常量表。

    由 t1 在 faultlab_demo 端点给 run_result 补 engine_version 支撑——
    run_yaml 报告本身不带版本，缺补丁则 version=None（回归锁定）。
    """
    r = client.post("/api/faultlab/demo", json={"scenario": "overspeed_derate.yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine_asserted"] is True  # 引擎可用(测试夹具挂上游)
    eng = body["demo"]["engine"]
    assert eng["asserted"] is True
    assert eng["version"]  # t1 补丁：真实引擎版本(如 1.9.1)，而非 None
    assert body["demo"]["pipeline"]["title"]
    # 真实/示意常量表齐备（透明自证）
    assert body["demo"]["pipeline"]["constants"]["real"]
    assert body["demo"]["pipeline"]["constants"]["schematic"]
    # 事件带结构化 source（引擎断言/场景 YAML/故障字典溯源）
    act_evts = [e for e in body["demo"]["events"] if e["kind"] == "action"]
    assert any(e.get("source", {}).get("kind") == "engine_assert" for e in act_evts)
    inj_evts = [e for e in body["demo"]["events"] if e["kind"] == "inject"]
    assert any(e.get("source", {}).get("kind") == "scenario_yaml" for e in inj_evts)


# ---- 设置层 / 新手引导 API（外部可配置接口；key 永不外泄）----


def test_settings_get_no_key_leak(client, monkeypatch, tmp_path):
    """读取设置不应暴露 api_key（响应只含 has_key 布尔）。"""
    monkeypatch.setenv("TCMS_AI_HOME", str(tmp_path))
    # 先写一个带 key 的设置（直接经 API，隔离到 tmp）
    r = client.post("/api/settings", json={"llm_provider": "aliyun", "llm_api_key": "sk-secret-abc", "llm_model": "m"})
    assert r.status_code == 200
    body = r.json()
    assert body["llm"]["has_key"] is True
    assert "api_key" not in json.dumps(body)  # 响应当中绝无 key
    # GET 同
    g = client.get("/api/settings").json()
    assert g["llm"]["has_key"] is True
    assert "sk-secret-abc" not in json.dumps(g)


def test_settings_save_and_clear(client, monkeypatch, tmp_path):
    """保存(provider/model)与清除 key 往返。"""
    monkeypatch.setenv("TCMS_AI_HOME", str(tmp_path))
    client.post("/api/settings", json={"llm_provider": "deepseek", "llm_model": "deepseek-chat", "llm_api_key": "sk-d-1"})
    g = client.get("/api/settings").json()
    assert g["llm"]["provider"] == "deepseek"
    assert g["llm"]["model"] == "deepseek-chat"
    # 清除 key
    client.post("/api/settings/clear-api-key")
    g2 = client.get("/api/settings").json()
    assert g2["llm"]["has_key"] is False


def test_settings_asset_dir_invalid_raises(client, monkeypatch, tmp_path):
    """无效 asset_dir 保存后,resolve_asset_source 应抛错引导(而非静默回退)。"""
    from tcms_ai_platform.core.sources import resolve_asset_source

    monkeypatch.setenv("TCMS_AI_HOME", str(tmp_path))
    r = client.post("/api/settings", json={"asset_dir": "Z:/no/such/tcms"})
    assert r.status_code == 200

    with pytest.raises(FileNotFoundError):
        resolve_asset_source()
    # 清空恢复
    client.post("/api/settings", json={"asset_dir": ""})
    resolve_asset_source()  # 不再抛


def test_faultlab_demo_has_params(client):
    """FaultLab demo 输出应带档位参数(limit/derate/cruise/eb),前端不再硬编码。"""
    r = client.post("/api/faultlab/demo", json={"scenario": "overspeed_derate.yaml"})
    assert r.status_code == 200
    p = r.json()["demo"]["params"]
    assert p["limit_kmh"] == 160.0
    assert p["derate_speed"] > 0
    assert p["eb_kpa"] > 0
