import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentFreeResp, type AgentRunResp } from "../api";
import { Panel, Tag, EmptyState, SkeletonRows } from "../components/ui";

type AgentRun = AgentRunResp["runs"][number];

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

/** 管线顺序（与后端真实轨迹的 step 对齐：plan→retrieve→act→exec→verify→reflect→report） */
const STEP_ORDER = ["plan", "retrieve", "act", "exec", "verify", "reflect", "report"];

/** 跳 FaultLab：run.scenario 是真实场景文件名（含 .yaml）→ 直达 ?scenario= 演示本次执行的场景动画
 * 通道契约与 fe-faultlab t4 对齐：from=agent-exec → FaultLab 顶部标注「来自 Agent 执行」 */
function faultlabHref(scenario: string, from: string): string {
  const p = new URLSearchParams({ scenario, from });
  return `/faultlab?${p.toString()}`;
}

const DIM_LABELS: Record<string, string> = {
  result_grounded: "真实断言",
  evidence_used: "证据使用",
  threshold_aware: "阈值感知",
  domain_aware: "领域语义",
  requirement_trace: "需求追溯",
  honesty: "诚实性",
};

/** 运行中「Agent 思考中…」的步骤提示（随动画轮换，给用户"进程在走"的感觉） */
const RUN_HINTS = [
  "正在把你的目标拆成「故障 → 期望处置」…",
  "正在从知识底座检索证据（GraphRAG）…",
  "正在挑选覆盖该故障的真实场景…",
  "正在真实引擎上执行并核对断言…",
  "正在评审结果：阈值 / 联锁 / 需求追溯…",
];

/** 单条 run 的「管线进程视图」：把逐条 reveal 映射到横排 step 点亮 */
function StepPipeline({ trace, showCount }: { trace: AgentRun["trace"]; showCount: number }) {
  if (trace.length === 0) return null;
  const shown = trace.slice(0, showCount);
  const doneSteps = new Set(shown.map((t) => t.step));
  const lastStep = shown.length > 0 ? shown[shown.length - 1].step : null;
  const stillRevealing = showCount < trace.length;
  const toneCls: Record<string, string> = {
    ok: "text-ok border-ok/40 bg-ok/10",
    warn: "text-warn border-warn/40 bg-warn/10",
    bad: "text-bad border-bad/40 bg-bad/10",
    info: "text-info border-info/40 bg-info/10",
    vio: "text-vio border-vio/40 bg-vio/10",
    dim: "text-ink-dim border-line bg-surface-2",
  };
  return (
    <ol className="flex flex-wrap items-center gap-y-1.5 gap-x-0 px-4 pt-3 pb-0.5" aria-label="执行管线">
      {STEP_ORDER.map((s, i) => {
        const meta = STEP_META[s] ?? { label: s, tone: "info" as const };
        const isDone = doneSteps.has(s);
        const isActive = isDone && stillRevealing && s === lastStep;
        const isTodo = !isDone;
        return (
          <li key={s} className="flex items-center gap-x-0">
            {i > 0 && <span className="text-ink-faint mx-1 text-[10px]">→</span>}
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] leading-4 whitespace-nowrap transition-all ${
                isActive
                  ? "text-info border-info/70 bg-info/15"
                  : isDone
                    ? toneCls[meta.tone] ?? toneCls.info
                    : "text-ink-faint border-line bg-transparent"
              }`}
            >
              {isActive ? (
                <span className="h-1.5 w-1.5 rounded-full bg-info pulse-dot" />
              ) : isDone ? (
                <span className="text-[9px]">✓</span>
              ) : (
                <span className="h-1.5 w-1.5 rounded-full border border-ink-faint/50" />
              )}
              {isTodo ? <span className="opacity-60">{meta.label}</span> : meta.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** 自由目标 → 解析卡：给人看 Agent 怎么理解自然语言 */
function GoalParseCard({ resp }: { resp: AgentFreeResp }) {
  const p = resp.parsed;
  if (!p) return null;
  const conf = typeof p.confidence === "number" ? Math.round(p.confidence * 100) : null;
  return (
    <div className="panel border-info/30 bg-info/5 px-4 py-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] text-ink-faint font-medium uppercase tracking-wide">Agent 理解你的目标</span>
        <span className="text-[11px] text-ink-dim">“{resp.goal}”</span>
        {conf !== null && (
          <span className="ml-auto">
            <Tag tone={conf >= 60 ? "ok" : "warn"}>置信度 {conf}%</Tag>
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
        <span className="text-ink-dim">锚定故障</span>
        <code className="kbd-mono !text-[13px] !text-bad border border-bad/30 bg-bad/10 rounded px-1.5 py-0.5">
          {p.fault_name ? `${p.fault_name}（${p.fault}）` : p.fault}
        </code>
        <span className="text-ink-faint">→</span>
        <span className="text-ink-dim">期望处置</span>
        <code className="kbd-mono !text-[13px] !text-ok border border-ok/30 bg-ok/10 rounded px-1.5 py-0.5">
          {p.expected_zh ? `${p.expected_zh}（${p.expected}）` : p.expected}
        </code>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-ink-faint">
        {p.resolver && (
          <span>
            解析方式：{p.resolver === "llm" ? "LLM 语义理解" : "规则匹配"}
          </span>
        )}
        {p.matched_on && <span>命中依据：{p.matched_on}</span>}
        <span className="text-ink-faint">下面按这条理解走完整流程：检索证据 → 真实执行 → 评审。</span>
      </div>
    </div>
  );
}

export function AgentPage() {
  const [tasks, setTasks] = useState<{ task_id: string; title: string; goal: string; target_fault: string; expected_action: string }[]>([]);
  const [sel, setSel] = useState("");
  const [sys, setSys] = useState<SysStatus | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done">("idle");
  const [result, setResult] = useState<AgentRunResp | null>(null);
  const [freeResp, setFreeResp] = useState<AgentFreeResp | null>(null);
  const [visible, setVisible] = useState(0); // 事件流逐条揭示
  const [err, setErr] = useState("");
  const [goal, setGoal] = useState("");
  const [goalHint, setGoalHint] = useState(""); // 自由目标没锚定 → 换说法引导
  const [hintIdx, setHintIdx] = useState(0); // 运行中步骤提示轮换
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    api.agentTasks().then((t) => { setTasks(t); if (t.length) setSel(t[0].task_id); }).catch(() => undefined);
    api.systemStatus().then(setSys).catch(() => undefined);
    return () => timers.current.forEach(clearTimeout);
  }, []);

  // 运行中：步骤提示轮换（简单 interval；离开 running 自动停）
  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => setHintIdx((i) => i + 1), 2000);
    return () => clearInterval(id);
  }, [phase]);

  const current = tasks.find((t) => t.task_id === sel);
  const engineBlocked = sys !== null && !sys.engine.ok;

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  /** 按真实轨迹时间逐条揭示（事件流感：顺序/耗时是后端真实记录） */
  const scheduleReveal = (runs: AgentRun[]) => {
    setVisible(0);
    const run0 = runs[0];
    if (run0) {
      const totalMs = run0.duration_ms || 1200;
      run0.trace.forEach((_, i) => {
        const delay = 250 + (totalMs / Math.max(run0.trace.length, 1)) * 0.9;
        timers.current.push(setTimeout(() => setVisible(i + 1), i * delay));
      });
    } else {
      setVisible(1);
    }
  };

  const begin = () => {
    clearTimers();
    setPhase("running");
    setResult(null);
    setFreeResp(null);
    setErr("");
    setGoalHint("");
    setVisible(0);
  };

  const run = async (taskId?: string) => {
    const id = taskId ?? sel;
    if (!id || phase === "running") return;
    // 引擎缺失 → 不执行，引导（不产生 0% 的假失败）
    if (sys && !sys.engine.ok) {
      setErr("engine_missing");
      return;
    }
    begin();
    try {
      const r = await api.agentRun(id);
      setResult(r);
      scheduleReveal(r.runs);
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("done");
    }
  };

  const runFree = async () => {
    const g = goal.trim();
    if (!g || phase === "running") return;
    if (sys && !sys.engine.ok) {
      setErr("engine_missing");
      return;
    }
    begin();
    try {
      // 契约：命中 → 200 恒带 parsed；规则未命中 → 200 no_match + suggested_faults（RAG 候选）
      const r = await api.agentFree(g);
      setFreeResp(r);
      if (r.no_match) {
        setGoalHint(r.detail ?? "");
      } else {
        scheduleReveal(r.runs);
      }
      setPhase("done");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 后端意外 422/400（异常路径）→ 中文空态引导；其余 → 错误条
      if (/^422:|^400:/.test(msg)) {
        setGoalHint(msg.replace(/^4\d\d:\s*/, ""));
      } else {
        setErr(msg);
      }
      setPhase("done");
    }
  };

  const runs: AgentRun[] = result?.runs ?? freeResp?.runs ?? [];

  return (
    <div className="space-y-4 max-w-[1100px]">
      {/* 自由目标（像 DSH 一样：给 Agent 一句话，它先理解再查证） */}
      <Panel title="用大白话，直接给 Agent 一个目标" bodyClass="p-3">
        <textarea
          className="input resize-none"
          rows={2}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="用大白话描述你想验证的：如「车门故障了还能发车吗？」「超速后系统该怎么办」「验证紧急制动失败必须停车」"
          aria-label="自由目标输入"
          disabled={phase === "running"}
        />
        <div className="mt-2 flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <button
            className="btn justify-center sm:w-auto"
            onClick={() => void runFree()}
            disabled={phase === "running" || !goal.trim() || engineBlocked}
            title={engineBlocked ? "需先启用 TCMS 引擎" : "让 Agent 先去理解你的目标，再检索证据、真实执行"}
          >
            {phase === "running" ? "执行中…" : "✦ 让 Agent 去查证"}
          </button>
          <span className="text-[11px] text-ink-faint leading-4">
            不用选任务、不用懂报文——Agent 会先把你的话理解成「故障 → 期望处置」，再去知识库查证。
          </span>
        </div>
      </Panel>

      {/* 内置任务（保留原有入口） */}
      <Panel title="或选一个内置真实测试任务" bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择任务" disabled={phase === "running"}>
            {tasks.map((t) => (
              <option key={t.task_id} value={t.task_id}>
                {t.title}
              </option>
            ))}
          </select>
          <button className="btn justify-center" onClick={() => run()} disabled={phase === "running" || !sel || engineBlocked} title={engineBlocked ? "需先启用 TCMS 引擎" : undefined}>
            {phase === "running" ? "执行中…" : "▶ 执行此任务"}
          </button>
          <button className="btn-ghost justify-center" onClick={() => run(tasks[0]?.task_id)} disabled={phase === "running" || tasks.length === 0 || engineBlocked}>
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
        <div className="mt-2 text-[11px] text-ink-faint">
          也可以直接在上方输入你自己的目标，Agent 会先理解再查证——两者走的是同一条执行流水线。
        </div>
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

      {err && err !== "engine_missing" && (
        <div className="panel border-bad/30 bg-bad/5 px-4 py-2.5 text-sm text-bad">⚠ {err}</div>
      )}

      {/* 运行中：Agent 思考中…（步骤提示轮换 + pulse） */}
      {phase === "running" && !result && !freeResp && !goalHint && (
        <div className="panel px-4 py-4 flex items-start gap-3 step-in">
          <span className="mt-1.5 flex h-2.5 w-2.5">
            <span className="h-2.5 w-2.5 rounded-full bg-info pulse-dot" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-ink">Agent 思考中…</div>
            <div className="text-xs text-ink-dim mt-0.5 h-4">{RUN_HINTS[hintIdx % RUN_HINTS.length]}</div>
            <div className="mt-1">
              <SkeletonRows rows={1} cols={3} />
            </div>
          </div>
        </div>
      )}

      {/* 自由目标没锚定 → 引导：RAG 候选（可点选续跑）或换说法示例 */}
      {goalHint && phase === "done" && (
        <div className="panel px-4 py-5 step-in">
          <EmptyState
            icon="?"
            title="这句我没法锚定到具体故障"
            desc={`${goalHint}${freeResp?.suggested_faults?.length ? " —— 但 AI 检索到了几个可能相关的真实故障，点选即可让 Agent 去查证：" : " —— 试试让目标里出现故障对象（如：车门故障 / 超速 / 心跳丢失）和期望（如：不能发车 / 降级 / 停车）。"}`}
          />
          {freeResp && freeResp.suggested_faults && freeResp.suggested_faults.length > 0 && (
            <div className="flex flex-wrap gap-1.5 justify-center pb-3">
              {freeResp.suggested_faults.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  className="tag text-info border-info/40 bg-info/10 hover:bg-info/20 cursor-pointer transition-colors text-left"
                  title={`等级 ${s.level ?? "?"} · 期望处置 ${s.action ?? "?"}`}
                  onClick={() => setGoal(`验证${s.name ?? s.key}必须${s.action ?? ""}的处置`)}
                >
                  {s.name ?? s.key} <span className="opacity-70">({s.key})</span>
                </button>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-1.5 justify-center">
            {["车门故障了还能发车吗", "超速后系统该怎么办", "验证紧急制动失败必须停车"].map((ex) => (
              <Tag key={ex} tone="dim" onClick={() => setGoal(ex)}>
                {ex}
              </Tag>
            ))}
          </div>
        </div>
      )}

      {/* 运行中 / 结果：真实事件流（含管线进程视图）；no_match 时 runs 为空，不渲染 */}
      {phase !== "idle" && !freeResp?.no_match && (result || freeResp) && (
        <div className="step-in space-y-4">
          {/* 自由目标命中 → 先给人看 Agent 怎么理解这句话（后端契约：命中恒带 parsed） */}
          {freeResp && <GoalParseCard resp={freeResp} />}

          {runs.map((run, ri) => {
            const isRevealed = ri === 0; // 只对触发的首个任务做逐条揭示动效
            const showCount = isRevealed && phase === "done" ? Math.max(visible, 1) : run.trace.length;
            return (
              <Panel
                key={`${run.task_id}-${ri}`}
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
                {/* 管线进程视图：随 reveal 逐段点亮 */}
                <StepPipeline trace={run.trace} showCount={showCount} />
                <div className="px-4 py-2.5 space-y-0 border-t border-line-soft">
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
                {/* 看动画：把本次真实执行的场景送进 FaultLab 演示（资产化动画，非额定设置） */}
                {run.scenario && (
                  <div className="px-4 py-2 border-t border-line-soft flex items-center gap-2 flex-wrap">
                    <span className="text-[11px] text-ink-faint">
                      场景 <code className="kbd-mono">{run.scenario}</code> 已真实执行完成
                    </span>
                    <a
                      className="btn-ghost btn-sm ml-auto shrink-0"
                      href={faultlabHref(run.scenario, "agent-exec")}
                      title="跳转 FaultLab，用动画回放这个场景的故障注入 → 检测 → 处置 → 恢复"
                    >
                      ▶ 看动画
                    </a>
                  </div>
                )}
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
            desc="选一个任务（如「验证紧急制动执行失败必须触发 emergency_brake」），或直接在上方输入你自己的目标。它会先理解成故障+期望处置，再检索知识、选场景、真实执行，并把每一步做了什么实时列出来。"
          />
        </Panel>
      )}
    </div>
  );
}
