import { useEffect, useState } from "react";
import { api, type RunScenarioResult, type ScenarioInfo } from "../api";

export function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [sel, setSel] = useState("");
  const [running, setRunning] = useState(false);
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
  }, []);

  const run = async () => {
    if (!sel) return;
    setRunning(true);
    setErr("");
    try {
      const r = await api.runScenario(sel);
      setResult(r);
    } catch (e) {
      setErr(String(e));
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const current = scenarios.find((s) => s.file === sel);

  return (
    <div>
      <h1 className="page-title">场景执行</h1>
      <p className="page-sub">在真实上游 tcms 引擎上执行声明式故障场景（离线确定性，结果沉淀回知识库）。</p>

      <div className="card">
        <h3>选择场景</h3>
        <div className="toolbar">
          <select value={sel} onChange={(e) => setSel(e.target.value)} style={{ minWidth: 280 }}>
            {scenarios.map((s) => (
              <option key={s.file} value={s.file}>
                {s.name} ({s.file})
              </option>
            ))}
          </select>
          <button onClick={run} disabled={running || !sel}>
            {running ? "执行中…" : "▶ 执行"}
          </button>
        </div>
        {current && (
          <div className="muted">
            故障:{" "}
            {current.fault_keys.map((f) => (
              <span key={f} className="pill warn">
                {f}
              </span>
            ))}
            节点: {current.nodes.map((n) => (
              <span key={n} className="pill">
                {n}
              </span>
            ))}
          </div>
        )}
        {err && <div className="err">⚠ {err}</div>}
      </div>

      {result && (
        <>
          <div className="card">
            <h3>
              执行结果 · <code>{result.scenario}</code> · 引擎 v{result.engine_version}
              {result.run_id && <span className="muted"> · run {result.run_id}</span>}
            </h3>
            <div className="grid grid-4" style={{ marginBottom: 10 }}>
              <div className="stat">
                <div className="num">{result.passed}</div>
                <div className="lbl">通过断言</div>
              </div>
              <div className="stat">
                <div className="num" style={{ color: result.failed ? "var(--bad)" : "var(--text-dim)" }}>
                  {result.failed}
                </div>
                <div className="lbl">失败断言</div>
              </div>
              <div className="stat">
                <div className="num" style={{ color: result.all_passed ? "var(--good)" : "var(--bad)" }}>
                  {result.all_passed ? "PASS" : "FAIL"}
                </div>
                <div className="lbl">总判定</div>
              </div>
            </div>
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>故障</th>
                  <th>期望处置</th>
                  <th>实际处置</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                {result.assertions.map((a, i) => (
                  <tr key={i}>
                    <td className="mono">{a.ts}s</td>
                    <td>
                      <code>{a.fault}</code>
                    </td>
                    <td>{a.expected}</td>
                    <td>{a.actual}</td>
                    <td>
                      {a.passed ? (
                        <span className="verdict-ok">✓ PASS</span>
                      ) : (
                        <span className="verdict-bad">✗ FAIL</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
