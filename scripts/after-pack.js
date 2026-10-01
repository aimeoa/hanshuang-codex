"use strict";
/*
  electron-builder 的 afterPack 钩子。

  时机正好：应用目录已经打包好、但安装器还没生成，所以这里改的 exe 会被
  一起打进安装包，装出来的就是带正确图标和版本信息的。

  为什么不用 electron-builder 自己的 signAndEditExecutable：
  Windows 上它要先解压 winCodeSign 压缩包，包里含 macOS 的符号链接，
  普通权限创建不了，解压报错整个构建就中断；而且它每次算一个新的缓存 key，
  预填缓存也没用。rcedit 本来就在那个包里，我们直接调它。
*/

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

/** 在 electron-builder 缓存里找 rcedit-x64.exe（任何一次成功解压留下的即可）。 */
function findRcedit() {
  const cacheRoot = path.join(
    process.env.LOCALAPPDATA || path.join(process.env.USERPROFILE || "", "AppData", "Local"),
    "electron-builder",
    "Cache",
    "winCodeSign",
  );
  let dirs = [];
  try {
    dirs = fs.readdirSync(cacheRoot);
  } catch {
    return null;
  }
  for (const d of dirs) {
    const p = path.join(cacheRoot, d, "rcedit-x64.exe");
    if (fs.existsSync(p)) return p;
  }
  return null;
}

exports.default = async function afterPack(context) {
  const appDir = context.appOutDir;
  const platform = context.electronPlatformName || process.platform;
  const appRoot = path.join(__dirname, "..");

  /*
    macOS 分支：.app 的图标由 electron-builder 自己从 build/icon.png 生成 icns，
    不需要（也没有）rcedit 这一步。这里只做一件事 —— 把便携版卸载脚本放进
    <App>.app/Contents/Resources，方便用户不用时能一键清干净。
  */
  if (platform === "darwin") {
    const resDir = path.join(appDir, context.packager.appInfo.productFilename + ".app", "Contents", "Resources");
    const src = path.join(appRoot, "scripts", "install", "portable-uninstall.sh");
    if (!fs.existsSync(src)) {
      console.log("[after-pack] 缺少 macOS 卸载脚本，跳过:", src);
      return;
    }
    try {
      fs.mkdirSync(resDir, { recursive: true });
      const dst = path.join(resDir, "portable-uninstall.sh");
      fs.copyFileSync(src, dst);
      fs.chmodSync(dst, 0o755);
      console.log("[after-pack] 已放入卸载脚本: Contents/Resources/portable-uninstall.sh");
    } catch (e) {
      console.log("[after-pack] 拷贝卸载脚本失败:", String(e && e.message));
    }
    return;
  }

  const productName =
    (context.packager && context.packager.appInfo && context.packager.appInfo.productName) ||
    "app";
  const exePath = path.join(appDir, productName + ".exe");
  if (!fs.existsSync(exePath)) {
    console.log("[after-pack] 找不到 exe，跳过:", exePath);
    return;
  }

  const rcedit = findRcedit();
  if (!rcedit) {
    console.log("[after-pack] 没找到 rcedit-x64.exe，跳过图标写入");
    return;
  }

  // 按变体选图标（build.mjs 会先把 PNG 转成 .ico）
  let variant = "free";
  try {
    variant = JSON.parse(fs.readFileSync(path.join(appRoot, "variant.json"), "utf8")).variant;
  } catch {
    /* 用默认 */
  }
  const ico = path.join(appRoot, "build", variant === "pro" ? "icon-pro.ico" : "icon.ico");

  const args = [
    exePath,
    "--set-version-string", "ProductName", productName,
    "--set-version-string", "FileDescription", productName,
    "--set-version-string", "CompanyName", "寒霜",
    "--set-file-version", "1.0.0",
    "--set-product-version", "1.0.0",
  ];
  if (fs.existsSync(ico)) {
    args.push("--set-icon", ico);
  } else {
    console.log("[after-pack] 图标文件不存在，只写版本信息:", ico);
  }

  try {
    execFileSync(rcedit, args, { stdio: "inherit" });
    console.log("[after-pack] 已写入图标与版本信息:", path.basename(exePath));
  } catch (e) {
    console.log("[after-pack] rcedit 失败:", String(e && e.message));
  }

  // 便携版一键卸载：把脚本拷到应用根目录，解压后跟 exe 并排，双击即可完全卸载。
  // 便携版没有安装器，删文件夹就等于卸载 —— 但直接删会留下 %APPDATA%\<name>、
  // ~/.codex 下的状态文件和快捷方式，这两个文件负责把这些一并清掉。
  for (const f of ["portable-uninstall.ps1", "卸载-便携版.bat"]) {
    const src = path.join(appRoot, f);
    if (!fs.existsSync(src)) {
      console.log("[after-pack] 缺少便携版卸载脚本，跳过:", f);
      continue;
    }
    try {
      fs.copyFileSync(src, path.join(appDir, f));
      console.log("[after-pack] 已放入便携版卸载脚本:", f);
    } catch (e) {
      console.log("[after-pack] 拷贝失败:", f, String(e && e.message));
    }
  }
};
