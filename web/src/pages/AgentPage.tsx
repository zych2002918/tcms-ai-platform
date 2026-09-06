import { useEffect, useState } from "react";
import { api, type AgentRunResp } from "../api";
import { Panel, Tag, StepFlow, EmptyState, StatusDot, SkeletonRows } from "../components/ui";

export function AgentPage() {
  const [tasks, setTasks] = useState<{ task_id: string; title: string; goal: string; target_fault: string; expected_action: string }[]>([]);
  const [sel, setSel] = useState("");
  const [phase, setPhase] = useState<"idle" | "running" | "done">("idle");
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<AgentRunResp | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .agentTasks()
      .then((t) => {
        setTasks(t);
        if (t.length) setSel(t[0].task_id);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const current = tasks.find((t) => t.task_id === sel);

  const run = async (taskId?: string) => {
    const id = taskId ?? sel;
    if (!id || phase === "running") return;
    setPhase("running");
    setResult(null);
    setErr("");
    setStep(0);
    // 步骤逐个点亮（对应 agent 真实阶段）
    const seq = ["规划任务", "检索知识底座", "选择场景", "真实执行", "验证与汇报"];
    for (let i = 0; i < seq.length; i++) {
      setStep(i);
      await new Promise((r) => setTimeout(r, 280 + Math.random() * 260));
    }
    try {
      setResult(await api.agentRun(id));
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("done");
    }
  };

  const steps =
    phase === "running"
      ? ([
          { label: "规划", state: step >= 0 ? "done" : "todo" },
          { label: "检索", state: step >= 1 ? (step === 1 ? "active" : "done") : "todo" },
          { label: "执行", state: step === 2 ? "active" : step > 2 ? "done" : "todo" },
          { label: "汇报", state: step === 3 ? "active" : step > 3 ? "done" : "todo" },
        ] as { label: string; state: "done" | "active" | "todo" }[])
      : phase === "done" && result
        ? [
            { label: "规划", state: "done" as const },
            { label: "检索", state: "done" as const },
            { label: "执行", state: "done" as const },
            { label: "汇报", state: "done" as const },
          ]
        : [];

  return (
    <div className="space-y-4 max-w-[1100px]">
      <Panel title="给 Agent 一个真实测试任务" bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择任务">
            {tasks.map((t) => (
              <option key={t.task_id} value={t.task_id}>
                {t.title}
              </option>
            ))}
          </select>
          <button className="btn justify-center" onClick={() => run()} disabled={phase === "running" || !sel}>
            {phase === "running" ? "执行中…" : "▶ 执行此任务"}
          </button>
          <button className="btn-ghost justify-center" onClick={() => run(tasks[0]?.task_id)} disabled={phase === "running" || tasks.length === 0} title="依次运行全部 4 个任务">
            运行全部
          </button>
        </div>
        {current && (
          <div className="mt-2.5 text-xs text-ink-dim leading-5">
            <Tag tone="dim">{current.task_id}</Tag> 目标故障 <code className="kbd-mono">{current.target_fault}</code> 期望处置{" "}
            <code className="kbd-mono">{current.expected_action}</code>
            <div className="mt-1">{current.goal}</div>
          </div>
        )}
      </Panel>

      {/* 流程感 */}
      {phase === "running" && (
        <Panel title="Agent 正在工作…" right={<StatusDot tone="info" pulse />} bodyClass="py-3">
          <StepFlow steps={steps} active={step} />
          <div className="mt-3">
            <SkeletonRows rows={2} cols={3} />
          </div>
        </Panel>
      )}

      {err && <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">⚠ {err}</div>}

      {phase === "done" && result && (
        <div className="step-in space-y-4">
          <div className="grid grid-cols-3 gap-3 max-w-md">
            <div className="panel px-4 py-3">
              <div className="stat-num text-info num">{result.total}</div>
              <div className="text-xs text-ink-dim mt-0.5">任务数</div>
            </div>
            <div className="panel px-4 py-3">
              <div className="stat-num text-ok num">{result.achieved}</div>
              <div className="text-xs text-ink-dim mt-0.5">达成</div>
            </div>
            <div className="panel px-4 py-3">
              <div className={`stat-num num ${result.success_rate >= 1 ? "text-ok" : "text-warn"}`}>
                {(result.success_rate * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-ink-dim mt-0.5">成功率</div>
            </div>
          </div>

          {result.runs.map((r) => (
            <Panel
              key={r.task_id}
              title={
                <>
                  <code className="kbd-mono">{r.task_id}</code>
                  <span className="text-ink font-normal ml-1">
                    {r.fault} → {r.expected}
                  </span>
                  {r.achieved ? <Tag tone="ok">✓ 达成</Tag> : <Tag tone="bad">✗ 未达成</Tag>}
                </>
              }
              right={
                <span className="text-[11px] text-ink-faint">
                  评分 <span className="text-info font-semibold num">{r.score.score}</span> · {r.duration_ms}ms
                  {r.reflected && " · 经反思"}
                </span>
              }
              bodyClass="p-0"
            >
              <div className="px-4 pt-2 text-[12px] text-ink-dim flex flex-wrap gap-x-4 gap-y-1">
                <span>
                  执行场景：<code className="kbd-mono">{r.scenario ?? "—"}</code>
                </span>
                <span>
                  证据 <span className="num">{r.score.evidence_count}</span> 条
                </span>
                <span>
                  尝试 <span className="num">{r.attempts}</span> 次
                </span>
                <span>
                  真实执行：{r.score.exec_passed ? <span className="text-ok">通过</span> : <span className="text-bad">未过</span>}
                </span>
              </div>
              <div className="mt-2 border-t border-line-soft">
                <table>
                  <thead>
                    <tr>
                      <th className="th">阶段</th>
                      <th className="th">Agent 实际做了什么</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.trace.map((t, i) => (
                      <tr key={i} className="tr-hover">
                        <td className="td">
                          <Tag tone={t.step === "exec" ? "warn" : t.step === "verify" || t.step === "report" ? "ok" : "info"}>
                            {t.step}
                          </Tag>
                        </td>
                        <td className="td text-ink-dim">{t.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          ))}
        </div>
      )}

      {phase === "idle" && (
        <Panel>
          <EmptyState
            icon="✦"
            title="Agent 会像测试工程师一样完成任务"
            desc="选一个任务（如「验证紧急制动执行失败必须触发 emergency_brake」），它会自主检索知识、选场景、真实执行并给出带轨迹的报告。"
          />
        </Panel>
      )}
    </div>
  );
}
