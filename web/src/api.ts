/** 后端 API 客户端（/api 代理到 FastAPI）。 */

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

export interface Stats {
  version: string;
  source_upstream: string;
  messages: number;
  signals: number;
  devices: number;
  faults: number;
  scenarios: number;
  requirements: number;
  req_ids: number;
  functions: number;
}

export interface MessageInfo {
  name: string;
  frame_id: string;
  node: string;
  cycle_ms: number | null;
  send_type: string;
  signals: string[];
}

export interface SignalInfo {
  name: string;
  message: string;
  unit: string;
  choices: { value: number; label: string }[];
}

export interface FaultInfo {
  fid: string;
  key: string;
  name: string;
  subsystem: string;
  layer: string;
  level: string;
  action: string;
  sil: string;
  desc?: string;
  detect?: string;
  inject?: string;
  recovery?: string;
}

export interface ScenarioInfo {
  file: string;
  name: string;
  steps: number;
  fault_keys: string[];
  nodes: string[];
}

export interface FunctionInfo {
  fid: string;
  name: string;
  description: string;
  messages: string[];
  signals: string[];
  fault_keys: string[];
  requirements: string[];
}

export interface RequirementRow {
  req_id: string;
  rows: { module: string; test_file: string; verifies: string }[];
}

export interface KbNode {
  id: string;
  kind: string;
  label: string;
  props?: Record<string, unknown>;
}

export interface KbSearchHit {
  doc_id: string;
  kind: string;
  text: string;
  score: number;
  graph_neighbors: { id: string; kind: string; label: string; via: string }[];
}

export interface KbSearchResp {
  query: string;
  hits: KbSearchHit[];
}

export interface KbSubgraph {
  seed: string;
  depth: number;
  nodes: { id: string; kind: string; label: string }[];
  edges: { src: string; dst: string; kind: string }[];
  node_count: number;
}

export interface RunScenarioResult {
  scenario: string;
  steps: number;
  assertions: { fault: string; ts: number; expected: string; actual: string; passed: boolean }[];
  passed: number;
  failed: number;
  all_passed: boolean;
  engine_version: string;
  run_id?: string;
}

export interface FaultLabEvent {
  t: number;
  kind: "inject" | "detect" | "action" | "recover" | "note";
  fault: string;
  label: string;
  detail: string;
  level: string;
  action: string;
  derived: boolean;
  /** 引擎观察窗：结构化数据来源（引擎断言 / 故障字典 / 场景 YAML / 示意物理），
   *  由 faultlab 各事件 source{kind,ref,desc} 提供（t2 engine-observer 落地）。 */
  source?: { kind: string; ref: string; desc: string };
}

export interface FaultLabCurvePoint {
  t: number;
  speed_kmh: number;
  brake_kpa: number;
  eb: number;
  doors_open: number;
  door_fault_count: number;
  heartbeat_ok: boolean;
  bus_ok: boolean;
  pantograph_ok: boolean;
  soc: number;
  action: string;
  alarms: string[];
}

export interface FaultLabResp {
  demo: {
    scenario: string;
    scenario_name: string;
    faults: string[];
    steps: number;
    duration: number;
    sample_s: number;
    events: FaultLabEvent[];
    params: { limit_kmh: number; derate_speed: number; cruise_kmh: number; eb_kpa: number };
    honesty: string;
    /** 引擎真实执行的黑盒开窗（透明数据管线）：真实断言证据 + 结构/示意说明。
     *  引擎可用且真实执行时 asserted=true、version="x.y.z"；未接入引擎时
     *  asserted=false、version=null（后端 faultlab_demo 已附 engine_version）。 */
    engine?: {
      asserted: boolean;
      version: string | null;
      trace: unknown[];
      assertions: { fault: string; ts: number; expected: string; actual: string; passed: boolean }[];
      notes: string[];
    };
    /** 数据管线透明展示：demo 怎么从真实资产/引擎构建出来的可读步骤 + 真实/示意常量表。 */
    pipeline?: {
      title: string;
      steps: { name: string; desc: string; kind: string }[];
      constants?: { real?: ConstRow[]; schematic?: ConstRow[] };
    };
  };
  curve: FaultLabCurvePoint[];
  engine_asserted: boolean;
  honesty_note: string;
}

/** 数据管线常量行（pipeline.constants 条目：真实阈值/枚举 vs 示意规则）。 */
export interface ConstRow {
  name: string;
  value: string | number;
  unit: string;
  source: string;
  desc: string;
}

export const api = {
  stats: () => req<Stats>("/stats"),
  health: () => req<{ status: string; version: string }>("/health"),
  systemStatus: () =>
    req<{
      engine: { ok: boolean; version?: string; reason?: string };
      llm_key: boolean;
      asset_mode: string;
      capabilities: Record<string, boolean>;
      fix_hints: { engine: string[]; llm: string[] };
    }>("/system/status"),
  messages: () => req<MessageInfo[]>("/messages"),
  signals: () => req<SignalInfo[]>("/signals"),
  faults: () => req<FaultInfo[]>("/faults"),
  fault: (key: string) => req<FaultInfo>(`/faults/${key}`),
  scenarios: () => req<ScenarioInfo[]>("/scenarios"),
  functions: () => req<FunctionInfo[]>("/functions"),
  requirements: () => req<RequirementRow[]>("/requirements"),
  kbStats: () => req<{ graph: { nodes: number; edges: number; by_kind: Record<string, number> }; vector: { docs: number; by_kind: Record<string, number> } }>("/kb/stats"),
  kbSearch: (query: string, k = 5) =>
    req<KbSearchResp>("/kb/search", { method: "POST", body: JSON.stringify({ query, k }) }),
  kbSubgraph: (seed: string, depth = 2) =>
    req<KbSubgraph>("/kb/subgraph", { method: "POST", body: JSON.stringify({ seed, depth }) }),
  kbNodes: (kind?: string, q?: string) => {
    const p = new URLSearchParams();
    if (kind) p.set("kind", kind);
    if (q) p.set("q", q);
    const qs = p.toString();
    return req<KbNode[]>(`/kb/nodes${qs ? `?${qs}` : ""}`);
  },
  kbNode: (id: string) =>
    req<{ id: string; kind: string; label: string; props: Record<string, unknown>; neighbors: KbNode[] }>(
      `/kb/node/${encodeURIComponent(id)}`
    ),
  runScenario: (scenario: string) =>
    req<RunScenarioResult>("/run/scenario", { method: "POST", body: JSON.stringify({ scenario }) }),
  faultlabScenarios: () =>
    req<{ file: string; name: string; steps: number; fault_keys: string[]; duration_hint: number }[]>("/faultlab/scenarios"),
  faultlabDemo: (scenario: string) =>
    req<FaultLabResp>("/faultlab/demo", { method: "POST", body: JSON.stringify({ scenario }) }),
  agentTasks: () =>
    req<{ task_id: string; title: string; goal: string; target_fault: string; expected_action: string }[]>("/agent/tasks"),
  agentRun: (taskId?: string) =>
    req<AgentRunResp>("/agent/run", { method: "POST", body: JSON.stringify({ task_id: taskId ?? null }) }),
  agentFree: (goal: string) =>
    req<AgentFreeResp>("/agent/free", { method: "POST", body: JSON.stringify({ goal }) }),
  runCustom: (body: CustomScenarioRequest) =>
    req<RunScenarioResult & { custom: boolean }>("/run/custom", { method: "POST", body: JSON.stringify(body) }),
  settingsGet: () => req<SettingsView>("/settings"),
  settingsSave: (patch: Record<string, string | boolean>) =>
    req<SettingsView>("/settings", { method: "POST", body: JSON.stringify(patch) }),
  settingsClearApiKey: () => req<SettingsView>("/settings/clear-api-key", { method: "POST", body: JSON.stringify({}) }),
};

export interface AgentRunResp {
  total: number;
  achieved: number;
  success_rate: number;
  review_passed: number;
  runs: {
    task_id: string;
    fault: string;
    expected: string;
    achieved: boolean;
    attempts: number;
    reflected: boolean;
    scenario: string | null;
    duration_ms: number;
    score: { score: number; achieved: boolean; evidence_count: number; exec_passed: boolean; reflected: boolean };
    review: {
      task_id: string;
      passed: boolean;
      dimensions: Record<string, string>;
      issues: string[];
    };
    evidence: {
      doc_id: string;
      kind: string;
      score: number;
      text: string;
      neighbors: { id: string; kind: string; label: string; via: string }[];
    }[];
    trace: { step: string; detail: string; t: number }[];
  }[];
}

export interface SettingsView {
  dir: string;
  llm: { provider: string; base_url: string; model: string; has_key: boolean };
  asset_dir: string;
  port: number;
  onboarding_done: boolean;
  providers: Record<string, { label: string; base_url: string; model: string }>;
}

// ---- 自由 Agent 目标（/api/agent/free）----

export interface AgentFreeParsed {
  fault: string;
  fault_name: string;
  expected: string;
  expected_zh: string;
  confidence: number;
  resolver: "rule" | "llm";
  matched_on: string;
}

/** /api/agent/free 响应：解析结果 + 与 /api/agent/run 同构的执行报告。 */
export interface AgentFreeResp extends AgentRunResp {
  goal: string;
  parsed: AgentFreeParsed;
  matched_task_id: string; // T-FREE-1（自由任务动态生成）
}

// ---- 自定义场景执行（/api/run/custom）----

/** 自定义场景单步（与内置场景 YAML 步骤同构）。 */
export interface CustomStep {
  at: number;
  action: "inject" | "recover";
  fault?: string | null;
  node?: string | null;
  level?: string | null;
  expect?: string | null;
  impact?: string | null;
}

export interface CustomScenarioRequest {
  name?: string;
  steps: CustomStep[];
}
