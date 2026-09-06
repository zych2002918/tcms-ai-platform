import { chromium } from "playwright-core";
const BASE = "http://127.0.0.1:8000";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const b = await chromium.launch({ executablePath: EDGE, headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const results = [];
const assert = (name, cond) => results.push((cond ? "✓ " : "✗ ") + name);

// 1. 总览 —— 新仪表盘
await p.goto(BASE + "/", { waitUntil: "networkidle" });
await p.waitForTimeout(600);
let body = await p.locator("body").innerText();
assert("总览:状态条+从这里开始", body.includes("上游引擎就绪") && body.includes("从这里开始") && body.includes("被测功能"));

// 2. 资产 —— 报文 tab + 筛选
await p.goto(BASE + "/assets", { waitUntil: "networkidle" });
await p.waitForTimeout(600);
body = await p.locator("body").innerText();
assert("资产:报文表+DoorControl", body.includes("DoorControl") && body.includes("TCMS_Heartbeat"));
// 切故障 tab（按钮是 tab 样式，用 role=tab 语义或文字）
await p.click("button:has-text('故障')");
await p.waitForTimeout(500);
body = await p.locator("body").innerText();
assert("资产:故障含 EB 条目", body.includes("紧急制动执行失败"));
await p.click("tr:has-text('紧急制动执行失败')");
await p.waitForTimeout(500);
body = await p.locator("body").innerText();
assert("资产:故障详情侧栏(检测/恢复/处置)", body.includes("恢复") && body.includes("检测") && body.includes("处置"));

// 3. 场景执行 —— 运行流程感
await p.goto(BASE + "/scenarios", { waitUntil: "networkidle" });
await p.selectOption("select", "eb_failure_eb.yaml");
await p.click("button:has-text('运行此场景')");
// 运行中步骤条应短暂出现
await p.waitForTimeout(700);
const runningText = await p.locator("body").innerText();
assert("场景:运行中出现步骤条", runningText.includes("正在真实引擎上执行"));
await p.waitForSelector("text=运行完成", { timeout: 12000 });
body = await p.locator("body").innerText();
assert("场景:完成后 PASS+断言", body.includes("PASS") && body.includes("emergency_brake"));

// 4. 图谱 —— 分类检索
await p.goto(BASE + "/graph", { waitUntil: "networkidle" });
await p.fill("input[placeholder*='大白话']", "车门故障");
await p.click("button:has-text('检索')");
await p.waitForTimeout(1800);
body = await p.locator("body").innerText();
assert("图谱:检索分类出现(故障/全部)", body.includes("全部") && body.includes("door_fault"));
assert("图谱:小白解释行出现", body.includes("这是一条"));
// 点一个命中聚焦图谱
await p.locator("code:has-text('door_fault')").first().click();
await p.waitForTimeout(1600);
const circles = await p.locator("svg circle").count();
assert("图谱:力导向画布渲染", circles >= 2);

// 5. Agent
await p.goto(BASE + "/agent", { waitUntil: "networkidle" });
await p.click("button:has-text('执行此任务')");
await p.waitForSelector("text=评分", { timeout: 15000 });
body = await p.locator("body").innerText();
assert("Agent:任务达成+轨迹(证据/评分)", body.includes("达成") && body.includes("评分") && body.includes("证据"));

// 6. 窄屏无横向溢出
const narrow = await b.newPage({ viewport: { width: 860, height: 900 } });
for (const path of ["/", "/assets", "/scenarios", "/graph", "/agent"]) {
  await narrow.goto(BASE + path, { waitUntil: "networkidle" });
  await narrow.waitForTimeout(500);
  const overflow = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert(`窄屏(860px)无横向溢出: ${path}`, overflow <= 2);
}
await narrow.close();

console.log("\n===== 新 UI 端到端走查 =====");
console.log(results.join("\n"));
const fails = results.filter((r) => r.startsWith("✗")).length;
console.log(fails ? `\n${fails} 项未通过` : "\n✅ 全部通过");
await b.close();
process.exit(fails ? 1 : 0);
