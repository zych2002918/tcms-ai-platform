import { chromium } from "playwright-core";
const BASE = "http://127.0.0.1:8000";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const b = await chromium.launch({ executablePath: EDGE, headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 1200 } });
const out = [];
const assert = (n, c) => out.push([n, c]);

// FaultLab: demo overspeed with auto-play; check event list visible after load
await p.goto(BASE + "/faultlab", { waitUntil: "networkidle" });
await p.waitForTimeout(500);
await p.selectOption("select", "overspeed_derate.yaml");
await p.click("button:has-text('演示此场景')");
await p.waitForTimeout(900);
let body = await p.locator("body").innerText();
assert("FaultLab 事件时间线含 注入", body.includes("注入故障"));
assert("FaultLab 事件时间线含 处置", body.includes("处置"));
assert("FaultLab 超速场景含 降级运行", body.includes("降级运行"));
assert("FaultLab 诚实标注", body.includes("诚实性标注"));
assert("FaultLab 事件刻度图例", body.includes("恢复"));
await p.screenshot({ path: "e2e/shots-faultlab-os2.png", fullPage: false });
// wait for auto play to reach ~ 12s (inject 10s)
await p.waitForTimeout(4000);
body = await p.locator("body").innerText();
assert("FaultLab 播放到事件后画面推进", body.includes("s / 24") || body.includes("s / 24.0") || /\.\ds \/ 24/.test(body));
await p.screenshot({ path: "e2e/shots-faultlab-playing2.png" });

// FaultLab eb_failure teaching point
await p.selectOption("select", "eb_failure_eb.yaml");
await p.click("button:has-text('演示此场景')");
await p.waitForTimeout(700);
body = await p.locator("body").innerText();
assert("eb_failure 场景事件含 紧急制动执行失败", body.includes("紧急制动执行失败"));
await p.screenshot({ path: "e2e/shots-faultlab-eb2.png" });

// agent evidence panel check
await p.goto(BASE + "/agent", { waitUntil: "networkidle" });
await p.waitForTimeout(500);
await p.click("button:has-text('执行此任务')");
await p.waitForSelector("text=评分", { timeout: 20000 });
await p.waitForTimeout(1200);
body = await p.locator("body").innerText();
const lowBody = body.toLowerCase();
assert("Agent 证据链面板(检索证据 GraphRAG)", lowBody.includes("检索证据") && lowBody.includes("graphrag"));
const evidLines = (body.match(/mechanism:|interlock:|threshold:|state:/g) || []).length;
assert("Agent 证据含真实知识节点", evidLines >= 1);
await p.screenshot({ path: "e2e/shots-agent-evidence2.png" });

// narrow screens
const narrow = await b.newPage({ viewport: { width: 860, height: 1000 } });
for (const path of ["/faultlab", "/graph"]) {
  await narrow.goto(BASE + path, { waitUntil: "networkidle" });
  await narrow.waitForTimeout(500);
  const overflow = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert(`窄屏无横向溢出 ${path}`, overflow <= 2);
}
await narrow.close();

console.log("\n===== FaultLab / 证据链 UI 验证 2 =====");
out.forEach(([n, ok]) => console.log((ok ? "✓ " : "✗ ") + n));
console.log("fails:", out.filter(([, c]) => !c).length);
await b.close();
process.exit(out.filter(([, c]) => !c).length ? 1 : 0);
