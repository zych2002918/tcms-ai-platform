import { useCallback, useEffect, useState } from "react";
import { api, type SettingsView } from "../api";
import { Panel, Tag, EmptyState, StatusDot } from "../components/ui";

type Sys = {
  engine: { ok: boolean; version?: string; reason?: string };
  llm_key: boolean;
  agent_backend?: string;
  asset_mode: string;
};

const STEP_LABELS = ["① 资产源", "② 接入 AI（可选）", "③ 检查引擎", "④ 完成"];

export function SettingsPage() {
  const [st, setSt] = useState<SettingsView | null>(null);
  const [sys, setSys] = useState<Sys | null>(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [okMsg, setOkMsg] = useState("");
  const [step, setStep] = useState(0); // 向导步
  // LLM 表单
  const [provider, setProvider] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  // 资产目录
  const [assetDir, setAssetDir] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, sy] = await Promise.all([api.settingsGet(), api.systemStatus()]);
      setSt(s);
      setSys(sy);
      setProvider(s.llm.provider || "");
      setBaseUrl(s.llm.base_url || "");
      setModel(s.llm.model || "");
      setAssetDir(s.asset_dir || "");
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 选择 provider 预设时填充 base_url/model
  const pickProvider = (p: string) => {
    setProvider(p);
    if (st?.providers?.[p]) {
      setBaseUrl(st.providers[p].base_url || "");
      setModel(st.providers[p].model || "");
    }
  };

  const saveLlm = async () => {
    setSaving(true);
    setErr("");
    setOkMsg("");
    try {
      const patch: Record<string, string | boolean> = {
        llm_provider: provider,
        llm_base_url: baseUrl,
        llm_model: model,
      };
      // 只在新填 key 时提交（避免每次清掉已存 key）
      if (apiKey.trim()) patch.llm_api_key = apiKey.trim();
      const s = await api.settingsSave(patch);
      setSt(s);
      setApiKey("");
      setOkMsg("AI 配置已保存到本机（key 只存本地文件，不会上传/入库）");
    } catch (e) {
      setErr(String(e as Error).slice(0, 200));
    } finally {
      setSaving(false);
    }
  };

  const saveAsset = async (dir: string) => {
    setSaving(true);
    setErr("");
    setOkMsg("");
    try {
      const s = await api.settingsSave({ asset_dir: dir });
      setSt(s);
      setOkMsg("资产目录设置已保存。重启服务后生效（当前页面数据仍来自原资产源）。");
    } catch (e) {
      setErr(String(e as Error).slice(0, 200));
    } finally {
      setSaving(false);
    }
  };

  const finishOnboarding = async () => {
    setSaving(true);
    try {
      const s = await api.settingsSave({ onboarding_done: true });
      setSt(s);
      setOkMsg("引导完成！你已经可以开始使用了。");
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  };

  const engineOk = sys?.engine.ok ?? true;
  const llmReady = sys?.llm_key ?? false;
  const hasAssetCustom = Boolean(st?.asset_dir);

  return (
    <div className="space-y-4 max-w-[1100px]">
      {/* 顶部状态行 */}
      {st && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12px] text-ink-dim">
          <span>
            <StatusDot tone={engineOk ? "ok" : "warn"} pulse={!engineOk} /> 引擎 {engineOk ? `v${sys?.engine.version ?? ""}` : "未启用"}
          </span>
          <span>
            <StatusDot tone={llmReady ? "ok" : "info"} /> AI 后端 {llmReady ? "LLM" : "Mock（离线）"}
          </span>
          <span className="text-ink-faint">
            设置目录：<code className="kbd-mono">{st.dir}</code>
          </span>
        </div>
      )}

      {err && <div className="panel border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">⚠ {err}</div>}
      {okMsg && <div className="panel border-ok/40 bg-ok/10 px-4 py-2.5 text-sm text-ok">✓ {okMsg}</div>}

      {/* ============ 新手引导向导 ============ */}
      <Panel
        title="新手引导（按顺序走一遍即可上手）"
        right={st?.onboarding_done ? <Tag tone="ok">已完成</Tag> : <Tag tone="warn">未完成</Tag>}
        bodyClass="p-4"
      >
        {/* 步骤条 */}
        <div className="flex flex-wrap items-center gap-1 mb-4">
          {STEP_LABELS.map((l, i) => (
            <span key={l} className="flex items-center gap-1">
              {i > 0 && <span className="text-ink-faint mx-0.5 text-xs">→</span>}
              <button
                onClick={() => setStep(i)}
                className={`rounded-full px-2.5 py-1 text-xs border transition-colors ${
                  step === i ? "text-ink border-info/50 bg-info/10" : i < step ? "text-ok border-ok/30 bg-ok/5" : "text-ink-faint border-line"
                }`}
              >
                {i < step && <span className="text-ok">✓ </span>}
                {l}
              </button>
            </span>
          ))}
        </div>

        {/* 第 0 步：资产源 */}
        {step === 0 && (
          <div className="space-y-3">
            <div className="text-[13px] leading-6">
              平台的测试资产（报文 / 故障 / 场景 / 需求）来自 <b className="text-ink">TCMS 引擎目录</b>。
              <div className="text-ink-dim text-[12px] mt-1">
                当前模式：<code className="kbd-mono">{sys?.asset_mode ?? "…"}</code>
                {!hasAssetCustom && "（内置快照，可直接开始）"}
              </div>
            </div>
            <div className="panel bg-surface-2/40 p-3 space-y-2">
              <div className="text-[12px] text-ink-dim">
                想用自己的实际数据？（例如：往 tcms-can-test 的 <code className="kbd-mono">tcms/faults.yaml</code> 加故障、往
                <code className="kbd-mono">scenarios/</code> 加场景）——把你的 tcms-can-test 目录路径填到下面：
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  className="input flex-1 font-mono text-[12px]"
                  placeholder="如 D:\my-tcms\tcms-can-test"
                  value={assetDir}
                  onChange={(e) => setAssetDir(e.target.value)}
                />
                <button className="btn btn-sm justify-center" onClick={() => saveAsset(assetDir)} disabled={saving}>
                  保存资产目录
                </button>
              </div>
              {hasAssetCustom && (
                <div className="text-[11px] text-warn">
                  ⚠ 已设置自定义目录（重启后生效）。想回到内置快照？清空输入框后点「保存」。
                </div>
              )}
            </div>
            <div className="flex justify-end">
              <button className="btn" onClick={() => setStep(1)}>下一步：接入 AI →</button>
            </div>
          </div>
        )}

        {/* 第 1 步：LLM / API */}
        {step === 1 && (
          <div className="space-y-3">
            <div className="text-[13px] leading-6">
              想让 Agent 用<b className="text-ink">真 LLM 做规划决策</b>（而非离线规则）？填一个 OpenAI 兼容的 API。
              <div className="text-ink-dim text-[12px] mt-0.5">
                不填也能用：Agent 自动走离线 Mock，全流程可演示、不花钱。
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-ink-faint">服务商（选预设自动填 base_url/model）
                <select className="select w-full mt-1" value={provider} onChange={(e) => pickProvider(e.target.value)}>
                  <option value="">（自定义）</option>
                  {st?.providers &&
                    Object.entries(st.providers).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v.label}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-[11px] text-ink-faint">API Key
                <input
                  className="input mt-1 font-mono"
                  type={showKey ? "text" : "password"}
                  placeholder={st?.llm.has_key ? "已保存（留空保持不变）" : "sk-…"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </label>
              <label className="text-[11px] text-ink-faint">Base URL
                <input className="input mt-1 font-mono text-[12px]" placeholder="https://…/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
              </label>
              <label className="text-[11px] text-ink-faint">模型名
                <input className="input mt-1 font-mono" placeholder="deepseek-v3.2 / deepseek-chat / …" value={model} onChange={(e) => setModel(e.target.value)} />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn btn-sm" onClick={saveLlm} disabled={saving}>保存 AI 配置</button>
              <label className="flex items-center gap-1.5 text-[11px] text-ink-faint cursor-pointer">
                <input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} /> 显示 key
              </label>
              {st?.llm.has_key && (
                <button className="btn-ghost btn-sm" onClick={async () => { await api.settingsClearApiKey().then(setSt); setOkMsg("已清除本机保存的 API key"); }} disabled={saving}>
                  清除已存 key
                </button>
              )}
              <span className="ml-auto text-[10px] text-ink-faint">key 只写入本机 ~/.tcms-ai-platform/settings.json，绝不上传/入库</span>
            </div>
            <div className="flex justify-between">
              <button className="btn-ghost" onClick={() => setStep(0)}>← 上一步</button>
              <button className="btn" onClick={() => setStep(2)}>下一步：检查引擎 →</button>
            </div>
          </div>
        )}

        {/* 第 2 步：引擎检查 */}
        {step === 2 && (
          <div className="space-y-3">
            <div className="text-[13px] leading-6">
              场景真实执行 / Agent 需要 <b className="text-ink">TCMS 引擎</b>（tcms-can-test）。
            </div>
            <div className="panel bg-surface-2/40 p-3 space-y-1.5 text-[13px]">
              <div className="flex items-center gap-2">
                <StatusDot tone={engineOk ? "ok" : "warn"} pulse={!engineOk} />
                TCMS 引擎：{engineOk ? `可用（v${sys?.engine.version ?? ""}）` : "不可用"}
              </div>
              <div className="flex items-center gap-2">
                <StatusDot tone={llmReady ? "ok" : "info"} />
                AI 后端：{llmReady ? "LLM（已配 key）" : "Mock（离线，可完整演示）"}
              </div>
            </div>
            {!engineOk && (
              <div className="text-[12px] text-ink-dim leading-5 panel border-warn/30 bg-warn/5 p-3">
                引擎不可用时：资产浏览、知识图谱、故障演示仍完整可用；场景执行与 Agent 会提示引导。
                <div className="mt-1.5 text-warn">启用方法：在终端跑 <code className="kbd-mono">pip install -e ".[upstream]"</code> 或把资产目录指向已安装 tcms-can-test 的路径（见第①步）。</div>
              </div>
            )}
            <div className="flex justify-between">
              <button className="btn-ghost" onClick={() => setStep(1)}>← 上一步</button>
              <button className="btn" onClick={() => setStep(3)}>下一步：完成 →</button>
            </div>
          </div>
        )}

        {/* 第 3 步：完成 */}
        {step === 3 && (
          <div className="space-y-3">
            <div className="text-[13px] leading-6">
              都设置好了。接下来你可以：
            </div>
            <div className="grid sm:grid-cols-2 gap-2 text-[12px]">
              {[
                ["▶ 故障演示", "到「故障演示」选一个真实故障，看它如何被检测与处置"],
                ["◈ 知识图谱", "用大白话问 TCMS 领域知识，看证据链"],
                ["✦ AI Agent", "给 Agent 真实任务，看它检索证据并真实执行"],
                ["▤ 测试资产", "浏览 DBC 报文 / 故障字典 / 安全需求"],
              ].map(([t, d]) => (
                <div key={t} className="panel bg-surface-2/40 px-3 py-2.5">
                  <div className="font-medium text-ink">{t}</div>
                  <div className="text-ink-dim mt-0.5">{d}</div>
                </div>
              ))}
            </div>
            <div className="flex justify-between items-center">
              <button className="btn-ghost" onClick={() => setStep(2)}>← 上一步</button>
              {!st?.onboarding_done ? (
                <button className="btn" onClick={finishOnboarding} disabled={saving}>
                  我完成了，开始使用 →
                </button>
              ) : (
                <Tag tone="ok">引导已完成</Tag>
              )}
            </div>
          </div>
        )}
      </Panel>

      {/* 高级说明：外接配置接口 */}
      <Panel title="进阶：外部可配置接口（给开发者 / 现场人员）" bodyClass="p-4">
        <div className="space-y-2 text-[12px] text-ink-dim leading-5">
          <div>所有配置都持久化在 <code className="kbd-mono">{st?.dir ?? "~/.tcms-ai-platform/settings.json"}</code>，不进仓库、不改代码：</div>
          <ul className="list-disc pl-5 space-y-1">
            <li><b className="text-ink">自定义资产 / 故障 / 场景</b>：把任意含 <code className="kbd-mono">tcms/dbc</code> + <code className="kbd-mono">faults.yaml</code> + <code className="kbd-mono">scenarios/</code> 的 tcms-can-test 目录填到资产源（加故障 = 往 faults.yaml 加条目并补对应场景）。</li>
            <li><b className="text-ink">LLM / API</b>：任意 OpenAI 兼容端点（阿里云百炼 / DeepSeek / 自建）。key 仅本机保存。</li>
            <li><b className="text-ink">环境变量</b>（可选，优先级高于设置文件）：<code className="kbd-mono">TCMS_UPSTREAM_DIR</code>、<code className="kbd-mono">DASH_API_KEY</code>、<code className="kbd-mono">LLM_BASE_URL</code>、<code className="kbd-mono">LLM_MODEL</code>、<code className="kbd-mono">PORT</code>。</li>
          </ul>
        </div>
      </Panel>

      {!st && !err && (
        <Panel><EmptyState icon="⚙" title="加载设置中…" desc="正在读取本地配置。" /></Panel>
      )}
    </div>
  );
}
