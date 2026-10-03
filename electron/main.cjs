"use strict";
/*
  寒霜破甲工具 · Electron 主进程

  功能逻辑与 fj_tool.py 保持一致：同样的 install*.ps1、同样的参数、同样的超时时间。
  渲染进程通过 preload 暴露的 window.hs 调用下面的 IPC。
*/

const { app, BrowserWindow, ipcMain, shell, Tray, Menu, nativeImage } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// 应用名由构建变体决定（scripts/build.mjs 写入 variant.json）
let APP_NAME = "寒霜破甲工具";
let VARIANT = "free";
try {
  const v = require("../variant.json");
  if (v && v.appName) APP_NAME = v.appName;
  if (v && v.variant) VARIANT = v.variant;
} catch {
  /* 开发环境缺文件时用默认值 */
}
const INSTALL_TIMEOUT = 300000;
const UNINSTALL_TIMEOUT = 120000;

let win = null;
let tray = null;
let quitting = false;
let child = null; // 当前运行的 powershell
let childTimer = null;
let childLabel = "";

// ---------- 路径 ----------

/**
   脚本目录：打包后在 resources/；开发时 main.cjs 位于 <工具目录>/electron/，
   所以先试上一级，再在上一级的同级目录里找带 install.ps1 的那一层
   （项目目录名可能带中文或空格，不能写死）。
*/
const INSTALL_SCRIPTS = [
  "install.ps1",
  "install-zcode.ps1",
  "install-cursor.ps1",
  "install-claude.ps1",
  "install-workbuddy.ps1",
  "install-dsh.ps1",
];

function hasScripts(dir) {
  try {
    return INSTALL_SCRIPTS.every((f) => fs.existsSync(path.join(dir, f)));
  } catch {
    return false;
  }
}

function toolDir() {
  if (app.isPackaged) return process.resourcesPath;
  const parent = path.join(__dirname, "..");
  if (hasScripts(parent)) return path.resolve(parent);
  try {
    for (const entry of fs.readdirSync(parent, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const dir = path.join(parent, entry.name);
      if (hasScripts(dir)) return path.resolve(dir);
    }
  } catch {
    /* 落到兜底 */
  }
  return path.resolve(parent);
}

function homeDir() {
  return os.homedir();
}

/**
   Codex 的配置目录（home）。不能写死 ~/.codex：
     * 用户可能把 CODEX_HOME 指到别的盘（C 盘紧张时的常见做法，Codex 官方支持）
     * 也可能直接把 .codex 放在某个盘的根目录（迁移过数据目录的机器）
   探测顺序：CODEX_HOME 环境变量 → ~/.codex → 各盘根目录下的 .codex → 兜底 ~/.codex。
   写操作（如首次写状态文件）落在最后那个兜底路径上，不影响读取判断。
   结果缓存，避免每次调用都扫一遍盘。
*/
let cachedCodexHome = null;
function codexHome() {
  if (cachedCodexHome) return cachedCodexHome;
  const envHome = process.env.CODEX_HOME;
  const def = path.join(homeDir(), ".codex");
  if (envHome) {
    try { if (fs.existsSync(envHome)) { cachedCodexHome = envHome; return cachedCodexHome; } } catch { /* 忽略 */ }
  }
  try { if (fs.existsSync(def)) { cachedCodexHome = def; return cachedCodexHome; } } catch { /* 忽略 */ }
  for (let c = 67; c <= 90; c++) {   // C: 到 Z:
    const p = String.fromCharCode(c) + ":\\" + ".codex";
    try { if (fs.existsSync(p)) { cachedCodexHome = p; return cachedCodexHome; } } catch { /* 盘不存在 */ }
  }
  cachedCodexHome = def;
  return cachedCodexHome;
}

function statePath() {
  return path.join(codexHome(), "fj_desktop_state.json");
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2), "utf8");
}

// ---------- 任务定义（与 Python 版一致） ----------

const SCRIPTS = {
  codex: "install.ps1",
  zcode: "install-zcode.ps1",
  cursor: "install-cursor.ps1",
  claude: "install-claude.ps1",
  workbuddy: "install-workbuddy.ps1",
  // WorkBuddy 国内版：同一个脚本，靠 -ConfigDir 指到 ~/.workbuddy 区分
  "workbuddy-cn": "install-workbuddy.ps1",
  dsh: "install-dsh.ps1",
  doubao: "install-doubao.ps1",
  omp: "install-omp.ps1",
};

const TARGET_IDS = Object.keys(SCRIPTS);

/**
   Codex V5 双提示词（gpt-6-astra-v1）：界面上是一个版本，点安装时二选一 ——
  「六」用 gpt-6-astra-v1.md，「5.6」用 gpt-5.6-sol-unrestricted-v45.md。
  两份提示词都不引用 skills，所以走 -NoSkills 只注入提示词。
  candidates 按顺序探测：开发环境是仓库里的原始嵌套目录，打包后在 resources/ 下。
*/
const ASTRA_PROMPTS = {
  "codex-astra-6": {
    label: "V5(六)",
    name: "六 · GPT-6 Astra",
    candidates: [
      ["gpt-6-astra-v1", "gpt-6-astra-v1", "gpt-6-astra-v1.md"],
      ["gpt-6-astra-v1", "gpt-6-astra-v1.md"],
    ],
  },
  "codex-astra-56": {
    label: "V5(5.6)",
    name: "5.6 · GPT-5.6 Sol",
    candidates: [
      ["gpt-6-astra-v1", "gpt-5.6-sol-unrestricted-v45.md"],
      ["gpt-5.6-sol-unrestricted-v45.md"],
    ],
  },
};

/** config.toml 里出现这些文件名 = 当前注入的是对应那一份（用于「已安装」标记）。 */
const ASTRA_PROMPT_FILES = {
  "gpt-6-astra-v1.md": "codex-astra-6",
  "gpt-5.6-sol-unrestricted-v45.md": "codex-astra-56",
};

function p(...parts) {
  return path.join(toolDir(), ...parts);
}

/** 找到 V5 双提示词的真实路径；找不到返回 null，由调用方报错而不是静默装错文件。 */
function astraPromptPath(entry) {
  for (const parts of entry.candidates) {
    const full = p(...parts);
    try {
      if (fs.existsSync(full)) return full;
    } catch {
      /* 试下一个 */
    }
  }
  return null;
}

/** 判断某个记忆文件（AGENTS.md / CLAUDE.md）正文是不是「就是某份随包提示词」时用的候选清单。 */
function knownPromptPaths() {
  const list = [];
  for (const entry of Object.values(ASTRA_PROMPTS)) {
    const full = astraPromptPath(entry);
    if (full) list.push(full);
  }
  for (const name of CODEX_PROMPT_NAMES.concat(["寒霜v4-claude.md"])) {
    if (ASTRA_PROMPT_FILES[name]) continue; // 已在上面按候选路径处理过
    try {
      const full = p(name);
      if (fs.existsSync(full)) list.push(full);
    } catch {
      /* 缺文件就跳过 */
    }
  }
  return list;
}

function installArgs(targetId, promptFile) {
  const script = SCRIPTS[targetId];
  if (!script) throw new Error("未知目标: " + targetId);
  const file = p(script);
  const prompt = p(promptFile);

  switch (targetId) {
    case "codex": {
      // 所有 Codex 版本都额外写一份到 <CodexHome>\AGENTS.md（Codex 原生全局指令文件；
      // config.toml 会被 Codex 自己重写，AGENTS.md 不会丢）
      const inject = ["-InjectAgents", "-AgentsKnown", knownPromptPaths().join(";")];
      // V5 双提示词：按用户选的那一份注入，且不装任何 skills
      const astra = ASTRA_PROMPTS[promptFile];
      if (astra) {
        const src = astraPromptPath(astra);
        if (!src) throw new Error("找不到 V5 提示词文件：" + astra.candidates[0].join("/"));
        return ["-File", file, "-SourcePrompt", src, "-NoSkills", ...inject];
      }
      const args = ["-File", file, "-SourcePrompt", prompt];
      if (promptFile === "寒霜v5.md") {
        // 技能库改用 v4：v5 那套（codex-skills-v5 / codex-bundle-v5）整个来自外部包
        // 「codex＋Astra6破 v2」，已从仓库移除，不再作为分发内容
        args.push("-SkillsSource", "codex-skills-v4");
      } else {
        args.push("-SkillsSource", "codex-skills-v4");
      }
      return [...args, ...inject];
    }
    case "zcode": {
      const args = [
        "-File", file,
        "-PatchSystemPrompt",
        "-SourcePrompt", prompt,
        "-MemorySourcePrompt", prompt,
      ];
      if (promptFile === "寒霜v4.md") args.push("-SkillsSource", "codex-skills-v4");
      return args;
    }
    case "claude":
      // -KnownPrompts：CLAUDE.md 正文若本来就是某份随包提示词（手工贴过/老版本注入的），
      // 允许整份改写成带标记的块，而不是当成用户内容追加
      return [
        "-File", file,
        "-SourcePrompt", prompt,
        "-SkillsSource", "codex-skills-v4",
        "-KnownPrompts", knownPromptPaths().join(";"),
      ];
    case "workbuddy":
      return ["-File", file, "-SourcePrompt", prompt, "-SkillsSource", "codex-skills-v4"];
    case "workbuddy-cn":
      // 国内版数据目录固定是 ~/.workbuddy，必须显式指定 ——
      // 脚本的自动探测优先国际版（.workbuddy-ai），不指定的话国内版永远装不上。
      return [
        "-File", file,
        "-SourcePrompt", prompt,
        "-SkillsSource", "codex-skills-v4",
        "-ConfigDir", path.join(homeDir(), ".workbuddy"),
      ];
    // DeepSeek Harness：注入 ~/.dsh/AGENTS.md + 同步 ~/.dsh/skills
    case "dsh":
      return ["-File", file, "-SourcePrompt", prompt, "-SkillsSource", "codex-skills-v4"];
    // 豆包：提示词写进云端全局记忆（AGENTS.md 式整份覆盖），不走本地文件、不需要技能库
    case "doubao":
      return ["-File", file, "-SourcePrompt", prompt];
    // Oh My Pi：写原生规则目录，界面只走全局模式（-Scope all，见 data/targets.ts 的说明）。
    // 脚本不装技能库：OMP 的技能走自己的发现源（claude/codex 用户目录、customDirectories）。
    case "omp":
      return ["-File", file, "-SourcePrompt", prompt, "-Scope", "all"];
    case "cursor":
      return ["-File", file, "-SourcePrompt", prompt];
    default:
      return ["-File", file, "-SourcePrompt", prompt];
  }
}

function uninstallArgs(targetId) {
  const args = ["-File", p(SCRIPTS[targetId]), "-Uninstall"];
  // 国内版必须显式指定数据目录，否则卸载会走自动探测跑到国际版上去
  if (targetId === "workbuddy-cn") args.push("-ConfigDir", path.join(homeDir(), ".workbuddy"));
  return args;
}

/**
   提示词残留兜底清扫（scripts/clear-injected-prompts.ps1，由 extraResources 打进
   resources/scripts/）。按 -Targets 限定到当前目标，避免卸载一个目标时把别的目标的
   提示词也一起清掉。
*/
function clearPromptsArgs(targetId) {
  // 清理脚本的 workbuddy 分支按 Home 目录扫，已经同时覆盖 .workbuddy-ai 与 .workbuddy，
  // 所以国内版映射到同一个 target，不需要单独的清理分支。
  const t = targetId === "workbuddy-cn" ? "workbuddy" : targetId;
  return ["-File", p("scripts", "clear-injected-prompts.ps1"), "-Apply", "-Targets", t];
}

// ---------- 运行 powershell ----------

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function killChild() {
  if (!child) return;
  const pid = child.pid;
  child = null;
  try {
    // /T 连带子进程一起杀，否则 powershell 退出后残留的安装进程仍会写文件
    execFile("taskkill", ["/PID", String(pid), "/T", "/F"], () => {});
  } catch {
    /* ignore */
  }
}

function runPowerShell(args, label, timeoutMs) {
  return new Promise((resolve) => {
    if (child) {
      killChild();
    }
    if (childTimer) clearTimeout(childTimer);

    let out = "";
    let timedOut = false;
    childLabel = label;
    send("tool:status", { label, state: "running" });

    const ps = spawn(
      "powershell.exe",
      ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", ...args],
      { cwd: toolDir(), windowsHide: true },
    );
    child = ps;

    ps.stdout.on("data", (buf) => {
      const text = buf.toString("utf8");
      out = (out + text).slice(-60000);
      send("tool:log", { label, text });
    });
    ps.stderr.on("data", (buf) => {
      const text = buf.toString("utf8");
      out = (out + text).slice(-60000);
      send("tool:log", { label, text });
    });

    childTimer = setTimeout(() => {
      timedOut = true;
      send("tool:log", { label, text: "\n[超时] 已强制终止\n" });
      killChild();
    }, timeoutMs);

    ps.on("error", (err) => {
      if (childTimer) clearTimeout(childTimer);
      child = null;
      resolve({ ok: false, code: -1, out, timedOut, error: String(err && err.message) });
    });

    ps.on("close", (code) => {
      if (childTimer) clearTimeout(childTimer);
      child = null;
      resolve({ ok: !timedOut && code === 0, code: code == null ? -1 : code, out, timedOut });
    });
  });
}

// ---------- 已安装状态 ----------

/** 读 config.toml 判断 Codex 当前注入的是哪一版（对应 Python 版 _active_prompt_file）。 */
/** Codex 各版本都会往 <CodexHome>\AGENTS.md 写带标记的注入块，标记行里带着提示词文件名。 */
const CODEX_PROMPT_NAMES = [
  ...Object.keys(ASTRA_PROMPT_FILES),
  "寒霜v5.md",
  "寒霜v4.md",
  "寒霜v3.md",
  "寒霜-变体B-v3-英文.md",
  "寒霜v1.2.md",
];

function agentsPromptFile() {
  let text = "";
  try {
    text = fs.readFileSync(path.join(codexHome(),"AGENTS.md"), "utf8");
  } catch {
    return null;
  }
  // 兼容早先写下的「寒霜破甲 V5 注入开始 · x.md」与现在的「寒霜破甲注入开始 · x.md」
  const m = text.match(/<!--[^\n]*寒霜破甲[^\n]*注入开始[^\n]*-->/);
  if (!m) return null;
  for (const name of CODEX_PROMPT_NAMES) {
    if (m[0].includes(name)) return name;
  }
  return null;
}

function activePromptFile() {
  const cp = path.join(codexHome(),"config.toml");
  let text = "";
  try {
    text = fs.readFileSync(cp, "utf8");
  } catch {
    text = "";
  }
  for (const name of CODEX_PROMPT_NAMES) {
    if (text.includes(name)) return name;
  }
  // config.toml 里没有（Codex 重写 config.toml 会丢掉 model_instructions_file 行），
  // 再认 AGENTS.md 的注入块
  return agentsPromptFile();
}

const PROMPT_LABEL = {
  // V5 双提示词：版本标识与磁盘文件名都要能映射到同一个展示名
  "codex-astra-6": ASTRA_PROMPTS["codex-astra-6"].label,
  "codex-astra-56": ASTRA_PROMPTS["codex-astra-56"].label,
  "gpt-6-astra-v1.md": ASTRA_PROMPTS["codex-astra-6"].label,
  "gpt-5.6-sol-unrestricted-v45.md": ASTRA_PROMPTS["codex-astra-56"].label,
  // 付费版对外统一叫「付费版v1」，不暴露内部版本号
  "寒霜v5.md": VARIANT === "pro" ? "付费版v1" : "V5",
  "寒霜v4.md": "V4",
  "寒霜v3.md": "V3",
  "寒霜v1.2.md": "V2",
  "寒霜-变体B-v3-英文.md": "v1",
};

function loadState() {
  const st = readJson(statePath(), {});
  return {
    installed: st.installed || {},
    autoInstall: !!st.autoInstall,
  };
}

function saveState(patch) {
  const st = loadState();
  const next = { ...st, ...patch };
  writeJson(statePath(), next);
  return next;
}

function installedSnapshot() {
  const st = loadState();
  // Codex 以 config.toml 为准；其余用上次成功安装的记录
  const codexFile = activePromptFile();
  if (codexFile) st.installed.codex = PROMPT_LABEL[codexFile] || true;
  else delete st.installed.codex;
  return st;
}

// ---------- skills ----------

function skillsDir() {
  return path.join(codexHome(),"skills");
}

function configToml() {
  return path.join(codexHome(),"config.toml");
}

/** 解析 [[skills.config]] 块，返回被禁用的 skill 目录名集合。 */
function readDisabledSkills() {
  const disabled = new Set();
  let text = "";
  try {
    text = fs.readFileSync(configToml(), "utf8");
  } catch {
    return disabled;
  }
  const blocks = text.split(/^\[\[skills\.config\]\]\s*$/m);
  for (const blk of blocks.slice(1)) {
    const mp = blk.match(/^\s*path\s*=\s*"([^"]+)"/m);
    if (!mp) continue;
    const me = blk.match(/^\s*enabled\s*=\s*(true|false)/m);
    const enabled = me ? me[1] === "true" : true;
    if (enabled) continue;
    const parts = mp[1].replace(/\\/g, "/").split("/");
    const name = parts[parts.length - 2];
    if (name) disabled.add(name);
  }
  return disabled;
}

function writeDisabledSkills(disabled) {
  const cp = configToml();
  let text;
  try {
    text = fs.readFileSync(cp, "utf8");
  } catch {
    return { ok: false, error: "找不到 config.toml" };
  }
  text = text.replace(/^\[\[skills\.config\]\]\s*$[\s\S]*?(?=^\[\[|$)/gm, "");
  text = text.replace(/\s+$/, "") + "\n";
  for (const name of [...disabled].sort()) {
    const sk = path.join(skillsDir(), name, "SKILL.md").replace(/\\/g, "/");
    text += `\n[[skills.config]]\npath = "${sk}"\nenabled = false\n`;
  }
  try {
    fs.writeFileSync(cp, text, "utf8");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e.message) };
  }
}

function listSkills() {
  const dir = skillsDir();
  const disabled = readDisabledSkills();
  let names = [];
  try {
    names = fs.readdirSync(dir, { withFileTypes: true })
      .filter((d) => d.isDirectory() && fs.existsSync(path.join(dir, d.name, "SKILL.md")))
      .map((d) => d.name)
      .sort();
  } catch {
    return [];
  }
  return names.map((name) => {
    let desc = "";
    try {
      const head = fs.readFileSync(path.join(dir, name, "SKILL.md"), "utf8").slice(0, 600);
      const m = head.match(/description:\s*(.+)/);
      if (m) desc = m[1].trim().slice(0, 120);
    } catch {
      /* ignore */
    }
    return { name, desc, enabled: !disabled.has(name) };
  });
}

// ---------- 压缩守护 ----------
// 轮询 ~/.codex/sessions 下的 rollout-*.jsonl：命中压缩标记，或文件体积骤降，
// 就提示用户重新发激活词。逻辑对齐 fj_tool.py 的 CompactionWatcher。

const COMPACT_MARKERS = [
  "compacted",
  "compaction",
  "summary of the conversation",
  "conversation summary",
  "对话已压缩",
  "上下文已压缩",
  "对话摘要",
];

const sessionsDir = () => path.join(codexHome(),"sessions");

class CompactionWatcher {
  constructor() {
    this.known = new Map(); // path -> { size, pos }
    this.drop = new Map(); // path -> [size, remainingPolls]
    this.timer = null;
  }

  start() {
    this.timer = setInterval(() => this.poll(), 5000);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  files() {
    const root = sessionsDir();
    const out = [];
    const walk = (dir) => {
      let entries;
      try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
      } catch {
        return;
      }
      for (const e of entries) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full);
        else if (e.name.startsWith("rollout-") && e.name.endsWith(".jsonl")) out.push(full);
      }
    };
    walk(root);
    return out;
  }

  hasMarker(text) {
    for (const line of text.split("\n")) {
      if (!/"role"\s*:\s*"system"/.test(line)) continue;
      const low = line.toLowerCase();
      if (COMPACT_MARKERS.some((m) => low.includes(m))) return true;
    }
    return false;
  }

  poll() {
    try {
      for (const p of this.files()) {
        let st;
        try {
          st = fs.statSync(p);
        } catch {
          continue;
        }
        const size = st.size;
        const prev = this.known.get(p);
        if (!prev) {
          this.known.set(p, { size, pos: size });
          continue;
        }
        let emit = false;
        if (size > prev.pos) {
          try {
            const fd = fs.openSync(p, "r");
            const len = size - prev.pos;
            const buf = Buffer.alloc(len);
            fs.readSync(fd, buf, 0, len, prev.pos);
            fs.closeSync(fd);
            if (this.hasMarker(buf.toString("utf8"))) emit = true;
          } catch {
            /* ignore */
          }
        }
        if (!emit) {
          if (prev.size > 20000 && size > 0 && size < prev.size * 0.6) {
            this.drop.set(p, [size, 6]);
          } else if (this.drop.has(p)) {
            const d = this.drop.get(p);
            if (size <= d[0]) {
              emit = true;
              this.drop.delete(p);
            } else if (--d[1] <= 0) {
              this.drop.delete(p);
            }
          }
        }
        if (emit) {
          send("tool:notify", {
            level: "warn",
            text: "检测到上下文已压缩 — 重新发一次「寒霜」即可重新激活。",
          });
        }
        this.known.set(p, { size, pos: size });
      }
      for (const p of [...this.known.keys()]) {
        if (!fs.existsSync(p)) {
          this.known.delete(p);
          this.drop.delete(p);
        }
      }
    } catch {
      /* ignore */
    }
  }
}

// ---------- WorkBuddy 云记忆守护 ----------
// WorkBuddy 会把 memoryBlock 回写成空，导致注入被冲掉；这里定期比对并补写。

class WorkBuddyGuard {
  constructor() {
    this.timer = null;
    this.blockRe = /## Memory Block\r?\n\r?\n([\s\S]*?)\r?\n\r?\n---/;
  }

  start() {
    this.timer = setInterval(() => this.check(), 45000);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  state() {
    for (const name of [".workbuddy-ai", ".workbuddy"]) {
      const p = path.join(homeDir(), name, ".hanshuang-state.json");
      if (fs.existsSync(p)) return readJson(p, null);
    }
    return null;
  }

  setReadonly(target, ro) {
    try {
      fs.chmodSync(target, ro ? 0o444 : 0o666);
    } catch {
      /* ignore */
    }
  }

  targets(st) {
    const list = (st.archives || []).filter(Boolean);
    const one = st.archive || "";
    if (one && !list.includes(one)) list.push(one);
    const memDir = st.memoryDir || (list[0] ? path.dirname(list[0]) : "");
    if (memDir && fs.existsSync(memDir)) {
      try {
        for (const n of fs.readdirSync(memDir)) {
          if (n.endsWith("_memory.md") && !n.includes(".bak")) {
            const p = path.join(memDir, n);
            if (!list.includes(p)) list.push(p);
          }
        }
      } catch {
        /* ignore */
      }
    }
    return list;
  }

  write(arch, block, st) {
    const now = new Date().toISOString().replace(/\.\d+Z$/, ".000Z");
    const ver = st.version ?? 999999;
    let uid = st.uid || "";
    if (fs.existsSync(arch)) {
      try {
        const m = fs.readFileSync(arch, "utf8").match(/"uid"\s*:\s*"([^"]+)"/);
        if (m) uid = m[1];
      } catch {
        /* ignore */
      }
    }
    if (!uid) uid = path.basename(arch).replace("_memory.md", "");
    const profile = { uid, memoryBlock: block, updatedAt: now, version: ver };
    const md =
      `# User Memory Profile\n> Last updated: ${now}\n> Version: ${ver}\n\n` +
      `## Memory Block\n\n${block}\n\n---\n\n` +
      `<!-- RAW_JSON_START\n${JSON.stringify(profile, null, 2)}\nRAW_JSON_END -->\n`;
    fs.mkdirSync(path.dirname(arch), { recursive: true });
    if (fs.existsSync(arch)) this.setReadonly(arch, false);
    fs.writeFileSync(arch, md, "utf8");
    this.setReadonly(arch, true);
  }

  check() {
    const st = this.state();
    if (!st || !st.prompt) return;
    const src = p(st.prompt);
    if (!fs.existsSync(src)) return;
    let block;
    try {
      block = fs.readFileSync(src, "utf8");
    } catch {
      return;
    }
    let fixed = 0;
    for (const arch of this.targets(st)) {
      let cur = "";
      if (fs.existsSync(arch)) {
        try {
          cur = fs.readFileSync(arch, "utf8");
        } catch {
          cur = "";
        }
      }
      const m = this.blockRe.exec(cur);
      if (m && m[1].trim() === block.trim()) continue;
      try {
        this.write(arch, block, st);
        fixed += 1;
      } catch {
        /* ignore */
      }
    }
    if (fixed) {
      send("tool:notify", {
        level: "info",
        text: `检测到 WorkBuddy 云记忆被回写/缺失，已自动补注入 ${fixed} 个档案。`,
      });
    }
  }
}

const compactionWatcher = new CompactionWatcher();
const workBuddyGuard = new WorkBuddyGuard();

// ---------- IPC ----------

function registerIpc() {
  ipcMain.handle("tool:state", () => ({
    installed: installedSnapshot().installed,
    autoInstall: loadState().autoInstall,
    version: app.getVersion(),
  }));

  ipcMain.handle("tool:install", async (_e, targetId, promptFile) => {
    let args;
    try {
      args = installArgs(targetId, promptFile);
    } catch (e) {
      // 参数准备失败（比如随包提示词缺失）也要回一个完整结果，界面才好显示原因
      const msg = String((e && e.message) || e);
      send("tool:log", { label: `安装 ${targetId}`, text: "\n[错误] " + msg + "\n" });
      return {
        ok: false,
        code: -1,
        out: msg,
        timedOut: false,
        error: msg,
        installed: installedSnapshot().installed,
      };
    }
    const res = await runPowerShell(args, `安装 ${targetId}`, INSTALL_TIMEOUT);
    if (res.ok) {
      const st = loadState();
      st.installed[targetId] = PROMPT_LABEL[promptFile] || true;
      saveState({ installed: st.installed });
    }
    return { ...res, installed: installedSnapshot().installed };
  });

  ipcMain.handle("tool:uninstall", async (_e, targetId) => {
    const res = await runPowerShell(uninstallArgs(targetId), `卸载 ${targetId}`, UNINSTALL_TIMEOUT);
    if (res.ok) {
      const st = loadState();
      delete st.installed[targetId];
      saveState({ installed: st.installed });
    }

    // 兜底清扫：**不依赖 install*.ps1 的卸载结果**，无条件执行。
    //
    // install*.ps1 的卸载靠 <Home>\managed-prompts\install-state.json 记录该删哪些提示词。
    // state 一旦不在了（被清理工具删过、用户手工删过、上次卸载删掉了），提示词就留在盘上
    // 没人管 —— 实测本机 5 个提示词 + 几个 .mdc 就是这么残留的。
    //
    // 而且卸载脚本自己也可能失败（文件被占用、权限不足、脚本报错）。早期写法把这一步
    // 放在 `if (res.ok)` 里面，于是「卸载脚本失败 ⇒ 兜底也不跑 ⇒ 提示词原样留着」——
    // 偏偏那正是最需要兜底的时候。「点卸载 = 提示词清干净」是硬要求，所以移到这里。
    //
    // 这一步按注入点和副产物直接扫，只清提示词，用户的 AGENTS.md / CLAUDE.md /
    // config.toml / 自己的备份一律不动（详见脚本头部注释）。
    const sweep = await runPowerShell(
      clearPromptsArgs(targetId),
      `清理 ${targetId} 提示词残留`,
      UNINSTALL_TIMEOUT,
    );
    res.out = (res.out || "") + "\n" + (sweep.out || "");
    if (!sweep.ok) {
      res.ok = false;
      res.error = sweep.error || "提示词残留清理失败";
    }
    return { ...res, installed: installedSnapshot().installed };
  });

  ipcMain.handle("tool:restartCodex", async () => {
    const cmd =
      "$ErrorActionPreference = 'SilentlyContinue'; " +
      "$appId = (Get-StartApps | Where-Object { $_.AppID -like 'OpenAI.Codex*' } | Select-Object -First 1 -ExpandProperty AppID); " +
      "$chat = @(Get-Process ChatGPT | Where-Object { $_.Path -like '*OpenAI.Codex*' }); " +
      "$chat | Stop-Process -Force; " +
      "$cx = @(Get-Process codex -ErrorAction SilentlyContinue); " +
      "$cx | Stop-Process -Force; " +
      "Start-Sleep -Milliseconds 1200; " +
      "if (-not $appId) { Write-Output 'no-appid'; exit 0 } " +
      // 直接 Start-Process shell:AppsFolder 拉起；多套一层 explorer.exe -ArgumentList 实测不可靠
      "Start-Process ('shell:AppsFolder\\' + $appId); " +
      // 等应用真起来再回话，避免「命令发出去了但其实没启动」也算成功
      "for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 500; if (@(Get-Process ChatGPT).Count -gt 0) { break } } " +
      "Write-Output ('launched:' + $appId + ' procs:' + @(Get-Process ChatGPT).Count)";
    return new Promise((resolve) => {
      /*
        这里不能带 detached: true。Windows 上 detached 走 DETACHED_PROCESS，
        powershell 失去控制台后会在 ~100ms 内直接退出、命令一行都不执行
        （实测：带 detached 时 stdout 为空、94ms 退出；去掉后 900ms 正常返回），
        表现就是点「重启 Codex」毫无反应。父进程 await close 即可，无需 detach。
      */
      const ps = spawn("powershell.exe", ["-NoProfile", "-Command", cmd], { windowsHide: true });
      let out = "";
      ps.stdout.on("data", (buf) => (out += buf.toString("utf8")));
      ps.stderr.on("data", (buf) => (out += buf.toString("utf8")));
      ps.on("close", (code) => {
        const text = out.trim();
        const launched = /^launched:/m.test(text);
        resolve({
          ok: code === 0 && launched,
          code: code == null ? -1 : code,
          out: text,
          // 没找到 AppID 时给一句能看懂的话，而不是把失败也报成「重启指令已发送」
          error: launched ? undefined : text || "未找到 Codex 应用（Get-StartApps 无 OpenAI.Codex* 条目）",
        });
      });
      ps.on("error", (e) => resolve({ ok: false, code: -1, out, error: String(e && e.message) }));
    });
  });

  ipcMain.handle("tool:skills:list", () => listSkills());
  ipcMain.handle("tool:skills:save", (_e, disabled) => writeDisabledSkills(disabled || []));

  ipcMain.handle("tool:autoInstall", (_e, value) => saveState({ autoInstall: !!value }));

  ipcMain.handle("tool:openQQ", async (_e, url) => {
    if (typeof url !== "string" || !/^https?:\/\//.test(url)) {
      console.log("[openQQ] 拒绝非 http(s) 链接:", url);
      return { ok: false, error: "invalid url" };
    }
    try {
      await shell.openExternal(url);
      console.log("[openQQ] 已用系统浏览器打开:", url.slice(0, 60) + "…");
      return { ok: true };
    } catch (e) {
      console.log("[openQQ] 打开失败:", String(e && e.message));
      return { ok: false, error: String(e && e.message) };
    }
  });

  ipcMain.handle("tool:quit", () => {
    app.quit();
    return { ok: true };
  });

  ipcMain.handle("tool:win", (_e, action) => {
    if (!win) return { ok: false };
    if (action === "minimize") win.minimize();
    else if (action === "maximize") win.isMaximized() ? win.unmaximize() : win.maximize();
    else if (action === "close") win.close();
    return { ok: true };
  });
}

// ---------- 窗口 ----------

function createWindow() {
  win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 940,
    minHeight: 620,
    show: false,
    backgroundColor: "#ffffff",
    title: APP_NAME,
    /*
      用系统原生标题栏。之前用 titleBarStyle:"hidden" 自绘拖拽条，
      在 Windows 上导致窗口拖不动、且只有上下边能缩放；原生边框两个问题都没有。
    */
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  /*
    显示窗口。只挂 ready-to-show 并不可靠：窗口以 show:false 创建时，若
    Chromium 判定窗口被遮挡 / 未激活，首帧可能迟迟不画，ready-to-show 就
    不触发，结果是进程活着但永远没有窗口。这里三重兜底。
  */
  const showOnce = () => {
    if (win && !win.isDestroyed() && !win.isVisible()) win.show();
  };
  win.once("ready-to-show", showOnce);
  win.webContents.once("did-finish-load", showOnce);
  setTimeout(showOnce, 1200);

  // 默认加载构建产物；只有显式 HS_DEV=1 时才连 Vite 开发服务器。
  if (!app.isPackaged && process.env.HS_DEV) {
    win.loadURL("http://localhost:5273");
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  // 关窗只收进托盘（与 Python 版一致）；真正退出走托盘菜单或 app.quit()
  win.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      win.hide();
    }
  });

  win.on("closed", () => {
    win = null;
  });

  // 开发用：把渲染进程的 console / 未捕获异常转发到终端
  if (process.env.HS_CAPTURE || process.env.HS_DEBUG) {
    win.webContents.on("console-message", (_e, lvl, msg, line, src) => {
      console.log("[renderer:%s] %s (%s:%s)", lvl, msg, src, line);
    });
    win.webContents.on("render-process-gone", (_e, d) => {
      console.log("[renderer gone]", JSON.stringify(d));
    });
    win.webContents.on("did-fail-load", (_e, code, desc) => {
      console.log("[load failed]", code, desc);
    });
  }

  // 开发用：HS_CAPTURE=<dir> 时逐页截图后退出，用于验收版式。
  if (process.env.HS_CAPTURE) {
    win.webContents.once("did-finish-load", () => {
      captureAll(process.env.HS_CAPTURE).catch(() => app.quit());
    });
  }
}

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function captureAll(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const nav = (i) => `document.querySelectorAll(".settings-nav-scroll .settings-nav-item")[${i}].click()`;
  // 索引跟随 data/targets.ts 的目标顺序；工具组固定排在目标组之后
  const shots = [
    ["codex", null],
    ["zcode", nav(1)],
    ["workbuddy", nav(4)],
    ["dsh", nav(6)],
    ["omp", nav(8)],
    ["skills", nav(9)],
    ["tutorial", nav(10)],
    ["profile", 'document.querySelector(".app-nav-foot .settings-nav-item").click()'],
  ];
  // 截图前确保窗口真正可见并聚焦，否则 Chromium 会冻结 CSS 动画时间线
  try {
    win.show();
    win.focus();
    win.moveTop();
  } catch {
    /* ignore */
  }
  await wait(2000);
  if (process.env.HS_QQTEST) {
    const r = await win.webContents.executeJavaScript(
      'window.hs.openQQ("https://qun.qq.com/universal-share/share?ac=1&authKey=test")',
    );
    console.log("[qqtest] openQQ ->", JSON.stringify(r));
  }
  if (process.env.HS_DOM) {
    console.log(
      "[vis]",
      await win.webContents.executeJavaScript(
        "document.visibilityState + ' hidden=' + document.hidden",
      ),
    );
  }
  if (process.env.HS_DOM) {
    const info = await win.webContents.executeJavaScript(`(() => {
      const r = document.getElementById("root");
      const cs = r ? getComputedStyle(r) : null;
      return JSON.stringify({
        rootChildren: r ? r.children.length : -1,
        rootHTML: r ? r.innerHTML.slice(0, 400) : "",
        rootBox: r ? [r.clientWidth, r.clientHeight] : null,
        bodyBox: [document.body.clientWidth, document.body.clientHeight],
        rootDisplay: cs ? cs.display : null,
        probe: [".app-shell", ".settings-shell-full", ".settings-nav", ".settings-content",
                ".settings-section-title", ".settings-card-heading"].map(sel => {
          const el = document.querySelector(sel);
          if (!el) return sel + " => MISSING";
          const c = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          return sel + " rect=" + Math.round(r.width) + "x" + Math.round(r.height) +
                 " disp=" + c.display + " vis=" + c.visibility + " op=" + c.opacity +
                 " color=" + c.color + " bg=" + c.backgroundColor +
                 " anim=" + c.animationName + " fs=" + c.fontSize;
        }),
        cssVars: ["--ds-text-primary","--ds-bg-primary","--text-md","--radius-md","--ds-accent"]
          .map(v => v + "=" + getComputedStyle(document.documentElement).getPropertyValue(v).trim()),
        scripts: [...document.scripts].map(s => s.src),
        sheets: [...document.styleSheets].length,
      });
    })()`);
    console.log("[dom]", info);
  }
  // 先同意免责声明，否则遮罩挡住后面的交互
  await win.webContents.executeJavaScript(
    'document.querySelector(".dialog .btn-primary")?.click(), true',
  );
  await wait(400);

  // 开发用：HS_INSTALLTEST=<targetId> 时在界面上真点一次「安装」，把状态与日志抓回来
  if (process.env.HS_INSTALLTEST) {
    const target = process.env.HS_INSTALLTEST;
    const navIdx = { codex: 0, zcode: 1, cursor: 2, claude: 3, workbuddy: 4, dsh: 5 }[target];
    if (navIdx !== undefined) {
      await win.webContents.executeJavaScript(
        `document.querySelectorAll(".settings-nav-scroll .settings-nav-item")[${navIdx}].click(), true`,
      );
      await wait(600);
    }
    // HS_PROMPTTEST=<版本名片段>：先选中对应版本，再点安装/卸载
    if (process.env.HS_PROMPTTEST) {
      const picked = await win.webContents.executeJavaScript(`(() => {
        const want = ${JSON.stringify(process.env.HS_PROMPTTEST)};
        const row = [...document.querySelectorAll(".settings-panel .settings-row")].find((r) => r.textContent.includes(want));
        if (row) row.click();
        return !!row;
      })()`);
      console.log("[installtest] 选中版本 " + process.env.HS_PROMPTTEST + " -> " + picked);
      await wait(400);
    }
    await win.webContents.executeJavaScript(`(() => {
      const btns = [...document.querySelectorAll(".app-inline-actions .btn")];
      const btn = ${process.env.HS_UNINSTALLTEST ? 'btns.find((b) => /卸载/.test(b.textContent))' : 'btns.find((b) => /安装/.test(b.textContent) && !/卸载|重启/.test(b.textContent))'};
      if (btn) btn.click();
      return !!btn;
    })()`);

    // HS_CHOICETEST=<名称片段>：V5 双提示词弹框里选中那一份再确认（截图留证）
    if (process.env.HS_CHOICETEST) {
      await wait(700);
      const info = await win.webContents.executeJavaScript(`(() => {
        const rows = [...document.querySelectorAll(".overlay .settings-row")];
        const row = rows.find((r) => r.textContent.includes(${JSON.stringify(process.env.HS_CHOICETEST)}));
        if (row) row.click();
        return JSON.stringify({
          rows: rows.map((r) => r.querySelector(".settings-row-title").textContent.trim()),
          picked: !!row,
        });
      })()`);
      console.log("[choicetest] 弹框选项 " + info);
      const shot = await win.webContents.capturePage();
      fs.writeFileSync(path.join(dir, "v5-choice-dialog.png"), shot.toPNG());
      const confirmed = await win.webContents.executeJavaScript(`(() => {
        const ok = [...document.querySelectorAll(".overlay .app-inline-actions .btn")]
          .find((b) => /^安装/.test(b.textContent.trim()));
        if (ok) ok.click();
        return ok ? ok.textContent.trim() : false;
      })()`);
      console.log("[choicetest] 确认 -> " + confirmed);
    }
    await wait(25000);
    const state = await win.webContents.executeJavaScript(`(() => {
      const descs = [...document.querySelectorAll(".settings-card-description")];
      const badge = document.querySelector(".badge-success, .badge-neutral");
      const pre = document.querySelector(".app-pre");
      const btn = [...document.querySelectorAll(".app-inline-actions .btn")].find((b) => /安装|执行中/.test(b.textContent));
      return JSON.stringify({
        status: descs.length ? descs[descs.length - 1].textContent.trim().slice(0, 200) : "(无)",
        badge: badge ? badge.textContent.trim().slice(0, 40) : "(无)",
        button: btn ? btn.textContent.trim() : "(无)",
        log: pre ? pre.textContent.trim().slice(-500) : "(无日志)",
      });
    })()`);
    console.log("[installtest] " + target + " -> " + state);
  }

  // 开发用：HS_SKILLTEST=1 时点一次「保存」并断言全局提示出现（验收 Skills 保存反馈）
  if (process.env.HS_SKILLTEST) {
    await win.webContents.executeJavaScript(
      'document.querySelectorAll(".settings-nav-scroll .settings-nav-item")[6].click(), true',
    );
    await wait(500);
    const clicked = await win.webContents.executeJavaScript(`(() => {
      const btns = [...document.querySelectorAll(".app-inline-actions .btn")];
      const save = btns.find((b) => b.textContent.trim() === "保存");
      if (!save) return "NO_SAVE_BUTTON";
      save.click();
      return "CLICKED";
    })()`);
    await wait(1200);
    const toast = await win.webContents.executeJavaScript(
      '(() => { const t = document.querySelector(".toast"); return t ? t.textContent.trim() : "NO_TOAST"; })()',
    );
    console.log("[skilltest] 点击=" + clicked + " 提示=" + toast);
    const img = await win.webContents.capturePage();
    fs.writeFileSync(path.join(dir, "skills-save-toast.png"), img.toPNG());
  }
  for (const [name, js] of shots) {
    if (js) {
      await win.webContents.executeJavaScript(js + ", true");
      await wait(450);
    }
    const img = await win.webContents.capturePage();
    fs.writeFileSync(path.join(dir, name + ".png"), img.toPNG());
  }
  app.quit();
}

/** 显示窗口；若之前已被销毁则重建。托盘点击、菜单、第二实例都走这里。 */
function showWindow() {
  if (!win || win.isDestroyed()) {
    createWindow();
    return;
  }
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function makeTrayIcon() {
  // 与安装包图标同一张图；打包后在 resources/icon.png，开发时在 build/
  const candidates = [
    path.join(process.resourcesPath || "", "icon.png"),
    path.join(__dirname, "..", "build", "icon-256.png"),
  ];
  for (const f of candidates) {
    try {
      if (f && fs.existsSync(f)) {
        const img = nativeImage.createFromPath(f);
        if (!img.isEmpty()) return img;
      }
    } catch {
      /* 落到下面的兜底 */
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">
    <rect width="32" height="32" rx="7" fill="#2E8FE0"/>
    <text x="16" y="23" font-size="20" text-anchor="middle" fill="#ffffff">寒</text>
  </svg>`;
  return nativeImage.createFromDataURL(
    "data:image/svg+xml;base64," + Buffer.from(svg, "utf8").toString("base64"),
  );
}

function setupTray() {
  try {
    tray = new Tray(makeTrayIcon());
    tray.setToolTip(APP_NAME);
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: "显示主界面", click: () => showWindow() },
        { type: "separator" },
        { label: "退出", click: () => app.quit() },
      ]),
    );
    tray.on("click", () => showWindow());
  } catch {
    tray = null;
  }
}

// ---------- 生命周期 ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showWindow();
  });

  app.whenReady().then(() => {
    registerIpc();
    createWindow();
    setupTray();
    compactionWatcher.start();
    workBuddyGuard.start();
  });

  app.on("window-all-closed", () => {
    // 托盘常驻：关掉窗口不退出应用
    if (!tray) app.quit();
  });

  app.on("before-quit", () => {
    quitting = true;
    killChild();
    compactionWatcher.stop();
    workBuddyGuard.stop();
    if (tray) {
      tray.destroy();
      tray = null;
    }
  });

  app.on("activate", () => showWindow());
}
