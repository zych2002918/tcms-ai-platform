import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type FaultLabCurvePoint, type FaultLabResp } from "../api";
import { Panel, Tag, EmptyState, SkeletonRows } from "../components/ui";

const KIND_COLOR: Record<string, string> = {
  inject: "#f5b84c",
  detect: "#4ca6ff",
  action: "#f4645a",
  recover: "#2dd4a0",
  note: "#8ca0c0",
};
const KIND_LABEL: Record<string, string> = {
  inject: "注入",
  detect: "检测",
  action: "处置",
  recover: "恢复",
  note: "说明",
};

function nearestPoint(curve: FaultLabCurvePoint[], t: number): FaultLabCurvePoint {
  let best = curve[0];
  for (const p of curve) {
    if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
  }
  return best;
}

/** 简化的列车侧视动画：车体 + 车门灯 + 轴 + 受电弓/心跳/总线状态 */
function TrainGlyph({ pt, derateSpeed }: { pt: FaultLabCurvePoint; derateSpeed: number }) {
  const moving = pt.speed_kmh > 0.5;
  const ebActive = pt.eb === 1;
  const derate = pt.action === "derate";
  const shutdown = pt.action === "shutdown";
  const alarmOn = pt.alarms.length > 0;
  return (
    <div className="relative select-none">
      {/* 车体 */}
      <svg width="100%" viewBox="0 0 520 150" style={{ display: "block", background: "#0a1120", borderRadius: 12 }} role="img" aria-label="列车状态示意">
        {/* 轨道 */}
        <line x1="0" y1="132" x2="520" y2="132" stroke="#233152" strokeWidth="3" />
        <line x1="0" y1="137" x2="520" y2="137" stroke="#1a2540" strokeWidth="1" />
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={i} x1={i * 40} y1="132" x2={i * 40 - 6} y2="137" stroke="#1a2540" strokeWidth="2" />
        ))}
        {/* 车体（含受电弓状态） */}
        <g>
          <rect x="60" y="38" width="400" height="72" rx="8" fill="#131c33" stroke={shutdown ? "#f4645a" : alarmOn ? "#f5b84c" : "#233152"} strokeWidth={2} />
          {/* 车窗 */}
          {[100, 160, 220, 280, 340, 400].map((x) => (
            <rect key={x} x={x} y="52" width="34" height="20" rx="4" fill="#0a1120" stroke="#233152" />
          ))}
          {/* 驾驶室 */}
          <path d="M60 46 q -18 6 -18 26 v 24 h 18 z" fill="#0d1424" stroke="#233152" />
          {/* 车门状态（4 门，故障=红，正常=绿） */}
          {[0, 1, 2, 3].map((i) => {
            const x = 110 + i * 80;
            const bad = pt.door_fault_count > i;
            return (
              <g key={i}>
                <rect x={x + 14} y="92" width="26" height="18" rx="3" fill={bad ? "#f4645a" : "#16203a"} stroke={bad ? "#f4645a" : "#233152"} />
                <circle cx={x + 27} cy="101" r="2.5" fill={bad ? "#fff" : "#2dd4a0"} />
              </g>
            );
          })}
          {/* 受电弓 */}
          <g>
            <line x1="340" y1="38" x2="352" y2="16" stroke="#8ca0c0" strokeWidth="3" />
            <line x1="420" y1="38" x2="408" y2="16" stroke="#8ca0c0" strokeWidth="3" />
            <line x1="352" y1="16" x2="408" y2="16" stroke="#8ca0c0" strokeWidth="3.5" />
            <line x1="430" y1="38" x2="430" y2="16" stroke="#233152" strokeWidth="3" />
            <circle cx={pt.pantograph_ok ? 380 : 430} cy="10" r="4" fill={pt.pantograph_ok ? "#2dd4a0" : "#f4645a"} />
          </g>
        </g>
        {/* 轮子 + 运动效果 */}
        {[120, 200, 320, 400].map((x) => (
          <g key={x} className={moving ? "wheel-spin" : undefined}>
            <circle cx={x} cy="122" r="11" fill="#0d1424" stroke="#233152" strokeWidth="2.5" />
            <line x1={x} y1="122" x2={x + (moving ? 7 : 0)} y2={moving ? 117 : 122} stroke="#4ca6ff" strokeWidth="2" style={{ transformOrigin: `${x}px 122px` }} />
          </g>
        ))}
        {/* 速度尾迹 */}
        {moving &&
          Array.from({ length: 4 }).map((_, i) => (
            <circle key={i} cx={48 - i * 14} cy={84 + (i % 2) * 8} r={3 - i * 0.5} fill="#4ca6ff" opacity={0.5 - i * 0.1} />
          ))}
        {/* EB 光带 */}
        {ebActive && (
          <>
            <rect x="60" y="30" width="400" height="4" rx="2" fill="#f4645a" className="pulse-glow" />
            <text x="260" y="25" textAnchor="middle" fill="#f4645a" fontSize="13" fontWeight="700">
              ⚠ 紧急制动请求
            </text>
          </>
        )}
        {derate && !ebActive && (
          <text x="260" y="25" textAnchor="middle" fill="#f5b84c" fontSize="12">
            降级运行（限速 {derateSpeed} km/h）
          </text>
        )}
      </svg>
      {/* 通道状态行 */}
      <div className="mt-2 grid grid-cols-4 gap-1.5 text-center">
        <MiniStat label="心跳" ok={pt.heartbeat_ok} text={pt.heartbeat_ok ? "正常" : "丢失"} />
        <MiniStat label="总线" ok={pt.bus_ok} text={pt.bus_ok ? "正常" : "异常"} />
        <MiniStat label="受电弓" ok={pt.pantograph_ok} text={pt.pantograph_ok ? "正常" : "故障"} />
        <MiniStat label="紧急制动" ok={pt.eb !== 1} text={pt.eb === 1 ? (pt.brake_kpa > 0 ? "已施加" : "命令未落地") : "未触发"} tone={pt.brake_kpa > 0 || pt.eb === 1 ? "bad" : "ok"} />
      </div>
    </div>
  );
}

function MiniStat({ label, ok, text, tone }: { label: string; ok?: boolean; text: string; tone?: "ok" | "bad" }) {
  const c = tone === "bad" ? "#f4645a" : tone === "ok" ? "#2dd4a0" : ok ? "#2dd4a0" : "#f4645a";
  return (
    <div className="panel px-1 py-1.5 bg-surface-2/40">
      <div className="text-[10px] text-ink-faint">{label}</div>
      <div className="text-[11px] font-semibold" style={{ color: c }}>
        {text}
      </div>
    </div>
  );
}

function Curves({ curve, t, limitKmh }: { curve: FaultLabCurvePoint[]; t: number; limitKmh: number }) {
  const W = 640;
  const H = 130;
  const maxT = curve.length ? curve[curve.length - 1].t : 1;
  const x = (tt: number) => 30 + (tt / maxT) * (W - 50);
  const ySpeed = (v: number) => H - 12 - (v / 180) * (H - 34);
  const yKpa = (v: number) => H - 12 - (v / 400) * (H - 34);
  const speedPath = curve.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${ySpeed(p.speed_kmh).toFixed(1)}`).join(" ");
  const kpaPath = curve.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${yKpa(p.brake_kpa).toFixed(1)}`).join(" ");
  const cur = nearestPoint(curve, t);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block", background: "#0a1120", borderRadius: 12 }}>
      <text x={8} y={16} fill="#8ca0c0" fontSize="10">km/h</text>
      {[0, 60, 120, 180].map((v) => (
        <g key={v}>
          <line x1="28" y1={ySpeed(v)} x2={W - 14} y2={ySpeed(v)} stroke="#1a2540" strokeWidth="0.6" />
          <text x={2} y={ySpeed(v) + 3} fill="#5d6f8f" fontSize="9">{v}</text>
        </g>
      ))}
      {/* 限速参考线（后端真实阈值） */}
      <line x1="28" y1={ySpeed(limitKmh)} x2={W - 14} y2={ySpeed(limitKmh)} stroke="#f5b84c" strokeWidth="1" strokeDasharray="4 3" />
      <text x={W - 60} y={ySpeed(limitKmh) - 3} fill="#f5b84c" fontSize="9">{limitKmh} 限速</text>
      <path d={speedPath} fill="none" stroke="#4ca6ff" strokeWidth="2" />
      <path d={kpaPath} fill="none" stroke="#2dd4a0" strokeWidth="1.6" />
      {/* 游标 */}
      <line x1={x(t)} y1="6" x2={x(t)} y2={H - 6} stroke="#e8eef9" strokeWidth="1.4" opacity="0.7" />
      <circle cx={x(t)} cy={ySpeed(cur.speed_kmh)} r="4" fill="#4ca6ff" stroke="#070b16" strokeWidth="1.5" />
      <text x={x(t) + 5} y={14} fill="#e8eef9" fontSize="10" fontWeight="700">{cur.speed_kmh.toFixed(0)} km/h</text>
    </svg>
  );
}

export function FaultLabPage() {
  const [scenarios, setScenarios] = useState<{ file: string; name: string; steps: number; fault_keys: string[] }[]>([]);
  const [sel, setSel] = useState("");
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [data, setData] = useState<FaultLabResp | null>(null);
  const [t, setT] = useState(0); // 当前回放时刻（场景秒）
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1); // 回放倍速
  const [err, setErr] = useState("");
  const rafRef = useRef<number>(0);
  const lastRef = useRef<number>(0);
  const playingRef = useRef(false);
  const tRef = useRef(0);
  playingRef.current = playing;
  tRef.current = t;

  useEffect(() => {
    api.faultlabScenarios().then((s) => {
      setScenarios(s);
      if (s.length) setSel(s[0].file);
    }).catch((e) => setErr(String(e)));
  }, []);

  // 回放主循环（rAF，按场景秒推进）
  useEffect(() => {
    const loop = (now: number) => {
      if (playingRef.current && data) {
        if (!lastRef.current) lastRef.current = now;
        const dt = (now - lastRef.current) / 1000 * speed;
        const next = Math.min(tRef.current + dt, data.demo.duration);
        setT(next);
        if (next >= data.demo.duration) {
          setPlaying(false);
        }
      }
      lastRef.current = playingRef.current ? now : 0;
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [data, speed]);

  const load = async (file: string) => {
    if (!file || phase === "loading") return;
    setPhase("loading");
    setPlaying(false);
    setErr("");
    try {
      const r = await api.faultlabDemo(file);
      setData(r);
      setT(0);
      setPhase("ready");
      // 加载即自动播放：让观众立刻看到「注入→检测→处置→恢复」的过程
      setPlaying(true);
    } catch (e) {
      setErr(String(e));
      setPhase("error");
    }
  };

  const currentPt = useMemo(() => (data ? nearestPoint(data.curve, t) : null), [data, t]);
  const activeEvents = useMemo(() => {
    if (!data) return [];
    return data.demo.events.filter((e) => Math.abs(e.t - t) < 0.4);
  }, [data, t]);

  const seek = useCallback((tt: number) => {
    setT(Math.max(0, Math.min(tt, data?.demo.duration ?? 0)));
  }, [data]);

  const dur = data?.demo.duration ?? 1;

  return (
    <div className="space-y-4 max-w-[1180px]">
      <Panel title="故障演示 · FaultLab" bodyClass="p-3">
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select className="select flex-1" value={sel} onChange={(e) => setSel(e.target.value)} aria-label="选择演示场景">
            {scenarios.map((s) => (
              <option key={s.file} value={s.file}>
                {s.name} — {s.file}
              </option>
            ))}
          </select>
          <button className="btn justify-center" onClick={() => load(sel)} disabled={phase === "loading" || !sel}>
            {phase === "loading" ? "加载中…" : "▶ 演示此场景"}
          </button>
        </div>
        <p className="mt-2 text-[11px] text-ink-faint leading-5">
          这不是花哨动效——事件时刻来自真实场景 YAML，处置结果来自真实引擎（若已执行）或故障字典；速度/压力曲线是按真实阈值
          （160 km/h 限速、300 kPa 制动缸）做的示意回放。下方每个事件都可溯源。
        </p>
      </Panel>

      {err && <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">⚠ {err}</div>}

      {phase === "loading" && (
        <Panel title="正在重建演示…" bodyClass="py-2">
          <SkeletonRows rows={3} cols={3} />
          <p className="text-[11px] text-ink-faint mt-1">装载场景 → 真实执行（若引擎可用）→ 生成事件时间线与通道曲线</p>
        </Panel>
      )}

      {phase === "error" && !err && (
        <Panel><EmptyState icon="⚠" title="演示加载失败" desc="请确认后端与引擎状态后重试。" /></Panel>
      )}

      {phase === "ready" && data && currentPt && (
        <div className="step-in space-y-4">
          {/* 顶部摘要：场景 + 断言来源 */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Tag tone="info">{data.demo.scenario_name}</Tag>
            <code className="kbd-mono">{data.demo.scenario}</code>
            <span className="text-ink-faint">总时长 {data.demo.duration}s · {data.demo.events.length} 个事件</span>
            {data.engine_asserted ? (
              <Tag tone="ok">处置已由真实引擎断言</Tag>
            ) : (
              <Tag tone="warn">引擎未启用 · 处置来自故障字典（示意）</Tag>
            )}
          </div>

          {/* 列车动画 */}
          <Panel bodyClass="p-3">
            <TrainGlyph pt={currentPt} derateSpeed={data.demo.params.derate_speed} />
          </Panel>

          {/* 速度/压力曲线 */}
          <Panel title="速度与制动缸压力（示意回放）" bodyClass="p-2">
            <Curves curve={data.curve} t={t} limitKmh={data.demo.params.limit_kmh} />
            {/* 控制条 */}
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <button className="btn-ghost btn-sm" onClick={() => { setPlaying((p) => !p); if (!playing && t >= dur) seek(0); }} disabled={!data}>
                {playing ? "⏸ 暂停" : "▶ 播放"}
              </button>
              <button className="btn-ghost btn-sm" onClick={() => { setPlaying(false); seek(0); }}>↺ 重置</button>
              <div className="flex items-center gap-1">
                {[0.5, 1, 2, 4].map((s) => (
                  <button key={s} className={`btn-ghost btn-sm ${speed === s ? "!text-info !border-info/50" : ""}`} onClick={() => setSpeed(s)}>
                    {s}×
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-ink-faint num ml-auto">{t.toFixed(1)}s / {dur.toFixed(0)}s</span>
            </div>
            {/* 时间轴 scrubber */}
            <input
              type="range"
              min={0}
              max={dur}
              step={0.1}
              value={t}
              onChange={(e) => seek(parseFloat(e.target.value))}
              className="w-full mt-2 faultlab-range"
              aria-label="回放进度"
            />
            {/* 事件刻度条 */}
            <div className="relative h-6 mt-0.5" aria-hidden>
              {data.demo.events.map((e, i) => {
                const left = (e.t / dur) * 100;
                return (
                  <span
                    key={i}
                    onClick={() => seek(e.t)}
                    className="absolute top-1/2 -translate-y-1/2 h-3.5 w-[3px] rounded-full cursor-pointer hover:scale-y-150 transition-transform"
                    style={{ left: `calc(${left}% - 1px)`, background: KIND_COLOR[e.kind] }}
                    title={`${e.t}s ${KIND_LABEL[e.kind]}：${e.label}`}
                  />
                );
              })}
              {/* 播放头 */}
              <span
                className="absolute top-0 bottom-0 w-[2px] bg-ink/70"
                style={{ left: `calc(${(t / dur) * 100}% - 1px)` }}
              />
            </div>
            <div className="flex gap-3 mt-1 flex-wrap">
              {(Object.keys(KIND_COLOR) as (keyof typeof KIND_COLOR)[]).map((k) => (
                <span key={k} className="inline-flex items-center gap-1 text-[10px] text-ink-faint">
                  <span className="h-2 w-2 rounded-sm" style={{ background: KIND_COLOR[k] }} /> {KIND_LABEL[k]}
                </span>
              ))}
            </div>
          </Panel>

          {/* 事件解释（当前时刻） */}
          <Panel title="此刻发生了什么" bodyClass="p-3">
            {activeEvents.length === 0 ? (
              <div className="text-xs text-ink-dim leading-5">
                {currentPt.action === "none" && currentPt.alarms.length === 0
                  ? "正常巡航中：车速平稳，各通道健康。拖动上方时间轴跳到事件处看故障如何发生。"
                  : `处置中：${currentPt.action}${currentPt.alarms.length ? " · 告警 " + currentPt.alarms.join("、") : ""}`}
              </div>
            ) : (
              <div className="space-y-2">
                {activeEvents.map((e, i) => (
                  <div key={i} className="flex items-start gap-2.5">
                    <Tag tone={e.kind === "inject" ? "warn" : e.kind === "action" ? "bad" : e.kind === "recover" ? "ok" : e.kind === "detect" ? "info" : "dim"}>
                      {KIND_LABEL[e.kind]}
                    </Tag>
                    <div className="flex-1 text-[12.5px] leading-5 min-w-0">
                      <span className="text-ink font-medium">{e.label}</span>
                      {e.derived && <Tag tone="dim" title="示意重建：此事件时刻/处置来源为演示标注">示意</Tag>}
                      {e.detail && <div className="text-ink-dim">{e.detail}</div>}
                    </div>
                    <span className="text-ink-faint text-[10px] num shrink-0">{e.t.toFixed(1)}s</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {/* 完整事件时间线（叙事流：一屏看清故障生命周期） */}
          <Panel title="完整事件时间线" bodyClass="p-3">
            <div className="space-y-1">
              {data.demo.events.map((e, i) => {
                const isNear = Math.abs(e.t - t) < 0.5;
                const isPast = e.t <= t;
                return (
                  <button
                    key={i}
                    onClick={() => seek(e.t)}
                    className={`w-full text-left flex items-start gap-2.5 rounded-lg px-2.5 py-1.5 transition-colors ${
                      isNear ? "bg-info/10 border border-info/30" : isPast ? "hover:bg-surface-2/60 opacity-90" : "opacity-55 hover:bg-surface-2/40"
                    }`}
                  >
                    <span className="text-ink-faint text-[10px] num pt-0.5 w-10 shrink-0">{e.t.toFixed(1)}s</span>
                    <Tag tone={e.kind === "inject" ? "warn" : e.kind === "action" ? "bad" : e.kind === "recover" ? "ok" : e.kind === "detect" ? "info" : "dim"}>
                      {KIND_LABEL[e.kind]}
                    </Tag>
                    <span className={`flex-1 text-[12.5px] leading-5 min-w-0 ${isNear ? "text-ink" : "text-ink-dim"}`}>
                      <span className={isNear ? "text-ink font-medium" : ""}>{e.label}</span>
                      {e.derived && <span className="ml-1 text-[10px] text-ink-faint">（示意）</span>}
                      {isNear && e.detail && <div className="text-ink-dim text-[11.5px]">{e.detail}</div>}
                    </span>
                  </button>
                );
              })}
            </div>
          </Panel>

          {/* 诚实标注 */}
          <div className="panel border-line bg-surface-2/30 px-4 py-2.5">
            <div className="text-[10px] text-ink-faint uppercase tracking-wide mb-0.5">诚实性标注（演示为示意，不是回放）</div>
            <p className="text-[11px] text-ink-dim leading-5">{data.honesty_note}</p>
          </div>
        </div>
      )}

      {phase === "idle" && (
        <Panel>
          <EmptyState
            icon="⚙"
            title="选一个真实故障场景，看它如何发生"
            desc="FaultLab 把真实场景 YAML 变成可播放的事件时间线：故障注入 → 检测 → 处置 → 恢复。列车状态、速度曲线、事件解释会随时间轴同步推进。"
          />
        </Panel>
      )}
    </div>
  );
}
