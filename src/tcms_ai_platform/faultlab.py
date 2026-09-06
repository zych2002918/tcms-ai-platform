"""FaultLab —— 故障场景「演示动画」的数据重建器。

把一次真实故障场景(声明式 YAML)重建为一条可播放的事件时间线 + 通道曲线，
供前端以列车/驾驶台动画演示「故障如何发生、如何被检测、系统如何处置」。

诚实性纪律(与全仓库一致，数字机器自证)：
- 事件时刻(注入/恢复 ts)与期望处置 = 真实场景 YAML 步骤(assets 派生)；
- 处置结果 = 真实引擎断言(若有引擎执行结果)或故障字典 action(诚实标注来源)；
- 检测/恢复描述 = 真实故障字典(faults.yaml detect/recovery)；
- 通道波形(车速/制动缸压/门状态/心跳/总线…) = 事件级示意重建：
  只按「故障激活区间 × 真实阈值常量」做阶梯变化，不做逐周期总线级仿真。
  前端须展示此标注，避免把示意波形误当逐周期回放。

通道在故障激活期间的取值来自各故障档案(profile)；档案值若非源码常量
则以 `derived: true` 标注，保持诚实。

用法：
    from tcms_ai_platform.faultlab import build_demo
    demo = build_demo(asset_model, "overspeed_derate.yaml", run_result=None)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .core.models import AssetModel

# 采样步长（秒）——前端动画播放粒度
SAMPLE_S = 0.2
# 场景结束后多留几秒尾段，让演示有「处置后仍在运行」的观察窗口
TAIL_S = 4.0
# 检测到动作生效的示意延迟（秒；检测→处置的工程响应时间，非源码常量 → derived）
DETECT_DELAY_S = 0.4

# 常规「巡航」基线：出库加速到 120 km/h 后匀速（示意驾驶曲线，非源码常量）
CRUISE_KMH = 120.0


@dataclass
class DemoEvent:
    """时间线上一个事件(标记点)。"""

    t: float
    kind: str  # inject / detect / action / recover / note
    fault: str
    label: str
    detail: str = ""
    level: str = ""
    action: str = ""
    derived: bool = False  # True = 示意重建(检测延迟等)，False = 场景/字典真实

    def to_dict(self) -> dict:
        return {
            "t": round(self.t, 2),
            "kind": self.kind,
            "fault": self.fault,
            "label": self.label,
            "detail": self.detail,
            "level": self.level,
            "action": self.action,
            "derived": self.derived,
        }


def _fault_name(m: AssetModel, key: str) -> str:
    try:
        return m.fault(key).name
    except KeyError:
        return key


# ---------------------------------------------------------------------------
# 故障档案：故障激活期间各通道的示意取值 + 检测语义（真实阈值锚定）
# ---------------------------------------------------------------------------
# 说明：值若来自上游源码常量/故障字典则写来源；示意演示值标注 derived。
# 通道集合：speed_kmh / brake_kpa / eb / doors_open / door_fault_count /
#          heartbeat_ok / bus_ok / soc / pantograph_ok / alarm_text
def _profiles() -> dict[str, dict]:
    """每故障的通道影响档案（只用真实语义；fallback 由 build_demo 兜底）。"""
    return {
        # ---- 牵引 / 速度 ----
        "overspeed": {
            "zh": "超速",
            "level": "major",
            "detect_zh": "ATP 速度监督判定超限",
            "note": "真实阈值：限速 160 km/h，Warning>155 / SBI>158 / EBI>160（atp.py 常量）",
            "speed": 168.0,  # 越过 EBI 160（derived 演示档）
            "alarm": "超速告警 Overspeed",
        },
        "traction_loss": {
            "zh": "牵引丢失",
            "level": "major",
            "detect_zh": "牵引可用性异常（手柄请求与速度矛盾）",
            "note": "处置 derate：限功率继续运行（示意演示档）",
            "alarm": "牵引丢失 TractionLoss",
            "speed": 90.0,
        },
        "speed_sensor_drift": {
            "zh": "速度传感器轻微漂移",
            "level": "minor",
            "detect_zh": "2oo3 表决不一致 / 变化率监测",
            "note": "轻微漂移 → warning 提示（示意演示档）",
            "alarm": "速度传感器漂移 SpeedDrift",
        },
        "sensor_stuck": {
            "zh": "传感器卡死",
            "level": "minor",
            "detect_zh": "信号变化率/新鲜度检查",
            "note": "warning 提示（示意演示档）",
            "alarm": "传感器无变化 SensorStuck",
        },
        # ---- 车门 ----
        "door_fault": {
            "zh": "车门故障(按未关处理)",
            "level": "major",
            "detect_zh": "DoorControl 状态枚举异常(Fault/Unknown)",
            "note": "真实枚举：Door1State 2=Fault / 3=Unknown（DBC VAL_）",
            "doors_open": 0,
            "door_fault_count": 1,
            "alarm": "车门故障 DoorFault",
        },
        "door_sensor_noise": {
            "zh": "车门传感器偶发噪声",
            "level": "minor",
            "detect_zh": "状态稳定性/时序检查(seqcheck)",
            "note": "瞬时跳变 → warning 提示（示意演示档）",
            "alarm": "门传感器噪声 DoorNoise",
        },
        # ---- 制动 / 冲突 ----
        "eb_failure": {
            "zh": "紧急制动执行失败",
            "level": "critical",
            "detect_zh": "执行反馈闭环(压力+回执+牵引切除三重证据)",
            "note": "真实机制：exec_feedback 三重证据；EB 命令发出但回路无响应",
            "alarm": "紧急制动无响应 EB_Fail",
            "eb_request": True,
            "eb_ok": False,  # 制动缸压力不上升（执行失败）
        },
        "traction_brake_conflict": {
            "zh": "牵引制动冲突",
            "level": "critical",
            "detect_zh": "联锁(interlocks.traction_brake_conflict)",
            "note": "真实联锁：手柄牵引位同时存在制动请求 → 冲突，须紧急制动",
            "alarm": "牵引制动冲突 Conflict",
            "eb": True,
        },
        "brake_actuator_stuck": {
            "zh": "制动执行器卡滞",
            "level": "major",
            "detect_zh": "EBR 硬线回路断点诊断 + 执行反馈超时",
            "note": "处置 derate：降级 + 冗余通道投入（示意演示档）",
            "alarm": "制动执行器故障 BrakeActuator",
        },
        # ---- 受电弓 / 能源 ----
        "pantograph_arc": {
            "zh": "受电弓拉弧风险",
            "level": "critical",
            "detect_zh": "联锁(弓状态×网压异常)",
            "note": "真实联锁：弓升起但接触网电压过低/过高 → 拉弧风险，降弓停车",
            "alarm": "受电弓拉弧 PantographArc",
            "eb": True,
            "pantograph_ok": False,
        },
        "soc_low": {
            "zh": "SOC 偏低",
            "level": "info",
            "detect_zh": "EnergyStatus.SocPercent 阈值监测",
            "note": "info 提示，仅建议充电（示意演示档）",
            "alarm": "电量低 SOC_Low",
            "soc": 25.0,
        },
        "temp_high": {
            "zh": "电池温度偏高",
            "level": "info",
            "detect_zh": "EnergyStatus.BatteryTemp 阈值监测",
            "note": "info 提示，温度回落自动恢复（示意演示档）",
            "alarm": "电池温度高 TempHigh",
        },
        # ---- 网络 / 心跳 / 总线 ----
        "heartbeat_loss_vcu": {
            "zh": "VCU 心跳丢失",
            "level": "major",
            "detect_zh": "看门狗健康表(超时/丢帧判定)",
            "note": "真实阈值：心跳周期 100ms、丢失 3 周期判离线、迟滞 2 周期恢复(watchdogs.py)",
            "alarm": "VCU 心跳丢失 HBeat_Loss",
            "heartbeat_ok": False,
        },
        "node_restart_storm": {
            "zh": "节点重启风暴",
            "level": "major",
            "detect_zh": "健康表反复 fault/active 翻转计数",
            "note": "真实机制：反复复位 → 心跳周期性中断（示意演示档）",
            "alarm": "节点重启风暴 RestartStorm",
            "heartbeat_ok": False,
        },
        "crc_error_frame": {
            "zh": "报文 CRC 校验错误",
            "level": "major",
            "detect_zh": "应用层 CRC-8 校验失败",
            "note": "真实机制：CRC-8 失败帧丢弃并计数(faults.py)",
            "alarm": "CRC 错误 CRC_Err",
            "bus_ok": False,
        },
        "bit_flip_frame": {
            "zh": "单比特翻转",
            "level": "major",
            "detect_zh": "CRC-8 校验失败或值域检查",
            "note": "真实机制：错误帧丢弃，后续正确帧恢复(faults.py)",
            "alarm": "位翻转 BitFlip",
            "bus_ok": False,
        },
        "rolling_counter_gap": {
            "zh": "滚动计数器跳变",
            "level": "minor",
            "detect_zh": "计数器连续性检查(seqcheck)",
            "note": "真实机制：alive/rolling counter 跳变 → 丢帧检测（示意演示档）",
            "alarm": "计数跳变 CounterGap",
        },
        "bus_short": {
            "zh": "总线短路",
            "level": "critical",
            "detect_zh": "错误状态机 Bus-Off(errstate)",
            "note": "真实阈值：TEC≥256 进 Bus-Off（errstate.py）",
            "alarm": "总线短路 Bus_Short",
            "bus_ok": False,
        },
        "bus_open_circuit": {
            "zh": "总线断路",
            "level": "major",
            "detect_zh": "错误状态机 Error-Passive + ACK 失败计数",
            "note": "真实阈值：TEC/REC ≥128 进 Error-Passive（errstate.py）",
            "alarm": "总线断路 Bus_Open",
            "bus_ok": False,
        },
        "bus_noise_burst": {
            "zh": "总线噪声突发",
            "level": "minor",
            "detect_zh": "REC/TEC 统计 + CRC 失败计数",
            "note": "真实机制：随机位错误突发 → 错误计数器上升（示意演示档）",
            "alarm": "总线噪声 Bus_Noise",
        },
        "arbitration_error": {
            "zh": "仲裁错误",
            "level": "minor",
            "detect_zh": "错误状态机仲裁错误计数",
            "note": "真实机制：发送重试（示意演示档）",
            "alarm": "仲裁错误 Arb_Err",
        },
        "short_frame": {
            "zh": "短帧(DLC 不足)",
            "level": "minor",
            "detect_zh": "DLC 校验(canlog/parser 长度检查)",
            "note": "真实机制：DLC 不足 → 信号不完整（示意演示档）",
            "alarm": "短帧 ShortFrame",
        },
    }


# ---------------------------------------------------------------------------
# 时间线重建
# ---------------------------------------------------------------------------


def _action_zh(action: str) -> str:
    return {
        "none": "仅记录（none）",
        "warning": "司机告警（warning）",
        "derate": "降级运行（derate）",
        "emergency_brake": "紧急制动（emergency_brake）",
        "shutdown": "停车/断电（shutdown）",
    }.get(action, action)


def build_demo(
    m: AssetModel,
    scenario_file: str,
    run_result: dict | None = None,
) -> dict:
    """把一个真实场景重建为演示时间线。

    - scenario_file 必须在 asset_model 场景中（否则抛 KeyError）。
    - run_result 可选：真实引擎 run 报告（含 assertions），用于替换
      「处置结果」来源为真实断言；缺省用故障字典 action(诚实标注)。
    """
    scen = m.scenario(scenario_file)
    prof = _profiles()
    events: list[DemoEvent] = []
    active: dict[str, float] = {}  # fault -> inject ts（用于派生检测事件去重）
    asserted_action: dict[str, str] = {}

    if run_result:
        for a in run_result.get("assertions", []):
            if a.get("fault"):
                asserted_action[a["fault"]] = a.get("actual", "")

    steps = sorted(scen.steps, key=lambda s: s.at)
    last_t = steps[-1].at if steps else 0.0

    for st in steps:
        if st.action == "inject" and st.fault:
            fk = st.fault
            p = prof.get(fk, {})
            name = _fault_name(m, fk)
            fd = m.fault(fk) if fk in m.faults_by_key else None
            # 1) 注入（真实：场景步骤）
            events.append(
                DemoEvent(
                    t=st.at,
                    kind="inject",
                    fault=fk,
                    label=f"注入故障：{name}",
                    detail=st.impact or (fd.desc if fd else ""),
                    level=st.level or (fd.level if fd else ""),
                    action=st.expect or (fd.action if fd else ""),
                )
            )
            # 2) 检测（真实：故障字典 detect 文本；时刻为注入+示意检测延迟 → derived）
            detect_zh = p.get("detect_zh") or (fd.detect if fd else "系统检测到异常")
            events.append(
                DemoEvent(
                    t=round(st.at + DETECT_DELAY_S, 2),
                    kind="detect",
                    fault=fk,
                    label="检测到异常",
                    detail=detect_zh,
                    level=st.level or "",
                    derived=True,
                )
            )
            # 3) 处置（来源优先真实断言 actual，否则故障字典 action）
            actual = asserted_action.get(fk) or (fd.action if fd else "")
            src = "真实引擎断言" if fk in asserted_action else "故障字典 action"
            events.append(
                DemoEvent(
                    t=round(st.at + DETECT_DELAY_S, 2),
                    kind="action",
                    fault=fk,
                    label=f"处置：{_action_zh(actual)}",
                    detail=f"来源：{src} · 期望 {st.expect or fd.action}",
                    level=st.level or "",
                    action=actual,
                    derived=fk not in asserted_action,
                )
            )
            if p:
                active[fk] = st.at
        elif st.action == "recover" and st.fault:
            fk = st.fault
            fd = m.fault(fk) if fk in m.faults_by_key else None
            events.append(
                DemoEvent(
                    t=st.at,
                    kind="recover",
                    fault=fk,
                    label=f"恢复：{_fault_name(m, fk)}",
                    detail=(fd.recovery if fd else "故障消除"),
                    level=fd.level if fd else "",
                )
            )
            active.pop(fk, None)

    # 若场景未显式恢复的故障仍在激活 → 尾注（诚实：不虚构恢复）
    if active:
        at_tail = last_t + 1.0
        events.append(
            DemoEvent(
                t=round(at_tail, 2),
                kind="note",
                fault=",".join(sorted(active)),
                label="场景结束，故障仍处处置状态",
                detail="本场景未编排恢复步骤；真实恢复语义见故障字典 recovery 字段。",
                derived=True,
            )
        )

    duration = round(last_t + TAIL_S, 2)
    return {
        "scenario": scen.file,
        "scenario_name": scen.name,
        "faults": sorted({e.fault for e in events if e.kind in ("inject",)}),
        "steps": len(scen.steps),
        "duration": duration,
        "sample_s": SAMPLE_S,
        "events": [e.to_dict() for e in sorted(events, key=lambda e: e.t)],
        # 档位参数：前端动画据此显示（derate 限速等，避免前端硬编码漂移）
        "params": {
            "limit_kmh": 160.0,  # 真实线路限速（atp.DEFAULT_LIMIT_KMH）
            "derate_speed": _DERATE_SPEED,  # 降级限速目标（示意演示档）
            "cruise_kmh": CRUISE_KMH,  # 正常巡航（示意）
            "eb_kpa": _EB_KPA,  # EB 制动缸压力基准
        },
        "honesty": (
            "事件时刻来自真实场景 YAML；处置结果来自真实引擎断言（若已执行）或故障字典；"
            "通道波形为事件级示意重建（依据真实阈值/枚举），非逐周期总线回放。"
        ),
    }


# ---------------------------------------------------------------------------
# 通道曲线：按时间推进计算各通道状态（供前端逐帧动画）
# ---------------------------------------------------------------------------
# 物理模型为「示意」（derived）：加速/巡航/制动减速仅用于演示处置效果，
# 数字依据真实阈值（160 限速 / EB 300kPa / 心跳 100ms 等），非逐周期仿真。

# 加速率 / 巡航（示意）
_ACCEL_RATE = 40.0  # km/h 每秒（3s 到 120 巡航）
_DERATE_SPEED = 90.0  # derate 限速目标（示意演示档，非源码常量）
_EB_DECEL = 50.0  # EB/停车 减速 km/h 每秒（示意）
_DERATE_DECEL = 25.0  # 降级减速（示意）
_COAST_DECEL = 2.5  # 牵引丢失/无动力滑行衰减（示意）
_EB_FAIL_COAST = 0.8  # EB 执行失败：几乎不减速（教学点：命令≠执行）
_EB_KPA = 300.0  # EB 制动缸压力基准（真实标定 0.1 kPa/LSB，300 kPa 为典型目标）
# 巡航基线（模块内统一用 _CRUISE_KMH；顶部 CRUISE_KMH 保留兼容别名）
_CRUISE_KMH = CRUISE_KMH


def _active_flags(m: AssetModel, demo: dict, t: float) -> dict:
    """t 时刻各故障激活标志 + 通道强制值（纯事件查询，无物理）。"""
    prof = _profiles()
    inject_at: dict[str, float] = {}
    recover_at: dict[str, float] = {}
    for e in demo["events"]:
        if e["kind"] == "inject":
            inject_at[e["fault"]] = e["t"]
        elif e["kind"] == "recover":
            recover_at[e["fault"]] = e["t"]

    flags = {
        "eb_request": False,
        "eb_ok": True,
        "eb_applied": False,  # EB 真正施加（压力上升 + 减速）
        "doors_open": 0,
        "door_fault_count": 0,
        "heartbeat_ok": True,
        "bus_ok": True,
        "pantograph_ok": True,
        "soc": 80.0,
        "overspeed": False,
        "traction_loss": False,
        "alarms": [],
        "forbidden_speed": None,  # 若故障把速度钉在超限值(超速注入)
    }
    for fk, inj_t in inject_at.items():
        end_t = recover_at.get(fk, demo["duration"])
        if not (inj_t <= t <= end_t):
            continue
        p = prof.get(fk)
        if not p:
            flags["alarms"].append(f"{_fault_name(m, fk)} 激活")
            continue
        if p.get("eb_request"):
            flags["eb_request"] = True
            flags["eb_ok"] = bool(p.get("eb_ok", True))
        if p.get("eb"):
            flags["eb_request"] = True
            flags["eb_applied"] = True
        if "door_fault_count" in p:
            flags["door_fault_count"] = p["door_fault_count"]
        if "doors_open" in p:
            flags["doors_open"] = p["doors_open"]
        if "heartbeat_ok" in p and not p["heartbeat_ok"]:
            flags["heartbeat_ok"] = False
        if "bus_ok" in p and not p["bus_ok"]:
            flags["bus_ok"] = False
        if "pantograph_ok" in p and not p["pantograph_ok"]:
            flags["pantograph_ok"] = False
        if "soc" in p:
            flags["soc"] = p["soc"]
        if p.get("speed") and fk == "overspeed":
            flags["forbidden_speed"] = p["speed"]
        if fk == "traction_loss":
            flags["traction_loss"] = True
        if fk == "overspeed":
            flags["overspeed"] = True
        if p.get("alarm"):
            flags["alarms"].append(p["alarm"])

    # 处置动作（取当前激活故障里最高优先级）
    actions = [
        e["action"]
        for e in demo["events"]
        if e["kind"] == "action"
        and inject_at.get(e["fault"], float("inf")) <= t
        <= recover_at.get(e["fault"], demo["duration"])
        and e["action"]
    ]
    prio = {"none": 0, "warning": 1, "derate": 2, "emergency_brake": 3, "shutdown": 4}
    flags["action"] = max(actions, key=lambda a: prio.get(a, 0)) if actions else "none"
    return flags


def _phys_step(speed: float, flags: dict, dt: float) -> float:
    """一步物理积分（示意）：处置 → 加速/减速。"""
    action = flags["action"]
    # EB 执行失败：虽然请求 EB，但压力不上升 → 列车几乎不减速（教学点：命令≠执行）
    if flags["eb_request"] and not flags["eb_ok"] and not flags["eb_applied"]:
        return max(speed - _EB_FAIL_COAST * dt, 0.0)
    if flags["eb_applied"] or action in ("emergency_brake", "shutdown"):
        return max(speed - _EB_DECEL * dt, 0.0)
    if action == "derate":
        if speed > _DERATE_SPEED:
            # 降级限速：以一定减速率回落到 derate 目标速度
            return max(speed - _DERATE_DECEL * dt, _DERATE_SPEED)
        return speed
    if flags["traction_loss"]:
        # 牵引丢失：无法加速，滑行衰减（示意）
        return max(speed - _COAST_DECEL * dt, 0.0)
    # 正常/仅告警：向巡航加速
    if speed < _CRUISE_KMH:
        return min(speed + _ACCEL_RATE * dt, _CRUISE_KMH)
    return speed


def _walk(m: AssetModel, demo: dict):
    """逐步积分生成 (t, speed, flags)；overspeed 用上升沿一次性置位。"""
    duration = demo["duration"]
    dt = demo["sample_s"]
    speed = 0.0
    prev_flags: dict | None = None
    t = 0.0
    n = max(1, int(math.ceil(duration / dt))) if (duration and dt) else 0
    for _ in range(n + 1):
        t = min(t, duration)
        flags = _active_flags(m, demo, t)
        if flags["overspeed"] and (prev_flags is None or not prev_flags["overspeed"]):
            speed = flags.get("forbidden_speed") or 168.0
        elif t > 0:
            speed = _phys_step(speed, flags, dt)
        yield t, speed, flags
        prev_flags = flags
        t += dt


def build_curve(m: AssetModel, demo: dict) -> list[dict]:
    """生成整条采样曲线（前端一次取回，逐帧播放，不做本地复算）。"""
    pts = [_channel_point(m, demo, t, speed, flags) for t, speed, flags in _walk(m, demo)]
    if pts:
        pts[-1]["t"] = demo["duration"]
    return pts


def _channel_point(m: AssetModel, demo: dict, t: float, speed: float, flags: dict) -> dict:
    """把一个时间点打包成通道帧。"""
    eb = 1 if (flags["eb_request"] and flags["eb_applied"]) else 0
    brake_kpa = _EB_KPA if flags["eb_applied"] else 0.0
    # eb_failure：EB 请求但未执行 → 压力不上（这就是教学点）
    if flags["eb_request"] and not flags["eb_applied"]:
        eb = 1  # 命令有效（指示灯亮）
        brake_kpa = 0.0  # 但执行未落地 → 压力 0
    return {
        "t": round(t, 2),
        "speed_kmh": round(speed, 1),
        "brake_kpa": round(brake_kpa, 1),
        "eb": eb,
        "doors_open": flags["doors_open"],
        "door_fault_count": flags["door_fault_count"],
        "heartbeat_ok": flags["heartbeat_ok"],
        "bus_ok": flags["bus_ok"],
        "pantograph_ok": flags["pantograph_ok"],
        "soc": round(flags["soc"], 1),
        "action": flags["action"],
        "alarms": flags["alarms"],
    }


def channel_at(m: AssetModel, demo: dict, t: float) -> dict:
    """单点通道状态（重放积分到 t，逻辑与 build_curve 完全一致）。"""
    t = min(max(t, 0.0), demo["duration"])
    last = None
    for tt, speed, flags in _walk(m, demo):
        last = (tt, speed, flags)
        if tt >= t:
            break
    if last is None:
        last = (t, 0.0, _active_flags(m, demo, t))
    tt, speed, flags = last
    return _channel_point(m, demo, min(tt, demo["duration"]), speed, flags)
