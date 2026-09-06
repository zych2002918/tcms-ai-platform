import { chromium } from "playwright-core";
const BASE = "http://127.0.0.1:8000";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const b = await chromium.launch({ executablePath: EDGE, headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const results = [];
const assert = (name, cond) => results.push((cond ? "✓ " : "✗ ") + name);

await p.goto(BASE + "/", { waitUntil: "networkidle" });
await p.waitForTimeout(500);
let body = await p.locator("body").innerText();
assert("总览:标题+被测功能", body.includes("TCMS × AI 测试平台") && body.includes("被测功能"));

await p.goto(BASE + "/assets", { waitUntil: "networkidle" });
await p.waitForTimeout(500);
body = await p.locator("body").innerText();
assert("资产:报文表", body.includes("DoorControl") && body.includes("TCMS_Heartbeat"));
await p.click("button:has-text('故障')");
await p.waitForTimeout(500);
body = await p.locator("body").innerText();
assert("资产:故障含 EB", body.includes("紧急制动执行失败"));
await p.click("tr:has-text('紧急制动执行失败')");
await p.waitForTimeout(400);
body = await p.locator("body").innerText();
assert("资产:故障详情展开(检测/恢复)", body.includes("恢复") && body.includes("检测"));

await p.goto(BASE + "/scenarios", { waitUntil: "networkidle" });
await p.selectOption("select", "eb_failure_eb.yaml");
await p.click("button:has-text('执行')");
await p.waitForTimeout(2500);
body = await p.locator("body").innerText();
assert("场景执行:结果+PASS+run沉淀", body.includes("执行结果") && body.includes("PASS") && body.includes("run-"));

await p.goto(BASE + "/graph", { waitUntil: "networkidle" });
await p.fill("input[placeholder*='车门故障']", "紧急制动 执行失败");
await p.click("button:has-text('GraphRAG')");
await p.waitForTimeout(1800);
body = await p.locator("body").innerText();
assert("图谱:检索命中 eb_failure", body.includes("检索结果") && body.includes("fault:eb_failure"));
// 点整个结果块(code 触发父 onClick)聚焦
await p.locator("code:has-text('fault:eb_failure')").click();
await p.waitForTimeout(1500);
const circles = await p.locator("svg circle").count();
assert("图谱:力导向画布节点渲染", circles >= 2);

await p.goto(BASE + "/agent", { waitUntil: "networkidle" });
await p.click("button:has-text('执行任务')");
await p.waitForTimeout(3500);
body = await p.locator("body").innerText();
assert("Agent:任务达成+轨迹(证据/评分)", body.includes("达成") && body.includes("评分") && body.includes("证据"));

console.log("\n===== 小白端到端走查 =====");
console.log(results.join("\n"));
const fails = results.filter((r) => r.startsWith("✗")).length;
console.log(fails ? `\n${fails} 项未通过` : "\n✅ 全部通过");
await b.close();
process.exit(fails ? 1 : 0);
