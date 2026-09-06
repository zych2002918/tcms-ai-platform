import { useEffect, useMemo, useRef, useState } from "react";
import { api, type KbNode, type KbSearchHit, type KbSubgraph } from "../api";

// 节点类型 → 颜色
const KIND_COLOR: Record<string, string> = {
  message: "#38bdf8",
  signal: "#a78bfa",
  device: "#f472b6",
  fault: "#f87171",
  scenario: "#fbbf24",
  requirement: "#34d399",
  function: "#22d3ee",
  run: "#94a3b8",
};

interface Pos {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export function GraphWorkspace() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KbSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [sub, setSub] = useState<KbSubgraph | null>(null);
  const [seedLabel, setSeedLabel] = useState("");
  const [selNode, setSelNode] = useState<{ id: string; kind: string; label: string; props?: Record<string, unknown>; neighbors?: KbNode[] } | null>(null);
  const [kindFilter, setKindFilter] = useState("");
  const [allNodes, setAllNodes] = useState<KbNode[]>([]);
  const [err, setErr] = useState("");

  const loadAll = async () => {
    try {
      const n = await api.kbNodes(kindFilter || undefined, undefined);
      setAllNodes(n);
    } catch (e) {
      setErr(String(e));
    }
  };
  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindFilter]);

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setErr("");
    try {
      const r = await api.kbSearch(query, 6);
      setHits(r.hits);
      setSelNode(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSearching(false);
    }
  };

  const focus = async (seedId: string) => {
    setErr("");
    try {
      const r = await api.kbSubgraph(seedId, 2);
      setSub(r);
      setHits(null);
      setSeedLabel(r.nodes.find((n) => n.id === seedId)?.label ?? seedId);
      setSelNode(null);
    } catch (e) {
      setErr(String(e));
    }
  };

  const openNode = async (id: string) => {
    try {
      const n = await api.kbNode(id);
      setSelNode(n);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <h1 className="page-title">知识图谱</h1>
      <p className="page-sub">
        TCMS 领域知识：信号 → 报文 → 设备 → 被测功能 → 安全需求 → 故障 → 场景。
        语义检索返回「证据链」——命中文档 + 图谱邻接。
      </p>

      <div className="card">
        <div className="toolbar">
          <input
            type="text"
            placeholder="问：如「车门故障 不能发车」「紧急制动执行失败」"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            style={{ flex: 1, minWidth: 280 }}
          />
          <button onClick={search} disabled={searching || !query.trim()}>
            {searching ? "检索中…" : "🔍 GraphRAG 检索"}
          </button>
          <span className="muted">或点下方实体聚焦图谱</span>
        </div>
        <select
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          style={{ marginBottom: 8 }}
        >
          <option value="">全部类型</option>
          {Object.entries(KIND_COLOR).map(([k]) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 120, overflowY: "auto" }}>
          {allNodes.slice(0, 300).map((n) => (
            <span
              key={n.id}
              className="pill"
              style={{ cursor: "pointer", borderColor: KIND_COLOR[n.kind] }}
              title={n.id}
              onClick={() => focus(n.id)}
            >
              {n.label}
            </span>
          ))}
        </div>
        {err && <div className="err">⚠ {err}</div>}
      </div>

      {hits && (
        <div className="card">
          <h3>检索结果（语义命中 + 图谱证据）</h3>
          {hits.map((h) => (
            <div
              key={h.doc_id}
              style={{
                padding: "10px 0",
                borderBottom: "1px solid var(--border)",
                cursor: "pointer",
              }}
              onClick={() => focus(h.doc_id)}
            >
              <div>
                <span className="pill" style={{ borderColor: KIND_COLOR[h.kind] }}>
                  {h.kind}
                </span>
                <code>{h.doc_id}</code>
                <span className="muted"> · score {h.score}</span>
              </div>
              <div className="muted" style={{ margin: "4px 0", fontSize: 12 }}>
                {h.text.slice(0, 220)}
                {h.text.length > 220 ? "…" : ""}
              </div>
              {h.graph_neighbors.length > 0 && (
                <div>
                  {h.graph_neighbors.slice(0, 6).map((nb) => (
                    <span key={nb.id} className="pill" style={{ borderColor: KIND_COLOR[nb.kind] }}>
                      {nb.via} → {nb.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {sub && (
        <>
          <div className="card">
            <h3>
              图谱 · {seedLabel}{" "}
              <span className="muted">
                （{sub.node_count} 节点 / {sub.edges.length} 边 · 深度 {sub.depth}）
              </span>
            </h3>
            <GraphCanvas sub={sub} onNodeClick={(id) => openNode(id)} />
          </div>
          <div className="muted" style={{ marginBottom: 14 }}>
            💡 点击节点查看邻接详情；双击语义结果可重新聚焦。
          </div>
        </>
      )}

      {selNode && (
        <div className="card">
          <h3>
            <span className="pill" style={{ borderColor: KIND_COLOR[selNode.kind] }}>
              {selNode.kind}
            </span>{" "}
            {selNode.label}
          </h3>
          <div className="muted mono" style={{ marginBottom: 8 }}>
            {selNode.id}
          </div>
          {selNode.props && Object.keys(selNode.props).length > 0 && (
            <table style={{ marginBottom: 10 }}>
              <tbody>
                {Object.entries(selNode.props).map(([k, v]) => (
                  <tr key={k}>
                    <td className="muted">{k}</td>
                    <td>{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {selNode.neighbors && selNode.neighbors.length > 0 && (
            <>
              <div className="muted" style={{ marginBottom: 6 }}>
                邻接（{selNode.neighbors.length}）
              </div>
              <div>
                {selNode.neighbors.map((nb) => (
                  <span
                    key={nb.id}
                    className="pill"
                    style={{ cursor: "pointer", borderColor: KIND_COLOR[nb.kind] }}
                    onClick={() => focus(nb.id)}
                  >
                    {nb.label}
                  </span>
                ))}
              </div>
            </>
          )}
          <div className="toolbar" style={{ marginTop: 12 }}>
            <button className="ghost" onClick={() => setSelNode(null)}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 简易力导向 SVG 图（无第三方依赖）。 */
function GraphCanvas({ sub, onNodeClick }: { sub: KbSubgraph; onNodeClick: (id: string) => void }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const W = 900;
  const H = 520;

  // 稳定初始位置（按 seed 半径 + 环形散布）
  const initPos = useMemo(() => {
    const map = new Map<string, Pos>();
    const nodes = sub.nodes;
    const cx = W / 2;
    const cy = H / 2;
    nodes.forEach((n, i) => {
      // seed 居中，其余环形
      if (n.id === sub.seed) {
        map.set(n.id, { x: cx, y: cy, vx: 0, vy: 0 });
        return;
      }
      const ang = (i / Math.max(nodes.length - 1, 1)) * Math.PI * 2;
      const r = 130 + (i % 3) * 60;
      map.set(n.id, { x: cx + Math.cos(ang) * r, y: cy + Math.sin(ang) * r, vx: 0, vy: 0 });
    });
    return map;
  }, [sub]);

  // 简单力导向迭代（单次静态布局，够用）
  const layout = useMemo(() => {
    const pos = new Map(initPos);
    const nodes = sub.nodes;
    const links = sub.edges;
    const rep = 9000;
    const attr = 0.06;
    const k = 140;
    for (let iter = 0; iter < 220; iter++) {
      const forces = new Map<string, { fx: number; fy: number }>();
      nodes.forEach((n) => forces.set(n.id, { fx: 0, fy: 0 }));
      // repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos.get(nodes[i].id)!;
          const b = pos.get(nodes[j].id)!;
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) {
            dx = (Math.random() - 0.5) * 2;
            dy = (Math.random() - 0.5) * 2;
            d2 = dx * dx + dy * dy;
          }
          const d = Math.sqrt(d2);
          const f = rep / d2;
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          forces.get(nodes[i].id)!.fx += fx;
          forces.get(nodes[i].id)!.fy += fy;
          forces.get(nodes[j].id)!.fx -= fx;
          forces.get(nodes[j].id)!.fy -= fy;
        }
      }
      // springs
      links.forEach((l) => {
        const a = pos.get(l.src);
        const b = pos.get(l.dst);
        if (!a || !b) return;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (dist - k) * attr;
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        forces.get(l.src)!.fx += fx;
        forces.get(l.src)!.fy += fy;
        forces.get(l.dst)!.fx -= fx;
        forces.get(l.dst)!.fy -= fy;
      });
      // center gravity + apply
      nodes.forEach((n) => {
        const p = pos.get(n.id)!;
        p.x += (W / 2 - p.x) * 0.01;
        p.y += (H / 2 - p.y) * 0.01;
        p.x += forces.get(n.id)!.fx;
        p.y += forces.get(n.id)!.fy;
        p.x = Math.max(30, Math.min(W - 30, p.x));
        p.y = Math.max(30, Math.min(H - 30, p.y));
      });
    }
    return pos;
  }, [initPos, sub]);

  void svgRef;
  const labelText = (label: string) => (label.length > 16 ? label.slice(0, 15) + "…" : label);

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ background: "#0e1830", borderRadius: 8 }}>
      {/* edges */}
      {sub.edges.map((e, i) => {
        const a = layout.get(e.src);
        const b = layout.get(e.dst);
        if (!a || !b) return null;
        return (
          <g key={i}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#2c3d5e" strokeWidth={1.2} />
            <text
              x={(a.x + b.x) / 2}
              y={(a.y + b.y) / 2 - 4}
              fill="#5b6d8c"
              fontSize={9}
              textAnchor="middle"
            >
              {e.kind}
            </text>
          </g>
        );
      })}
      {/* nodes */}
      {sub.nodes.map((n) => {
        const p = layout.get(n.id);
        if (!p) return null;
        const isSeed = n.id === sub.seed;
        const color = KIND_COLOR[n.kind] ?? "#94a3b8";
        return (
          <g
            key={n.id}
            transform={`translate(${p.x},${p.y})`}
            style={{ cursor: "pointer" }}
            onClick={() => onNodeClick(n.id)}
          >
            <circle r={isSeed ? 15 : 10} fill={color} opacity={isSeed ? 1 : 0.9} stroke="#0b1220" strokeWidth={2} />
            <text y={isSeed ? 30 : 24} fill="#dbe6f5" fontSize={isSeed ? 12 : 10.5} textAnchor="middle" style={{ pointerEvents: "none" }}>
              {labelText(n.label)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
