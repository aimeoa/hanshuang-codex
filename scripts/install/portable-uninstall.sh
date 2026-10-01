#!/usr/bin/env bash
# =============================================================================
#  寒霜破甲工具 · 便携版完全卸载（macOS）
#
#  便携版没有安装器，删掉文件夹就等于卸载 —— 但直接删文件夹会留下：
#    ~/Library/Application Support/hanshuang-free        （运行过就会生成，Chromium 用户数据）
#    ~/Library/Application Support/寒霜破甲工具
#    ~/Library/Preferences/com.hanshuang.desktop.plist
#    ~/Library/Saved Application State/com.hanshuang.desktop.savedState
#    ~/Library/Caches/com.hanshuang.desktop
#    ~/.codex/fj_desktop_state.json / fj_settings.json    （本工具自己的状态文件）
#  这个脚本把这些一并清掉，最后删掉程序目录，做到零残留。
#
#  安全规则（硬约束，改脚本时不要放宽）：
#    * 白名单式：只删下面 TARGETS 里逐条列出的路径，不做「包含寒霜/破甲」的模糊匹配。
#    * 受保护路径一律拒删：$HOME 本身、Desktop / Documents / Downloads / Library 这些
#      用户目录，以及 /、/Users、/Applications、/System 这类系统目录。宁可漏删，不许删错。
#    * 每个路径删之前先判断存在性并打印；默认先把要删的清单全部打印出来。
#    * 默认是 DRY-RUN 之外的「真删」，但 -DryRun 可以只打印不动手 —— 卸载脚本没有
#      第二次机会，先把清单打出来让人看清是必要的。
#
#  用法：
#    bash portable-uninstall.sh -AppDir /Applications/寒霜破甲工具.app -DryRun
#    bash portable-uninstall.sh -AppDir /Applications/寒霜破甲工具.app
#    bash portable-uninstall.sh -KeepData          # 只删程序目录，保留用户数据与状态文件
#
#  ---- 相对 portable-uninstall.ps1 的 macOS 适配 ----
#    · %APPDATA% / %LOCALAPPDATA% → ~/Library/Application Support
#    · 快捷方式（.lnk）与注册表（HKCU:\...）在 macOS 没有对应物，那两节只打一行说明
#    · .bat 复制到 %TEMP% 再执行的「自删副本」逻辑不需要，去掉
#    · 「按回车关闭窗口」是 Windows 控制台的习惯，去掉
# =============================================================================

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

DRY_RUN=0
hs_flag -DryRun && DRY_RUN=1
KEEP_DATA=0
hs_flag -KeepData && KEEP_DATA=1
APP_DIR="$(hs_arg -AppDir '')"

APPSUP="$(hs_appsupport)"
REMOVED=0
FAILED=(); FAILED_N=0
fail_add() {
  FAILED[$FAILED_N]="$1"
  FAILED_N=$((FAILED_N + 1))
}

# -----------------------------------------------------------------------------
# 受保护路径：无论谁传进来都不删
# -----------------------------------------------------------------------------
guard_path() {
  local p="$1"
  [ -n "$p" ] || return 1
  case "$p" in
    / | /Users | /Applications | /System | /Library | /private | /usr | /bin | /etc) return 1 ;;
    "$HOME" | "$HOME"/Desktop | "$HOME"/Documents | "$HOME"/Downloads | "$HOME"/Library \
    | "$HOME"/Library/Application\ Support | "$HOME"/Library/Preferences \
    | "$HOME"/Library/Caches | "$HOME"/Library/Saved\ Application\ State) return 1 ;;
  esac
  # 至少要有两级（/a/b），根下的一级目录一律不碰
  case "$p" in
    /*/*) return 0 ;;
    *) return 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# 待清理清单（白名单，逐条列出）
# -----------------------------------------------------------------------------
PT_KIND=(); PT_PATH=(); PT_N=0
add_target() {
  PT_KIND[$PT_N]="$1"
  PT_PATH[$PT_N]="$2"
  PT_N=$((PT_N + 1))
}

hs_log '============================================'
hs_log '  寒霜破甲工具 · 便携版完全卸载（macOS）'
if [ -n "$APP_DIR" ]; then
  hs_log "  目录: $APP_DIR"
else
  hs_log '  目录: （未传 -AppDir，跳过程序目录删除）'
fi
hs_log '============================================'
hs_log ''

# --- 用户数据与缓存 -----------------------------------------------------------
# 只认这几个确切名字，不做「包含寒霜/破甲」的模糊匹配，避免误删无关目录
if [ "$KEEP_DATA" -eq 1 ]; then
  hs_log '[1/6] 用户数据与缓存'
  hs_log '  （-KeepData：保留用户数据）'
  hs_log ''
else
  add_target '数据目录' "$APPSUP/hanshuang-free"
  add_target '数据目录' "$APPSUP/寒霜破甲工具"
  add_target '配置文件' "$HOME/Library/Preferences/com.hanshuang.desktop.plist"
  add_target '窗口状态' "$HOME/Library/Saved Application State/com.hanshuang.desktop.savedState"
  add_target '缓存目录' "$HOME/Library/Caches/com.hanshuang.desktop"
  # 本工具自己的状态文件（Codex 数据目录可能在别处，CODEX_HOME 指到哪就清到哪）
  if [ -n "${CODEX_HOME:-}" ] && [ -d "$CODEX_HOME" ]; then
    add_target '状态文件' "$CODEX_HOME/fj_desktop_state.json"
    add_target '状态文件' "$CODEX_HOME/fj_settings.json"
  else
    add_target '状态文件' "$HOME/.codex/fj_desktop_state.json"
    add_target '状态文件' "$HOME/.codex/fj_settings.json"
  fi
fi

# --- 程序目录 -----------------------------------------------------------------
if [ -n "$APP_DIR" ]; then
  case "${APP_DIR##*/}" in
    *hanshuang* | *寒霜* | *破甲*) add_target '程序目录' "$APP_DIR" ;;
    *) hs_log "  （-AppDir 名字不像本工具的程序目录，已忽略：$APP_DIR）" ;;
  esac
fi

# -----------------------------------------------------------------------------
# 先把要删的清单全部打印出来（这是硬要求：卸载没有第二次机会）
# -----------------------------------------------------------------------------
hs_log "--- 待清理 $PT_N 项 ---"
i=0
EXIST_N=0
while [ "$i" -lt "$PT_N" ]; do
  if [ -e "${PT_PATH[$i]}" ]; then
    hs_log "  [${PT_KIND[$i]}] ${PT_PATH[$i]}"
    EXIST_N=$((EXIST_N + 1))
  else
    hs_log "  [${PT_KIND[$i]}] ${PT_PATH[$i]}（不存在，跳过）"
  fi
  i=$((i + 1))
done
hs_log "  —— 其中 $EXIST_N 项实际存在。"
hs_log ''

if [ "$DRY_RUN" -eq 1 ]; then
  hs_log 'DRY-RUN：以上是将会删除的路径，本次没有删任何东西。'
  hs_log '（去掉 -DryRun 即执行；执行前请确认清单里没有你自己的目录。）'
  hs_log ''
  hs_log '[2/6] 清除注入到 AI 工具里的提示词'
  hs_log '  （-DryRun：不实际执行清理脚本）'
  hs_log '[3/6] 清理用户数据与缓存 / [4/6] 快捷方式 / [5/6] 注册表 / [6/6] 程序目录'
  hs_log '  （-DryRun：未改动任何东西）'
  exit 0
fi

# -----------------------------------------------------------------------------
# 逐项删除
# -----------------------------------------------------------------------------
remove_target() {
  local kind="$1" path="$2"
  if [ ! -e "$path" ]; then
    return 0
  fi
  if ! guard_path "$path"; then
    hs_log "  SKIP [$kind] 受保护路径，拒绝删除：$path"
    fail_add "$path"
    return 1
  fi
  if rm -rf "$path" 2>/dev/null; then
    hs_log "  OK   [$kind] $path"
    REMOVED=$((REMOVED + 1))
    return 0
  fi
  hs_log "  FAIL [$kind] $path"
  fail_add "$path"
  return 1
}

# --- 1. 结束正在运行的程序 ----------------------------------------------------
# 程序还在跑的话，它会把自己刚被删掉的数据目录重新建出来。只按「进程名完全相同」匹配，
# 不用模糊匹配，免得误伤别的程序。
hs_log '[1/6] 结束正在运行的程序'
if command -v pkill >/dev/null 2>&1; then
  for name in '寒霜破甲工具' 'hanshuang-free'; do
    if pkill -x "$name" 2>/dev/null; then
      hs_log "  已结束进程: $name"
    fi
  done
else
  hs_log '  未找到 pkill，跳过'
fi
sleep 1

# --- 2. 注入的提示词 ----------------------------------------------------------
# 必须排在删除程序目录之前：清理脚本本体就在 <AppDir>/Contents/Resources/scripts/ 下面。
# 便携版没有安装器，「卸载」就是本脚本，所以这一步只能在这里完成 ——
# 少了它，注入到 Codex / Claude / ZCode / DSH / WorkBuddy / Cursor 里的提示词会全部留下。
# 脚本按内容判定，只删提示词；用户的 AGENTS.md / CLAUDE.md / config.toml /
# 自己的备份一律不动（详见脚本头部注释）。失败不阻断后续清理。
hs_log '[2/6] 清除注入到 AI 工具里的提示词'
CLEAR_SCRIPT=''
for cand in \
  "$APP_DIR/Contents/Resources/scripts/install/clear-injected-prompts.sh" \
  "$APP_DIR/Contents/Resources/scripts/clear-injected-prompts.sh" \
  "$APP_DIR/resources/scripts/install/clear-injected-prompts.sh" \
  "$APP_DIR/resources/scripts/clear-injected-prompts.sh" \
  "$APP_DIR/scripts/install/clear-injected-prompts.sh" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/clear-injected-prompts.sh"; do
  [ -n "$cand" ] || continue
  if [ -f "$cand" ]; then
    CLEAR_SCRIPT="$cand"
    break
  fi
done
if [ -n "$CLEAR_SCRIPT" ]; then
  hs_log "  执行: $CLEAR_SCRIPT -Apply"
  bash "$CLEAR_SCRIPT" -Apply
  hs_log "  清理脚本退出码: $?（0=已完成）"
else
  hs_log '  未找到清理脚本，跳过'
fi
hs_log ''

# --- 3. 用户数据与缓存 --------------------------------------------------------
hs_log '[3/6] 清理用户数据与缓存'
if [ "$KEEP_DATA" -eq 1 ]; then
  hs_log '  （-KeepData：保留用户数据）'
else
  i=0
  while [ "$i" -lt "$PT_N" ]; do
    remove_target "${PT_KIND[$i]}" "${PT_PATH[$i]}"
    i=$((i + 1))
  done
fi
hs_log ''

# --- 4. 快捷方式 --------------------------------------------------------------
hs_log '[4/6] 清理快捷方式'
hs_log '  （macOS 没有 .lnk 快捷方式，跳过）'

# --- 5. 注册表 ----------------------------------------------------------------
hs_log '[5/6] 清理注册表残留'
hs_log '  （macOS 没有注册表，跳过；AppUserModelId 之类只在 Windows 存在）'

# --- 6. 程序目录 --------------------------------------------------------------
hs_log '[6/6] 删除程序目录'
if [ -n "$APP_DIR" ]; then
  case "${APP_DIR##*/}" in
    *hanshuang* | *寒霜* | *破甲*) remove_target '程序目录' "$APP_DIR" ;;
    *) hs_log "  已忽略（名字不像本工具的程序目录）：$APP_DIR" ;;
  esac
else
  hs_log '  未传 -AppDir，跳过'
fi

# --- 结果 ---------------------------------------------------------------------
hs_log ''
if [ "$FAILED_N" -eq 0 ]; then
  hs_log "完成：已清理 $REMOVED 项，零残留。"
  exit 0
fi
hs_log "完成，但有 $FAILED_N 项没删掉（多半是被占用或受保护）："
i=0
while [ "$i" -lt "$FAILED_N" ]; do
  hs_log "  ${FAILED[$i]}"
  i=$((i + 1))
done
hs_log '关掉占用这些文件的程序后再跑一次即可。'
exit 1
