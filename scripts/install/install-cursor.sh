#!/usr/bin/env bash
# install-cursor.sh — Cursor 规则破甲注入（macOS）
#
# 对齐 install-cursor.ps1 的全部行为：
#   · 往 Cursor 的全局规则目录写「寒霜注入.mdc」：frontmatter + 注入标记 + 提示词正文
#   · 从 workspaceStorage 自动探测 Cursor 打开过的项目，写 {项目}/.cursor/rules/寒霜注入.mdc
#   · 旧版兼容（Cursor <0.42）：项目根 .cursorrules 与 ~/.cursorrules，纯文本、无 frontmatter；
#     只在「本来不存在」或「是我们装的（含 marker）」时写，绝不覆盖用户自有规则
#   · 已存在的非注入同名文件先备份成 .bak
#   · 状态文件记录 writtenPaths，卸载按它精确还原/删除
#   · 退出码：主路径写入成功 → 0；主路径失败但有部分写入 → 2；全部失败 → 1
#
# 与 Windows 版的差异（无法对等实现的部分）：
#   · 删除了「盘符根祖先规则」(Get-DriveRulePaths)。该逻辑依赖 Windows 的「多盘符 +
#     规则沿工作区→父目录→盘符根向上加载」。macOS 是单一根文件系统 /，往 /.cursor/rules
#     写需要 root 且会污染整机，且 Cursor 在 macOS 上不沿卷根继承规则，没有等价物。
#   · 删除了「运行中 Cursor 的 --user-data-dir 探测」(Get-CimInstance Win32_Process)：
#     macOS 版只认下面三个标准候选目录，不再解析进程命令行。
#
# 用法：
#   ./install-cursor.sh -SourcePrompt /path/寒霜v4.md
#   ./install-cursor.sh -Uninstall

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"

RULE_FILE='寒霜注入.mdc'
LEGACY_RULE_FILE='.cursorrules'
MARKER="$HS_CURSOR_MARK"
# macOS：Cursor 自己的数据在 Application Support 下，状态文件跟它放一起
STATE_PATH="$(hs_appsupport)/Cursor/hs-install-state.json"
STATE_DIR="$(dirname "$STATE_PATH")"

# 全局规则目录候选：官方 User Rules（Cursor 实际读取的位置）+ 主目录 .cursor/rules
RULES_DIRS=(
  "$HOME/.cursor/rules"
  "$(hs_appsupport)/Cursor/User/rules"
  "$(hs_appsupport)/Cursor/rules"
)

# ---------- 工具 ----------

# file:// URL 的路径解码：先把已有反斜杠转义成 \\，再把 %XX 换成 \xXX 交给 printf %b
# 还原成字节（UTF-8 逐字节还原，中文路径也能解）。
url_decode() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="$(printf '%s' "$s" | sed -e 's/%\([0-9A-Fa-f][0-9A-Fa-f]\)/\\x\1/g')"
  printf '%b' "$s"
}

count_lines() { wc -l <"$1" | tr -d ' '; }

# 往清单文件里追加去重后的路径（PowerShell 的 Select-Object -Unique）
add_unique() {
  local file="$1" p="$2"
  [ -n "$p" ] || return 0
  if [ -f "$file" ] && grep -Fxq -- "$p" "$file" 2>/dev/null; then return 0; fi
  printf '%s\n' "$p" >>"$file"
}

# 主路径 = 全局 User Rules（决定注入是否真的全局生效）
is_primary() {
  local p="$1" d
  for d in "${RULES_DIRS[@]}"; do
    [ "$p" = "$d/$RULE_FILE" ] && return 0
  done
  return 1
}

# ---------- 项目探测 ----------

# 从 Cursor 的 workspaceStorage 里解析用户打开过的项目目录，每行一个
cursor_projects() {
  local ws_root ws_json d loc
  ws_root="$(hs_appsupport)/Cursor/User/workspaceStorage"
  hs_isdir "$ws_root" || return 0
  for d in "$ws_root"/*; do
    [ -d "$d" ] || continue
    ws_json="$d/workspace.json"
    [ -f "$ws_json" ] || continue
    loc="$(hs_json_get "$ws_json" folder)"
    [ -n "$loc" ] || loc="$(hs_json_get "$ws_json" workspace)"
    [ -n "$loc" ] || continue
    case "$loc" in
      file://*) loc="$(url_decode "${loc#file://}")" ;;
    esac
    # macOS 路径本来就是 / 分隔，不像 Windows 版还要把 / 换成 \
    [ -d "$loc" ] && printf '%s\n' "$loc"
  done
}

# 项目级规则路径：{项目}/.cursor/rules/寒霜注入.mdc
project_rule_paths() {
  local list="$1" p
  cursor_projects | while IFS= read -r p; do
    [ -n "$p" ] || continue
    add_unique "$list" "$p/.cursor/rules/$RULE_FILE"
  done
}

# 旧版 .cursorrules：只在「本来不存在」或「是我们装的」时算数。
# mode=install 时主目录那份也要过同一道守卫（安装不能覆盖用户自己的 ~/.cursorrules）；
# mode=uninstall 时主目录那份无条件纳入清单，由调用方按标记判断要不要删。
legacy_rule_paths() {
  local list="$1" mode="${2:-uninstall}" p legacy home_legacy
  cursor_projects | while IFS= read -r p; do
    [ -n "$p" ] || continue
    legacy="$p/$LEGACY_RULE_FILE"
    if [ ! -e "$legacy" ] || hs_contains "$legacy" "$MARKER"; then
      add_unique "$list" "$legacy"
    fi
  done
  # 旧版注入器还往用户主目录写过 .cursorrules，工作区扫描扫不到那里；
  # 卸载时按标记判断，只删带寒霜标记的那份，用户自己的规则不动。
  home_legacy="$HOME/$LEGACY_RULE_FILE"
  if [ "$mode" = "install" ]; then
    if [ ! -e "$home_legacy" ] || hs_contains "$home_legacy" "$MARKER"; then
      add_unique "$list" "$home_legacy"
    fi
  else
    add_unique "$list" "$home_legacy"
  fi
}

# ---------- 卸载 ----------

if hs_flag -Uninstall; then
  targets="$(hs_tmp)/targets.txt"
  : >"$targets"
  # 1) 安装记录里写过的路径（卸载兜底）
  if [ -f "$STATE_PATH" ]; then
    hs_state_list "$STATE_PATH" writtenPaths | while IFS= read -r full; do
      [ -n "$full" ] || continue
      case "$(printf '%s' "$full" | tr 'A-Z' 'a-z')" in
        *.mdc) ;;
        *) full="$full/$RULE_FILE" ;;
      esac
      add_unique "$targets" "$full"
    done
  fi
  # 2) 已存在的候选目录 + 3) 项目级规则
  for d in "${RULES_DIRS[@]}"; do
    [ -d "$d" ] && add_unique "$targets" "$d/$RULE_FILE"
  done
  project_rule_paths "$targets"

  removed_any=0
  restored_any=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ -f "$p" ] || continue
    if [ -f "$p.bak" ]; then
      cp -f "$p.bak" "$p"
      rm -f "$p.bak"
      hs_log "Restored original rule: $p"
      restored_any=1
    else
      content="$(hs_read "$p")"
      case "$content" in
        *"$MARKER"*)
          rm -f "$p"
          hs_log "Removed injected rule: $p"
          removed_any=1
          ;;
        *) hs_log "No injection found, skipped: $p" ;;
      esac
    fi
  done <"$targets"

  # 卸载旧版 .cursorrules（含我们标记的）
  legacy_list="$(hs_tmp)/legacy.txt"
  : >"$legacy_list"
  legacy_rule_paths "$legacy_list"
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ -f "$p" ] || continue
    content="$(hs_read "$p")"
    case "$content" in
      *"$MARKER"*)
        if [ -f "$p.bak" ]; then
          cp -f "$p.bak" "$p"
          rm -f "$p.bak"
        else
          rm -f "$p"
        fi
        hs_log "Removed legacy rule: $p"
        removed_any=1
        ;;
    esac
  done <"$legacy_list"

  rm -f "$STATE_PATH"
  if [ "$removed_any" -eq 0 ] && [ "$restored_any" -eq 0 ]; then
    hs_log "No Cursor rule injection found, nothing to do"
  fi
  hs_log "Cursor 注入卸载完成"
  exit 0
fi

# ---------- 安装 ----------

if [ -z "$SOURCE_PROMPT" ]; then
  # 兜底：取脚本根目录下第一个 .md
  for f in "$HS_ROOT"/*.md; do
    [ -f "$f" ] || continue
    SOURCE_PROMPT="$f"
    break
  done
  [ -n "$SOURCE_PROMPT" ] || hs_die "Prompt file not found: $SOURCE_PROMPT"
fi

[ -f "$SOURCE_PROMPT" ] || hs_die "Prompt file not found: $SOURCE_PROMPT"

BODY="$(hs_read "$SOURCE_PROMPT")"
# 对齐 PowerShell 的 $body.TrimEnd()：只削正文末尾的空白，不动行内内容
while [ "$BODY" != "${BODY%[[:space:]]}" ]; do BODY="${BODY%[[:space:]]}"; done
[ -n "$BODY" ] || hs_die "Prompt file is empty: $SOURCE_PROMPT"

# .mdc 格式：description + globs + alwaysApply frontmatter + 正文（带注入标记便于卸载识别）
MDC="---
description: 寒霜工作规范（自动注入 · 全局生效）
globs: \"**/*\"
alwaysApply: true
---

$MARKER
$BODY"

WRITTEN="$(hs_tmp)/written.txt"
FAILED="$(hs_tmp)/failed.txt"
: >"$WRITTEN"
: >"$FAILED"
PRIMARY_OK=0

write_rule_file() {
  local target="$1" legacy="${2:-0}" cur content msg
  hs mkdir "$(dirname "$target")" 2>/dev/null || true
  if [ -f "$target" ]; then
    cur="$(hs_read "$target")"
    case "$cur" in
      *"$MARKER"*) ;;
      *)
        # 已存在非注入文件（用户自建规则撞名）：先备份
        cp -f "$target" "$target.bak" 2>/dev/null || true
        ;;
    esac
  fi
  if [ "$legacy" -eq 1 ]; then
    # 旧版 .cursorrules 是纯 markdown，不带 frontmatter
    content="$MARKER
$BODY"
  else
    content="$MDC"
  fi
  if printf '%s\n' "$content" | hs write "$target" 2>"$(hs_tmp)/err.txt" && [ -f "$target" ]; then
    printf '%s\n' "$target" >>"$WRITTEN"
    if [ "$legacy" -eq 0 ] && is_primary "$target"; then PRIMARY_OK=1; fi
    hs_log "OK: $target"
  else
    msg="$(head -n 1 "$(hs_tmp)/err.txt" 2>/dev/null)"
    [ -n "$msg" ] || msg='写入后文件不存在（被占用或权限不足）'
    printf '%s\n' "$target -> $msg" >>"$FAILED"
    hs_warn "跳过(非致命): $target -> $msg"
  fi
}

# 1) 全局规则目录（User Rules + ~/.cursor/rules 等全部候选）——决定新文件夹全局生效
for d in "${RULES_DIRS[@]}"; do
  write_rule_file "$d/$RULE_FILE"
done

# 2) 项目级规则：自动探测 Cursor 打开过的每个项目
proj_list="$(hs_tmp)/proj.txt"
: >"$proj_list"
project_rule_paths "$proj_list"
while IFS= read -r target; do
  [ -n "$target" ] || continue
  write_rule_file "$target"
done <"$proj_list"

# 3) 旧版兼容：项目根目录 .cursorrules（只写没有用户自有规则的，纯文本格式）
legacy_list="$(hs_tmp)/legacy-install.txt"
: >"$legacy_list"
legacy_rule_paths "$legacy_list" install
while IFS= read -r target; do
  [ -n "$target" ] || continue
  write_rule_file "$target" 1
done <"$legacy_list"

# （Windows 版的盘符根祖先规则在 macOS 无等价物，已整段删除，见文件头说明）

# 记录实际写入路径，供卸载精确清理
hs mkdir "$STATE_DIR" 2>/dev/null || true
if hs_json_set "$STATE_PATH" installedAt "$(hs_now)" 2>/dev/null \
   && hs_json_array "$STATE_PATH" writtenPaths <"$WRITTEN" 2>/dev/null; then
  :
else
  hs_warn "警告: 安装状态未记录（卸载时将无法精确清理）- $STATE_PATH"
fi

n_written="$(count_lines "$WRITTEN")"
n_failed="$(count_lines "$FAILED")"
hs_log "Cursor rules installed: $n_written 处"
if [ "$n_failed" -gt 0 ]; then
  hs_warn "以下 $n_failed 处写入被跳过（不影响全局生效，多为系统盘权限）:"
  while IFS= read -r line; do
    [ -n "$line" ] && hs_warn "  $line"
  done <"$FAILED"
fi
if [ "$PRIMARY_OK" -eq 1 ] && [ "$n_written" -gt 0 ]; then
  hs_log "全局 User Rules 注入成功 - 新开任意文件夹都会自动加载"
  hs_log "重启 Cursor 生效（Rules → User 可见「寒霜注入」）"
  exit 0
fi
if [ "$n_written" -gt 0 ]; then
  hs_warn "主路径写入失败但部分规则已写入（可能不全局生效），请检查 Cursor 安装目录权限"
  exit 2
fi
hs_warn "全部写入失败 - 请确认 Cursor 已安装且你有写入权限"
exit 1
