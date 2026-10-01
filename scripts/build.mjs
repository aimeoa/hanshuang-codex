#!/usr/bin/env node
/*
  变体构建脚本（Windows + macOS）。

  用法：
    node scripts/build.mjs                       # 按当前平台构建 free 变体
    node scripts/build.mjs free                  # 同上
    node scripts/build.mjs pro                   # 付费版：只提供 V5
    node scripts/build.mjs free mac              # 显式指定平台
    node scripts/build.mjs free mac x64          # 指定架构（默认 arm64）

  两个变体共用同一份源码，靠写入 variant.json 区分：
  主进程读它决定窗口/托盘标题，渲染层读它决定版本表与品牌名。
  产物落到 release/，appId / 应用名 / 图标都不同，因此两个版本可以并存安装。

  注意：变体配置写成 JSON 文件再交给 electron-builder，不走命令行参数——
  Windows 下中文经 cmd.exe 传参会损坏。
*/
import { execFileSync } from "node:child_process";
import {
  readFileSync,
  writeFileSync,
  rmSync,
  readdirSync,
  existsSync,
  mkdtempSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = join(dirname(fileURLToPath(import.meta.url)), "..");

// 独立项目：不带参数时直接读 variant.json，本文件夹只产出自己那个变体
const variant =
  process.argv[2] || JSON.parse(readFileSync(join(appDir, "variant.json"), "utf8")).variant;

// 平台默认取当前系统：Windows 出 exe，macOS 出 dmg/app
const HOST = process.platform === "win32" ? "win" : "mac";
const platform = process.argv[3] || HOST;
if (!["win", "mac"].includes(platform)) {
  console.error("用法: node scripts/build.mjs <free|pro> [win|mac] [arm64|x64]");
  process.exit(1);
}
const arch = process.argv[4] || "";
const isMac = platform === "mac";

/** 界面左上角与个人中心展示的版本号（与安装包文件名的版本无关）。 */
const DISPLAY_VERSION = "1.0";

const VARIANTS = {
  free: {
    appName: "寒霜破甲工具",
    appId: "com.hanshuang.desktop",
    output: "release",
    icon: "build/icon.png",
    artifact: "寒霜破甲工具-安装版-${version}.${ext}",
  },
  pro: {
    appName: "寒霜破甲工具 Pro",
    appId: "com.hanshuang.desktop.pro",
    output: "release",
    icon: "build/icon-pro.png",
    artifact: "寒霜破甲工具Pro-安装版-${version}.${ext}",
  },
};

const cfg = VARIANTS[variant];
if (!cfg) {
  console.error("用法: node scripts/build.mjs <free|pro> [win|mac]");
  process.exit(1);
}

// 1) 写变体标记（主进程与渲染层都读这个文件）
writeFileSync(
  join(appDir, "variant.json"),
  JSON.stringify({ variant, appName: cfg.appName, version: DISPLAY_VERSION }, null, 2) + "\n",
  "utf8",
);
console.log(
  `[build] 变体 = ${variant}（${cfg.appName}） 平台 = ${platform}${arch ? " 架构 = " + arch : ""}`,
);

// Windows 下走 cmd.exe，带空格的参数必须自己加引号，否则会被拆成多个参数
// （项目文件夹名里可能带空格，比如「寒霜破甲工具 Pro」）
const quote = (a) => (/\s/.test(a) ? `"${a}"` : a);
const run = (args) =>
  execFileSync("npx", args.map(quote), {
    cwd: appDir,
    stdio: "inherit",
    shell: process.platform === "win32",
  });

/** 直接跑系统命令（macOS 上的 codesign / ditto 用）。 */
const runBin = (bin, args) => execFileSync(bin, args, { cwd: appDir, stdio: "inherit" });

/**
  electron-builder 打 DMG 时会执行 `which python`。macOS 从 12.3 起不再自带 python
  （只有 python3），这一步直接退出码 1、整个构建中断 —— 现象很迷惑：.app 和 zip
  都已经产出了，唯独 dmg 没了，报错还只有一句 `Command failed: which python`。

  这里在临时目录补一个 `python` → python3 的转发脚本，只影响本次构建派生的子进程，
  构建结束就删掉，不往用户环境里装任何东西。
*/
let pyShimDir = "";
function ensurePythonShim() {
  if (!isMac) return;
  try {
    execFileSync("which", ["python"], { stdio: "ignore" });
    return; // 系统里已经有 python，不用管
  } catch {
    /* 没有，继续补 shim */
  }
  const candidates = [
    "/opt/homebrew/bin/python3", // Apple Silicon Homebrew
    "/usr/local/bin/python3", // Intel Homebrew
    "/usr/bin/python3", // 系统自带（可能被 Xcode 许可协议拦住）
  ];
  let py3 = null;
  for (const c of candidates) {
    if (!existsSync(c)) continue;
    try {
      execFileSync(c, ["-c", "print(1)"], { stdio: "ignore" });
      py3 = c;
      break;
    } catch {
      /* 这个 python3 跑不起来，试下一个 */
    }
  }
  if (!py3) {
    console.log("[build] 警告：找不到可用的 python3，DMG 目标大概率会失败");
    return;
  }
  pyShimDir = mkdtempSync(join(tmpdir(), "hs-py-"));
  const shim = join(pyShimDir, "python");
  writeFileSync(shim, `#!/bin/sh\nexec "${py3}" "$@"\n`, { mode: 0o755 });
  process.env.PATH = pyShimDir + ":" + process.env.PATH;
  console.log(`[build] 系统没有 python 命令，已临时补 shim: python -> ${py3}`);
}

/** 清掉临时 shim 目录。 */
function cleanupPythonShim() {
  if (pyShimDir) {
    rmSync(pyShimDir, { recursive: true, force: true });
    pyShimDir = "";
  }
}

// 2) 构建渲染层
run(["vite", "build"]);

// 3) 由 package.json 的 build 段派生本变体的完整配置
const pkg = JSON.parse(readFileSync(join(appDir, "package.json"), "utf8"));
const base = pkg.build || {};
const buildCfg = {
  ...base,
  appId: cfg.appId,
  productName: cfg.appName,
  // 不在这里统设 artifactName：那会把 nsis / portable 两个目标压成同一个
  // 文件名互相覆盖。各自的命名写在 package.json 的 nsis / portable / dmg 段里。
  directories: { ...(base.directories || {}), output: cfg.output },
  // 打完应用目录、生成安装器之前跑：Windows 上写 exe 图标，macOS 上放卸载脚本
  afterPack: "scripts/after-pack.js",
};

if (isMac) {
  /*
    macOS 不需要 NSIS/portable 那套（也就没有 rcedit 写 exe 图标那一步），
    把 Windows 专有段从派生配置里摘掉，生成的配置文件和实际构建内容对得上。

    identity: null = 不找开发者证书、不签名。本机自用没问题；真要分发再换成
    自己的 Developer ID 并打开 hardenedRuntime + notarize。
    注意 Apple Silicon 上未签名的可执行文件会被内核直接杀掉，所以下面打包完
    会补一次 ad-hoc 签名（codesign --sign -）。
  */
  delete buildCfg.win;
  delete buildCfg.nsis;
  delete buildCfg.portable;
  buildCfg.mac = { ...(base.mac || {}), icon: cfg.icon, identity: null };

  /*
    electron-builder 默认会自己去 GitHub Releases 下 100MB 的 Electron 发行版，
    国内网络下这个下载经常 EOF 中断（实测直接卡死整个构建）。
    而 npm install 时 electron 包已经下好了一份完全同版本的发行版在
    node_modules/electron/dist，直接指过去，一次网络请求都不用发。
  */
  const localDist = join(appDir, "node_modules", "electron", "dist");
  if (existsSync(localDist)) {
    buildCfg.electronDist = localDist;
    console.log("[build] 复用本地 Electron 发行版:", localDist);
  } else {
    console.log("[build] 未找到本地 Electron 发行版，将走网络下载");
  }
} else {
  // 生成 .ico（rcedit 只认 ico；afterPack 钩子会用它写进 exe）
  const png = join(appDir, cfg.icon);
  const ico = png.replace(/\.png$/, ".ico");
  try {
    execFileSync("python", [join(appDir, "scripts", "make-ico.py"), png, ico], {
      cwd: appDir,
      stdio: "inherit",
    });
  } catch (e) {
    console.error("[build] 生成 ico 失败，exe 图标将保持不变:", String(e && e.message));
  }
  buildCfg.win = { ...(base.win || {}), icon: cfg.icon };
  buildCfg.nsis = {
    ...(base.nsis || {}),
    shortcutName: cfg.appName,
    uninstallDisplayName: cfg.appName,
    artifactName: cfg.artifact,
  };
}

const cfgFile = join(appDir, `.electron-builder.${variant}.${platform}.json`);
writeFileSync(cfgFile, JSON.stringify(buildCfg, null, 2) + "\n", "utf8");

ensurePythonShim();

try {
  const args = [
    "electron-builder",
    isMac ? "--mac" : "--win",
    "--publish", "never",
    "--config", cfgFile,
  ];
  if (arch) args.push("--" + arch);
  run(args);
} finally {
  rmSync(cfgFile, { force: true });
}

const pkgVer = JSON.parse(readFileSync(join(appDir, "package.json"), "utf8")).version;

if (isMac) {
  // ---------- macOS 收尾：ad-hoc 签名 + 便携版 zip ----------
  const outDir = join(appDir, cfg.output);
  let appPath = null;
  for (const d of readdirSync(outDir, { withFileTypes: true })) {
    if (!d.isDirectory() || !d.name.startsWith("mac")) continue;
    const sub = join(outDir, d.name);
    for (const f of readdirSync(sub)) {
      if (f.endsWith(".app")) {
        appPath = join(sub, f);
        break;
      }
    }
    if (appPath) break;
  }
  if (!appPath) {
    console.error("[build] 没找到 .app 产物，跳过签名与 zip");
    process.exit(1);
  }

  // Apple Silicon 要求可执行文件至少有 ad-hoc 签名，否则双击直接被系统杀掉
  try {
    runBin("codesign", ["--force", "--deep", "--sign", "-", appPath]);
    console.log("[build] 已 ad-hoc 签名:", appPath);
  } catch (e) {
    console.error(
      "[build] ad-hoc 签名失败（可能仍能运行，但 Gatekeeper 会拦）:",
      String(e && e.message),
    );
  }

  /*
    用 ditto 而不是 python zipfile：.app 内部（Frameworks 等）有大量符号链接，
    python 的 zip 会把符号链接变成副本、体积翻倍还可能破坏结构。
    ditto -c -k --sequesterRsrc --keepParent 是 macOS 官方推荐的打包方式。
  */
  try {
    const zipName = `${cfg.appName}-便携版-${pkgVer}.zip`;
    const zipPath = join(outDir, zipName);
    rmSync(zipPath, { force: true });
    runBin("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", appPath, zipPath]);
    console.log(`[build] 便携版 zip: ${zipName}（解压后把 .app 拖进「应用程序」即可）`);
  } catch (e) {
    console.error("[build] 生成便携版 zip 失败（不影响 dmg）:", String(e && e.message));
  }
} else {
  // ---------- Windows 收尾：便携版 zip ----------
  // 为什么要这个：electron-builder 的 "portable" 目标每次启动都要把 ~110MB 自解压到临时
  // 目录（还要被杀软扫一遍），实测开窗要 2 分钟；而解压好的目录直接跑只要 2 秒。
  // zip 内不带顶层目录，用户解压到哪就能在哪双击运行。
  try {
    const zipName = `${cfg.appName}-便携版-${pkgVer}.zip`;
    const zipPath = join(appDir, cfg.output, zipName);
    rmSync(zipPath, { force: true });
    execFileSync(
      "python",
      [
        "-c",
        `import zipfile,os,sys
src,out=sys.argv[1],sys.argv[2]
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for root,dirs,files in os.walk(src):
        for f in files:
            p=os.path.join(root,f)
            z.write(p,os.path.relpath(p,src))`,
        join(appDir, cfg.output, "win-unpacked"),
        zipPath,
      ],
      { stdio: "inherit" },
    );
    console.log(`[build] 便携版 zip: ${zipName}（解压即用，启动约 2 秒）`);
  } catch (e) {
    console.error("[build] 生成便携版 zip 失败（不影响安装包）:", String(e && e.message));
  }
}

console.log(`[build] 完成，产物目录 ${cfg.output}`);
cleanupPythonShim();
