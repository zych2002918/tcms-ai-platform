"""LLM 决策后端（AgentBackend 实现，OpenAI 兼容）。

让 Agent 的「规划/选场景/策略」由真 LLM 决策（而非确定性规则）。设计：
- 无 key / 请求失败 / 解析失败 → **自动落回 MockAgentBackend**（诚实降级，
  保证离线与断网也可复现——Harness 红线）
- key 来源（环境变量，任意一个）：DASH_API_KEY / DEEPSEEK_API_KEY /
  OPENAI_API_KEY；base_url 可用 LLM_BASE_URL 覆盖（默认阿里百炼兼容端点）
- 请求超时与重试受控（测试/演示不卡死）

用法：
    backend = LLMAgentBackend(fallback=MockAgentBackend())
    harness = AgentHarness(..., backend=backend)
"""

from __future__ import annotations

import json
import os
import time

import httpx

from .harness import AgentBackend, MockAgentBackend, Plan
from .tasks import TaskDef

DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "deepseek-v3.2"
TIMEOUT_S = 25
MAX_RETRY = 1


def _api_key() -> str | None:
    """环境变量优先；其次读 ~/.dsh/.credentials.yaml 的 refs.ALIYUN_API_KEY
    （本地可信源；key 永不写入仓库/日志）。
    测试可用 DSH_CREDENTIALS_FILE 指向临时文件来隔离真实凭据。"""
    for k in ("DASH_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        import yaml

        cred = os.environ.get("DSH_CREDENTIALS_FILE") or os.path.expanduser("~/.dsh/.credentials.yaml")
        if os.path.isfile(cred):
            d = yaml.safe_load(open(cred, encoding="utf-8"))
            refs = d.get("refs", {}) or {}
            key = refs.get("ALIYUN_API_KEY")
            if isinstance(key, str) and key.strip():
                return key.strip()
    except Exception:  # noqa: BLE001 - 读凭据失败不阻塞（落回 mock）
        pass
    return None


def llm_available() -> bool:
    return bool(_api_key())


class LLMAgentBackend(AgentBackend):
    """OpenAI 兼容 LLM 决策后端（失败自动落回 Mock）。"""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        fallback: AgentBackend | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.fallback = fallback or MockAgentBackend()
        self.used_llm = False  # 本次是否真的用了 LLM（供 trace/自证）

    # ---- 工具 ----

    def _chat(self, system: str, user: str) -> str | None:
        key = _api_key()
        if not key:
            return None
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        last_err: Exception | None = None
        for _ in range(MAX_RETRY + 1):
            try:
                r = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
                if r.status_code == 200:
                    data = r.json()
                    return data["choices"][0]["message"]["content"]
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.5)
        if last_err:
            print(f"[llm-backend] chat failed, fallback to mock: {last_err}")
        return None

    @staticmethod
    def _parse_scenario_choice(text: str, scenarios: list[dict]) -> str | None:
        """从 LLM 文本提取所选场景文件名（容忍 JSON/散句）。"""
        # 先试 JSON {scenario: ...}
        try:
            start = text.find("{")
            if start >= 0:
                obj = json.loads(text[start : text.rfind("}") + 1])
                cand = obj.get("scenario") or obj.get("file")
                if cand and any(s["file"] == cand for s in scenarios):
                    return cand
        except Exception:  # noqa: BLE001
            pass
        # 散句：找出现在文本里的场景文件名
        for s in scenarios:
            if s["file"] in text:
                return s["file"]
        return None

    # ---- AgentBackend ----

    def plan(self, task: TaskDef, evidence: list[dict], scenarios: list[dict]) -> Plan:
        # 候选 = 覆盖目标故障的场景
        covering = [s for s in scenarios if task.target_fault in s.get("fault_keys", [])]
        if not covering:
            return self.fallback.plan(task, evidence, scenarios)
        # 无 key → 直接 mock
        if not _api_key():
            return self.fallback.plan(task, evidence, scenarios)

        evidence_txt = "\n".join(
            f"- {h.get('doc_id')}: {h.get('text', '')[:200]}" for h in evidence[:5]
        ) or "（无）"
        scen_txt = "\n".join(f"- {s['file']}（覆盖 {s.get('fault_keys')}，涉及 {s.get('nodes')}）" for s in covering)
        system = (
            "你是 TCMS 列车控制软件测试的规划 Agent。你的任务是：为给定测试目标，"
            "从候选场景中选一个最合适的真实执行场景，并给出一句话策略。"
            "只输出 JSON：{\"scenario\": \"<文件名>\", \"strategy\": \"<一句话理由>\"}。"
            "scenario 必须是候选列表里的文件名。"
        )
        user = (
            f"目标：验证故障 {task.target_fault} 必须触发处置 {task.expected_action}。\n\n"
            f"候选场景：\n{scen_txt}\n\n检索到的证据：\n{evidence_txt}"
        )
        text = self._chat(system, user)
        if text is None:
            # 诚实降级
            p = self.fallback.plan(task, evidence, scenarios)
            return Plan(
                task_id=p.task_id,
                fault=p.fault,
                expected_action=p.expected_action,
                chosen_scenario=p.chosen_scenario,
                strategy=p.strategy + " [LLM 不可用，已落回确定性]",
            )
        chosen = self._parse_scenario_choice(text, covering)
        if chosen is None:
            p = self.fallback.plan(task, evidence, scenarios)
            return Plan(
                task_id=p.task_id,
                fault=p.fault,
                expected_action=p.expected_action,
                chosen_scenario=p.chosen_scenario,
                strategy=f"LLM 输出未解析({text[:80]})，落回确定性",
            )
        self.used_llm = True
        # 提取 strategy(尽力)
        strategy = "LLM 决策"
        try:
            start = text.find("{")
            obj = json.loads(text[start : text.rfind("}") + 1])
            strategy = obj.get("strategy", "LLM 决策")
        except Exception:  # noqa: BLE001
            pass
        return Plan(
            task_id=task.task_id,
            fault=task.target_fault,
            expected_action=task.expected_action,
            chosen_scenario=chosen,
            strategy=f"[LLM {self.model}] {strategy}",
        )
