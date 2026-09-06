import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type KbNode, type KbSearchHit, type KbSubgraph } from "../api";
import { Panel, Tag, SkeletonRows, EmptyState, Explain } from "../components/ui";
import { KIND_META, plainExplain } from "../lib/explanations";

/** 力导向 SVG（保持既有算法，视觉改用 token） */

export function GraphWorkspace() {
  const [params] = useSearchParams();
  const focusParam = params.get("focus");

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KbSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [sub, setSub] = useState<KbSubgraph | null>(null);
  const [seedLabel, setSeedLabel] = useState("");
  const [selNode, setSelNode] = useState<{ id: string; kind: string; label: string; props?: Record<string, unknown>; neighbors?: KbNode[] } | null>(null);
  const [err, setErr] = useState("");
  const [activeKind, setActiveKind] = useState<string>("all");
  const didFocus = useRef(false);

  const focus = useCallback(async (seedId: string) => {
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
  }, []);

  // 支持 ?focus= 直达（从总览/资产页跳入）
  useEffect(() => {
    if (focusParam && !didFocus.current) {
      didFocus.current = true;
      void focus(`function:${focusParam}`);
    }
  }, [focusParam, focus]);

  const search = async (q?: string) => {
    const text = (q ?? query).trim();
    if (!text) return;
    setSearching(true);
    setErr("");
    setSub(null);
    try {
      const r = await api.kbSearch(text, 10);
      setHits(r.hits);
      setActiveKind("all");
      setSelNode(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSearching(false);
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

  // 结果按类型分类 + 每个 kind 计数
  const grouped = useMemo(() => {
    if (!hits) return null;
    const by: Record<string, KbSearchHit[]> = {};
    for (const h of hits) {
      (by[h.kind] ??= []).push(h);
    }
    return by;
  }, [hits]);

  const order = ["fault", "message", "signal", "scenario", "requirement", "function", "device", "run"];
  const kindTabs = grouped
    ? order.filter((k) => grouped[k]?.length).map((k) => ({ kind: k, n: grouped[k]!.length }))
    : [];

  return (
    <div className="space-y-4 max-w-[1200px]">
      {/* 检索区 */}
      <Panel bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint text-sm">🔍</span>
            <input
              className="input pl-9"
              placeholder="用大白话问，如：车门故障了还能发车吗 / 紧急制动失败会怎样"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              aria-label="知识检索"
            />
          </div>
          <button className="btn justify-center sm:w-auto" onClick={() => search()} disabled={searching || !query.trim()}>
            {searching ? "检索中…" : "检索"}
          </button>
        </div>
        <Explain text="怎么读结果：每一条命中都带「它是哪种资产 + 一句话解释 + 它与谁相连」。点任意条目可展开成关系图谱。" />
      </Panel>

      {err && <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">⚠ {err}</div>}

      {/* 检索中 */}
      {searching && (
        <Panel title="正在检索领域知识…" bodyClass="py-1">
          <SkeletonRows rows={3} cols={3} />
        </Panel>
      )}

      {/* 结果（分类展示） */}
      {!searching && hits && (
        <>
          {hits.length === 0 ? (
            <Panel>
              <EmptyState
                icon="?"
                title="没找到直接匹配"
                desc="试试更口语化的问法，例如「心跳丢失」「门没关就发车」「超速」。也可点击下方类型直接浏览资产。"
              />
            </Panel>
          ) : (
            <>
              {/* 分类 tab */}
              <div className="flex flex-wrap items-center gap-1.5 px-1">
                <button
                  className={`btn-ghost btn-sm ${activeKind === "all" ? "!text-info !border-info/50" : ""}`}
                  onClick={() => setActiveKind("all")}
                >
                  全部 {hits.length}
                </button>
                {kindTabs.map(({ kind, n }) => (
                  <button
                    key={kind}
                    className={`btn-ghost btn-sm ${activeKind === kind ? "!text-info !border-info/50" : ""}`}
                    onClick={() => setActiveKind(kind)}
                  >
                    {KIND_META[kind]?.label ?? kind} {n}
                  </button>
                ))}
              </div>

              {/* 结果组 */}
              <div className="space-y-4 mt-1">
                {kindTabs
                  .filter(({ kind }) => activeKind === "all" || activeKind === kind)
                  .map(({ kind, n }) => (
                    <div key={kind}>
                      <div className="px-1 mb-1.5 flex items-baseline gap-2">
                        <span className="text-[12px] font-semibold text-ink">
                          {KIND_META[kind]?.label} <span className="text-ink-faint font-normal">({n})</span>
                        </span>
                        <span className="text-[11px] text-ink-faint">{KIND_META[kind]?.what}</span>
                      </div>
                      <div className="space-y-1.5">
                        {grouped![kind].map((h) => (
                          <div
                            key={h.doc_id}
                            className="panel panel-hover p-3 cursor-pointer step-in"
                            onClick={() => focus(h.doc_id)}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => e.key === "Enter" && focus(h.doc_id)}
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <code className="kbd-mono">{h.doc_id}</code>
                              <Tag tone={KIND_META[kind]?.color}>
                                相关度 {(h.score * 100).toFixed(0)}%
                              </Tag>
                              <span className="ml-auto text-[11px] text-ink-faint">点击查看关系图谱 →</span>
                            </div>
                            <div className="mt-1.5 text-[13px] text-ink leading-5 line-clamp-2">
                              {h.text.slice(0, 160)}
                              {h.text.length > 160 ? "…" : ""}
                            </div>
                            <Explain text={plainExplain(h.doc_id, h.text)} />
                            {h.graph_neighbors.length > 0 && (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {h.graph_neighbors.slice(0, 5).map((nb) => (
                                  <Tag key={nb.id} tone="dim" title={`${nb.via} → ${nb.label}`}>
                                    {KIND_META[nb.kind]?.label ?? nb.kind} · {nb.label}
                                  </Tag>
                                ))}
                                {h.graph_neighbors.length > 5 && (
                                  <span className="text-[11px] text-ink-faint">+{h.graph_neighbors.length - 5}</span>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </>
          )}
        </>
      )}

      {/* 图谱 */}
      {sub && (
        <>
          <Panel
            title={
              <>
                关系图谱 · <span className="text-ink">{seedLabel}</span>
              </>
            }
            right={<Tag tone="dim">{sub.node_count} 节点 / {sub.edges.length} 边</Tag>}
            bodyClass="p-0"
          >
            <GraphCanvas sub={sub} onNodeClick={openNode} />
          </Panel>
          <div className="px-1 -mt-2 text-[11px] text-ink-faint">
            说明：中心是「{seedLabel}」，向外一圈是它直接关联的资产，连线标着关系（如“发送方→”“触发”）。点节点看详情，点节点旁标签可跳转。
          </div>
        </>
      )}

      {/* 节点详情 */}
      {selNode && (
        <Panel
          title={
            <>
              <Tag tone={KIND_META[selNode.kind]?.color}>{KIND_META[selNode.kind]?.label ?? selNode.kind}</Tag>{" "}
              {selNode.label}
            </>
          }
          right={
            <button className="btn-ghost btn-sm" onClick={() => setSelNode(null)}>
              关闭
            </button>
          }
        >
          <div className="kbd-mono mb-2">{selNode.id}</div>
          {KIND_META[selNode.kind] && <Explain text={KIND_META[selNode.kind].what} />}
          {selNode.props && Object.keys(selNode.props).length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 mt-2">
              {Object.entries(selNode.props).map(([k, v]) => (
                <div key={k} className="text-xs flex gap-2">
                  <span className="text-ink-faint shrink-0">{k}</span>
                  <span className="text-ink truncate" title={String(v)}>
                    {String(v)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {selNode.neighbors && selNode.neighbors.length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] text-ink-faint mb-1.5">直接关联（{selNode.neighbors.length}）</div>
              <div className="flex flex-wrap gap-1.5">
                {selNode.neighbors.map((nb) => (
                  <Tag key={nb.id} tone={KIND_META[nb.kind]?.color} onClick={() => focus(nb.id)} title="点击跳转到该节点">
                    {nb.label}
                  </Tag>
                ))}
              </div>
            </div>
          )}
        </Panel>
      )}

      {/* 无任何操作时：提示浏览实体 */}
      {!hits && !sub && !selNode && !searching && (
        <Panel bodyClass="py-1">
          <EmptyState
            icon="◈"
            title="从这里开始检索"
            desc="上方输入框支持大白话提问。也可以先看几个高频对象找感觉："
          />
          <div className="flex flex-wrap gap-1.5 justify-center pb-3">
            {["message:DoorControl", "fault:overspeed", "function:F-EBM", "requirement:SR-01"].map((id) => (
              <Tag key={id} tone={KIND_META[id.split(":")[0]]?.color} onClick={() => focus(id)}>
                {id}
              </Tag>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

/** 力导向 SVG 图 */
function GraphCanvas({ sub, onNodeClick }: { sub: KbSubgraph; onNodeClick: (id: string) => void }) {
  const W = 900;
  const H = 480;
  const K = 150;

  const initPos = useMemo(() => {
    const map = new Map<string, { x: number; y: number; vx: number; vy: number }>();
    const nodes = sub.nodes;
    const cx = W / 2;
    const cy = H / 2;
    nodes.forEach((n, i) => {
      if (n.id === sub.seed) {
        map.set(n.id, { x: cx, y: cy, vx: 0, vy: 0 });
        return;
      }
      const ang = (i / Math.max(nodes.length - 1, 1)) * Math.PI * 2;
      const r = 120 + (i % 3) * 55;
      map.set(n.id, { x: cx + Math.cos(ang) * r, y: cy + Math.sin(ang) * r, vx: 0, vy: 0 });
    });
    return map;
  }, [sub]);

  const layout = useMemo(() => {
    const pos = new Map(initPos);
    const nodes = sub.nodes;
    const links = sub.edges;
    const rep = 9000;
    const attr = 0.06;
    for (let iter = 0; iter < 200; iter++) {
      const forces = new Map<string, { fx: number; fy: number }>();
      nodes.forEach((n) => forces.set(n.id, { fx: 0, fy: 0 }));
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
      links.forEach((l) => {
        const a = pos.get(l.src);
        const b = pos.get(l.dst);
        if (!a || !b) return;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (dist - K) * attr;
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        forces.get(l.src)!.fx += fx;
        forces.get(l.src)!.fy += fy;
        forces.get(l.dst)!.fx -= fx;
        forces.get(l.dst)!.fy -= fy;
      });
      nodes.forEach((n) => {
        const p = pos.get(n.id)!;
        p.x += (W / 2 - p.x) * 0.01;
        p.y += (H / 2 - p.y) * 0.01;
        p.x += forces.get(n.id)!.fx;
        p.y += forces.get(n.id)!.fy;
        p.x = Math.max(40, Math.min(W - 40, p.x));
        p.y = Math.max(35, Math.min(H - 35, p.y));
      });
    }
    return pos;
  }, [initPos, sub]);

  const colorOf = (kind: string): string => {
    const map: Record<string, string> = {
      message: "#4ca6ff",
      signal: "#8b7cf6",
      device: "#f472b6",
      fault: "#f4645a",
      scenario: "#f5b84c",
      requirement: "#2dd4a0",
      function: "#22d3ee",
      run: "#8ca0c0",
      // P6 领域知识节点
      mode: "#f472b6",
      state: "#f59e0b",
      interlock: "#f4645a",
      threshold: "#f5b84c",
      mechanism: "#a78bfa",
      standard: "#60a5fa",
      hazard: "#ef4444",
      concept: "#34d399",
    };
    return map[kind] ?? "#8ca0c0";
  };

  const label = (s: string) => (s.length > 15 ? s.slice(0, 14) + "…" : s);

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ background: "#0a1120", display: "block" }} role="img" aria-label="资产关系图谱">
      {sub.edges.map((e, i) => {
        const a = layout.get(e.src);
        const b = layout.get(e.dst);
        if (!a || !b) return null;
        return (
          <g key={i}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#233152" strokeWidth={1.2} />
            <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 5} fill="#5d6f8f" fontSize={9} textAnchor="middle">
              {e.kind}
            </text>
          </g>
        );
      })}
      {sub.nodes.map((n) => {
        const p = layout.get(n.id);
        if (!p) return null;
        const isSeed = n.id === sub.seed;
        return (
          <g
            key={n.id}
            transform={`translate(${p.x},${p.y})`}
            style={{ cursor: "pointer" }}
            onClick={() => onNodeClick(n.id)}
          >
            <circle
              r={isSeed ? 14 : 9}
              fill={colorOf(n.kind)}
              opacity={isSeed ? 1 : 0.9}
              stroke="#070b16"
              strokeWidth={2}
            />
            <text y={isSeed ? 28 : 22} fill="#c7d4e8" fontSize={isSeed ? 11.5 : 10} textAnchor="middle" style={{ pointerEvents: "none" }}>
              {label(n.label)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
