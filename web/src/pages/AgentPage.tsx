import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentRunResp } from "../api";
import { Panel, Tag, EmptyState, SkeletonRows } from "../components/ui";

type SysStatus = {
  engine: { ok: boolean; version?: string };
  llm_key: boolean;
};

const STEP_META: Record<string, { label: string; tone: "info" | "ok" | "warn" | "vio" | "bad" }> = {
  plan: { label: "规划", tone: "vio" },
  retrieve: { label: "检索证据", tone: "info" },
  act: { label: "决策", tone: "info" },
  exec: { label: "真实执行", tone: "warn" },
  verify: { label: "验证", tone: "ok" },
  reflect: { label: "反思", tone: "bad" },
  report: { label: "汇报", tone: "ok" },
};

const DIM_LABELS: Record<string, string> = {
  result_grounded: "真实断言",
  evidence_used: "证据使用",
  threshold_aware: "阈值感知",
  domain_aware: "领域语义",
  requirement_trace: "需求追溯",
  honesty: "诚实性",
};

export function AgentPage() {
  const [tasks, setTasks] = useState<{ task_id: string; title: string; goal: string; target_fault: string; expected_action: string }[]>([]);
  const [sel, setSel] = useState("");
  const [sys, setSys] = useState<SysStatus | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done">("idle");
  const [result, setResult] = useState<AgentRunResp | null>(null);
  const [visible, setVisible] = useState(0); // 事件流逐条揭示
  const [err, setErr] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    api.agentTasks().then((t) => { setTasks(t); if (t.length) setSel(t[0].task_id); }).catch(() => undefined);
    api.systemStatus().then(setSys).catch(() => undefined);
    return () => timers.current.forEach(clearTimeout);
  }, []);

  const current = tasks.find((t) => t.task_id === sel);

  const run = async (taskId?: string) => {
    const id = taskId ?? sel;
    if (!id || phase === "running") return;
    // 引擎缺失 → 不执行，引导（不产生 0% 的假失败）
    if (sys && !sys.engine.ok) {
      setErr("engine_missing");
      return;
    }
    setPhase("running");
    setResult(null);
    setErr("");
    setVisible(0);
    try {
      const r = await api.agentRun(id);
      setResult(r);
      // 按真实轨迹时间逐条揭示（事件流感，顺序/耗时是后端真实记录）
      const run0 = r.runs[0];
      if (run0) {
        const totalMs = run0.duration_ms || 1200;
        run0.trace.forEach((_, i) => {
          const delay = 250 + (totalMs / Math.max(run0.trace.length, 1)) * 0.9;
          timers.current.push(setTimeout(() => setVisible(i + 1), i * delay));
        });
      } else {
        setVisible(1);
      }
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("done");
    }
  };

  return (
    <div className="space-y-4 max-w-[1100px]">
      <Panel title="给 Agent 一个真实测试任务" bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择任务" disabled={phase === "running"}>
            {tasks.map((t) => (
              <option key={t.task_id} value={t.task_id}>
                {t.title}
              </option>
            ))}
          </select>
          <button className="btn justify-center" onClick={() => run()} disabled={phase === "running" || !sel || (sys !== null && !sys.engine.ok)} title={sys && !sys.engine.ok ? "需先启用 TCMS 引擎" : undefined}>
            {phase === "running" ? "执行中…" : "▶ 执行此任务"}
          </button>
          <button className="btn-ghost justify-center" onClick={() => run(tasks[0]?.task_id)} disabled={phase === "running" || tasks.length === 0 || (sys !== null && !sys.engine.ok)}>
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

      {/* 引擎缺失引导 */}
      {sys && !sys.engine.ok && (
        <div className="panel border-warn/30 bg-warn/5 p-4">
          <div className="text-sm font-medium text-warn flex items-center gap-2">⚠ 需要先启用 TCMS 引擎</div>
          <p className="text-[12px] text-ink-dim mt-1 leading-5">
            Agent 需要真实引擎去执行场景（检索和评分不依赖引擎，但"真实执行"那一步需要它）。
            启用后成功率才有意义——现在直接跑只会得到 0% 的假结果。
          </p>
          <div className="mt-2 text-[12px] text-ink mono space-y-0.5 bg-surface px-3 py-2 rounded-lg">
            <div>· pip install -e ".[upstream]"  （安装 tcms-can-test 引擎）</div>
            <div>· 或设置 TCMS_UPSTREAM_DIR 指向其目录后重启</div>
          </div>
          <div className="mt-2">
            <Link to="/scenarios" className="text-[12px] text-info hover:underline">
              资产浏览与图谱不依赖引擎，可先去体验 →
            </Link>
          </div>
        </div>
      )}

      {err === "engine_missing" && !(sys && !sys.engine.ok) && (
        <div className="panel border-bad/30 bg-bad/5 px-4 py-2.5 text-sm text-bad">引擎状态已变化，请刷新后重试。</div>
      )}

      {/* 运行中 / 结果：真实事件流 */}
      {phase !== "idle" && result && (
        <div className="step-in space-y-4">
          {result.runs.map((run, ri) => {
            const isRevealed = ri === 0; // 只对触发的首个任务做逐条揭示动效
            const showCount = isRevealed && phase === "done" ? Math.max(visible, 1) : run.trace.length;
            return (
              <Panel
                key={run.task_id}
                title={
                  <>
                    <code className="kbd-mono">{run.task_id}</code>
                    <span className="text-ink font-normal ml-1">
                      {run.fault} → {run.expected}
                    </span>
                    {run.achieved ? <Tag tone="ok">✓ 达成</Tag> : <Tag tone="bad">✗ 未达成</Tag>}
                  </>
                }
                right={
                  <span className="text-[11px] text-ink-faint">
                    {phase === "running" && ri === 0 ? (
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-info pulse-dot" /> Agent 工作中
                      </span>
                    ) : (
                      <>
                        评分 <span className="text-info font-semibold num">{run.score.score}</span> · {run.duration_ms}ms
                        {run.reflected && " · 经反思"}
                      </>
                    )}
                  </span>
                }
                bodyClass="p-0"
              >
                <div className="px-4 py-3 space-y-0 border-b border-line-soft">
                  {run.trace.slice(0, showCount).map((t, i) => {
                    const m = STEP_META[t.step] ?? { label: t.step, tone: "info" as const };
                    return (
                      <div key={i} className="step-in flex items-start gap-2.5 py-1">
                        <Tag tone={m.tone}>{m.label}</Tag>
                        <div className="flex-1 text-[12.5px] text-ink leading-5 min-w-0">
                          <span className="break-words">{t.detail}</span>
                          <span className="text-ink-faint text-[10px] ml-1.5 num">+{t.t.toFixed(1)}s</span>
                        </div>
                      </div>
                    );
                  })}
                  {phase === "running" && ri === 0 && (
                    <div className="pt-2">
                      <SkeletonRows rows={1} cols={3} />
                    </div>
                  )}
                </div>
                <div className="px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                  <div className="bg-surface-2/50 rounded-lg py-2">
                    <div className="text-lg font-bold text-ok num">{run.score.evidence_count}</div>
                    <div className="text-[10px] text-ink-dim">条证据</div>
                  </div>
                  <div className="bg-surface-2/50 rounded-lg py-2">
                    <div className="text-lg font-bold text-info num">{run.attempts}</div>
                    <div className="text-[10px] text-ink-dim">次尝试</div>
                  </div>
                  <div className="bg-surface-2/50 rounded-lg py-2">
                    <div className={`text-lg font-bold num ${run.score.exec_passed ? "text-ok" : "text-bad"}`}>
                      {run.score.exec_passed ? "通过" : "未过"}
                    </div>
                    <div className="text-[10px] text-ink-dim">真实执行</div>
                  </div>
                  <div className="bg-surface-2/50 rounded-lg py-2">
                    <div className="text-lg font-bold text-vio num">{run.scenario ? run.scenario.replace(".yaml", "") : "—"}</div>
                    <div className="text-[10px] text-ink-dim">执行场景</div>
                  </div>
                </div>
                {/* 证据链（RAG 检索到哪些知识 → 供 Agent 决策） */}
                {run.evidence && run.evidence.length > 0 && (
                  <div className="px-4 py-2.5 border-t border-line-soft">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[11px] text-ink-faint font-medium uppercase tracking-wide">检索证据 · GraphRAG</span>
                      <span className="text-[10px] text-ink-faint num">{run.evidence.length} 条命中</span>
                    </div>
                    <div className="space-y-1">
                      {run.evidence.slice(0, 3).map((h, i) => (
                        <div key={i} className="flex items-start gap-2 text-[11.5px] leading-4 bg-surface-2/40 rounded-lg px-2.5 py-1.5">
                          <code className="kbd-mono shrink-0">{h.doc_id}</code>
                          <span className="text-ink-dim min-w-0 flex-1 line-clamp-1" title={h.text}>{h.text}</span>
                          <span className="text-ink-faint num shrink-0">{(h.score * 100).toFixed(0)}%</span>
                        </div>
                      ))}
                      {run.evidence.length > 3 && (
                        <div className="text-[10px] text-ink-faint pl-1">+{run.evidence.length - 3} 条…</div>
                      )}
                    </div>
                  </div>
                )}
                {/* 评审（真实领域语义, evaluator-optimizer） */}
                {run.review && (
                  <div className="px-4 pt-2 pb-3 border-t border-line-soft">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[11px] text-ink-faint font-medium uppercase tracking-wide">真实语义评审</span>
                      {run.review.passed ? <Tag tone="ok">通过</Tag> : <Tag tone="bad">未过</Tag>}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(run.review.dimensions).map(([dim, st]) => (
                        <span
                          key={dim}
                          className={`tag ${
                            st === "pass"
                              ? "text-ok border-ok/30 bg-ok/5"
                              : st === "warn"
                                ? "text-warn border-warn/30 bg-warn/10"
                                : "text-bad border-bad/30 bg-bad/10"
                          }`}
                          title={DIM_LABELS[dim] ?? dim}
                        >
                          {st === "pass" ? "✓" : st === "warn" ? "△" : "✗"} {DIM_LABELS[dim] ?? dim}
                        </span>
                      ))}
                    </div>
                    {run.review.issues.length > 0 && (
                      <ul className="mt-1.5 space-y-0.5">
                        {run.review.issues.map((iss, k) => (
                          <li key={k} className="text-[11px] text-warn leading-4">· {iss}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      )}

      {phase === "idle" && !(sys && !sys.engine.ok) && (
        <Panel>
          <EmptyState
            icon="✦"
            title="Agent 会像测试工程师一样完成任务"
            desc="选一个任务（如「验证紧急制动执行失败必须触发 emergency_brake」）。它会检索知识、选场景、真实执行，并把每一步做了什么实时列出来。"
          />
        </Panel>
      )}
    </div>
  );
}
