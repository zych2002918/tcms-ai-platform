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
// 引擎执行 <20ms，瞬态「执行中」状态难稳定采样 —— 改为断言完成流程（更稳）
await p.waitForSelector("text=运行完成", { timeout: 12000 });
body = await p.locator("body").innerText();
assert("场景:运行完成 + PASS+断言", body.includes("PASS") && body.includes("emergency_brake") && body.includes("TCMS 引擎"));

// 3b. 故障演示 —— 动画回放流程感
await p.goto(BASE + "/faultlab", { waitUntil: "networkidle" });
await p.selectOption("select", "overspeed_derate.yaml");
await p.click("button:has-text('演示此场景')");
await p.waitForTimeout(900);
body = await p.locator("body").innerText();
assert("FaultLab:事件时间线(注入/检测/处置/恢复)", body.includes("注入故障") && body.includes("处置") && body.includes("恢复") && body.includes("检测到异常"));
assert("FaultLab:诚实标注", body.includes("诚实性标注"));
// 播放中画面推进（超速在 10s 注入，等播放推进）
await p.waitForTimeout(6000);
body = await p.locator("body").innerText();
assert("FaultLab:自动播放推进到事件后", body.includes("降级运行") || body.includes("超速"));
await p.screenshot({ path: "docs/preview/faultlab-playing.png" });

// 4. 图谱 —— 分类检索
await p.goto(BASE + "/graph", { waitUntil: "networkidle" });
await p.waitForTimeout(600);
body = await p.locator("body").innerText();
assert("图谱:KB 索引概览(节点/向量)", body.includes("知识底座") && body.includes("向量索引"));
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
assert("Agent:检索证据链(GraphRAG)", body.toLowerCase().includes("检索证据") && body.toLowerCase().includes("graphrag"));

// 5b. 设置 / 新手引导
await p.goto(BASE + "/settings", { waitUntil: "networkidle" });
await p.waitForTimeout(600);
body = await p.locator("body").innerText();
assert("设置:新手引导向导(资产源)", body.includes("新手引导") && (body.includes("资产源") || body.includes("tcms-can-test")));
assert("设置:外部可配置接口说明", body.includes("外部可配置接口"));
// 走到 LLM 步骤
await p.click("button:has-text('下一步：接入 AI')");
await p.waitForTimeout(300);
body = await p.locator("body").innerText();
assert("设置:服务商预设(阿里云/DeepSeek)", body.includes("阿里云百炼") && body.includes("DeepSeek 官方"));
assert("设置:key 只存本机提示", body.includes("绝不上传") || body.includes("只写入本机"));
await p.click("button:has-text('下一步：检查引擎')");
await p.waitForTimeout(300);
body = await p.locator("body").innerText();
assert("设置:引擎状态检查步", body.includes("TCMS 引擎") && (body.includes("可用") || body.includes("不可用")));

// 6. 窄屏无横向溢出
const narrow = await b.newPage({ viewport: { width: 860, height: 900 } });
for (const path of ["/", "/assets", "/scenarios", "/faultlab", "/graph", "/agent", "/settings"]) {
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
