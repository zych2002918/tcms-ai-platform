import { useEffect, useMemo, useState } from "react";
import { api, type FaultInfo, type RunScenarioResult, type ScenarioInfo } from "../api";
import { Panel, Tag, EmptyState, SkeletonRows } from "../components/ui";

/**
 * 手动编排（自定义故障场景）—— 契约已由队长确认（be-contracts t1，POST /api/run/custom）：
 *   runCustom({ name?, steps: [{ at, action, fault?, node?, level?, expect?, impact? }] }) → RunScenarioResult
 *   字段均可为 string|null；inject 步骤 fault 必填且须在故障字典，后端 422 校验。
 *
 * TODO(t1): api.ts 尚未加入 runCustom 类型/方法（t1 接线中）。
 * 这里用「可选访问 + 运行时检测」调用 api.runCustom——t1 把方法挂上后本页自动生效，
 * 不阻塞本页开发、也不与 t1 编辑 api.ts 冲突。若后端契约字段有出入，以 t1 类型为准。
 */
type CustomStepPayload = {
  at: number;
  action: "inject" | "recover";
  fault?: string | null;
  node?: string | null;
  level?: string | null;
  expect?: string | null;
  impact?: string | null;
};
type CustomScenarioPayload = { name?: string; steps: CustomStepPayload[] };
type RunCustomFn = (body: CustomScenarioPayload) => Promise<RunScenarioResult>;

/** 手动编排步骤行（字符串态，提交时才 parse/校验） */
type Row = {
  id: number;
  at: string;
  action: "inject" | "recover";
  fault: string;
  node: string;
  level: string;
  expect: string;
  impact: string;
  err: string;
};

const LEVELS = ["major", "minor", "critical", "info"];
const EXPECTS = ["emergency_brake", "derate", "shutdown", "warning", "none"];
const NODES = ["vcu", "bcu", "bms"];

let _rid = 0;
const nextId = () => ++_rid;

const defaultRows = (): Row[] => [
  { id: nextId(), at: "10", action: "inject", fault: "overspeed", node: "vcu", level: "major", expect: "derate", impact: "速度超过限速，期望降级", err: "" },
  { id: nextId(), at: "20", action: "recover", fault: "overspeed", node: "vcu", level: "", expect: "", impact: "", err: "" },
];

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [faults, setFaults] = useState<FaultInfo[]>([]);
  const [sel, setSel] = useState("");
  const [sys, setSys] = useState<{ engine: { ok: boolean; version?: string } } | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<RunScenarioResult | null>(null);
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"builtin" | "custom">("builtin");
  // 手动编排状态
  const [sceneName, setSceneName] = useState("");
  const [rows, setRows] = useState<Row[]>(defaultRows);

  useEffect(() => {
    api
      .scenarios()
      .then((s) => {
        setScenarios(s);
        if (s.length) setSel(s[0].file);
      })
      .catch((e) => setErr(String(e)));
    api.faults().then(setFaults).catch(() => undefined);
    api.systemStatus().then(setSys).catch(() => undefined);
  }, []);

  const current = scenarios.find((s) => s.file === sel);
  const engineOk = sys?.engine.ok ?? true;
  const faultOpts = useMemo(() => [...faults].sort((a, b) => a.key.localeCompare(b.key)), [faults]);

  /** 每行字段更新 */
  const patchRow = (id: number, p: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...p, err: "" } : r)));

  const actionOf = (id: number) => rows.find((r) => r.id === id)?.action ?? "inject";

  /** 选故障后：inject 行若等级/期望仍空，用故障字典真实值预填（机器自证，可再改） */
  const pickFault = (id: number, key: string) => {
    const f = faults.find((x) => x.key === key);
    const r = rows.find((x) => x.id === id);
    const patch: Partial<Row> = { fault: key };
    if (r?.action === "inject" && f) {
      if (!r.level && LEVELS.includes(f.level)) patch.level = f.level;
      if (!r.expect && EXPECTS.includes(f.action)) patch.expect = f.action;
    }
    patchRow(id, patch);
  };

  /** 步骤行级校验（不合法 → 行内红字，阻止提交）。同步计算 next 行再 setState，保证返回值可靠。 */
  const validateRows = (): boolean => {
    const next = rows.map((r) => {
      const at = Number.parseFloat(r.at);
      const msgs: string[] = [];
      if (!Number.isFinite(at) || at <= 0) msgs.push("时间需大于 0 秒");
      if (!r.fault) msgs.push(r.action === "inject" ? "inject 行需选故障" : "需选要恢复的故障");
      return { ...r, err: msgs.join("；") };
    });
    setRows(next);
    return !next.some((r) => r.err);
  };

  const runBuiltin = async () => {
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

  /** 提交自定义场景：校验 → api.runCustom（t1 接线后自动可用） */
  const runCustom = async () => {
    if (phase === "running") return;
    if (!engineOk) {
      setErr("engine_missing");
      return;
    }
    const fn = (api as unknown as { runCustom?: RunCustomFn }).runCustom;
    if (!fn) {
      setErr("自定义场景执行接口尚未就绪（api.runCustom 由后端契约 t1 接线中，完成后本页自动可用）");
      return;
    }
    if (!validateRows()) return; // 行内红字提示
    const steps: CustomStepPayload[] = rows.map((r) => {
      const step: CustomStepPayload = {
        at: Number.parseFloat(r.at),
        action: r.action,
        fault: r.fault || null, // inject 必填（后端 422 校验）；recover 指定要恢复的故障
        node: r.node || null,
        level: r.level || null,
        expect: r.expect || null,
        impact: r.impact.trim() || null,
      };
      return step;
    });
    const body: CustomScenarioPayload = { steps };
    if (sceneName.trim()) body.name = sceneName.trim();
    setPhase("running");
    setResult(null);
    setErr("");
    try {
      const r = await fn(body);
      setResult(r);
      setPhase("done");
    } catch (e) {
      setErr(String(e));
      setPhase("error");
    }
  };

  const modeTab = (m: "builtin" | "custom", label: string) => (
    <button
      onClick={() => setMode(m)}
      className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
        mode === m ? "text-ink border-info/50 bg-info/10" : "text-ink-dim border-line hover:text-ink"
      }`}
    >
      {label}
    </button>
  );

  /** 单步行控件（带小标签） */
  const field = (label: string, children: React.ReactNode, extraCls = "") => (
    <label className={`flex flex-col gap-0.5 text-[10px] text-ink-faint ${extraCls}`}>
      {label}
      {children}
    </label>
  );
  const ctrl = "input !py-1.5 !px-2 text-[12px]";

  return (
    <div className="space-y-4 max-w-[1100px]">
      {/* 顶部：数量来源说明 + 模式切换 + 执行区 */}
      <Panel title="运行故障场景" bodyClass="p-3">
        {/* 数量来源说明（机器自证：N = 实际拉到的场景数） */}
        <p className="text-[11px] text-ink-faint leading-4.5 mb-2.5">
          ℹ 这里的 <span className="num">{scenarios.length}</span> 个场景来自当前资产源
          （真实引擎目录 <code className="kbd-mono">scenarios/</code> 或内置快照）—— 每个文件 = 一个场景；
          往里加 <code className="kbd-mono">scenarios/*.yaml</code> 即可自动出现在这里（无需改代码）。
        </p>

        {/* 内置 vs 手动编排 切换 */}
        <div className="flex items-center gap-1.5 mb-2.5">
          {modeTab("builtin", "▤ 内置场景")}
          {modeTab("custom", "✎ 手动编排")}
          {mode === "custom" && <span className="ml-auto text-[11px] text-ink-faint">自己编排故障注入 / 恢复步骤，真实执行</span>}
        </div>

        {mode === "builtin" ? (
          <>
            <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
              <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择场景">
                {scenarios.map((s) => (
                  <option key={s.file} value={s.file}>
                    {s.name} — {s.file}
                  </option>
                ))}
              </select>
              <button className="btn justify-center" onClick={runBuiltin} disabled={phase === "running" || !sel || !engineOk}>
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
          </>
        ) : (
          /* ---------- 手动编排编辑器 ---------- */
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-[11px] text-ink-faint">
                场景名称（可选）
                <input
                  className="input mt-0.5 font-mono text-[12px]"
                  placeholder="如：自定义超速降级演练"
                  value={sceneName}
                  onChange={(e) => setSceneName(e.target.value)}
                />
              </label>
            </div>

            {rows.length === 0 ? (
              <div className="panel bg-surface-2/40 px-3 py-4 text-center text-xs text-ink-faint">
                还没有步骤——点「+ 添加一步」开始编排。
              </div>
            ) : (
              <div className="space-y-1.5">
                {rows.map((r) => (
                  <div key={r.id} className="panel bg-surface-2/40 p-2.5">
                    <div className="flex flex-wrap items-end gap-1.5">
                      {field("时间 at（秒）", (
                        <input
                          className={`${ctrl} w-20`}
                          type="number"
                          min="0.1"
                          step="0.1"
                          placeholder="10"
                          value={r.at}
                          onChange={(e) => patchRow(r.id, { at: e.target.value })}
                        />
                      ))}
                      {field("动作", (
                        <select
                          className={`select !py-1.5 !px-2 text-[12px] w-24`}
                          value={r.action}
                          onChange={(e) =>
                            patchRow(r.id, {
                              action: e.target.value as Row["action"],
                              level: e.target.value === "recover" ? "" : r.level,
                              expect: e.target.value === "recover" ? "" : r.expect,
                            })
                          }
                        >
                          <option value="inject">inject（注入）</option>
                          <option value="recover">recover（恢复）</option>
                        </select>
                      ))}
                      {field("故障", (
                        <select
                          className={`select !py-1.5 !px-2 text-[12px] w-56`}
                          value={r.fault}
                          onChange={(e) => pickFault(r.id, e.target.value)}
                        >
                          <option value="">（选故障）</option>
                          {faultOpts.map((f) => (
                            <option key={f.key} value={f.key}>
                              {f.name} {f.key}
                            </option>
                          ))}
                          {r.fault && !faults.some((f) => f.key === r.fault) && <option value={r.fault}>{r.fault}</option>}
                        </select>
                      ))}
                      {actionOf(r.id) === "inject" && (
                        <>
                          {field("节点", (
                            <select
                              className="select !py-1.5 !px-2 text-[12px] w-20"
                              value={r.node}
                              onChange={(e) => patchRow(r.id, { node: e.target.value })}
                            >
                              {NODES.map((n) => (
                                <option key={n} value={n}>
                                  {n}
                                </option>
                              ))}
                            </select>
                          ))}
                          {field("等级（可选）", (
                            <select
                              className="select !py-1.5 !px-2 text-[12px] w-24"
                              value={r.level}
                              onChange={(e) => patchRow(r.id, { level: e.target.value })}
                            >
                              <option value="">（选填）</option>
                              {LEVELS.map((l) => (
                                <option key={l} value={l}>
                                  {l}
                                </option>
                              ))}
                            </select>
                          ))}
                          {field("期望处置（可选）", (
                            <select
                              className="select !py-1.5 !px-2 text-[12px] w-32"
                              value={r.expect}
                              onChange={(e) => patchRow(r.id, { expect: e.target.value })}
                            >
                              <option value="">（选填）</option>
                              {EXPECTS.map((x) => (
                                <option key={x} value={x}>
                                  {x}
                                </option>
                              ))}
                            </select>
                          ))}
                          {field("影响说明（可选）", (
                            <input
                              className={`${ctrl} min-w-40 flex-1`}
                              placeholder="中文描述该故障的影响…"
                              value={r.impact}
                              onChange={(e) => patchRow(r.id, { impact: e.target.value })}
                            />
                          ))}
                        </>
                      )}
                      <button
                        className="btn-ghost btn-sm !px-2 shrink-0"
                        title="删除此步"
                        onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                      >
                        ✕
                      </button>
                    </div>
                    {r.err && <div className="text-[11px] text-bad mt-1">⚠ {r.err}</div>}
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-0.5">
              <button
                className="btn-ghost btn-sm"
                onClick={() => setRows((rs) => [...rs, { id: nextId(), at: "", action: "inject", fault: "", node: "vcu", level: "", expect: "", impact: "", err: "" }])}
              >
                + 添加一步
              </button>
              <button className="btn btn-sm justify-center" onClick={runCustom} disabled={phase === "running" || !engineOk}>
                {phase === "running" ? "执行中…" : "▶ 执行这个自定义场景"}
              </button>
              {!engineOk && <span className="text-[11px] text-warn">需要先启用 TCMS 引擎（见下方说明）</span>}
            </div>
            <p className="text-[10px] text-ink-faint">
              步骤按时间先后执行：inject 注入故障并断言期望处置，recover 恢复故障。恢复（recover）步骤需要指定要恢复的故障。
            </p>
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
