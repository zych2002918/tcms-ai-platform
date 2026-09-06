import { useEffect, useState } from "react";
import { api, type AgentRunResp } from "../api";

export function AgentPage() {
  const [tasks, setTasks] = useState<{ task_id: string; title: string; goal: string; expected_action: string }[]>([]);
  const [sel, setSel] = useState("");
  const [running, setRunning] = useState(false);
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

  const run = async (taskId?: string) => {
    setRunning(true);
    setErr("");
    try {
      setResult(await api.agentRun(taskId));
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
  };

  const current = tasks.find((t) => t.task_id === sel);

  return (
    <div>
      <h1 className="page-title">AI Agent 工作台</h1>
      <p className="page-sub">
        给 Agent 一个真实测试任务，它自主完成：检索知识底座证据 → 选择场景 → 真实引擎执行 →
        断言验证 → 反思重试 → 汇报（轨迹全程可审计）。
      </p>

      <div className="card">
        <h3>任务库（锚定真实故障字典）</h3>
        <div className="toolbar">
          <select value={sel} onChange={(e) => setSel(e.target.value)} style={{ minWidth: 260 }}>
            {tasks.map((t) => (
              <option key={t.task_id} value={t.task_id}>
                {t.title}
              </option>
            ))}
          </select>
          <button onClick={() => run(sel || undefined)} disabled={running || !sel}>
            {running ? "执行中…" : "▶ 执行任务"}
          </button>
          <button className="ghost" onClick={() => run(undefined)} disabled={running}>
            全部执行
          </button>
        </div>
        {current && (
          <div className="muted" style={{ marginBottom: 4 }}>
            <code>{current.task_id}</code> · {current.goal}
          </div>
        )}
        {err && <div className="err">⚠ {err}</div>}
      </div>

      {result && (
        <>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <div className="stat">
              <div className="num">{result.total}</div>
              <div className="lbl">任务数</div>
            </div>
            <div className="stat">
              <div className="num">{result.achieved}</div>
              <div className="lbl">达成</div>
            </div>
            <div className="stat">
              <div className="num" style={{ color: result.success_rate >= 1 ? "var(--good)" : "var(--warn)" }}>
                {(result.success_rate * 100).toFixed(0)}%
              </div>
              <div className="lbl">成功率</div>
            </div>
          </div>

          {result.runs.map((r) => (
            <div className="card" key={r.task_id}>
              <h3>
                <code>{r.task_id}</code> · {r.fault} → {r.expected}{" "}
                {r.achieved ? <span className="verdict-ok">✓ 达成</span> : <span className="verdict-bad">✗ 未达成</span>}
                <span className="muted" style={{ fontWeight: 400 }}>
                  {" "}
                  · 评分 {r.score.score} · {r.duration_ms}ms
                  {r.reflected && " · 经反思"}
                </span>
              </h3>
              <div className="muted" style={{ marginBottom: 8 }}>
                执行场景: {r.scenario ?? "–"} · 证据 {r.score.evidence_count} 条 · 尝试 {r.attempts} 次 · 真实执行{" "}
                {r.score.exec_passed ? <span className="ok">通过</span> : "未过"}
              </div>
              <table>
                <thead>
                  <tr>
                    <th>步骤</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {r.trace.map((t, i) => (
                    <tr key={i}>
                      <td>
                        <span className="pill">{t.step}</span>
                      </td>
                      <td className="muted">{t.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
