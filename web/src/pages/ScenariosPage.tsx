import { useEffect, useState } from "react";
import { api, type RunScenarioResult, type ScenarioInfo } from "../api";
import { Panel, Tag, EmptyState, SkeletonRows } from "../components/ui";

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [sel, setSel] = useState("");
  const [sys, setSys] = useState<{ engine: { ok: boolean; version?: string } } | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<RunScenarioResult | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .scenarios()
      .then((s) => {
        setScenarios(s);
        if (s.length) setSel(s[0].file);
      })
      .catch((e) => setErr(String(e)));
    api.systemStatus().then(setSys).catch(() => undefined);
  }, []);

  const current = scenarios.find((s) => s.file === sel);
  const engineOk = sys?.engine.ok ?? true;

  const run = async () => {
    if (!sel || phase === "running") return;
    if (!engineOk) {
      setErr("engine_missing");
      return;
    }
    setPhase("running");
    setResult(null);
    setErr("");
    try {
      const r = await api.runScenario(sel);
      setResult(r);
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("error");
    }
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

      {/* 引擎缺失引导 */}
      {sys && !engineOk && (
        <div className="panel border-warn/30 bg-warn/5 p-4">
          <div className="text-sm font-medium text-warn flex items-center gap-2">⚠ 运行场景需要 TCMS 引擎</div>
          <p className="text-[12px] text-ink-dim mt-1 leading-5">
            场景由真实 TCMS 引擎执行（资产浏览与知识图谱不需要它）。启用方法：
          </p>
          <div className="mt-2 text-[12px] text-ink mono space-y-0.5 bg-surface px-3 py-2 rounded-lg">
            <div>· pip install -e ".[upstream]"  （从 GitHub 安装 tcms-can-test 引擎）</div>
            <div>· 或设置环境变量 TCMS_UPSTREAM_DIR 指向 tcms-can-test 目录后重启服务</div>
          </div>
        </div>
      )}

      {/* 运行中：真实引擎在工作（诚实加载态） */}
      {phase === "running" && (
        <Panel
          title="TCMS 引擎执行中…"
          right={
            <span className="flex items-center gap-1.5 text-[11px] text-ink-dim">
              <span className="h-1.5 w-1.5 rounded-full bg-info pulse-dot" /> 仿真 + 断言中
            </span>
          }
          bodyClass="py-3"
        >
          <SkeletonRows rows={3} cols={4} />
          <p className="text-[11px] text-ink-faint mt-2">
            引擎正在：装载场景 → 初始化虚拟时钟 → 注入故障推进时间线 → 逐条断言期望处置
          </p>
        </Panel>
      )}

      {phase === "error" && (
        <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">
          {err === "engine_missing" ? "⚠ 需要先启用 TCMS 引擎（见上方说明）" : `⚠ 执行失败：${err}`}
        </div>
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

      {phase === "idle" && engineOk && (
        <Panel>
          <EmptyState
            icon="▶"
            title="选好场景后点「运行此场景」"
            desc="引擎会真实执行：注入故障 → 推进时间线 → 断言期望处置。结果沉淀到知识库（run 记录）。"
          />
        </Panel>
      )}
    </div>
  );
}
