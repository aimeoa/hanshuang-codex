#!/usr/bin/env bash
# install-workbuddy.sh — WorkBuddy AI 破甲：全局记忆 + 文件记忆 + skills 一键装/卸（macOS）
#
# 对齐 install-workbuddy.ps1 的全部行为，四个注入点一个都不少：
#   1) <ConfigDir>/memory/<uid>_memory.md   账号级云记忆档案；memoryBlock 每轮自动包成
#                                           <memory>…</memory> 注入系统提示词（上限 10000 字符）
#                                           写 Version: 999999 触发 stale_version 守卫，防云端回写覆盖
#   2) <ConfigDir>/MEMORY.md                用户级文件记忆（每轮提醒 AI 主动读，兜底）
#   3) <ConfigDir>/app/app-config.json      generateMemoryEnabled（云记忆总闸）/ localMemoryEnabled
#   4) <ConfigDir>/skills/<name>/SKILL.md   用户级 Skills；开关态在 settings.json 的 skillOverrides
#   另：
#      <ConfigDir>/.hanshuang-state.json    注入状态（主进程 electron/main.cjs 的 WorkBuddyGuard 读它
#                                           做只读锁回写守护，字段名 prompt/archives/memoryDir/version/uid
#                                           等必须逐字保留）
#      <ConfigDir>/skills/.hanshuang-skills.json  技能安装清单
#
# <ConfigDir> 解析：-ConfigDir > cli/product.json 的 dataFolderName > ~/.workbuddy-ai > ~/.workbuddy
#   macOS 上这两个目录同样是 ~/.workbuddy-ai 与 ~/.workbuddy（不放到 Library 下），与主进程保持一致。
# uid 解析：-Uid > <ConfigDir>/memory/*_memory.md 文件名 > 未找到则跳过云记忆（明确打印「未执行」）
#
# macOS 替换：%APPDATA%/%LOCALAPPDATA% → $HOME/Library/Application Support；
#             Get/Stop/Start-Process → pgrep/pkill/open -a；attrib/只读属性 → chmod；路径分隔符一律 /
#
# 本脚本新增的私有辅助函数（lib.sh 里没有、也不改 lib.sh）：
#   hs_wblog              诊断日志（写 $TMPDIR/workbuddy-inject.log）
#   hs_sha256             文件 SHA256（shasum -a 256 / sha256sum，大写对齐 Get-FileHash）
#   hs_trim_all           从 stdin 读文本，去掉整段首尾空白后输出（对齐 PS .Trim()）
#   archive_block         从记忆档案里抽出 «## Memory Block» 段正文
#   archive_template      生成档案正文（含 uid/memoryBlock/updatedAt/version 的 RAW_JSON）
#   list_memory_archives  扫 memory 目录下所有 <uid>_memory.md（按 mtime 倒序）
#   resolve_install_root / resolve_config_dir / resolve_uid / find_other_profile_config_dirs
#   set_app_config_flags  合并写 app-config.json 的两个开关（保留原字段，缺 locale 补 zh-CN）
#   manifest_skill_pairs  从 .hanshuang-skills.json 取出 "技能名 sha256" 逐行
#   drop_skill_overrides  从 settings.json 的 skillOverrides 里摘掉指定技能键
#
# 用法：
#   ./install-workbuddy.sh                                  # 一键：寒霜V4 + V4 技能库
#   ./install-workbuddy.sh -SourcePrompt ./寒霜v3.md         # 指定提示词
#   ./install-workbuddy.sh -SkillsSource codex-skills-v4     # 指定技能库目录
#   ./install-workbuddy.sh -NoSkills                         # 只注入记忆，不装 skills
#   ./install-workbuddy.sh -KillApp -Restart                 # 注入前结束进程、注入后拉起
#   ./install-workbuddy.sh -Uninstall                        # 一键还原（记忆 + 开关 + skills）
#   ./install-workbuddy.sh -Status                           # 只读状态

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

# ---------- 参数（名字与 PowerShell 版逐字一致） ----------
VERSION="$(hs_arg -Version 'v4')"
SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
SKILLS_SOURCE="$(hs_arg -SkillsSource '')"
WB_UID_ARG="$(hs_arg -Uid '')"
CONFIG_DIR_ARG="$(hs_arg -ConfigDir '')"
INSTALL_ROOT_ARG="$(hs_arg -InstallRoot '')"
SCRIPT_ROOT="$(hs_arg -ScriptRoot '')"

NO_SKILLS=0; hs_flag -NoSkills && NO_SKILLS=1
KILL_APP=0;  hs_flag -KillApp  && KILL_APP=1
RESTART=0;   hs_flag -Restart  && RESTART=1
UNINSTALL=0; hs_flag -Uninstall && UNINSTALL=1
STATUS=0;    hs_flag -Status   && STATUS=1

# ---------- 常量 ----------
MEM_VERSION=999999      # 高版本号：程序写档案时 incoming < existing 会被判 stale_version 拒绝
SKILL_MANIFEST='.hanshuang-skills.json'
LOG_FILE="${TMPDIR:-/tmp}/workbuddy-inject.log"
APP_NAME='WorkBuddyAI'

# ---------- 诊断日志 ----------
hs_wblog() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE" 2>/dev/null || true; }

# ---------- 私有辅助 ----------

# 文件 SHA256，大写十六进制（对齐 PowerShell Get-FileHash 的输出）
hs_sha256() {
  local f="$1" out=""
  [ -f "$f" ] || { printf ''; return 0; }
  if command -v shasum >/dev/null 2>&1; then
    out="$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    out="$(sha256sum "$f" 2>/dev/null | awk '{print $1}')"
  else
    hs_die "找不到 shasum / sha256sum，无法计算哈希"
  fi
  printf '%s' "$out" | tr 'a-f' 'A-F'
}

# 把一个字符串转成 JSON 字符串字面量（转义 \ " 换行 制表 回车）。
# 用途：清单/状态文件用纯 shell 拼 JSON，避免「每个技能一次 node 调用」把安装拖到分钟级。
hs_json_str() {
  printf '%s' "$1" | awk '
    BEGIN { printf "\"" }
    {
      if (NR > 1) printf "\\n"
      s = $0
      gsub(/\\/, "\\\\", s)
      gsub(/"/, "\\\"", s)
      gsub(/\t/, "\\t", s)
      gsub(/\r/, "\\r", s)
      printf "%s", s
    }
    END { printf "\"" }
  '
}

# 逐行文本 → JSON 字符串数组（不含外层括号），用于状态文件的 archives / skills
hs_json_array_lines() {
  awk '
    { s = $0; gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); gsub(/\r/, "", s)
      if (NR > 1) printf ", "
      printf "\"%s\"", s }
  '
}

# 从 stdin 读文本，去掉「整段」首尾空白后输出（只动首尾，不动行内 —— 对齐 PS .Trim()）
hs_trim_all() {
  awk '
    { buf[NR] = $0 }
    END {
      s = 1; e = NR
      while (s <= e) { t = buf[s]; gsub(/^[[:space:]]+/, "", t); if (t == "") s++; else break }
      while (e >= s) { t = buf[e]; gsub(/[[:space:]]+$/, "", t); if (t == "") e--; else break }
      for (i = s; i <= e; i++) {
        line = buf[i]
        if (i == s) sub(/^[[:space:]]+/, "", line)
        if (i == e) sub(/[[:space:]]+$/, "", line)
        print line
      }
    }
  '
}

# 抽出记忆档案里 «## Memory Block» 段正文（对齐 PS 的 (?s)## Memory Block\r?\n\r?\n(.*?)\r?\n\r?\n---）
archive_block() {
  local f="$1"
  [ -f "$f" ] || return 0
  awk '
    BEGIN { inb = 0; lead = 1 }
    /^## Memory Block[[:space:]]*$/ { inb = 1; next }
    inb && /^---[[:space:]]*$/ { exit }
    inb {
      if (lead) { if ($0 ~ /^[[:space:]]*$/) next; lead = 0 }
      print
    }
  ' "$f"
}

# 生成一份记忆档案正文（$1=uid $2=memoryBlock 正文 $3=now）
archive_template() {
  local uid="$1" body="$2" now="$3" rawf raw
  rawf="$(hs_tmp)/raw-$$-$RANDOM.json"
  : >"$rawf"
  hs_json_set "$rawf" uid "\"$uid\""
  hs_json_set "$rawf" memoryBlock "$body"
  hs_json_set "$rawf" updatedAt "\"$now\""
  hs_json_set "$rawf" version "$MEM_VERSION"
  # 末尾补一个哨兵再截掉：命令替换会吃掉结尾换行，而 RAW_JSON 与标记之间需要保留那个换行
  raw="$(hs_read "$rawf"; printf 'X')"
  raw="${raw%X}"
  printf '# User Memory Profile\n> Last updated: %s\n> Version: %s\n\n## Memory Block\n\n%s\n\n---\n\n<!-- RAW_JSON_START\n%sRAW_JSON_END -->\n' \
    "$now" "$MEM_VERSION" "$body" "$raw"
}

# 扫 memory 目录下所有 <uid>_memory.md，按 mtime 倒序逐行输出（排除 *.bak*）
list_memory_archives() {
  local memDir="$1" f out=""
  [ -d "$memDir" ] || return 0
  for f in "$memDir"/*_memory.md; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in *'.bak'*) continue ;; esac
    out="$out$(hs mtime "$f")	$f
"
  done
  [ -n "$out" ] || return 0
  printf '%s' "$out" | sort -rn -k1,1 | sed -e 's/^[0-9]*	//'
}

# 安装目录：-InstallRoot > 运行中进程的可执行路径 > /Applications 下 *WorkBuddy*.app
resolve_install_root() {
  local explicit="$1" pid exe d
  if [ -n "$explicit" ]; then printf '%s' "$explicit"; return 0; fi
  if command -v pgrep >/dev/null 2>&1; then
    pid="$(pgrep -x "$APP_NAME" 2>/dev/null | head -n 1)"
    if [ -n "$pid" ]; then
      exe="$(ps -p "$pid" -o comm= 2>/dev/null | sed -e 's/[[:space:]]*$//')"
      case "$exe" in
        *.app/Contents/MacOS/*) printf '%s' "${exe%%/Contents/MacOS/*}"; return 0 ;;
        /*/*) d="$(dirname "$exe")"; [ -d "$d" ] && { printf '%s' "$d"; return 0; } ;;
      esac
    fi
  fi
  for d in /Applications/*WorkBuddy*.app "$HOME/Applications"/*WorkBuddy*.app; do
    [ -d "$d" ] && { printf '%s' "$d"; return 0; }
  done
  printf ''
}

# 数据目录：-ConfigDir > cli/product.json 的 dataFolderName > ~/.workbuddy-ai > ~/.workbuddy
resolve_config_dir() {
  local explicit="$1" root="$2" pj name cand
  if [ -n "$explicit" ]; then printf '%s' "$explicit"; return 0; fi
  if [ -n "$root" ]; then
    for pj in "$root/Contents/Resources/app.asar.unpacked/cli/product.json" \
              "$root/resources/app.asar.unpacked/cli/product.json" \
              "$root/app.asar.unpacked/cli/product.json" \
              "$root/cli/product.json"; do
      [ -f "$pj" ] || continue
      name="$(sed -n 's/.*"dataFolderName"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$pj" | head -n 1)"
      if [ -n "$name" ]; then printf '%s/%s' "$HOME" "$name"; return 0; fi
    done
  fi
  for cand in .workbuddy-ai .workbuddy; do
    [ -d "$HOME/$cand" ] && { printf '%s/%s' "$HOME" "$cand"; return 0; }
  done
  printf '%s' "$HOME/.workbuddy"
}

# 其它「属于当前用户」的家目录下真实存在的配置目录。
#
# 原实现直接遍历 /Users/* 下所有账户 —— 这是从 Windows 版（C:\Users\*）照搬的。
# 但在 macOS 上这个假设不成立：C:\Users 下多半是同一个人建的多套环境，
# 而 /Users 下通常是**不同的真人账户**。照搬的后果是：当本账户还没有 WorkBuddy
# 数据时，脚本会「跨账户」切到别人的配置目录并往里注入 —— 属于越权写入。
#
# 所以这里收紧成：只认当前用户自己拥有的家目录（同 uid）。
# 同一个人开多个账户的场景仍然支持，别人的账户一律不碰。
find_other_profile_config_dirs() {
  local primary="$1" u n cand myuid
  myuid="$(id -u 2>/dev/null || printf '')"
  for u in /Users/*; do
    [ -d "$u" ] || continue
    if [ -n "$myuid" ]; then
      [ "$(stat -f '%u' "$u" 2>/dev/null)" = "$myuid" ] || continue
    fi
    for n in .workbuddy-ai .workbuddy; do
      cand="$u/$n"
      [ -d "$cand" ] || continue
      [ "$cand" = "$primary" ] && continue
      printf '%s\n' "$cand"
    done
  done
}

# uid：-Uid > 最新档案文件名 > settings.json 的 claw.legacyOwnerUid
resolve_uid() {
  local explicit="$1" configDir="$2" root="$3" f base
  if [ -n "$explicit" ]; then printf '%s' "$explicit"; return 0; fi
  if [ -d "$configDir/memory" ]; then
    f="$(list_memory_archives "$configDir/memory" | head -n 1)"
    if [ -n "$f" ]; then
      base="$(basename "$f")"
      printf '%s' "${base%_memory.md}"
      return 0
    fi
  fi
  if [ -n "$root" ] && [ -f "$configDir/settings.json" ]; then
    base="$(sed -n 's/.*"legacyOwnerUid"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$configDir/settings.json" | head -n 1)"
    [ -n "$base" ] && { printf '%s' "$base"; return 0; }
  fi
  printf ''
}

# 合并写 app-config.json 开关：对象就合并、数组/字符串/坏结构就留证据后重建
set_app_config_flags() {
  local path="$1" gen="$2" loc="$3" first loc0
  if [ -f "$path" ]; then
    first="$(hs_read "$path" | tr -d '[:space:]' | cut -c 1)"
    if [ "$first" != "{" ]; then
      cp -f "$path" "$path.broken-inject" 2>/dev/null || true
      hs_log "  [警告] app-config.json 结构异常，已另存 .broken-inject 并重建"
      hs_wblog "app-config 结构异常，已重建"
      : >"$path"
    fi
  fi
  hs_json_set "$path" generateMemoryEnabled "$gen"
  hs_json_set "$path" localMemoryEnabled "$loc"
  loc0="$(hs_json_get "$path" locale)"
  [ -n "$loc0" ] || hs_json_set "$path" locale '"zh-CN"'
}

# 一次 shasum 算完 $1 里列出的技能名对应的 SKILL.md → "技能名 SHA256" 逐行写入 $2
# （逐技能起一次进程在 Windows 上要 4 分钟，会撞主进程的 300 秒超时）
build_skills_pairs() {
  local list="$1" dst="$2" n f
  local files=()
  : >"$dst"
  [ -f "$list" ] || return 0
  while IFS= read -r n || [ -n "$n" ]; do
    [ -n "$n" ] || continue
    f="$SKILLS_DIR/$n/SKILL.md"
    [ -f "$f" ] || continue
    files[${#files[@]}]="$f"
  done <"$list"
  [ "${#files[@]}" -eq 0 ] && return 0
  local shacmd
  if command -v shasum >/dev/null 2>&1; then shacmd='shasum -a 256'; else shacmd='sha256sum'; fi
  $shacmd "${files[@]}" | awk '
    {
      h = $1
      line = $0
      sub(/^[^ ]+[ ]+/, "", line)
      n = line
      sub(/\/SKILL\.md$/, "", n)
      sub(/^.*\//, "", n)
      printf "%s %s\n", n, toupper(h)
    }
  ' >"$dst"
  return 0
}

# 从 .hanshuang-skills.json 取 "技能名 sha256" 逐行输出。
# 末行必须带换行：bash 的 `while read` 在 EOF 前缺换行时会丢掉最后一行，最后一个技能就会漏删。
manifest_skill_pairs() {
  local f="$1" so inner
  hs_isfile "$f" || return 0
  so="$(hs_json_get "$f" skills)"
  [ -n "$so" ] || return 0
  inner="${so#\{}"; inner="${inner%\}}"
  [ -n "$inner" ] || return 0
  printf '%s\n' "$inner" | sed -e 's/},"/}\n"/g' \
    | sed -n 's/^"\([^"]*\)":{"sha256":"\([^"]*\)"}$/\1 \2/p'
}

# 从 settings.json 的 skillOverrides 里摘掉 $2 列出的技能键（无 key = 启用）
drop_skill_overrides() {
  local file="$1" keys="$2" so new kf
  hs_isfile "$file" || return 0
  so="$(hs_json_get "$file" skillOverrides)"
  [ -n "$so" ] || return 0
  case "$so" in \{*) ;; *) return 0 ;; esac
  kf="$(hs_tmp)/so-keys.txt"
  printf '%s\n' "$keys" >"$kf"
  new="$(printf '%s' "$so" | awk -v kf="$kf" '
    BEGIN {
      while ((getline l < kf) > 0) { gsub(/\r/, "", l); if (l != "") k[l] = 1 }
      close(kf)
      out = ""
    }
    function flush(p,   q, key) {
      if (p == "") return
      q = index(p, ":")
      if (q < 2) return
      key = substr(p, 1, q - 1)
      gsub(/^[[:space:]]*"/, "", key); gsub(/"[[:space:]]*$/, "", key)
      if (key in k) return
      if (out != "") out = out ","
      out = out p
    }
    {
      s = $0
      sub(/^[[:space:]]*\{/, "", s); sub(/\}[[:space:]]*$/, "", s)
      depth = 0; instr = 0; cur = ""
      L = length(s)
      for (i = 1; i <= L; i++) {
        c = substr(s, i, 1)
        if (instr) {
          cur = cur c
          if (c == "\\") { i++; cur = cur substr(s, i, 1) }
          else if (c == "\"") instr = 0
          continue
        }
        if (c == "\"") { instr = 1; cur = cur c; continue }
        if (c == "{" || c == "[") { depth++; cur = cur c; continue }
        if (c == "}" || c == "]") { depth--; cur = cur c; continue }
        if (c == "," && depth == 0) { flush(cur); cur = ""; continue }
        cur = cur c
      }
      flush(cur)
      printf "{%s}", out
    }
  ')"
  [ "$new" = "$so" ] || hs_json_set "$file" skillOverrides "$new"
}

# ---------- 解析 ----------
case "$VERSION" in
  v4) DEFAULT_PROMPT='寒霜v4.md' ;;
  v3) DEFAULT_PROMPT='寒霜v3.md' ;;
  v2) DEFAULT_PROMPT='寒霜v1.2.md' ;;
  *) hs_die "无效的 -Version: $VERSION（可选 v4 / v3 / v2）" ;;
esac

ROOT="$SCRIPT_ROOT"
[ -n "$ROOT" ] || ROOT="$HS_ROOT"

[ -n "$SOURCE_PROMPT" ] || SOURCE_PROMPT="$ROOT/$DEFAULT_PROMPT"
hs_isfile "$SOURCE_PROMPT" || hs_die "提示词文件不存在: $SOURCE_PROMPT"

if [ -z "$SKILLS_SOURCE" ]; then
  if [ "$VERSION" = 'v4' ]; then SKILLS_SOURCE='codex-skills-v4'; else SKILLS_SOURCE='codex-skills'; fi
fi
SKILLS_SRC="$ROOT/$SKILLS_SOURCE"

hs_wblog "=== 启动 === bash=$BASH_VERSION Script=$0 Root=$ROOT Temp=${TMPDIR:-/tmp}"

INSTALL_ROOT="$(resolve_install_root "$INSTALL_ROOT_ARG")"
# 是否由调用方显式指定了数据目录（国内版固定传 ~/.workbuddy）
CONFIG_DIR_PINNED=0
[ -n "$CONFIG_DIR_ARG" ] && CONFIG_DIR_PINNED=1
CONFIG_DIR="$(resolve_config_dir "$CONFIG_DIR_ARG" "$INSTALL_ROOT")"
# 同 uid 的其它家目录兜底：本账户目录里没有 WorkBuddy 数据（memory 子目录）时，
# 改用同一个人名下另一个家目录里真实存在的那份。
# 注意：只认同 uid 的家目录，别人账户的配置一律不碰（见 find_other_profile_config_dirs）。
# 显式指定数据目录时不兜底（否则国内版会跑到国际版上去）。
if [ "$CONFIG_DIR_PINNED" -eq 0 ] && [ ! -d "$CONFIG_DIR/memory" ]; then
  other="$(find_other_profile_config_dirs "$CONFIG_DIR" 2>/dev/null | while IFS= read -r c || [ -n "$c" ]; do
    [ -d "$c/memory" ] && { printf '%s' "$c"; break; }
  done)"
  if [ -n "$other" ]; then
    hs_log "  [同账户其它家目录] 本账户($HOME)无 WorkBuddy 数据，改用: $other"
    hs_wblog "同 uid 家目录切换: $CONFIG_DIR -> $other"
    CONFIG_DIR="$other"
  fi
fi

WB_UID="$(resolve_uid "$WB_UID_ARG" "$CONFIG_DIR" "$INSTALL_ROOT")"
MEM_DIR="$CONFIG_DIR/memory"

# 云记忆档案：指定 uid 用该 uid 的文件（不存在则新建）；未指定则扫该目录下所有 <uid>_memory.md
ARCHIVES=""
if [ -n "$WB_UID" ]; then
  ARCHIVES="$MEM_DIR/${WB_UID}_memory.md"
elif [ -d "$MEM_DIR" ]; then
  ARCHIVES="$(list_memory_archives "$MEM_DIR")"
fi
ARCHIVE0="$(printf '%s\n' "$ARCHIVES" | sed -n '1p')"
ARCHIVE_COUNT=0
if [ -n "$ARCHIVES" ]; then
  ARCHIVE_COUNT="$(printf '%s\n' "$ARCHIVES" | grep -c . )"
fi
# 这些中间文件可能一直为空（例如未登录、-NoSkills），先落空文件避免后面重定向报错
: >"$(hs_tmp)/arch.txt"
printf '%s\n' "$ARCHIVES" | grep -v '^$' >"$(hs_tmp)/arch.txt" || true
: >"$(hs_tmp)/cur-skills.txt"

FILE_MEM="$CONFIG_DIR/MEMORY.md"
FILE_MEM_BAK="$FILE_MEM.bak-inject"
CFG_FILE="$CONFIG_DIR/app/app-config.json"
CFG_BAK="$CFG_FILE.bak-inject"
SKILLS_DIR="$CONFIG_DIR/skills"
SETTINGS_FILE="$CONFIG_DIR/settings.json"
MANIFEST_FILE="$SKILLS_DIR/$SKILL_MANIFEST"
STATE_FILE="$CONFIG_DIR/.hanshuang-state.json"   # 给主进程守护线程读的注入状态

# 进程探测
APP_RUNNING=0
if command -v pgrep >/dev/null 2>&1 && [ -n "$(pgrep -x "$APP_NAME" 2>/dev/null)" ]; then
  APP_RUNNING=1
fi

hs_log "== WorkBuddy 破甲 =="
hs_log "  安装目录 : $(if [ -n "$INSTALL_ROOT" ]; then printf '%s' "$INSTALL_ROOT"; else printf '未找到（不影响注入）'; fi)"
hs_log "  配置目录 : $CONFIG_DIR"
case "$(basename "$CONFIG_DIR")" in
  .workbuddy)    VARIANT='国版' ;;
  .workbuddy-ai) VARIANT='国际版' ;;
  *)             VARIANT='自定义/品牌版' ;;
esac
hs_log "  版本判定 : $VARIANT（数据目录 $(basename "$CONFIG_DIR")）"
if [ -n "$WB_UID" ]; then
  WB_UID_DESC="$WB_UID"
elif [ "$ARCHIVE_COUNT" -gt 0 ]; then
  WB_UID_DESC="自动扫描到 $ARCHIVE_COUNT 个记忆档案"
else
  WB_UID_DESC='未找到 → 云记忆注入将跳过（脚本会自动重扫）'
fi
hs_log "  用户 uid : $WB_UID_DESC"
hs_log "  提示词   : $SOURCE_PROMPT"
if [ "$NO_SKILLS" -eq 1 ]; then
  hs_log "  技能库   : 已禁用 (-NoSkills)"
elif [ -d "$SKILLS_SRC" ]; then
  hs_log "  技能库   : $SKILLS_SRC"
else
  hs_log "  技能库   : 找不到 $SKILLS_SRC → 跳过"
fi
if [ -z "$INSTALL_ROOT" ] && [ ! -d "$CONFIG_DIR" ]; then
  hs_log "  [警告] 未检测到 WorkBuddy 安装或其数据目录 —— 目标机器可能没装 WorkBuddy，注入将无效"
fi
[ "$APP_RUNNING" -eq 1 ] && hs_log "  [注意] $APP_NAME 正在运行，写入后需重启才生效"
hs_wblog "解析结果 InstallRoot=$INSTALL_ROOT ConfigDir=$CONFIG_DIR Uid=$WB_UID 档案数=$ARCHIVE_COUNT"

# ---------- 状态（只读） ----------
if [ "$STATUS" -eq 1 ]; then
  SRC_HASH="$(hs_sha256 "$SOURCE_PROMPT")"
  hs_log ""
  hs_log "[状态]"
  LIVE=""
  if [ -n "$ARCHIVES" ]; then
    printf '%s\n' "$ARCHIVES" >"$(hs_tmp)/status-arch.txt"
    while IFS= read -r af || [ -n "$af" ]; do
      [ -n "$af" ] || continue
      [ -f "$af" ] || continue
      LIVE="$LIVE$af
"
      t="$(hs_read "$af")"
      ver="$(printf '%s' "$t" | sed -n 's/^>[[:space:]]*Version:[[:space:]]*\([0-9]*\).*/\1/p' | head -n 1)"
      blk="$(archive_block "$af" | hs_trim_all)"
      blk_len="$(printf '%s' "$blk" | wc -c | tr -d ' ')"
      blk_first="$(printf '%s\n' "$blk" | sed -n '1p')"
      if [ -w "$af" ]; then ro='False'; else ro='True'; fi
      hs_log "  云记忆档案          : $af"
      hs_log "  档案 Version        : $(if [ -n "$ver" ]; then printf '%s' "$ver"; else printf '-'; fi)"
      hs_log "  memoryBlock 字符数  : $blk_len  (上限 10000)"
      hs_log "  memoryBlock 首行    : $blk_first"
      hs_log "  档案只读锁          : $ro   (True = 已挡住程序回写)"
    done <"$(hs_tmp)/status-arch.txt"
  fi
  if [ -z "$LIVE" ]; then
    hs_log "  云记忆档案          : 未找到（该账号还没生成过记忆档案，或 WorkBuddy 未登录过）"
  fi
  if hs_isfile "$STATE_FILE"; then
    hs_log "  注入状态文件        : 存在（守护会重注入）"
  else
    hs_log "  注入状态文件        : 不存在（守护不工作）"
  fi
  gme="$(hs_json_get "$CFG_FILE" generateMemoryEnabled)"
  lme="$(hs_json_get "$CFG_FILE" localMemoryEnabled)"
  [ -n "$gme" ] || gme='-'
  [ -n "$lme" ] || lme='-'
  hs_log "  generateMemoryEnabled: $gme   (必须是 True 否则整条链路 skip)"
  hs_log "  localMemoryEnabled  : $lme"
  if hs_isfile "$FILE_MEM"; then
    same='False'
    [ "$(hs_sha256 "$FILE_MEM")" = "$SRC_HASH" ] && same='True'
    hs_log "  MEMORY.md           : $(hs size "$FILE_MEM") bytes / 与提示词一致=$same"
  else
    hs_log "  MEMORY.md           : 不存在"
  fi
  sk_count=0; sk_names=""
  if [ -d "$SKILLS_DIR" ]; then
    for d in "$SKILLS_DIR"/*; do
      [ -d "$d" ] || continue
      [ -f "$d/SKILL.md" ] || continue
      sk_count=$((sk_count + 1))
      sk_names="$sk_names$(basename "$d"), "
    done
  fi
  hs_log "  skills 已装         : $sk_count 个  (${sk_names%, })"
  arch_bak=0
  if [ -n "$ARCHIVES" ]; then
    while IFS= read -r af || [ -n "$af" ]; do
      [ -n "$af" ] || continue
      [ -f "$af.bak-inject" ] && arch_bak=$((arch_bak + 1))
    done <"$(hs_tmp)/status-arch.txt"
  fi
  hs_log "  备份                : 档案=$arch_bak 个 开关=$(if hs_isfile "$CFG_BAK"; then printf 'True'; else printf 'False'; fi) 记忆=$(if hs_isfile "$FILE_MEM_BAK"; then printf 'True'; else printf 'False'; fi)"
  exit 0
fi

# ---------- 卸载 ----------
if [ "$UNINSTALL" -eq 1 ]; then
  DONE=""
  add_done() { DONE="$DONE$1
"; }

  # 目标档案 = 本次扫描到的 + 状态文件里记录过的（换账号/换机器后仍能清干净）
  TARGETS=""
  [ -n "$ARCHIVES" ] && TARGETS="$ARCHIVES"
  if hs_isfile "$STATE_FILE"; then
    st_arch="$(hs_state_list "$STATE_FILE" archives)"
    st_one="$(hs_json_get "$STATE_FILE" archive)"
    for a in $st_arch $st_one; do
      [ -n "$a" ] || continue
      case "
$TARGETS
" in *"
$a
"*) continue ;; esac
      TARGETS="$TARGETS$a
"
    done
  fi
  TARGETS="$(printf '%s\n' "$TARGETS" | grep -v '^$')"

  if [ -n "$TARGETS" ]; then
    printf '%s\n' "$TARGETS" >"$(hs_tmp)/uninst-arch.txt"
    while IFS= read -r af || [ -n "$af" ]; do
      [ -n "$af" ] || continue
      # 解除只读锁（加固项，失败只告警）
      [ -f "$af" ] && hs chmod "$af" 666 2>/dev/null || true
      bak="$af.bak-inject"
      if [ -f "$bak" ]; then
        mv -f "$bak" "$af"
        add_done "档案已从备份还原: $(basename "$af")"
      elif [ -f "$af" ]; then
        uid_now="$(basename "$af")"
        uid_now="${uid_now%_memory.md}"
        now="$(hs_now)"
        archive_template "$uid_now" "" "$now" | hs write "$af"
        add_done "档案 memoryBlock 已清空: $(basename "$af")"
      fi
    done <"$(hs_tmp)/uninst-arch.txt"
  else
    add_done '云记忆档案未执行（该账号还没有档案文件）'
  fi

  if hs_isfile "$STATE_FILE"; then
    rm -f "$STATE_FILE"
    add_done '注入状态文件已删除（守护停止重注入）'
  fi

  if hs_isfile "$FILE_MEM_BAK"; then
    mv -f "$FILE_MEM_BAK" "$FILE_MEM"
    add_done 'MEMORY.md 已从备份还原'
  elif hs_isfile "$FILE_MEM"; then
    rm -f "$FILE_MEM"
    add_done 'MEMORY.md 已删除（无备份）'
  fi

  if hs_isfile "$CFG_BAK"; then
    mv -f "$CFG_BAK" "$CFG_FILE"
    add_done 'app-config.json 已从备份还原'
  elif hs_isfile "$CFG_FILE"; then
    set_app_config_flags "$CFG_FILE" 'false' 'false'
    add_done 'app-config.json 无备份：两个记忆开关已置 false'
  fi

  if hs_isfile "$MANIFEST_FILE"; then
    manifest_skill_pairs "$MANIFEST_FILE" >"$(hs_tmp)/uninst-pairs.txt"
    sed -e 's/ .*//' "$(hs_tmp)/uninst-pairs.txt" >"$(hs_tmp)/uninst-names.txt"
    # 当前磁盘上的 SHA256（一次算完），与清单逐个比：
    #   一致 = 未被用户改过 → 交给 lib.sh 删（只删随包分发过的，用户自建技能一条不沾）
    #   不一致 = 用户自己改过 → 保留
    build_skills_pairs "$(hs_tmp)/uninst-names.txt" "$(hs_tmp)/uninst-cur-pairs.txt"
    awk 'NR == FNR { m[$1] = $2; next } ($1 in m) && m[$1] == $2 { print $1 }' \
      "$(hs_tmp)/uninst-pairs.txt" "$(hs_tmp)/uninst-cur-pairs.txt" >"$(hs_tmp)/uninst-unmodified.txt"
    removed="$(hs_remove_skills "$(hs_tmp)/uninst-unmodified.txt" "$SKILLS_DIR")"
    removed="$(printf '%s\n' "$removed" | grep -c .)"
    kept=0
    while IFS= read -r name || [ -n "$name" ]; do
      [ -n "$name" ] || continue
      [ -d "$SKILLS_DIR/$name" ] && kept=$((kept + 1))
    done <"$(hs_tmp)/uninst-names.txt"
    rm -f "$MANIFEST_FILE"
    drop_skill_overrides "$SETTINGS_FILE" "$(sed -e 's/ .*//' "$(hs_tmp)/uninst-pairs.txt")"
    add_done "skills 已卸载 $removed 个（用户自行改过的保留 $kept 个）"
  else
    add_done 'skills 未执行（无安装清单）'
  fi

  hs_log ""
  hs_log "[还原结果]"
  printf '%s' "$DONE" | while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] && hs_log "  - $line"
  done
  if hs_isfile "$CFG_FILE"; then
    cg="$(hs_json_get "$CFG_FILE" generateMemoryEnabled)"
    cl="$(hs_json_get "$CFG_FILE" localMemoryEnabled)"
    hs_log "  现值: generateMemoryEnabled=$cg localMemoryEnabled=$cl"
  fi
  exit 0
fi

# ---------- 安装 ----------
if [ "$KILL_APP" -eq 1 ] && [ "$APP_RUNNING" -eq 1 ]; then
  pkill -x "$APP_NAME" 2>/dev/null || true
  sleep 3
  hs_log "  已结束 $APP_NAME 进程"
fi

SRC_TEXT="$(hs_read "$SOURCE_PROMPT"; printf 'X')"
SRC_TEXT="${SRC_TEXT%X}"
SRC_HASH="$(hs_sha256 "$SOURCE_PROMPT")"
now="$(hs_now)"
STEPS=0

# 1) 账号级云记忆档案（真正被自动注入的全局记忆）
ARCH_FAILED=""
if [ -n "$ARCHIVES" ]; then
  hs mkdir "$MEM_DIR"
  printf '%s\n' "$ARCHIVES" >"$(hs_tmp)/arch.txt"
  while IFS= read -r af || [ -n "$af" ]; do
    [ -n "$af" ] || continue
    af_bak="$af.bak-inject"
    if [ -f "$af" ] && [ ! -f "$af_bak" ]; then
      old_block="$(archive_block "$af" | hs_trim_all)"
      new_block="$(printf '%s' "$SRC_TEXT" | hs_trim_all)"
      if [ "$old_block" != "$new_block" ]; then
        cp -f "$af" "$af_bak"
      fi
    fi
    [ -f "$af" ] && hs chmod "$af" 666 2>/dev/null || true
    uid_of_file=""
    if [ -f "$af" ]; then
      uid_of_file="$(sed -n 's/.*"uid"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$af" | head -n 1)"
    fi
    [ -n "$uid_of_file" ] || { uid_of_file="$(basename "$af")"; uid_of_file="${uid_of_file%_memory.md}"; }
    md="$(archive_template "$uid_of_file" "$SRC_TEXT" "$now")"
    written=0
    try=1
    while [ "$try" -le 3 ]; do
      if printf '%s' "$md" | hs write "$af" 2>/dev/null; then written=1; break; fi
      hs_wblog "档案写入失败(第 $try 次): $af"
      sleep 0.8
      try=$((try + 1))
    done
    if [ "$written" -eq 0 ]; then
      ARCH_FAILED="$ARCH_FAILED$af
"
      hs_log "  [失败] 档案被占用，写入失败: $(basename "$af")"
      continue
    fi
    # 只读锁定：程序写档案走 tmp+rename，rename 覆盖只读文件会 EPERM，从而挡住空档案回写
    if ! hs chmod "$af" 444 2>/dev/null; then
      hs_log "  [提示] 只读锁设置失败(不影响注入生效): $(basename "$af")"
      hs_wblog "只读锁失败 $af"
    fi
  done <"$(hs_tmp)/arch.txt"
  STEPS=$((STEPS + 1))
  hs_log "[$STEPS] 云记忆档案已注入 memoryBlock：$ARCHIVE_COUNT 个（$(printf '%s' "$(printf '%s' "$SRC_TEXT" | hs_trim_all)" | wc -c | tr -d ' ') 字符，Version $MEM_VERSION，已设只读）"
  printf '%s\n' "$ARCHIVES" | while IFS= read -r af || [ -n "$af" ]; do
    [ -n "$af" ] && hs_log "      - $af"
  done
else
  hs_log "[1] 云记忆档案未执行：该账号还没有记忆档案文件（WorkBuddy 未登录或从未产生记忆）"
  hs_log "      处理：先在 WorkBuddy 里发一句话再重跑本脚本；或安装后由主进程守护自动补注入"
fi

# 2) 用户级文件记忆（AI 主动读取的兜底）
if hs_isfile "$FILE_MEM" && [ ! -f "$FILE_MEM_BAK" ] && [ "$(hs_sha256 "$FILE_MEM")" != "$SRC_HASH" ]; then
  cp -f "$FILE_MEM" "$FILE_MEM_BAK"
fi
if hs_write "$FILE_MEM" <"$SOURCE_PROMPT" 2>/dev/null; then :; else
  hs_log "  [提示] MEMORY.md 写入失败（可能被占用），已跳过"
  hs_wblog "MEMORY.md 写入失败"
fi
STEPS=$((STEPS + 1))
hs_log "[$STEPS] MEMORY.md 已写入 $(hs size "$FILE_MEM") bytes"

# 3) 记忆总闸
hs mkdir "$(dirname "$CFG_FILE")"
if hs_isfile "$CFG_FILE" && [ ! -f "$CFG_BAK" ]; then
  cp -f "$CFG_FILE" "$CFG_BAK"
fi
set_app_config_flags "$CFG_FILE" 'true' 'true'
STEPS=$((STEPS + 1))
hs_log "[$STEPS] generateMemoryEnabled = true（备份: $CFG_BAK）"

# 4) Skills
INSTALLED=""
if [ "$NO_SKILLS" -eq 1 ]; then
  hs_log "[$STEPS] skills 未执行（-NoSkills）"
elif [ ! -d "$SKILLS_SRC" ]; then
  hs_log "[$STEPS] skills 未执行（找不到 $SKILLS_SRC）"
else
  hs mkdir "$SKILLS_DIR"
  # 上一次安装清单里记过哪些技能（新版装完按它清理旧版遗留）
  PREV_SKILLS=""
  if hs_isfile "$MANIFEST_FILE"; then
    PREV_SKILLS="$(manifest_skill_pairs "$MANIFEST_FILE" | sed -e 's/ .*//')"
  fi
  printf '%s\n' "$PREV_SKILLS" >"$(hs_tmp)/prev-skills.txt"
  INSTALLED="$(hs_install_skills "$SKILLS_SRC" "$SKILLS_DIR")"
  printf '%s\n' "$INSTALLED" >"$(hs_tmp)/cur-skills.txt"
  # 安装清单：source / installedAt / prompt / skills{name:{sha256}}
  # 一次 shasum 算完所有已装 SKILL.md（逐技能起一次进程会撞主进程 300 秒超时）
  build_skills_pairs "$(hs_tmp)/cur-skills.txt" "$(hs_tmp)/skills-pairs.txt"
  {
    printf '{\n'
    printf '  "source": %s,\n' "$(hs_json_str "$SKILLS_SOURCE")"
    printf '  "installedAt": %s,\n' "$(hs_json_str "$now")"
    printf '  "prompt": %s,\n' "$(hs_json_str "$(basename "$SOURCE_PROMPT")")"
    printf '  "skills": {'
    awk -F' ' '{ if (NR > 1) printf ","; printf "\n    \"%s\": {\n      \"sha256\": \"%s\"\n    }", $1, $2 }' \
      "$(hs_tmp)/skills-pairs.txt"
    printf '\n  }\n}\n'
  } >"$(hs_tmp)/manifest.json"
  cp -f "$(hs_tmp)/manifest.json" "$MANIFEST_FILE"
  # 清掉上一版遗留、新版技能库里已移除的技能
  stale="$(hs_prune_stale_skills "$(hs_tmp)/prev-skills.txt" "$(hs_tmp)/cur-skills.txt" "$SKILLS_DIR")"
  if [ -n "$stale" ]; then
    hs_log "[$STEPS] 已清理旧版遗留 skills $(printf '%s\n' "$stale" | grep -c .) 个"
  fi
  # 清掉可能把这些技能禁用的 override（settings.json 的 skillOverrides：无 key = 启用）
  drop_skill_overrides "$SETTINGS_FILE" "$INSTALLED"
  STEPS=$((STEPS + 1))
  hs_log "[$STEPS] skills 已装 $(printf '%s\n' "$INSTALLED" | grep -c .) 个 → $SKILLS_DIR"
fi

# 5) 注入状态文件（主进程守护线程据此自动重注入）
#    字段名/顺序与 PowerShell 版逐字一致：prompt / promptSha256 / configDir / uid / memoryDir /
#    archives / archive / memoryFile / appConfig / version / skills / installedAt
{
  printf '{\n'
  printf '  "prompt": %s,\n' "$(hs_json_str "$(basename "$SOURCE_PROMPT")")"
  printf '  "promptSha256": %s,\n' "$(hs_json_str "$SRC_HASH")"
  printf '  "configDir": %s,\n' "$(hs_json_str "$CONFIG_DIR")"
  printf '  "uid": %s,\n' "$(hs_json_str "$WB_UID")"
  printf '  "memoryDir": %s,\n' "$(hs_json_str "$MEM_DIR")"
  printf '  "archives": [%s],\n' "$(hs_json_array_lines <"$(hs_tmp)/arch.txt")"
  printf '  "archive": %s,\n' "$(hs_json_str "$ARCHIVE0")"
  printf '  "memoryFile": %s,\n' "$(hs_json_str "$FILE_MEM")"
  printf '  "appConfig": %s,\n' "$(hs_json_str "$CFG_FILE")"
  printf '  "version": %s,\n' "$MEM_VERSION"
  printf '  "skills": [%s],\n' "$(hs_json_array_lines <"$(hs_tmp)/cur-skills.txt")"
  printf '  "installedAt": %s\n' "$(hs_json_str "$now")"
  printf '}\n'
} >"$STATE_FILE"
STEPS=$((STEPS + 1))
hs_log "[$STEPS] 注入状态已记录 → $STATE_FILE"

# ---------- 校验 ----------
hs_log ""
hs_log "[校验]"
OK=1
if [ -n "$ARCHIVES" ]; then
  printf '%s\n' "$ARCHIVES" >"$(hs_tmp)/verify-arch.txt"
  while IFS= read -r af || [ -n "$af" ]; do
    [ -n "$af" ] || continue
    [ -f "$af" ] || continue
    archive_block "$af" | hs_trim_all >"$(hs_tmp)/blk.txt"
    printf '%s' "$SRC_TEXT" | hs_trim_all >"$(hs_tmp)/src.txt"
    if cmp -s "$(hs_tmp)/blk.txt" "$(hs_tmp)/src.txt"; then blockOk='True'; else blockOk='False'; OK=0; fi
    if hs_contains "$af" '"memoryBlock"'; then rawOk='True'; else rawOk='False'; OK=0; fi
    hs_log "  档案 memoryBlock 可解析 : $blockOk  ($(basename "$af"))"
    hs_log "  档案 RAW_JSON 存在      : $rawOk"
  done <"$(hs_tmp)/verify-arch.txt"
fi
cg="$(hs_json_get "$CFG_FILE" generateMemoryEnabled)"
hs_log "  generateMemoryEnabled   : $cg"
[ "$cg" = 'true' ] || OK=0
if [ "$(hs_sha256 "$FILE_MEM")" = "$SRC_HASH" ]; then hs_log "  MEMORY.md 哈希一致      : True"; else hs_log "  MEMORY.md 哈希一致      : False"; OK=0; fi
if [ -n "$INSTALLED" ]; then
  sk=0
  for d in "$SKILLS_DIR"/*; do
    [ -d "$d" ] && [ -f "$d/SKILL.md" ] && sk=$((sk + 1))
  done
  hs_log "  skills 落盘             : $sk 个"
fi
# 状态文件是守护线程的输入，必须是可解析的 JSON（字段名不能错）
if [ -n "$(hs_json_get "$STATE_FILE" prompt)" ]; then
  hs_log "  注入状态文件可解析      : True"
else
  hs_log "  注入状态文件可解析      : False"
  OK=0
fi

ARCH_FAILED_N="$(printf '%s\n' "$ARCH_FAILED" | grep -c .)"
if [ "$OK" -eq 1 ] && [ "$ARCH_FAILED_N" -gt 0 ]; then
  hs_wblog "部分完成: 档案写入失败 $ARCH_FAILED_N 个"
  hs_log ""
  hs_log "[部分完成] 云记忆档案被占用，未能写入："
  printf '%s\n' "$ARCH_FAILED" | while IFS= read -r x || [ -n "$x" ]; do
    [ -n "$x" ] && hs_log "           - $x"
  done
  hs_log "           最常见原因：WorkBuddy 正在运行并占用该文件。"
  hs_log "           处理：完全退出 WorkBuddy（托盘/菜单栏退出）后重跑；开关/记忆文件/skills 已生效。"
  exit 2
fi
if [ "$OK" -eq 1 ]; then
  hs_wblog "完成: 校验全部通过"
  hs_log ""
  hs_log "[完成] WorkBuddy 破甲注入成功"
  if [ "$APP_RUNNING" -eq 1 ] && [ "$KILL_APP" -eq 0 ]; then
    hs_log "  下一步：完全退出 $APP_NAME 后重新启动"
  fi
  if [ "$RESTART" -eq 1 ]; then
    if command -v open >/dev/null 2>&1; then
      if [ -n "$INSTALL_ROOT" ] && [ -d "$INSTALL_ROOT" ]; then
        open -a "$INSTALL_ROOT" 2>/dev/null && hs_log "  已重新拉起 $APP_NAME"
      else
        open -a "$APP_NAME" 2>/dev/null && hs_log "  已重新拉起 $APP_NAME"
      fi
    else
      hs_log "  未执行：本平台没有 open 命令，请手动启动 $APP_NAME"
    fi
  fi
  hs_log "  生效验证：发一句话后看日志 memory_injection_success"
  hs_log "  还原命令：./install-workbuddy.sh -Uninstall"
else
  hs_wblog "中断: 校验未通过（见上方失败项）"
  hs_log ""
  hs_log "[中断] 校验未通过，检查上面的失败项"
  exit 1
fi
