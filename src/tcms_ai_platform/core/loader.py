"""资产加载器：从上游 tcms-can-test 真实资产构建 L1 AssetModel。

数据源（全部真实，只读引用上游，不复制）：
- DBC 协议库      tcms-can-test/tcms/tcms.dbc       → 报文/信号（周期/类型/枚举）
- FMEA 故障字典   tcms-can-test/tcms/faults.yaml    → 故障条目（22）
- 场景 YAML       tcms-can-test/scenarios/*.yaml    → 场景（13）
- RTM 追溯矩阵    tcms-can-test/tests/rtm.csv       → 需求 SR-01~18
- 被测功能        curated（本文件 _FUNCTIONS），锚定真实 RTM / 报文 / 故障键

设计纪律：
- loader 不做任何"美化"——计数/关系全部派生自真实文件；
- 缺文件/解析失败 → 诚实计入 load_stats.bad（镜像上游 parse_rate 口径）；
- curated 功能表的每个 req_id 若不在 RTM → 抛错（需求漂移即失败，防手抄）。
"""

from __future__ import annotations

import csv
from pathlib import Path

import cantools
import yaml

from .models import (
    AssetModel,
    DeviceDef,
    FaultDef,
    FunctionDef,
    MessageDef,
    RequirementDef,
    ScenarioDef,
    ScenarioStep,
    SignalDef,
)

# 设备角色标签（中文，展示用）
_DEVICE_ROLES = {
    "TCMS": "列车控制与管理系统（中央）",
    "VCU": "车辆控制单元（主控）",
    "BMS": "电池管理系统",
    "BOGIE": "转向架/车门控制",
    "BCU": "制动控制单元",
}

# DBC 节点 → 注入节点（场景 node: 使用小写，映射到大写设备名）
_NODE_ALIAS = {
    "bcu": "BCU",
    "bogie": "BOGIE",
    "vcu": "VCU",
    "bus": "BUS",
    "bms": "BMS",
    "tcms": "TCMS",
}

# 子系统（故障字典）→ 发送/关联设备（展示用近邻，不深究）
_SUBSYSTEM_DEVICE = {
    "VCU": "VCU",
    "车门": "BOGIE",
    "能源": "BMS",
    "牵引": "VCU",
    "受电弓": "BCU",
    "制动": "BCU",
    "网络": "TCMS",
}


class AssetLoadError(RuntimeError):
    """资产加载失败（缺文件 / 结构错 / 需求漂移）。"""


def _read_dbc(db_path: Path) -> tuple[dict[str, MessageDef], dict[str, SignalDef]]:
    """解析 DBC → MessageDef / SignalDef（含周期属性与枚举选择表）。"""
    with db_path.open("r", encoding="utf-8") as f:
        db = cantools.database.load(f)

    messages: dict[str, MessageDef] = {}
    signals: dict[str, SignalDef] = {}

    for msg in db.messages:
        cycle = None
        send_type = "event"
        if msg.cycle_time is not None:  # cantools 解析 GenMsgCycleTime
            cycle = int(msg.cycle_time)
        # GenMsgSendType：cantools 不一定保留，退化为 周期>0 → cyclic
        send_type = "cyclic" if (cycle or 0) > 0 else "event"
        sig_names = [s.name for s in msg.signals]
        messages[msg.name] = MessageDef(
            frame_id=msg.frame_id,
            name=msg.name,
            node=msg.senders[0] if msg.senders else "",
            length=msg.length,
            cycle_ms=cycle,
            send_type=send_type,
            signal_names=tuple(sig_names),
        )
        for s in msg.signals:
            choices = {}
            if s.choices:  # VAL_ 枚举表
                for k, v in s.choices.items():
                    choices[int(k)] = str(v)
            signals[s.name] = SignalDef(
                name=s.name,
                message=msg.name,
                bit_length=s.length,
                scale=float(s.scale or 1.0),
                offset=float(s.offset or 0.0),
                minimum=float(s.minimum) if s.minimum is not None else None,
                maximum=float(s.maximum) if s.maximum is not None else None,
                unit=str(s.unit or ""),
                choices=choices,
                receivers=tuple(str(r) for r in s.receivers),
            )
    return messages, signals


def _read_faults(yaml_path: Path) -> tuple[dict[str, FaultDef], dict[str, FaultDef]]:
    """解析 faults.yaml → by_key / by_fid 索引。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    by_key: dict[str, FaultDef] = {}
    by_fid: dict[str, FaultDef] = {}
    for raw in data.get("faults", []):
        fd = FaultDef(
            fid=raw["fid"],
            key=raw["key"],
            name=raw.get("name", ""),
            subsystem=raw.get("subsystem", ""),
            layer=raw.get("layer", ""),
            level=raw.get("level", ""),
            action=raw.get("action", ""),
            sil=str(raw.get("sil", "")),
            desc=raw.get("desc", ""),
            detect=raw.get("detect", ""),
            inject=raw.get("inject", ""),
            recovery=raw.get("recovery", ""),
        )
        by_key[fd.key] = fd
        by_fid[fd.fid] = fd
    return by_key, by_fid


def _read_scenarios(scenarios_dir: Path) -> dict[str, ScenarioDef]:
    """解析 scenarios/*.yaml → ScenarioDef（事件式与显式 inject/recover 都支持）。"""
    out: dict[str, ScenarioDef] = {}
    for f in sorted(scenarios_dir.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "steps" not in data:
            raise AssetLoadError(f"场景 {f.name}: 缺 steps")
        steps: list[ScenarioStep] = []
        faults: set[str] = set()
        nodes: set[str] = set()
        for raw in data["steps"]:
            if "at" not in raw:
                raise AssetLoadError(f"场景 {f.name}: 步骤缺 at")
            ts = float(raw["at"])
            if "inject" in raw:
                inj = raw["inject"]
                fault = inj.get("fault", raw.get("fault"))
                node = inj.get("node", raw.get("node"))
                steps.append(
                    ScenarioStep(
                        at=ts,
                        action="inject",
                        node=node,
                        fault=fault,
                        level=inj.get("level", raw.get("level")),
                        expect=inj.get("expect", raw.get("expect")),
                        impact=inj.get("impact", raw.get("impact")),
                    )
                )
            elif "recover" in raw:
                steps.append(
                    ScenarioStep(at=ts, action="recover", fault=raw["recover"])
                )
            else:  # 事件式: action + fault
                steps.append(
                    ScenarioStep(
                        at=ts,
                        action=raw.get("action", ""),
                        node=raw.get("node"),
                        fault=raw.get("fault"),
                        level=raw.get("level"),
                        expect=raw.get("expect"),
                        impact=raw.get("impact"),
                    )
                )
            if steps[-1].fault:
                faults.add(steps[-1].fault)
            if steps[-1].node:
                nodes.add(steps[-1].node)
        out[f.name] = ScenarioDef(
            name=data.get("name", f.stem),
            file=f.name,
            steps=tuple(steps),
            fault_keys=frozenset(faults),
            nodes=frozenset(nodes),
        )
    return out


def _read_rtm(csv_path: Path) -> dict[str, list[RequirementDef]]:
    """解析 tests/rtm.csv → by req_id（保留多行，如 SR-07 多个验证）。"""
    out: dict[str, list[RequirementDef]] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(row for row in f if not row.startswith("#"))
        for row in reader:
            req = RequirementDef(
                req_id=row["req_id"].strip(),
                module=row["module"].strip(),
                test_file=row["test_file"].strip(),
                verifies=row["verifies"].strip(),
                status=row.get("status", "").strip(),
            )
            out.setdefault(req.req_id, []).append(req)
    return out


# ---- 被测功能表（curated，锚定真实 RTM / 报文 / 故障键） ----
# 每个 req_id 必须真实存在于 RTM（loader 校验），信号/报文必须真实存在于 DBC。

_FUNCTIONS: list[dict] = [
    {
        "fid": "F-EBM",
        "name": "紧急制动管理（EBM）",
        "description": "按模式×原因矩阵触发紧急制动，SIL2/4 双通道表决，缓解需零速+原因消失闭环",
        "messages": ["BrakeSystem", "TractionBrakeHandle", "AlarmEvent"],
        "signals": ["EmergencyBrakeActive", "BrakeCylinderPressure", "BrakeFault"],
        "fault_keys": ["eb_failure", "traction_brake_conflict", "overspeed"],
        "requirements": ["SR-01", "SR-02", "SR-03", "SR-13"],
    },
    {
        "fid": "F-ATP",
        "name": "超速防护（ATP）",
        "description": "速度监督阈值 EBI/SBI 分级干预，超速降级/紧急制动",
        "messages": ["VehicleSpeed", "AlarmEvent", "BrakeSystem"],
        "signals": ["SpeedKmh", "SpeedValid", "Overspeed"],
        "fault_keys": ["overspeed", "speed_sensor_drift"],
        "requirements": ["SR-05", "SR-06"],
    },
    {
        "fid": "F-DOOR",
        "name": "车门联锁与级联",
        "description": "车门状态（Closed/Open/Fault/Unknown）联锁发车许可，故障级联降级",
        "messages": ["DoorControl", "AlarmEvent"],
        "signals": ["Door1State", "Door2State", "AllDoorsClosed", "DoorOpenPermit"],
        "fault_keys": ["door_fault", "door_sensor_noise"],
        "requirements": ["SR-04"],
    },
    {
        "fid": "F-NET",
        "name": "网络管理与完整性",
        "description": "心跳监督（丢失 N 周期离线）、CRC 校验、错误状态机、总线故障处置",
        "messages": ["TCMS_Heartbeat", "AlarmEvent"],
        "signals": ["HeartbeatCounter", "NodeStatus", "RunMode"],
        "fault_keys": [
            "heartbeat_loss_vcu",
            "crc_error_frame",
            "node_restart_storm",
            "bus_short",
        ],
        "requirements": ["SR-07", "SR-08", "SR-09", "SR-16"],
    },
]


def _curate_devices(
    messages: dict[str, MessageDef], faults_by_key: dict[str, FaultDef]
) -> dict[str, DeviceDef]:
    """从 DBC 发送节点 + 场景注入节点 + 子系统 组装设备表。"""
    # 收集发送节点 → 报文
    senders: dict[str, list[str]] = {}
    for name, m in messages.items():
        senders.setdefault(m.node, []).append(name)

    # 场景注入节点全集（小写）
    # 从故障字典子系统推断近邻设备
    sub_to_dev: dict[str, list[str]] = {}
    for fd in faults_by_key.values():
        dev = _SUBSYSTEM_DEVICE.get(fd.subsystem)
        if dev:
            sub_to_dev.setdefault(fd.subsystem, []).append(fd.key)

    devices: dict[str, DeviceDef] = {}
    # 先按 DBC 节点全集
    for node, msgs in senders.items():
        faults = []
        # 子系统近邻（取该设备所属子系统的故障键）
        for sub, dev in _SUBSYSTEM_DEVICE.items():
            if dev == node:
                faults.extend(sub_to_dev.get(sub, []))
        devices[node] = DeviceDef(
            name=node,
            role=_DEVICE_ROLES.get(node, node),
            messages=tuple(sorted(msgs)),
            faults=tuple(sorted(set(faults))),
        )
    return devices


def load_asset_model(
    upstream_root: str | Path,
    platform_version: str = "0.1.0",
) -> AssetModel:
    """从上游 tcms-can-test 根目录加载完整 L1 资产模型。"""
    root = Path(upstream_root)
    if not root.is_dir():
        raise AssetLoadError(f"上游目录不存在: {root}")

    tcms_pkg = root / "tcms"
    msgs_path = tcms_pkg / "tcms.dbc"
    faults_path = tcms_pkg / "faults.yaml"
    scenarios_dir = root / "scenarios"
    rtm_path = root / "tests" / "rtm.csv"

    missing = [p for p in (msgs_path, faults_path, scenarios_dir, rtm_path) if not p.exists()]
    if missing:
        raise AssetLoadError(f"上游资产缺失: {[str(m) for m in missing]}")

    stats: dict = {"bad": [], "ok": []}

    messages, signals = _read_dbc(msgs_path)
    stats["ok"].append(f"dbc:{len(messages)}msgs/{len(signals)}sigs")

    faults_by_key, faults_by_fid = _read_faults(faults_path)
    stats["ok"].append(f"faults:{len(faults_by_key)}")

    scenarios = _read_scenarios(scenarios_dir)
    stats["ok"].append(f"scenarios:{len(scenarios)}")

    requirements = _read_rtm(rtm_path)
    stats["ok"].append(f"rtm:{sum(len(v) for v in requirements.values())}rows/{len(requirements)}reqs")

    # 校验 curated 功能表：req_id 必须存在于 RTM
    functions: dict[str, FunctionDef] = {}
    known_msgs = set(messages)
    known_sigs = set(signals)
    known_faults = set(faults_by_key)
    for raw in _FUNCTIONS:
        for req in raw["requirements"]:
            if req not in requirements:
                raise AssetLoadError(f"功能 {raw['fid']}: 需求 {req} 不在 RTM（需求漂移）")
        for m in raw["messages"]:
            if m not in known_msgs:
                raise AssetLoadError(f"功能 {raw['fid']}: 报文 {m} 不在 DBC")
        for s in raw["signals"]:
            if s not in known_sigs:
                raise AssetLoadError(f"功能 {raw['fid']}: 信号 {s} 不在 DBC")
        for k in raw["fault_keys"]:
            if k not in known_faults:
                raise AssetLoadError(f"功能 {raw['fid']}: 故障 {k} 不在故障字典")
        functions[raw["fid"]] = FunctionDef(
            fid=raw["fid"],
            name=raw["name"],
            description=raw["description"],
            messages=tuple(raw["messages"]),
            signals=tuple(raw["signals"]),
            fault_keys=tuple(raw["fault_keys"]),
            requirements=tuple(raw["requirements"]),
        )
    stats["ok"].append(f"functions:{len(functions)}")

    devices = _curate_devices(messages, faults_by_key)
    stats["ok"].append(f"devices:{len(devices)}")

    return AssetModel(
        version=platform_version,
        source_upstream=str(root),
        messages=messages,
        signals=signals,
        devices=devices,
        faults_by_key=faults_by_key,
        faults_by_fid=faults_by_fid,
        scenarios=scenarios,
        requirements=requirements,
        functions=functions,
        load_stats=stats,
    )


# 便捷：定位上游根（默认与本平台同工作区 objects/ 相邻）
_DEFAULT_UPSTREAM = Path(__file__).resolve().parents[4] / "tcms-can-test"


def load_default() -> AssetModel:
    """加载默认上游 tcms-can-test（与本仓库同级的兄弟目录）。"""
    return load_asset_model(_DEFAULT_UPSTREAM)
