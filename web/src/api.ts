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

export const api = {
  stats: () => req<Stats>("/stats"),
  health: () => req<{ status: string; version: string }>("/health"),
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
};
