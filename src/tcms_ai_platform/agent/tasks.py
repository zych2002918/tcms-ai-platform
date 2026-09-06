"""P4 Agent 任务库：贴近真实测试工程师的任务定义 + 地面真值。

任务 = 验证「某个故障 → 期望处置」是否被真实引擎正确执行。
地面真值（ground truth）全部由资产派生：
    - target_fault      必须被覆盖的故障键（真实 faults.yaml 键）
    - expected_action   该故障的期望处置（真实 faults.yaml action）
    - 判定标准：运行覆盖该故障的场景，断言 expected == actual 且通过

评分维度（见 harness.score）：pass / coverage / evidence / self-heal
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.models import AssetModel


@dataclass(frozen=True)
class TaskDef:
    task_id: str
    title: str
    goal: str  # 给 agent 的自然语言任务描述
    target_fault: str  # 必须覆盖的故障键
    expected_action: str  # 期望处置（判定标准）
    kb_query: str = ""  # 检索提示


# 任务库：从真实故障字典挑选高价值安全故障
def default_tasks(m: AssetModel) -> list[TaskDef]:
    """内置任务（锚定真实故障键；未知键直接抛错防漂移）。"""
    known = m.faults_by_key
    specs = [
        TaskDef(
            task_id="T-EBM",
            title="验证紧急制动执行失败处置",
            goal="验证 eb_failure（紧急制动执行失败）必须触发 emergency_brake 处置，且相关场景真实执行通过。",
            target_fault="eb_failure",
            expected_action="emergency_brake",
            kb_query="紧急制动 执行失败 处置",
        ),
        TaskDef(
            task_id="T-DOOR",
            title="验证车门故障联锁",
            goal="验证 door_fault（车门故障）必须触发 derate 降级处置，禁止发车语义正确。",
            target_fault="door_fault",
            expected_action="derate",
            kb_query="车门故障 不能发车 联锁",
        ),
        TaskDef(
            task_id="T-OVERSPEED",
            title="验证超速降级",
            goal="验证 overspeed（超速）必须触发 derate 处置且真实执行通过。",
            target_fault="overspeed",
            expected_action="derate",
            kb_query="超速 降级 ATP",
        ),
        TaskDef(
            task_id="T-CONFLICT",
            title="验证牵引制动冲突",
            goal="验证 traction_brake_conflict（牵引制动冲突）必须触发 emergency_brake。",
            target_fault="traction_brake_conflict",
            expected_action="emergency_brake",
            kb_query="牵引 制动 冲突 联锁",
        ),
    ]
    # 校验所有锚定真实（防需求漂移——数字机器自证纪律）
    for t in specs:
        if t.target_fault not in known:
            raise KeyError(f"任务 {t.task_id}: 故障 {t.target_fault} 不在故障字典")
        f = known[t.target_fault]
        if f.action != t.expected_action:
            raise ValueError(
                f"任务 {t.task_id}: 期望处置 {t.expected_action} ≠ 故障字典实际 {f.action}"
            )
    return specs
