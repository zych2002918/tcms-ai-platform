import { useEffect, useState } from "react";
import {
  api,
  type FaultInfo,
  type FunctionInfo,
  type MessageInfo,
  type RequirementRow,
  type SignalInfo,
} from "../api";

const LEVEL_CLASS: Record<string, string> = {
  info: "level-info",
  minor: "level-minor",
  major: "level-major",
  critical: "level-critical",
};

type Tab = "messages" | "signals" | "faults" | "functions" | "requirements";

export function AssetsPage() {
  const [tab, setTab] = useState<Tab>("messages");
  const [messages, setMessages] = useState<MessageInfo[]>([]);
  const [signals, setSignals] = useState<SignalInfo[]>([]);
  const [faults, setFaults] = useState<FaultInfo[]>([]);
  const [functions, setFunctions] = useState<FunctionInfo[]>([]);
  const [reqs, setReqs] = useState<RequirementRow[]>([]);
  const [selFault, setSelFault] = useState<FaultInfo | null>(null);
  const [selMsg, setSelMsg] = useState<{ name: string; frame_id: string; node: string; cycle_ms: number | null; send_type: string; signals: SignalInfo[] } | null>(null);

  useEffect(() => {
    api.messages().then(setMessages).catch(() => undefined);
    api.signals().then(setSignals).catch(() => undefined);
    api.faults().then(setFaults).catch(() => undefined);
    api.functions().then(setFunctions).catch(() => undefined);
    api.requirements().then(setReqs).catch(() => undefined);
  }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: "messages", label: `报文 ${messages.length}` },
    { id: "signals", label: `信号 ${signals.length}` },
    { id: "faults", label: `故障 ${faults.length}` },
    { id: "functions", label: `功能 ${functions.length}` },
    { id: "requirements", label: `需求 ${reqs.length}` },
  ];

  return (
    <div>
      <h1 className="page-title">测试资产</h1>
      <p className="page-sub">列车视角的真实资产：从 DBC / FMEA / 场景 / RTM 派生。</p>

      <div className="toolbar">
        {tabs.map((t) => (
          <button key={t.id} className={tab === t.id ? "" : "ghost"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "messages" && (
        <div className="card">
          <h3>报文列表（双击行查看图谱邻接）</h3>
          <table>
            <thead>
              <tr>
                <th>报文</th>
                <th>ID</th>
                <th>节点</th>
                <th>周期</th>
                <th>类型</th>
                <th>信号</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((m) => (
                <tr
                  key={m.name}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    api.kbNode(`message:${m.name}`).then((n) => {
                      setSelMsg({
                        name: m.name,
                        frame_id: m.frame_id,
                        node: m.node,
                        cycle_ms: m.cycle_ms,
                        send_type: m.send_type,
                        signals: n.neighbors
                          .filter((x) => x.kind === "signal")
                          .map((x) => ({ name: x.label, message: m.name, unit: "", choices: [] })),
                      });
                    });
                  }}
                >
                  <td style={{ fontWeight: 600 }}>{m.name}</td>
                  <td className="mono">{m.frame_id}</td>
                  <td>{m.node}</td>
                  <td>{m.cycle_ms ? `${m.cycle_ms}ms` : "event"}</td>
                  <td>{m.send_type}</td>
                  <td className="muted">{m.signals.slice(0, 5).join(", ")}{m.signals.length > 5 ? "…" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selMsg && (
        <div className="card">
          <h3>
            {selMsg.name} <span className="muted mono">{selMsg.frame_id}</span>
          </h3>
          <div className="muted" style={{ marginBottom: 8 }}>
            节点 {selMsg.node} · 周期 {selMsg.cycle_ms ? `${selMsg.cycle_ms}ms` : "事件"} · {selMsg.send_type}
          </div>
          <div>
            {selMsg.signals.length === 0 && <span className="muted">（无信号邻接，点其他报文试试）</span>}
            {selMsg.signals.map((s) => (
              <span key={s.name} className="pill">
                ⚡ {s.name}
              </span>
            ))}
          </div>
          <div className="toolbar" style={{ marginTop: 10 }}>
            <button className="ghost" onClick={() => setSelMsg(null)}>
              关闭
            </button>
          </div>
        </div>
      )}

      {tab === "signals" && (
        <div className="card">
          <h3>信号列表（含枚举）</h3>
          <table>
            <thead>
              <tr>
                <th>信号</th>
                <th>报文</th>
                <th>单位</th>
                <th>取值</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.name}>
                  <td style={{ fontWeight: 600 }}>{s.name}</td>
                  <td>{s.message}</td>
                  <td>{s.unit || "–"}</td>
                  <td className="muted">
                    {s.choices.length > 0
                      ? s.choices.map((c) => `${c.value}=${c.label}`).join(" · ")
                      : "数值"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "faults" && (
        <div className="grid grid-2">
          <div className="card">
            <h3>故障字典（FMEA）</h3>
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>名称</th>
                  <th>等级</th>
                  <th>处置</th>
                </tr>
              </thead>
              <tbody>
                {faults.map((f) => (
                  <tr key={f.key} style={{ cursor: "pointer" }} onClick={() => setSelFault(f)}>
                    <td className="mono muted">{f.fid}</td>
                    <td style={{ fontWeight: 600 }}>{f.name}</td>
                    <td>
                      <span className={`pill ${LEVEL_CLASS[f.level] ?? ""}`}>{f.level}</span>
                    </td>
                    <td className="mono muted">{f.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selFault && (
            <div className="card">
              <h3>
                {selFault.fid} · {selFault.name}
              </h3>
              <p>{selFault.desc}</p>
              <table>
                <tbody>
                  <tr>
                    <td className="muted">子系统</td>
                    <td>{selFault.subsystem}</td>
                    <td className="muted">注入层</td>
                    <td>{selFault.layer}</td>
                  </tr>
                  <tr>
                    <td className="muted">等级</td>
                    <td>{selFault.level}</td>
                    <td className="muted">SIL</td>
                    <td>{selFault.sil}</td>
                  </tr>
                  <tr>
                    <td className="muted">处置</td>
                    <td colSpan={3}>{selFault.action}</td>
                  </tr>
                  <tr>
                    <td className="muted">检测</td>
                    <td colSpan={3}>{selFault.detect}</td>
                  </tr>
                  <tr>
                    <td className="muted">注入</td>
                    <td colSpan={3}>{selFault.inject}</td>
                  </tr>
                  <tr>
                    <td className="muted">恢复</td>
                    <td colSpan={3}>{selFault.recovery}</td>
                  </tr>
                </tbody>
              </table>
              <div className="toolbar" style={{ marginTop: 12 }}>
                <button className="ghost" onClick={() => setSelFault(null)}>
                  关闭
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "functions" && (
        <div className="card">
          <h3>被测功能（列车视角聚合）</h3>
          {functions.map((f) => (
            <div key={f.fid} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: "1px solid var(--border)" }}>
              <div style={{ fontWeight: 700 }}>
                <code>{f.fid}</code> {f.name}
              </div>
              <div className="muted" style={{ margin: "4px 0" }}>
                {f.description}
              </div>
              <div>
                {f.messages.map((m) => (
                  <span key={m} className="pill">
                    📨 {m}
                  </span>
                ))}
                {f.signals.map((s) => (
                  <span key={s} className="pill">
                    ⚡ {s}
                  </span>
                ))}
                {f.fault_keys.map((k) => (
                  <span key={k} className="pill warn">
                    ⚠ {k}
                  </span>
                ))}
                {f.requirements.map((r) => (
                  <span key={r} className="pill good">
                    ☑ {r}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "requirements" && (
        <div className="card">
          <h3>需求追溯矩阵（RTM）</h3>
          <table>
            <thead>
              <tr>
                <th>需求</th>
                <th>实现模块</th>
                <th>验证用例</th>
                <th>覆盖行为</th>
              </tr>
            </thead>
            <tbody>
              {reqs.flatMap((r) =>
                r.rows.map((row, i) => (
                  <tr key={`${r.req_id}-${i}`}>
                    <td>
                      <code>{r.req_id}</code>
                    </td>
                    <td className="mono muted">{row.module}</td>
                    <td className="mono muted">{row.test_file}</td>
                    <td>{row.verifies}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
