import { useEffect, useState } from "react";
import { api, type Stats } from "../api";

export function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [kb, setKb] = useState<{ graph: { nodes: number; edges: number }; vector: { docs: number } } | null>(null);
  const [funcs, setFuncs] = useState<{ fid: string; name: string; description: string }[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch((e) => setErr(String(e)));
    api
      .kbStats()
      .then(setKb)
      .catch(() => undefined);
    api
      .functions()
      .then(setFuncs)
      .catch(() => undefined);
  }, []);

  return (
    <div>
      <h1 className="page-title">TCMS × AI 测试平台</h1>
      <p className="page-sub">
        列车控制软件测试平台：真实资产模型 + 知识底座（图谱/向量）+ 真实引擎执行。数据全部派生自
        tcms-can-test 上游资产，数字机器自证。
      </p>
      {err && <div className="err">⚠ {err}</div>}

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <div className="stat">
          <div className="num">{stats?.messages ?? "–"}</div>
          <div className="lbl">报文 (DBC)</div>
        </div>
        <div className="stat">
          <div className="num">{stats?.signals ?? "–"}</div>
          <div className="lbl">信号</div>
        </div>
        <div className="stat">
          <div className="num">{stats?.faults ?? "–"}</div>
          <div className="lbl">故障 (FMEA)</div>
        </div>
        <div className="stat">
          <div className="num">{stats?.scenarios ?? "–"}</div>
          <div className="lbl">场景</div>
        </div>
        <div className="stat">
          <div className="num">{stats?.req_ids ?? "–"}</div>
          <div className="lbl">安全需求 (RTM)</div>
        </div>
        <div className="stat">
          <div className="num">{stats?.functions ?? "–"}</div>
          <div className="lbl">被测功能</div>
        </div>
        <div className="stat">
          <div className="num">{kb?.graph.nodes ?? "–"}</div>
          <div className="lbl">图谱节点</div>
        </div>
        <div className="stat">
          <div className="num">{kb?.vector.docs ?? "–"}</div>
          <div className="lbl">向量语料</div>
        </div>
      </div>

      <div className="card">
        <h3>被测功能（列车视角的测试对象）</h3>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>功能</th>
              <th>描述</th>
            </tr>
          </thead>
          <tbody>
            {funcs.map((f) => (
              <tr key={f.fid}>
                <td>
                  <code>{f.fid}</code>
                </td>
                <td style={{ fontWeight: 600 }}>{f.name}</td>
                <td className="muted">{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
