import { useEffect, useMemo, useState } from "react";
import { api, type FaultInfo, type MessageInfo, type RequirementRow, type SignalInfo } from "../api";
import { Panel, Tag, SkeletonRows, Explain, EmptyState } from "../components/ui";
import { KIND_META } from "../lib/explanations";

type Tab = "messages" | "signals" | "faults" | "requirements";

const LEVEL_TONE: Record<string, "ok" | "warn" | "bad" | "info"> = {
  info: "info",
  minor: "info",
  major: "warn",
  critical: "bad",
};

export function AssetsPage() {
  const [tab, setTab] = useState<Tab>("messages");
  const [messages, setMessages] = useState<MessageInfo[]>([]);
  const [signals, setSignals] = useState<SignalInfo[]>([]);
  const [faults, setFaults] = useState<FaultInfo[]>([]);
  const [reqs, setReqs] = useState<RequirementRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selFault, setSelFault] = useState<FaultInfo | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([api.messages(), api.signals(), api.faults(), api.requirements()])
      .then(([m, s, f, r]) => {
        setMessages(m);
        setSignals(s);
        setFaults(f);
        setReqs(r);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const tabs: { id: Tab; label: string; n: number; what: string }[] = [
    { id: "messages", label: "报文", n: messages.length, what: "设备间互发的 CAN 消息" },
    { id: "signals", label: "信号", n: signals.length, what: "报文里的数值/状态" },
    { id: "faults", label: "故障", n: faults.length, what: "可注入的异常及其处置" },
    { id: "requirements", label: "安全需求", n: reqs.length, what: "必须满足的安全要求" },
  ];

  const kw = q.trim().toLowerCase();

  // 统一关键词过滤
  const filter = (arr: unknown[], fields: string[]) =>
    !kw
      ? arr
      : arr.filter((row) => fields.some((f) => String((row as Record<string, unknown>)[f] ?? "").toLowerCase().includes(kw)));

  const filteredMessages = useMemo(() => filter(messages, ["name", "node", "send_type"]) as MessageInfo[], [messages, kw]);
  const filteredSignals = useMemo(() => filter(signals, ["name", "message", "unit"]) as SignalInfo[], [signals, kw]);
  const filteredFaults = useMemo(() => filter(faults, ["fid", "key", "name", "subsystem", "action"]) as FaultInfo[], [faults, kw]);

  return (
    <div className="space-y-4 max-w-[1200px]">
      {/* 类型切换 = 左对齐 tab 组 */}
      <div className="flex items-center gap-1 border-b border-line-soft overflow-x-auto pb-0">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3.5 py-2 text-[13px] whitespace-nowrap border-b-2 transition-colors ${
              tab === t.id ? "border-info text-ink font-medium" : "border-transparent text-ink-dim hover:text-ink"
            }`}
            title={t.what}
          >
            {t.label}
            <span className="ml-1 text-[11px] text-ink-faint num">{t.n}</span>
          </button>
        ))}
        <div className="ml-auto w-56 min-w-40 pb-1">
          <input className="input !py-1.5 text-[12px]" placeholder="筛选… 如 overspeed" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      {loading ? (
        <Panel>
          <SkeletonRows rows={6} cols={4} />
        </Panel>
      ) : (
        <>
          {/* 报文 */}
          {tab === "messages" && (
            <Panel
              title="报文"
              right={<Tag tone="dim">DBC 协议库</Tag>}
              bodyClass="p-0"
            >
              <Explain text="报文 = 车上设备之间定时互发的消息。点一行可看它含哪些信号（在图谱中定位）。" />
              <div className="table-scroll mt-1">
                <table>
                  <thead>
                    <tr>
                      <th className="th">报文</th>
                      <th className="th">ID</th>
                      <th className="th">发送方</th>
                      <th className="th">周期</th>
                      <th className="th">信号数</th>
                      <th className="th">动作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredMessages.map((m) => (
                      <tr key={m.name} className="tr-hover">
                        <td className="td font-medium text-ink">{m.name}</td>
                        <td className="td kbd-mono">{m.frame_id}</td>
                        <td className="td">
                          <Tag tone="dim">{m.node}</Tag>
                        </td>
                        <td className="td num">{m.cycle_ms ? `${m.cycle_ms} ms` : <Tag tone="warn">事件</Tag>}</td>
                        <td className="td num">{m.signals.length}</td>
                        <td className="td">
                          <button className="btn-ghost btn-sm" title={`在图谱中查看 ${m.name} 的关联`} onClick={() => (window.location.href = `/graph?focus=${m.name}`)}>
                            图谱 →
                          </button>
                        </td>
                      </tr>
                    ))}
                    {filteredMessages.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <EmptyState icon="?" title="无匹配报文" desc="换个关键词试试" />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          {/* 信号 */}
          {tab === "signals" && (
            <Panel title="信号" right={<Tag tone="dim">{signals.length} 个</Tag>} bodyClass="p-0">
              <Explain text="信号 = 报文里携带的单个数值/状态。枚举型信号会列出它的取值含义（如 0=关、1=开、2=故障）。" />
              <div className="table-scroll mt-1">
                <table>
                  <thead>
                    <tr>
                      <th className="th">信号</th>
                      <th className="th">所属报文</th>
                      <th className="th">单位</th>
                      <th className="th">取值含义</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredSignals.map((s) => (
                      <tr key={s.name} className="tr-hover">
                        <td className="td font-medium text-ink">{s.name}</td>
                        <td className="td kbd-mono">{s.message}</td>
                        <td className="td">{s.unit || "—"}</td>
                        <td className="td">
                          {s.choices.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {s.choices.map((c) => (
                                <Tag key={c.value} tone="vio">
                                  {c.value}={c.label}
                                </Tag>
                              ))}
                            </div>
                          ) : (
                            <span className="text-ink-faint text-xs">数值型</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredSignals.length === 0 && (
                      <tr>
                        <td colSpan={4}>
                          <EmptyState icon="?" title="无匹配信号" desc="换个关键词试试" />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          {/* 故障 */}
          {tab === "faults" && (
            <div className="grid lg:grid-cols-5 gap-4 items-start">
              <div className="lg:col-span-3">
                <Panel title="故障字典（FMEA）" right={<Tag tone="dim">22 条 · 全部可注入</Tag>} bodyClass="p-0">
                  <Explain text="故障 = 可注入的异常。每条都规定了：什么等级（信号灯颜色）、系统该做什么处置。点一行看细节。" />
                  <div className="table-scroll mt-1">
                    <table>
                      <thead>
                        <tr>
                          <th className="th">故障</th>
                          <th className="th">子系统</th>
                          <th className="th">等级</th>
                          <th className="th">处置</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredFaults.map((f) => (
                          <tr key={f.key} className={`tr-hover cursor-pointer ${selFault?.key === f.key ? "!bg-info/5" : ""}`} onClick={() => setSelFault(f)}>
                            <td className="td">
                              <div className="font-medium text-ink">{f.name}</div>
                              <div className="kbd-mono text-[11px]">
                                {f.fid} · {f.key}
                              </div>
                            </td>
                            <td className="td">
                              <Tag tone="dim">{f.subsystem}</Tag>
                            </td>
                            <td className="td">
                              <Tag tone={LEVEL_TONE[f.level] ?? "info"}>{f.level}</Tag>
                            </td>
                            <td className="td kbd-mono">{f.action}</td>
                          </tr>
                        ))}
                        {filteredFaults.length === 0 && (
                          <tr>
                            <td colSpan={4}>
                              <EmptyState icon="?" title="无匹配故障" desc="换个关键词试试" />
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </div>
              {/* 详情侧栏 */}
              <div className="lg:col-span-2">
                {selFault ? (
                  <Panel
                    title={
                      <>
                        <Tag tone={LEVEL_TONE[selFault.level] ?? "info"}>{selFault.level}</Tag> {selFault.name}
                      </>
                    }
                    right={
                      <button className="btn-ghost btn-sm" onClick={() => setSelFault(null)}>
                        ✕
                      </button>
                    }
                  >
                    <div className="kbd-mono text-[11px] mb-2">
                      {selFault.fid} · {selFault.key}
                    </div>
                    <dl className="space-y-2 text-[13px]">
                      <div>
                        <dt className="text-ink-faint text-[11px]">描述</dt>
                        <dd className="text-ink leading-5">{selFault.desc}</dd>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <dt className="text-ink-faint text-[11px]">子系统</dt>
                          <dd>{selFault.subsystem}</dd>
                        </div>
                        <div>
                          <dt className="text-ink-faint text-[11px]">安全等级 SIL</dt>
                          <dd>
                            <Tag tone={Number(selFault.sil) >= 3 ? "bad" : Number(selFault.sil) >= 2 ? "warn" : "dim"}>
                              {selFault.sil}
                            </Tag>
                          </dd>
                        </div>
                        <div>
                          <dt className="text-ink-faint text-[11px]">处置动作</dt>
                          <dd className="kbd-mono">{selFault.action}</dd>
                        </div>
                        <div>
                          <dt className="text-ink-faint text-[11px]">注入层</dt>
                          <dd>{selFault.layer}</dd>
                        </div>
                      </div>
                      <div>
                        <dt className="text-ink-faint text-[11px]">如何检测</dt>
                        <dd className="leading-5">{selFault.detect}</dd>
                      </div>
                      <div>
                        <dt className="text-ink-faint text-[11px]">如何注入</dt>
                        <dd className="leading-5">{selFault.inject}</dd>
                      </div>
                      <div>
                        <dt className="text-ink-faint text-[11px]">如何恢复</dt>
                        <dd className="leading-5">{selFault.recovery}</dd>
                      </div>
                    </dl>
                    <div className="mt-3 flex gap-2">
                      <button className="btn btn-sm" onClick={() => (window.location.href = `/graph?focus=fault:${selFault.key}`)}>
                        在图谱中查看 →
                      </button>
                    </div>
                  </Panel>
                ) : (
                  <Panel>
                    <EmptyState icon="☝" title="点左侧任一故障" desc="这里会显示它的等级、处置、检测与恢复方式。" />
                  </Panel>
                )}
              </div>
            </div>
          )}

          {/* 需求 */}
          {tab === "requirements" && (
            <Panel title="需求追溯矩阵 (RTM)" right={<Tag tone="dim">SR-01 ~ SR-18</Tag>} bodyClass="p-0">
              <Explain text="每条安全需求都被实现模块与测试用例覆盖。这是“我测的东西有依据”的证明。" />
              <div className="table-scroll mt-1">
                <table>
                  <thead>
                    <tr>
                      <th className="th">需求</th>
                      <th className="th">实现模块</th>
                      <th className="th">验证用例</th>
                      <th className="th">覆盖的行为</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reqs.flatMap((r) =>
                      r.rows.map((row, i) => (
                        <tr key={`${r.req_id}-${i}`} className="tr-hover">
                          <td className="td">
                            <code className="kbd-mono">{r.req_id}</code>
                          </td>
                          <td className="td kbd-mono">{row.module}</td>
                          <td className="td kbd-mono">{row.test_file}</td>
                          <td className="td text-ink-dim">{row.verifies}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

// 供类型引用避免未使用告警
void KIND_META;
