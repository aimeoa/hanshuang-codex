"use strict";
/*
  zcode-patch.cjs — 给 ZCode 的 resources/glm/zcode.cjs 打系统提示词补丁

  为什么要单独写一个 node 程序，而不是在 install-zcode.sh 里用 bash 字符串操作：

    1. zcode.cjs 是压缩后的 14MB 单行 JS。bash 的 `${var#pattern}` 在这种规模下
       既慢又容易在中文（多字节）下标上错位 —— 一旦错位就是写坏 ZCode 本体。
    2. 需要「字符串感知的括号配对」才能安全地清空一个数组字面量，bash 做不了。

  ── 原实现为什么失效 ──────────────────────────────────────────────
  原 PowerShell/bash 版用的是**压缩后的变量名**当锚点：
      function u9o  /  function Alt  /  s9o="You are ZCode, ..."  /  Xlt={...beforeDefault:[...]}
  ZCode 3.14.4 重新压缩后这些名字全变了：
      · function Alt  不存在          → 前置条件不成立，整步被静默跳过
      · function u9o  存在但已是无关函数（workflow 作用域判断）
      · s9o  → 改名为 IJs
      · Xlt  → 改名，但 beforeDefault 这个「键名」还在
  所以补丁从来没生效过，而脚本只是打印一行 skipped 就继续跑。

  ── 本实现的两个原则 ──────────────────────────────────────────────
  1. **锚点用字符串字面量或键名，不用压缩变量名。**
     CLI 前缀锚的是内容 "You are ZCode, an interactive coding agent"，
     变量名靠正则现读（`([A-Za-z0-9_$]+)=`），换版本也不会失效。
  2. **找不到锚点必须显式报错**，不能静默跳过（退出码非 0）。

  用法：
    node zcode-patch.cjs check <zcode.cjs>
    node zcode-patch.cjs apply <zcode.cjs> <promptFile> [--dry-run]

  退出码：0 = 全部成功；2 = 部分锚点缺失（已打上的部分仍写入）；1 = 出错
*/

const fs = require("node:fs");

/** CLI 前缀的默认内容：这是 ZCode 自带的身份声明，也是本补丁要替换掉的东西。 */
const CLI_DEFAULT = "You are ZCode, an interactive coding agent";
/** 沟通指南那一段的起始标记（beforeDefault 数组的第一个元素）。 */
const GUIDE_HEAD = "# Communicating with the user";

const out = (k, v) => console.log(`${k}=${v}`);

function readUtf8(p) {
  return fs.readFileSync(p, "utf8");
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 找 CLI 前缀赋值：`<var>="You are ZCode, an interactive coding agent"` */
function findCli(src) {
  const re = new RegExp(`([A-Za-z0-9_$]+)\\s*=\\s*"${escapeRe(CLI_DEFAULT)}"`);
  const m = re.exec(src);
  if (!m) return null;
  return { varName: m[1], start: m.index, end: m.index + m[0].length, raw: m[0] };
}

/**
  字符串感知地找数组字面量的结束下标。
  跳过字符串内部（含转义）与嵌套括号，避免把字符串里的 ']' 当成数组结尾。
*/
function findArrayEnd(src, openIdx) {
  let depth = 0;
  let quote = null;
  for (let i = openIdx; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (c === "\\") {
        i++;
        continue;
      }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      continue;
    }
    if (c === "[") depth++;
    else if (c === "]") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** 找沟通指南的 beforeDefault 数组：键名 + 首元素内容双重定位。 */
function findGuide(src) {
  let from = 0;
  for (;;) {
    const k = src.indexOf("beforeDefault", from);
    if (k === -1) return null;
    from = k + 1;
    const open = src.indexOf("[", k);
    if (open === -1) continue;
    // 键名与数组之间只允许空白/冒号，避免匹配到别处的 beforeDefault
    const between = src.slice(k + "beforeDefault".length, open);
    if (!/^\s*:\s*$/.test(between)) continue;
    const close = findArrayEnd(src, open);
    if (close === -1) continue;
    const body = src.slice(open + 1, close);
    if (!body.includes(GUIDE_HEAD)) continue;
    // end 必须是 close + 1：slice 的上界是排他的，close 本身是 ']' 那个字符，
    // 少加 1 会把 ']' 留在原地，结果变成 `[]]` —— 直接写坏整个 bundle。
    return { start: open, end: close + 1, len: close - open + 1, body };
  }
}

/**
  判定当前状态。
    · 还能找到默认身份声明  → clean（没打过补丁）
    · 找不到，但能在文件里找到提示词特征串 → patched（打过了）
    · 找不到，也没有提示词特征串 → unknown（版本换了写法，需要人工确认）

  注意：不要用固定标记串（原实现用 'CTF-LAB-2.0'，而它根本不在任何提示词里，
  所以那个判断从来就是失效的）。这里直接拿提示词正文的一段当特征。
*/
function detect(src, promptSig) {
  const cli = findCli(src);
  const guide = findGuide(src);
  let state;
  if (cli) state = "clean";
  else if (promptSig && src.includes(promptSig)) state = "patched";
  else state = "unknown";
  return { cli, guide, state };
}

/** 从提示词里取一段稳定特征串（跳过头部的空行/标记，取一段纯正文）。 */
function promptSignature(prompt) {
  const lines = prompt
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length >= 12);
  return lines.length ? lines[0].slice(0, 40) : "";
}

function cmdCheck(path, promptFile) {
  const src = readUtf8(path);
  const sig = promptFile ? promptSignature(readUtf8(promptFile)) : "";
  const { cli, guide, state } = detect(src, sig);
  out("FILE_SIZE", src.length);
  out("ANCHOR_CLI", cli ? "found" : "missing");
  if (cli) out("CLI_VAR", cli.varName);
  out("ANCHOR_GUIDE", guide ? "found" : "missing");
  if (guide) out("GUIDE_ARRAY_LEN", guide.len);
  out("STATE", state);
  if (sig) out("PROMPT_SIG", sig);
  return 0;
}

function cmdApply(path, promptFile, dryRun) {
  let src = readUtf8(path);
  const prompt = readUtf8(promptFile);
  const sig = promptSignature(prompt);

  const before = detect(src, sig);
  out("FILE_SIZE_BEFORE", src.length);
  out("STATE_BEFORE", before.state);
  out("ANCHOR_CLI", before.cli ? "found" : "missing");
  out("ANCHOR_GUIDE", before.guide ? "found" : "missing");

  // 已经打过就直接返回成功，不重复写盘（幂等）
  if (before.state === "patched") {
    out("ACTION", "already-patched");
    return 0;
  }

  let failed = false;

  // ── 补丁 1：把 CLI 前缀的内容换成寒霜提示词 ──
  // 对应原实现的「替换 u9o 函数 + 清空 s9o」两步的合并效果：
  // 让 ZCode 系统提示词的第一节（CLI Prefix，injectionTarget=system）直接就是寒霜提示词。
  if (before.cli) {
    const lit = JSON.stringify(prompt); // 正确的 JS 字符串字面量（转义、换行都交给它）
    const replacement = `${before.cli.varName}=${lit}`;
    src = src.slice(0, before.cli.start) + replacement + src.slice(before.cli.end);
    out("ACTION_CLI", "replaced");
    out("CLI_VAR", before.cli.varName);
    out("CLI_PROMPT_CHARS", prompt.length);
  } else {
    out("ACTION_CLI", "skipped:anchor-missing");
    failed = true;
  }

  // ── 补丁 2：清空沟通指南（beforeDefault 数组）──
  const guide = findGuide(src); // 补丁 1 之后重新定位（下标已变）
  if (guide) {
    src = src.slice(0, guide.start) + "[]" + src.slice(guide.end);
    out("ACTION_GUIDE", "cleared");
    out("GUIDE_ARRAY_LEN_BEFORE", guide.len);
  } else {
    out("ACTION_GUIDE", "skipped:anchor-missing");
    failed = true;
  }

  if (dryRun) {
    out("DRY_RUN", "true");
    out("FILE_SIZE_AFTER", src.length);
    return failed ? 2 : 0;
  }

  // 写入前自检：体积不能离谱地变化，且不能再出现默认身份声明
  if (src.length < 1000000) {
    console.error("zcode-patch: 写入前自检失败 —— 结果体积异常（疑似写坏）");
    return 1;
  }
  if (src.includes(`="${CLI_DEFAULT}"`)) {
    console.error("zcode-patch: 写入前自检失败 —— 默认身份声明仍然存在");
    return 1;
  }

  fs.writeFileSync(path, src, "utf8");
  out("FILE_SIZE_AFTER", src.length);
  out("WROTE", path);
  return failed ? 2 : 0;
}

const [cmd, ...args] = process.argv.slice(2);
try {
  if (cmd === "check") {
    process.exit(cmdCheck(args[0], args[1]));
  } else if (cmd === "apply") {
    const dryRun = args.includes("--dry-run");
    const [path, promptFile] = args.filter((a) => a !== "--dry-run");
    process.exit(cmdApply(path, promptFile, dryRun));
  } else {
    console.error("用法: node zcode-patch.cjs check <zcode.cjs> [promptFile]");
    console.error("      node zcode-patch.cjs apply <zcode.cjs> <promptFile> [--dry-run]");
    process.exit(1);
  }
} catch (e) {
  console.error("zcode-patch 错误: " + (e && e.message));
  process.exit(1);
}
