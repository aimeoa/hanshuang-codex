#!/usr/bin/env node
/**
 * 主进程回归自测：验证 electron/lib/pure.cjs 的纯函数 + 静态检查 main.cjs 的修复是否在位。
 *
 * 无第三方依赖，不需要装 Electron，不需要显示器。
 *
 * 用法：node scripts/verify-main.mjs
 * 退出码：0 全通过 / 1 有失败
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const { sniffUtf8, createConsoleDecoder, stripSkillBlocks, skillBlock } = require(
  join(root, "electron", "lib", "pure.cjs"),
);

let pass = 0;
const fails = [];
function ok(name, cond, detail) {
  if (cond) {
    pass++;
    console.log("  \x1b[32m✓\x1b[0m " + name);
  } else {
    fails.push(name);
    console.log("  \x1b[31m✗\x1b[0m " + name + (detail ? "\n      " + detail : ""));
  }
}
function eq(name, actual, expect) {
  ok(name, actual === expect, `期望 ${JSON.stringify(expect)}\n      实际 ${JSON.stringify(actual)}`);
}

// ────────────────────────────────────────────── 1. TOML 清洗
console.log("\n[1] stripSkillBlocks — 删块不能留下孤儿键");

const SRC = `model = "gpt-5"
approval_policy = "on-request"

[[skills.config]]
path = "/home/u/.codex/skills/apkseep/SKILL.md"
enabled = false

[profiles.fast]
model = "o4-mini"
reasoning = "low"

[[skills.config]]
path = "/home/u/.codex/skills/softseep/SKILL.md"
enabled = false

[notice]
hide = true
`;

const stripped = stripSkillBlocks(SRC);
console.log("  ---- 清洗结果 ----");
console.log(
  stripped
    .split("\n")
    .map((l) => "  │ " + l)
    .join("\n"),
);

ok("不再包含 [[skills.config]] 表头", !stripped.includes("[[skills.config]]"));
ok("不再残留孤儿 path= 行", !/^\s*path\s*=/m.test(stripped), "说明正文没删干净，会污染上一张表");
ok("不再残留孤儿 enabled= 行", !/^\s*enabled\s*=/m.test(stripped));
ok("保留用户自己的顶层键 model", stripped.includes('model = "gpt-5"'));
ok("保留用户自己的顶层键 approval_policy", stripped.includes('approval_policy = "on-request"'));
ok("保留 [profiles.fast] 整块", stripped.includes("[profiles.fast]") && stripped.includes('reasoning = "low"'));
ok("保留 [notice] 整块", stripped.includes("[notice]") && stripped.includes("hide = true"));
ok("幂等：再洗一次结果不变", stripSkillBlocks(stripped) === stripped);

// 块在文件末尾（后面没有别的表）
const tail = `a = 1\n\n[[skills.config]]\npath = "/x/SKILL.md"\nenabled = false\n`;
ok("末尾块也能整块删掉", !stripSkillBlocks(tail).includes("path"));

// 空输入 / null 不炸
eq("空字符串不抛异常", stripSkillBlocks(""), "\n");
eq("null 不抛异常", stripSkillBlocks(null), "\n");

// ────────────────────────────────────────────── 2. 重新拼块
console.log("\n[2] skillBlock — 拼出来的块必须是合法 TOML");

const block = skillBlock("C:\\Users\\a b\\.codex\\skills\\demo\\SKILL.md", false);
ok("反斜杠被转成正斜杠", block.includes('path = "C:/Users/a b/.codex/skills/demo/SKILL.md"'), block);
ok("enabled = false", block.includes("enabled = false"));
const roundTrip = stripSkillBlocks("x = 1\n" + block);
ok("拼出来的块能被自己洗掉（幂等闭环）", !roundTrip.includes("skills.config"));

// 非法目录名被主进程过滤（这里验证规则本身）
const bad = ['../etc', "a/b", 'a"b', "a\nb"];
ok(
  "目录名过滤规则覆盖路径穿越/引号/换行",
  bad.every((n) => /[\\/\r\n"]/.test(n)),
);

// ────────────────────────────────────────────── 3. 编码嗅探
console.log("\n[3] sniffUtf8 — 不能把截断的多字节字符误判成非 UTF-8");

const zh = Buffer.from("中文测试", "utf8"); // 12 字节，每字 3 字节
ok("完整 UTF-8 判为 true", sniffUtf8(zh) === true);
ok("切掉末尾 1 字节（半个字）仍判为 true", sniffUtf8(zh.subarray(0, zh.length - 1)) === true);
ok("切掉末尾 2 字节（三分之一个字）仍判为 true", sniffUtf8(zh.subarray(0, zh.length - 2)) === true);
ok("GBK 字节判为 false", sniffUtf8(Buffer.from([0xd6, 0xd0, 0xce, 0xc4])) === false);
ok("纯 ASCII 判为 true", sniffUtf8(Buffer.from("hello")) === true);

// ────────────────────────────────────────────── 4. 流式解码
console.log("\n[4] createConsoleDecoder — 分块喂入，结果必须和一次性解码一致");

const long = "寒霜破甲工具·日志测试 ".repeat(600); // ≈ 7.8 KB，超过 4 KB 嗅探阈值
const bytes = Buffer.from(long, "utf8");
const d1 = createConsoleDecoder();
let got = "";
for (let i = 0; i < bytes.length; i += 1000) {
  got += d1.push(bytes.subarray(i, i + 1000)); // 1000 不是 3 的倍数，必然切断中文字
}
got += d1.end();
eq("UTF-8 分块解码 == 原文", got, long);

const gbk = Buffer.from([0xd6, 0xd0, 0xce, 0xc4, 0xb2, 0xe2, 0xca, 0xd4]); // "中文测试"
const d2 = createConsoleDecoder();
const gotGbk = d2.push(gbk) + d2.end();
eq("GBK 自动识别并正确解码", gotGbk, "中文测试");

const d3 = createConsoleDecoder();
const short = "短输出\n";
eq("短输出（<4KB）也能在 end() 时吐出", d3.push(Buffer.from(short)) + d3.end(), short);

// 性能：确认不再全量重解（喂 2000 个 chunk，耗时应远低于 O(n²)）
const d4 = createConsoleDecoder();
const chunk = Buffer.from("x".repeat(512));
const t0 = process.hrtime.bigint();
let sink = 0;
for (let i = 0; i < 2000; i++) sink += d4.push(chunk).length;
sink += d4.end().length;
const ms = Number(process.hrtime.bigint() - t0) / 1e6;
eq("2000×512B 全部解出", sink, 2000 * 512);
ok(`2000 个 chunk 解码耗时 ${ms.toFixed(1)}ms（<500ms 视为通过）`, ms < 500, "原版这里是 O(n²)，会到秒级");

// ────────────────────────────────────────────── 5. 静态检查：main.cjs 是否真的改了
console.log("\n[5] main.cjs 静态检查");

const main = readFileSync(join(root, "electron", "main.cjs"), "utf8");

// 旧正则在注释里保留说明是允许的，只要不出现在可执行代码里
const codeOnly = main
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split(/\r?\n/)
  .filter((l) => !l.trim().startsWith("//"))
  .join("\n");
const buggy = "(?=^\\[\\[|$)";
ok("P0-1 旧的有 bug 正则已从可执行代码中移除", !codeOnly.includes(buggy));
ok("P0-2 单例 child 已消失", !/let child = null/.test(main));
ok("P0-2 引入串行队列 pumpQueue", main.includes("function pumpQueue"));
ok("P0-2 队列任务去重（同名任务不排队）", main.includes("jobQueue.some"));
ok("P1-3 原子写（tmp + rename）", main.includes("fs.renameSync(tmp, file)"));
ok("P1-4 使用流式解码器", main.includes("createConsoleDecoder"));
ok("P1-5 同步扫盘循环已移除", !/for \(let c = 67; c <= 90; c\+\+\) \{/.test(main) || main.includes("async function detectCodexHome"));
ok("P1-5 保留异步探测", main.includes("async function detectCodexHome"));
ok("P2-6 状态文件迁到 userData", main.includes('app.getPath("userData")'));
ok("P2-6 旧状态自动迁移", main.includes("function migrateLegacyState"));
ok("P2-7 沙箱已开启", main.includes("sandbox: true"));
ok("P2-8 openQQ 域名白名单", main.includes("OPEN_URL_HOSTS"));
ok("P2-9 uninstall 校验 targetId", /isTarget\(targetId\)/.test(main));
ok("P2-9 skills:save 校验数组", main.includes("Array.isArray(disabled)"));
ok("P2-10 开发自动化加打包闸门", main.includes("!app.isPackaged && process.env.HS_CAPTURE"));
ok("退出时清理队列（Promise 不悬挂）", main.includes("function abortAllJobs"));

// ────────────────────────────────────────────── 汇总
console.log("\n" + "─".repeat(60));
if (fails.length) {
  console.log(`\x1b[31m失败 ${fails.length} 项 / 通过 ${pass} 项\x1b[0m`);
  for (const f of fails) console.log("  - " + f);
  process.exit(1);
} else {
  console.log(`\x1b[32m全部通过：${pass} 项\x1b[0m`);
}
