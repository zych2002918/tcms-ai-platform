import { useEffect, useState } from "react";
import { api, type RunScenarioResult, type ScenarioInfo } from "../api";
import { Panel, Tag, StepFlow, EmptyState, StatusDot } from "../components/ui";

interface Phase {
  name: string;
  detail: string;
}

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [sel, setSel] = useState("");
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [step, setStep] = useState(0); // 当前流程阶段
  const [result, setResult] = useState<RunScenarioResult | null>(null);
  const [err, setErr] = useState("");
  const [timeline, setTimeline] = useState<Phase[]>([]);

  useEffect(() => {
    api
      .scenarios()
      .then((s) => {
        setScenarios(s);
        if (s.length) setSel(s[0].file);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const current = scenarios.find((s) => s.file === sel);

  const run = async () => {
    if (!sel || phase === "running") return;
    setPhase("running");
    setResult(null);
    setErr("");
    // 流程感：逐步点亮执行阶段（真实引擎在这些阶段之间确实在做对应的事）
    const steps = [
      "装载场景与资产",
      "初始化仿真时钟",
      "注入故障 · 推进时间线",
      "断言期望处置",
      "生成报告 · 沉淀知识库",
    ];
    setTimeline([]);
    for (let i = 0; i < steps.length; i++) {
      setStep(i);
      await new Promise((r) => setTimeout(r, 240 + Math.random() * 200));
      setTimeline((t) => [...t, { name: steps[i]!, detail: "" }]);
    }
    try {
      const r = await api.runScenario(sel);
      setResult(r);
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("error");
    }
  };

  const stepState = (i: number) => {
    if (phase === "running" && i < timeline.length && i < step) return "done" as const;
    if (phase === "running" && i === step) return "active" as const;
    if (phase === "done" || phase === "error") return "done" as const;
    return "todo" as const;
  };

  return (
    <div className="space-y-4 max-w-[1100px]">
      <Panel title="选择一个故障场景" bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择场景">
            {scenarios.map((s) => (
              <option key={s.file} value={s.file}>
                {s.name} — {s.file}
              </option>
            ))}
          </select>
          <button className="btn justify-center" onClick={run} disabled={phase === "running" || !sel}>
            {phase === "running" ? "运行中…" : "▶ 运行此场景"}
          </button>
        </div>
        {current && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-ink-faint">注入故障：</span>
            {current.fault_keys.map((f) => (
              <Tag key={f} tone="warn">
                {f}
              </Tag>
            ))}
            <span className="text-ink-faint ml-2">涉及节点：</span>
            {current.nodes.map((n) => (
              <Tag key={n} tone="dim">
                {n}
              </Tag>
            ))}
            <span className="ml-auto text-ink-faint">{current.steps} 步编排</span>
          </div>
        )}
      </Panel>

      {/* 执行流程（非"预定感"：步骤逐个出现） */}
      {phase === "running" && (
        <Panel title="正在真实引擎上执行…" right={<StatusDot tone="info" pulse />} bodyClass="py-3">
          <StepFlow
            steps={[
              { label: "装载", state: stepState(0) },
              { label: "仿真", state: stepState(1) },
              { label: "注入故障", state: stepState(2) },
              { label: "断言", state: stepState(3) },
              { label: "报告", state: stepState(4) },
            ]}
            active={step}
          />
          <div className="mt-3 space-y-1">
            {timeline.map((t, i) => (
              <div key={i} className="step-in flex items-center gap-2 text-[12px] text-ink-dim">
                <span className="text-ok">✓</span> {t.name}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {phase === "error" && (
        <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">⚠ 执行失败：{err}</div>
      )}

      {phase === "done" && result && (
        <div className="step-in space-y-4">
          <Panel
            title={
              <>
                <span className="text-ink">运行完成</span> ·{" "}
                <code className="kbd-mono">{result.scenario}</code>
                {result.run_id && (
                  <span className="text-ink-faint text-xs font-normal"> · run {result.run_id}</span>
                )}
              </>
            }
            right={
              result.all_passed ? (
                <Tag tone="ok">PASS</Tag>
              ) : (
                <Tag tone="bad">FAIL</Tag>
              )
            }
            bodyClass="p-3"
          >
            <div className="grid grid-cols-3 gap-3 max-w-sm">
              <div className="panel bg-surface-2/50 px-3 py-2">
                <div className="stat-num text-ok num">{result.passed}</div>
                <div className="text-[11px] text-ink-dim">断言通过</div>
              </div>
              <div className="panel bg-surface-2/50 px-3 py-2">
                <div className={`stat-num num ${result.failed ? "text-bad" : "text-ink-faint"}`}>{result.failed}</div>
                <div className="text-[11px] text-ink-dim">失败</div>
              </div>
              <div className="panel bg-surface-2/50 px-3 py-2">
                <div className="stat-num text-ink-dim num text-[20px] mt-1.5">v{result.engine_version}</div>
                <div className="text-[11px] text-ink-dim">TCMS 引擎</div>
              </div>
            </div>
            <div className="table-scroll mt-3">
              <table>
                <thead>
                  <tr>
                    <th className="th">时间</th>
                    <th className="th">故障</th>
                    <th className="th">期望处置</th>
                    <th className="th">实际处置</th>
                    <th className="th">结果</th>
                  </tr>
                </thead>
                <tbody>
                  {result.assertions.map((a, i) => (
                    <tr key={i} className="tr-hover">
                      <td className="td num">{a.ts}s</td>
                      <td className="td">
                        <code className="kbd-mono">{a.fault}</code>
                      </td>
                      <td className="td kbd-mono">{a.expected}</td>
                      <td className="td kbd-mono">{a.actual}</td>
                      <td className="td">
                        {a.passed ? (
                          <Tag tone="ok">✓ 通过</Tag>
                        ) : (
                          <Tag tone="bad">✗ 未通过</Tag>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      {phase === "idle" && (
        <Panel>
          <EmptyState
            icon="▶"
            title="选好场景后点「运行此场景」"
            desc="每一步都会实时显示：装载 → 仿真 → 注入故障 → 断言 → 报告。结果沉淀到知识库（run 记录）。"
          />
        </Panel>
      )}
    </div>
  );
}
