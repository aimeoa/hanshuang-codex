#!/usr/bin/env bash
# install-doubao.sh — 豆包（Doubao）破甲注入（macOS）
#
# 和别的目标不一样：豆包的全局记忆不在本地磁盘，存在字节云端、绑定账号。
# 本地只有开关状态（IndexedDB 里的 switchMemoryV2_），没有记忆正文。
# 所以这里不写文件，而是用 CDP 驱动豆包客户端自身的登录会话去调云端接口：
#   /alice/generaltask/memory/get_agentsmd   读全局记忆
#   /alice/generaltask/memory/set_agentsmd   整份覆盖写全局记忆
#
# 前提：豆包必须以 --remote-debugging-port=<Port> 运行。没开的话本脚本会自动
# 重启豆包到调试模式（会话在云端，重启不丢聊天记录）。
#
# 与 Windows 版的差异（macOS 对等实现）：
#   · 找应用：Windows 查注册表 + 进程路径，换成扫 /Applications（以及 ~/Applications）
#     下的「豆包.app / Doubao.app」。
#   · 结束进程：Get-Process Doubao | Stop-Process → pkill -f 豆包 / pkill -f Doubao。
#   · 启动：Windows 直接跑 app\Doubao.exe（绕开根目录启动器）；macOS 的等价物是
#     .app 包内的 Contents/MacOS 可执行文件，失败再退回 open -a "豆包" --args。
#   · CDP 需要 WebSocket，bash 做不了 → 下沉到 doubao-cdp.cjs（本目录，无第三方依赖），
#     经 lib.sh 的 hs_node 调用。
#   · 状态/备份/日志目录：Windows 的 ~\.doubao\managed-prompts 换成
#     $HOME/Library/Application Support/豆包/（详见 -Uninstall 输出与 README）。
#
# 用法：
#   ./install-doubao.sh                          # 装 V4（Claude 版）提示词
#   ./install-doubao.sh -SourcePrompt ./x.md     # 指定提示词
#   ./install-doubao.sh -Status                  # 看当前全局记忆
#   ./install-doubao.sh -Uninstall               # 还原注入前的记忆

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

HS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDP_JS="$HS_DIR/doubao-cdp.cjs"

hs_parse_args "$@"

SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
VERSION="$(hs_arg -Version 'v4')"
PORT="$(hs_arg -Port '9222')"
DO_UNINSTALL=0; hs_flag -Uninstall && DO_UNINSTALL=1
DO_STATUS=0;    hs_flag -Status    && DO_STATUS=1
NO_LAUNCH=0;    hs_flag -NoLaunch  && NO_LAUNCH=1

case "$PORT" in
  ''|*[!0-9]*) hs_warn "无效的 -Port: $PORT"; exit 1 ;;
esac

# macOS：状态/备份/日志统一放 Application Support（豆包自己的数据也在这里）
STATE_DIR="$(hs_appsupport)/豆包"
STATE_FILE="$STATE_DIR/hanshuang-state.json"
BACKUP_FILE="$STATE_DIR/agentsmd-backup.md"
LOG_FILE="$STATE_DIR/hanshuang-doubao.log"

# 「未执行」出口：macOS 上做不到的步骤一律显式报错、退出码非 0，绝不假装成功
not_done() {
  hs_warn "未执行: $*"
  exit 1
}

log_line() {
  hs mkdir "$STATE_DIR" 2>/dev/null || true
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE" 2>/dev/null || true
}

# ---------- 提示词来源 ----------

# 文件 SHA256（对齐 PowerShell 的 Get-FileHash -Algorithm SHA256）
sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" 2>/dev/null | cut -d' ' -f1
  fi
}

if [ -z "$SOURCE_PROMPT" ]; then
  case "$VERSION" in
    v4) SOURCE_PROMPT="$HS_ROOT/寒霜v4-claude.md" ;;
    v3) SOURCE_PROMPT="$HS_ROOT/寒霜v3.md" ;;
    v5) SOURCE_PROMPT="$HS_ROOT/寒霜v5.md" ;;
    *)  hs_warn "未知的 -Version: $VERSION（可用 v3 / v4 / v5，或用 -SourcePrompt 指定文件）"; exit 1 ;;
  esac
fi
[ -f "$SOURCE_PROMPT" ] || { hs_warn "提示词文件不存在: $SOURCE_PROMPT"; exit 1; }
SRC_TEXT="$(hs_read "$SOURCE_PROMPT")"
SRC_HASH="$(sha256_of "$SOURCE_PROMPT")"
# 字符数由 doubao-cdp.cjs 在写入时一并返回（JS 的 String.length 与 PowerShell 的
# .Length 同为 UTF-16 码元数；用字节数会在中文提示词上对不上）
SRC_LEN=0

# ---------- 找豆包 ----------

# 对齐 PowerShell 的 Resolve-DoubaoExe：返回 .app 包路径（找不到返回空）
#
# 候选里的 DoubaoWork.app：macOS 上装出来的豆包客户端实际叫这个名字
# （BundleID com.work.pc.doubao，显示名 DoubaoWork），
# 只找 豆包.app / Doubao.app 会直接扫不到 —— 这是实测踩到的坑。
#
# HS_DOUBAO_APP：显式指定 .app 路径。用于应用被改名、装在非常规位置、
# 或以后又出现新发行名的机器 —— 不用改脚本就能适配。
resolve_app() {
  local c
  if [ -n "${HS_DOUBAO_APP:-}" ]; then
    if [ -d "$HS_DOUBAO_APP" ]; then printf '%s' "$HS_DOUBAO_APP"; return 0; fi
    printf 'HS_DOUBAO_APP 指向的路径不存在: %s\n' "$HS_DOUBAO_APP" >&2
    return 1
  fi
  for c in "/Applications/豆包.app" "/Applications/Doubao.app" \
           "/Applications/DoubaoWork.app" "/Applications/Doubao Work.app" \
           "$HOME/Applications/豆包.app" "$HOME/Applications/Doubao.app" \
           "$HOME/Applications/DoubaoWork.app"; do
    if [ -d "$c" ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}

test_debug_port() {
  curl -s --max-time 3 "http://127.0.0.1:$PORT/json/version" 2>/dev/null | grep -q 'webSocketDebuggerUrl'
}

kill_doubao() {
  pkill -f '豆包' >/dev/null 2>&1 || true
  pkill -f 'Doubao' >/dev/null 2>&1 || true
}

# 对齐 PowerShell 的 Start-DoubaoDebug：绕开启动器，直接带调试参数跑 Chromium 主体
#
# macOS 上豆包用的是「主壳 + Helpers 子应用」布局（和 Chrome 一样）：
#   <App>.app/Contents/MacOS/<App>                        ← 只是启动器（实测仅 2.6MB）
#   <App>.app/Contents/Helpers/<X> Browser.app/...        ← 真正的 Chromium 内核
# 启动器未必把 --remote-debugging-port 透传给内核，所以**优先直接跑 Helpers 里的内核**，
# 这才是「绕开启动器」在 macOS 上的等价做法。
start_doubao_debug() {
  local app="$1" bin="" c i=0

  # 1. 优先：包内 Helpers 下的 Chromium 主体
  for c in "$app/Contents/Helpers/"*.app/Contents/MacOS/*; do
    if [ -f "$c" ] && [ -x "$c" ]; then bin="$c"; break; fi
  done

  # 2. 退回：外层可执行文件（非 Helpers 布局的版本，或老版本）
  if [ -z "$bin" ]; then
    for c in "$app/Contents/MacOS/"*; do
      if [ -f "$c" ] && [ -x "$c" ]; then bin="$c"; break; fi
    done
  fi

  if [ -n "$bin" ]; then
    nohup "$bin" --remote-debugging-port="$PORT" >/dev/null 2>&1 &
  else
    open -a "$(basename "$app" .app)" --args --remote-debugging-port="$PORT" >/dev/null 2>&1 || true
  fi
  while [ "$i" -lt 40 ]; do
    sleep 0.5
    if test_debug_port; then return 0; fi
    i=$((i + 1))
  done
  # 兜底：直接跑内层二进制没起来时，用 open --args 再试一轮
  if [ -n "$bin" ]; then
    open -a "$(basename "$app" .app)" --args --remote-debugging-port="$PORT" >/dev/null 2>&1 || true
    i=0
    while [ "$i" -lt 40 ]; do
      sleep 0.5
      if test_debug_port; then return 0; fi
      i=$((i + 1))
    done
  fi
  return 1
}

# ---------- CDP 封装（真正的 WebSocket 在 doubao-cdp.cjs 里）----------

cdp() { "$(hs_node)" "$CDP_JS" "$@"; }

# 选目标：stdout 无输出，结果填进 TARGET_TYPE / TARGET_URL / TARGET_WS
resolve_target() {
  local out err
  out="$(hs_tmp)/target.json"
  err="$(hs_tmp)/target.err"
  rm -f "$out" "$err"
  if ! cdp target --port "$PORT" --wait 60 --out "$out" 2>"$err"; then
    hs_warn "未执行: 等不到豆包对话页的调试目标（60 秒），确认豆包已登录并打开主界面"
    [ -s "$err" ] && sed 's/^/    /' "$err" >&2
    return 1
  fi
  TARGET_TYPE="$(hs_json_get "$out" type)"
  TARGET_URL="$(hs_json_get "$out" url)"
  TARGET_WS="$(hs_json_get "$out" ws)"
  [ -n "$TARGET_WS" ]
}

# 读云端全局记忆：填进 CUR_LEN / CUR_CONTENT / CUR_RAW
read_agents_md() {
  local out err
  out="$(hs_tmp)/get.json"
  err="$(hs_tmp)/get.err"
  rm -f "$out" "$err"
  if ! cdp get --ws "$TARGET_WS" --port "$PORT" --out "$out" 2>"$err"; then
    hs_warn "未执行: 读取云端全局记忆失败（CDP 调用出错）"
    [ -s "$err" ] && sed 's/^/    /' "$err" >&2
    return 1
  fi
  CUR_LEN="$(hs_json_get "$out" len)"
  CUR_CONTENT="$(hs_json_get "$out" content)"
  CUR_RAW="$(hs_json_get "$out" raw)"
  [ -n "$CUR_LEN" ] || CUR_LEN=0
  return 0
}

# 写云端全局记忆（整份覆盖）：填进 SET_STATUS / SET_BODY
write_agents_md() {
  local content_file="$1" out err
  out="$(hs_tmp)/set.json"
  err="$(hs_tmp)/set.err"
  rm -f "$out" "$err"
  if [ -z "$content_file" ] || [ ! -f "$content_file" ]; then
    content_file="$(hs_tmp)/empty-content.txt"
    : >"$content_file"
  fi
  if ! cdp set --ws "$TARGET_WS" --port "$PORT" --content-file "$content_file" --out "$out" 2>"$err"; then
    hs_warn "未执行: 写入云端全局记忆失败（CDP 调用出错）"
    [ -s "$err" ] && sed 's/^/    /' "$err" >&2
    return 1
  fi
  SET_STATUS="$(hs_json_get "$out" status)"
  SET_BODY="$(hs_json_get "$out" body)"
  SET_CHARS="$(hs_json_get "$out" chars)"
  return 0
}

# ---------- 主流程 ----------

hs_log "== 豆包破甲 =="
APP_BUNDLE="$(resolve_app)" || APP_BUNDLE=""
if [ -n "$APP_BUNDLE" ]; then
  hs_log "  豆包程序 : $APP_BUNDLE"
else
  hs_log "  豆包程序 : 未找到（请确认已安装到 /Applications）"
fi
hs_log "  提示词   : $SOURCE_PROMPT"
hs_log "  调试端口 : $PORT"
hs_log "  状态目录 : $STATE_DIR"

command -v curl >/dev/null 2>&1 || not_done "macOS 上没有 curl，无法探测调试端口 $PORT"
[ -f "$CDP_JS" ] || not_done "缺少 CDP 辅助文件 $CDP_JS"

if ! test_debug_port; then
  if [ "$NO_LAUNCH" -eq 1 ]; then
    hs_warn "豆包没有以调试模式运行（$PORT 不通），且指定了 -NoLaunch"
    exit 1
  fi
  if pgrep -f '豆包' >/dev/null 2>&1 || pgrep -f 'Doubao' >/dev/null 2>&1; then
    hs_log "  [i] 豆包正在运行但没有开调试端口，重启到调试模式（聊天记录在云端，不会丢）"
    kill_doubao
    sleep 2
  fi
  [ -n "$APP_BUNDLE" ] || not_done "找不到豆包程序，无法自动启动。请手动以调试模式运行客户端（在 .app 包内可执行文件后加 --remote-debugging-port=$PORT）"
  hs_log "  [i] 启动豆包（调试模式）..."
  if ! start_doubao_debug "$APP_BUNDLE"; then
    hs_warn "未执行: 豆包启动后 $PORT 仍不通；如果界面停在登录页，先登录再重试"
    exit 1
  fi
fi

resolve_target || exit 1
hs_log "  调试目标 : $TARGET_TYPE $TARGET_URL"

# 状态
if [ "$DO_STATUS" -eq 1 ]; then
  read_agents_md || exit 1
  hs_log ""
  hs_log "[状态]"
  hs_log "  云端全局记忆 : $CUR_LEN 字符"
  if [ -f "$BACKUP_FILE" ]; then
    hs_log "  本地备份     : $(hs size "$BACKUP_FILE") 字节"
  else
    hs_log "  本地备份     : 无"
  fi
  if [ -f "$STATE_FILE" ]; then
    hs_log "  注入状态     : 已注入（可 -Uninstall 还原）"
  else
    hs_log "  注入状态     : 未注入"
  fi
  if [ "$CUR_LEN" -gt 0 ]; then
    hs_log ""
    hs_log "--- 记忆开头 ---"
    printf '%s\n' "$CUR_CONTENT" | head -n 6
    hs_log "---"
  fi
  log_line "Status: len=$CUR_LEN"
  exit 0
fi

# 卸载
if [ "$DO_UNINSTALL" -eq 1 ]; then
  done_list="$(hs_tmp)/done.txt"
  : >"$done_list"
  if [ -f "$BACKUP_FILE" ]; then
    BAK="$(hs_read "$BACKUP_FILE")"
    # 备份内容本身就是寒霜注入时（上一版工具写进去的、或用户手工贴的），
    # 还原它等于把破甲留着 —— 这种情况直接清空，才算真卸干净。
    case "$BAK" in
      *寒霜*|*中转站保护*)
        write_agents_md "" || exit 1
        read_agents_md || exit 1
        printf '%s\n' "备份内容本身是上一次的注入 → 已清空云端记忆（现在 $CUR_LEN 字符）" >>"$done_list"
        ;;
      *)
        write_agents_md "$BACKUP_FILE" || exit 1
        read_agents_md || exit 1
        if [ "$CUR_CONTENT" = "$BAK" ]; then
          printf '%s\n' "全局记忆已还原（$CUR_LEN 字符）" >>"$done_list"
        else
          printf '%s\n' "还原后校验不一致（当前 $CUR_LEN 字符）" >>"$done_list"
        fi
        ;;
    esac
    rm -f "$BACKUP_FILE"
  else
    write_agents_md "" || exit 1
    printf '%s\n' "没有备份，已清空全局记忆" >>"$done_list"
  fi
  rm -f "$STATE_FILE"

  log_line "Uninstall: $(tr '\n' ';' <"$done_list" | sed 's/;$//')"
  # 收拾本地痕迹：日志 + 空目录。$STATE_DIR 是本脚本专用的（豆包自己的数据在
  # ~/Library/Application Support/Doubao），空掉就删，别在用户目录下留垃圾。
  if [ -f "$LOG_FILE" ]; then
    rm -f "$LOG_FILE"
    printf '%s\n' "已删除日志 hanshuang-doubao.log" >>"$done_list"
  fi
  if [ -d "$STATE_DIR" ] && [ -z "$(ls -A "$STATE_DIR" 2>/dev/null)" ]; then
    rmdir "$STATE_DIR" 2>/dev/null && printf '%s\n' "已删除空目录 $(basename "$STATE_DIR")" >>"$done_list"
  fi

  hs_log ""
  hs_log "[完成] 卸载"
  while IFS= read -r line; do
    [ -n "$line" ] && hs_log "  - $line"
  done <"$done_list"
  hs_log ""
  hs_log "  提示：豆包仍以调试模式运行（端口 $PORT）。要恢复正常模式，先退出豆包再正常启动："
  if [ -n "$APP_BUNDLE" ]; then
    hs_log "        open -a \"$(basename "$APP_BUNDLE" .app)\""
  else
    hs_log "        open -a \"豆包\""
  fi
  exit 0
fi

# 备份（只在首次注入时备份，别把注入后的内容当原始记忆备份了）
read_agents_md || exit 1
BEFORE_LEN="$CUR_LEN"
hs_log "  写入前   : $BEFORE_LEN 字符"
if [ ! -f "$BACKUP_FILE" ]; then
  if [ "$CUR_LEN" -gt 0 ]; then
    printf '%s' "$CUR_CONTENT" | hs write "$BACKUP_FILE"
    hs_log "  [i] 原记忆已备份 → $BACKUP_FILE"
  else
    printf '' | hs write "$BACKUP_FILE"
    hs_log "  [i] 原记忆为空，已记录空备份（卸载时会清空而不是还原）"
  fi
fi

# 写入
write_agents_md "$SOURCE_PROMPT" || exit 1
[ -n "$SET_CHARS" ] && SRC_LEN="$SET_CHARS"
hs_log "  接口返回 : status=$SET_STATUS $SET_BODY"
read_agents_md || exit 1
if [ "$CUR_CONTENT" = "$SRC_TEXT" ]; then EXACT="true"; else EXACT="false"; fi

hs mkdir "$STATE_DIR" 2>/dev/null || true
hs_json_set "$STATE_FILE" prompt "$SOURCE_PROMPT"
hs_json_set "$STATE_FILE" sha256 "\"$SRC_HASH\""
hs_json_set "$STATE_FILE" chars "$SRC_LEN"
hs_json_set "$STATE_FILE" writtenAt "$(hs_now)"
hs_json_set "$STATE_FILE" exactMatch "$EXACT"

hs_log ""
hs_log "[校验]"
hs_log "  写入后   : $CUR_LEN 字符"
hs_log "  逐字一致 : $EXACT"
log_line "Inject: chars=$SRC_LEN exact=$EXACT status=$SET_STATUS"

if [ "$EXACT" = "true" ]; then
  hs_log ""
  hs_log "[完成] 豆包全局记忆已替换为 $(basename "$SOURCE_PROMPT")"
  hs_log "  生效验证：在豆包里开一个通用任务问一句，看是否按寒霜规范回应"
  hs_log "  还原命令：./install-doubao.sh -Uninstall"
  exit 0
fi
hs_log ""
hs_warn "[失败] 写进去了但读回来对不上 —— 云端可能有审核或长度截断"
hs_warn "  写入前 $BEFORE_LEN 字符 / 期望 $SRC_LEN 字符 / 实际 $CUR_LEN 字符"
exit 2
