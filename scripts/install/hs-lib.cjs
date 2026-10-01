"use strict";
/*
  hs-lib.cjs — 寒霜 macOS 版公共文本/JSON 处理库

  为什么用 node 而不是 sed/awk：
    · 注入块定位要按「正则 + 从某下标往后找」两段匹配，sed/awk 的字符下标在多字节
      中文下会错位，一旦错位就是写坏用户的 AGENTS.md / CLAUDE.md；
    · 状态文件是 JSON，用 sed 解析一旦转义就崩。
  node 是 Electron 自带的（打包后可用 ELECTRON_RUN_AS_NODE 复用 app 二进制），
  所以不引入任何新依赖。

  全部子命令都只读写显式给出的路径，不做隐式扫描。
*/

const fs = require("node:fs");
const path = require("node:path");

function read(p) {
  try {
    return fs.readFileSync(p, "utf8");
  } catch {
    return "";
  }
}

function write(p, text) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, text, "utf8");
}

/** CRLF → LF，并去掉首尾空白（对齐 PowerShell 版 $norm 的行为）。 */
function norm(s) {
  return String(s).replace(/\r\n/g, "\n").trim();
}

/** 用正则找注入块的起止：begin 匹配后，只在它之后找 end。 */
function findBlock(text, beginRe, endRe) {
  const b = new RegExp(beginRe).exec(text);
  if (!b) return null;
  const tailStart = b.index + b[0].length;
  const e = new RegExp(endRe).exec(text.slice(tailStart));
  if (!e) return null;
  return { start: b.index, end: tailStart + e.index + e[0].length };
}

/** 去掉注入块，块外内容原样保留。 */
function stripBlock(text, beginRe, endRe) {
  const blk = findBlock(text, beginRe, endRe);
  if (!blk) return text;
  return text.slice(0, blk.start) + text.slice(blk.end);
}

/** 有块就换块内内容，没块就追加到末尾。 */
function spliceBlock(text, beginRe, endRe, block) {
  const blk = findBlock(text, beginRe, endRe);
  if (blk) return text.slice(0, blk.start) + block + text.slice(blk.end);
  const base = text.replace(/\s+$/, "");
  if (!base) return block;
  return base + "\n\n" + block;
}

function jsonLoad(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}

/** 取顶层字段；字符串直接打印，数组每个元素一行，其余打印紧凑 JSON。 */
function jsonGet(p, key) {
  const o = jsonLoad(p);
  if (!o || o[key] === undefined || o[key] === null) return "";
  const v = o[key];
  if (Array.isArray(v)) return v.filter((x) => x != null).map((x) => String(x)).join("\n");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** 写顶层字段：key 为空时整个文件用 argv[4] 的 JSON 覆盖。 */
function jsonSet(p, key, valueJson) {
  const o = jsonLoad(p) || {};
  let value;
  try {
    value = JSON.parse(valueJson);
  } catch {
    value = valueJson;
  }
  o[key] = value;
  write(p, JSON.stringify(o, null, 2) + "\n");
}

// ---------- 技能库 ----------
// 这三段整体放在 node 里，是为了把「每个技能 5 次进程调用」压成一次。
// 实测单次 node 启动约 385ms（Windows 更慢），63 个技能 × 5 次会把一次安装
// 拖到 2 分钟以上，直接撞上主进程的 300 秒超时。

/** 列出目录下含 SKILL.md 的技能名。 */
function listSkillDirs(dir) {
  const out = [];
  try {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      if (fs.existsSync(path.join(dir, e.name, "SKILL.md"))) out.push(e.name);
    }
  } catch {
    /* 目录不存在 = 没有技能 */
  }
  return out.sort();
}

/** 随包分发的技能名（去重）：用于判断某个技能是不是本工具装进去的。 */
function shippedSkillNames(root) {
  const set = new Set();
  for (const lib of ["codex-skills", "codex-skills-v3", "codex-skills-v4", "codex-skills-v5"]) {
    for (const n of listSkillDirs(path.join(root, lib))) set.add(n);
  }
  return [...set].sort();
}

/**
  单个技能是否已是最新：只比 SKILL.md 的大小 + 时间戳。
  这是「这个技能没变过」的便宜代理指标，重装时绝大多数技能都能命中，省掉整目录复制。
*/
function skillCurrent(src, dst) {
  try {
    const a = fs.statSync(path.join(src, "SKILL.md"));
    const b = fs.statSync(path.join(dst, "SKILL.md"));
    if (a.size !== b.size) return false;
    return Math.abs(a.mtimeMs - b.mtimeMs) <= 2000;
  } catch {
    return false;
  }
}

function readLines(p) {
  try {
    return fs
      .readFileSync(p, "utf8")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

/** 安装技能库；返回本次安装的技能名（保持源目录顺序）。 */
function skillsInstall(src, dst) {
  const names = listSkillDirs(src);
  for (const name of names) {
    const from = path.join(src, name);
    const to = path.join(dst, name);
    if (skillCurrent(from, to)) continue;
    fs.rmSync(to, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(to), { recursive: true });
    // preserveTimestamps 必须开：skillCurrent 就是拿 mtime 当「没变过」的判据，
    // 不保留时间戳的话每次重装都会认为全部技能都变了，白复制一遍。
    fs.cpSync(from, to, { recursive: true, force: true, preserveTimestamps: true });
  }
  return names;
}

/**
  清理上一版遗留：候选 = 上次安装清单 ∩ 随包技能库 ∩ 当前不再分发。
  只删同时满足三条的目录 —— 用户自己放进来的技能一条都不沾。
*/
function skillsPrune(prevFile, curFile, dst, root) {
  const cur = new Set(readLines(curFile));
  const shipped = new Set(shippedSkillNames(root));
  const removed = [];
  for (const name of readLines(prevFile)) {
    if (!shipped.has(name)) continue;
    if (cur.has(name)) continue;
    const d = path.join(dst, name);
    if (!fs.existsSync(path.join(d, "SKILL.md"))) continue;
    fs.rmSync(d, { recursive: true, force: true });
    removed.push(name);
  }
  return removed;
}

/** 卸载：只删「上次安装清单 ∩ 随包技能库」。 */
function skillsRemove(listFile, dst, root) {
  const shipped = new Set(shippedSkillNames(root));
  const removed = [];
  for (const name of readLines(listFile)) {
    if (!shipped.has(name)) continue;
    const d = path.join(dst, name);
    if (fs.existsSync(d)) {
      fs.rmSync(d, { recursive: true, force: true });
      removed.push(name);
    }
  }
  return removed;
}

const [cmd, ...args] = process.argv.slice(2);

switch (cmd) {
  case "read":
    process.stdout.write(read(args[0]));
    break;

  case "write": {
    // 内容走 stdin，避免命令行长度与转义问题
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => {
      write(args[0], Buffer.concat(chunks).toString("utf8"));
    });
    break;
  }

  case "norm":
    process.stdout.write(norm(read(args[0])));
    break;

  case "norm-text":
    process.stdout.write(norm(args[0]));
    break;

  case "eq": {
    const a = norm(read(args[0]));
    const b = norm(read(args[1]));
    process.exit(a === b && a.length > 0 ? 0 : 1);
    break;
  }

  case "eq-text": {
    // 比「文件正文」与「提示词正文」是否一致
    const a = norm(read(args[0]));
    const b = norm(args[1] === "-" ? "" : read(args[1]));
    process.exit(a === b && a.length > 0 ? 0 : 1);
    break;
  }

  case "contains":
    process.exit(read(args[0]).includes(args[1]) ? 0 : 1);
    break;

  case "block-find": {
    const blk = findBlock(read(args[0]), args[1], args[2]);
    process.stdout.write(blk ? `${blk.start} ${blk.end - blk.start}` : "none");
    break;
  }

  case "block-strip":
    process.stdout.write(stripBlock(read(args[0]), args[1], args[2]));
    break;

  case "block-splice":
    process.stdout.write(spliceBlock(read(args[0]), args[1], args[2], read(args[3])));
    break;

  case "json-get":
    process.stdout.write(jsonGet(args[0], args[1]));
    break;

  case "json-set":
    jsonSet(args[0], args[1], args[2]);
    break;

  case "json-write": {
    // 从 stdin 读一个完整 JSON 文档写进去（不做校验，调用方保证格式）
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => {
      write(args[0], Buffer.concat(chunks).toString("utf8"));
    });
    break;
  }

  case "json-array": {
    // 把 stdin 的逐行文本写成一个 JSON 字符串数组到 <file> 的 <key>
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => {
      const items = Buffer.concat(chunks)
        .toString("utf8")
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      jsonSet(args[0], args[1], JSON.stringify(items));
    });
    break;
  }

  case "json-array-of-objects": {
    // stdin 每行一个 JSON 对象，写成一个 JSON 数组（Cursor 的 writtenPaths 用不到，
    // 但 dsh 的 deployed 清单需要保留对象结构）
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => {
      const items = Buffer.concat(chunks)
        .toString("utf8")
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => JSON.parse(s));
      jsonSet(args[0], args[1], JSON.stringify(items));
    });
    break;
  }

  case "mkdir":
    fs.mkdirSync(args[0], { recursive: true });
    break;

  case "exists":
    process.exit(fs.existsSync(args[0]) ? 0 : 1);
    break;

  case "isfile":
    try {
      process.exit(fs.statSync(args[0]).isFile() ? 0 : 1);
    } catch {
      process.exit(1);
    }
    break;

  case "isdir":
    try {
      process.exit(fs.statSync(args[0]).isDirectory() ? 0 : 1);
    } catch {
      process.exit(1);
    }
    break;

  case "size":
    try {
      process.stdout.write(String(fs.statSync(args[0]).size));
    } catch {
      process.stdout.write("0");
    }
    break;

  case "mtime":
    try {
      process.stdout.write(String(Math.floor(fs.statSync(args[0]).mtimeMs)));
    } catch {
      process.stdout.write("0");
    }
    break;

  case "chmod":
    try {
      fs.chmodSync(args[0], parseInt(args[1], 8));
    } catch {
      /* ignore */
    }
    break;

  case "skills-shipped":
    process.stdout.write(shippedSkillNames(args[0]).join("\n"));
    break;

  case "skills-install":
    process.stdout.write(skillsInstall(args[0], args[1]).join("\n"));
    break;

  case "skills-prune":
    process.stdout.write(skillsPrune(args[0], args[1], args[2], args[3]).join("\n"));
    break;

  case "skills-remove":
    process.stdout.write(skillsRemove(args[0], args[1], args[2]).join("\n"));
    break;

  case "now":
    process.stdout.write(new Date().toISOString().replace(/\.\d+Z$/, ".000Z"));
    break;

  case "stamp":
    // yyyyMMdd-HHmmss，本地时间（对齐 PowerShell Get-Date -Format）
    {
      const d = new Date();
      const z = (n) => String(n).padStart(2, "0");
      process.stdout.write(
        `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(
          d.getMinutes(),
        )}${z(d.getSeconds())}`,
      );
    }
    break;

  default:
    process.stderr.write(`hs-lib: 未知子命令 ${cmd}\n`);
    process.exit(2);
}
