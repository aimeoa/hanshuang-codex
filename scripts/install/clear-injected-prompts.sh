#!/usr/bin/env bash
# =============================================================================
#  寒霜破甲工具 · 清除全部注入提示词（零提示词）· macOS
#
#  六个目标（codex / zcode / cursor / claude / workbuddy / dsh）各有一套安装脚本、
#  各有自己的注入点。这个脚本把它们全部还原到「没有注入过任何提示词」的状态。
#
#  安全规则（硬约束，改脚本时不要放宽）：
#    * 白名单式：只处理下面明确列出的注入点，不做「扫到像的就删」。
#    * AGENTS.md / CLAUDE.md 只按注入标记块摘除；没有标记的文件一个字节都不碰。
#    * managed-prompts 是本工具自己的目录，提示词整目录清空。
#    * .bak 不是提示词 —— 它是注入前用户原文的备份。要先验证它确实干净（不含注入
#      痕迹）才能用来还原；备份自己就是旧注入的话还原等于没卸载，那种直接删。
#    * WorkBuddy 记忆档案只清 «## Memory Block» 段内容，档案文件本身、uid 和
#      RAW_JSON 都保留 —— 那是 WorkBuddy 的文件，不是我们的。
#    * 默认先 dry-run，加 -Apply 才真删。
#
#  用法（对齐 PowerShell 版的开关名，主进程会带 -Apply -Targets <target> 调用）：
#    bash clear-injected-prompts.sh
#    bash clear-injected-prompts.sh -Apply
#    bash clear-injected-prompts.sh -Apply -Targets claude
#    bash clear-injected-prompts.sh -ListOnly          # 只吐待清除路径，供别的脚本解析
#
#  ---- 相对 clear-injected-prompts.ps1 的 macOS 适配 ----
#    · %APPDATA% / %LOCALAPPDATA% → $HOME/Library/Application Support
#    · 盘符相关逻辑全部删掉：.codex 候选不再遍历盘符、Cursor 不再检查「盘符根祖先规则」、
#      WorkBuddy 的「限深扫盘」改成限深扫 $HOME（不再遍历所有卷）
#    · 写文件统一 LF（PS 版在 Windows 上是 CRLF），正文内容与判定规则不变
#
#  ---- 本脚本自带的两个函数（lib.sh 由主 agent 维护，不修改它）----
#    · is_artifact()  在 hs_is_artifact（硬标记层）之上补上 PS 版的第二层判据：
#                     取候选文件最长的 8 行（≥20 字符）去随包提示词里逐字比对，
#                     命中 ≥3 行才算注入产物。这一层专为「旧版无标记覆盖式注入」而设，
#                     判错就是丢用户数据，阈值 3 是 PS 版实测标定的值，不要改。
#    · backup_base()  惰性匹配备份命名 <名>.<bak|backup>[_.-]…（对应 PS 的 `.+?` 惰性量词）。
#
#  ---- 一处刻意的「多认一套」----
#    DSH 的 ~/.dsh/AGENTS.md 同时认两套标记：源脚本记录的「寒霜破甲注入开始/结束」，
#    以及本仓库 macOS 的 install-dsh.sh 实际写入的 HANSHUANG-INJECT:BEGIN/END。
#    两套都是本工具自己的标记，多认一套只会摘得更准（保留块外的用户内容），
#    少认一套则会把整份文件当注入产物挪走 —— 那是丢用户数据的边缘行为。
#
#  ---- 性能 ----
#    热循环里不 spawn 外部命令、也不起子 shell（技能树有 200+ 个目录，
#    basename/cmp 这类外部命令实测 ~0.6s/次，逐个调用会把脚本拖到两分钟以上）。
# =============================================================================

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

APPLY=0
hs_flag -Apply && APPLY=1
LIST_ONLY=0
hs_flag -ListOnly && LIST_ONLY=1
SCAN_DEPTH="$(hs_arg -ScanDepth 4)"

if [ "$APPLY" -eq 1 ]; then
  MODE='APPLY（真删）'
else
  MODE='DRY-RUN（只看不删，加 -Apply 执行）'
fi

# -----------------------------------------------------------------------------
# 目标筛选
# -----------------------------------------------------------------------------
TARGETS=()
TARGETS_N=0

add_target() {
  local t="$1" i=0
  [ -n "$t" ] || return 0
  while [ "$i" -lt "$TARGETS_N" ]; do
    [ "${TARGETS[$i]}" = "$t" ] && return 0
    i=$((i + 1))
  done
  TARGETS[$TARGETS_N]="$t"
  TARGETS_N=$((TARGETS_N + 1))
}

# -Targets codex,zcode 在 PS 的 -File 模式下会作为「一个字符串」传进来（不会自动按逗号
# 拆分），结果对所有目标都返回 false —— 脚本什么都不做，却报告「没有发现残留」。
# 静默的假阴性比报错更危险，这里统一拆一次。
TARGETS_RAW="$(hs_arg -Targets '')"
if [ -n "$TARGETS_RAW" ]; then
  TARGETS_SPLIT="$(printf '%s' "$TARGETS_RAW" | tr ',' '\n')"
  while IFS= read -r _t; do
    add_target "$_t"
  done <<<"$TARGETS_SPLIT"
fi

want() {
  local i=0
  [ "$TARGETS_N" -eq 0 ] && return 0
  while [ "$i" -lt "$TARGETS_N" ]; do
    [ "${TARGETS[$i]}" = "$1" ] && return 0
    i=$((i + 1))
  done
  return 1
}

# -----------------------------------------------------------------------------
# 计划表 / 保留表（bash 3.2 没有关联数组，用并行数组 + 计数器）
# -----------------------------------------------------------------------------
PLAN_KIND=(); PLAN_PATH=(); PLAN_NOTE=(); PLAN_SRC=(); PLAN_N=0
plan_add() {
  PLAN_KIND[$PLAN_N]="$1"
  PLAN_PATH[$PLAN_N]="$2"
  PLAN_NOTE[$PLAN_N]="${3:-}"
  PLAN_SRC[$PLAN_N]="${4:-}"
  PLAN_N=$((PLAN_N + 1))
}

KEPT=(); KEPT_N=0
keep_add() {
  KEPT[$KEPT_N]="$1"
  KEPT_N=$((KEPT_N + 1))
}

PLANNED=(); PLANNED_N=0
planned_has() {
  local i=0
  while [ "$i" -lt "$PLANNED_N" ]; do
    [ "${PLANNED[$i]}" = "$1" ] && return 0
    i=$((i + 1))
  done
  return 1
}
# 返回 0 = 本次新加入（对应 PS 的 HashSet.Add()）
planned_add() {
  planned_has "$1" && return 1
  PLANNED[$PLANNED_N]="$1"
  PLANNED_N=$((PLANNED_N + 1))
  return 0
}

RESTORE_TARGETS=(); RESTORE_N=0
restore_has() {
  local i=0
  while [ "$i" -lt "$RESTORE_N" ]; do
    [ "${RESTORE_TARGETS[$i]}" = "$1" ] && return 0
    i=$((i + 1))
  done
  return 1
}
restore_add() {
  restore_has "$1" && return 0
  RESTORE_TARGETS[$RESTORE_N]="$1"
  RESTORE_N=$((RESTORE_N + 1))
}

# -----------------------------------------------------------------------------
# 注入痕迹判定
# -----------------------------------------------------------------------------
CORPUS_FILE="$(hs_tmp)/bundled-prompts.txt"
CORPUS_READY=0

# 随包提示词正文汇总（PS 版 Get-BundledPrompts 的等价物）：
# 寒霜*.md / gpt-*.md / gpt-6-astra-v1/*.md，都拼进一个文件，后面用 grep -F 逐行比对。
corpus_build() {
  [ "$CORPUS_READY" -eq 1 ] && return 0
  : >"$CORPUS_FILE"
  local f
  for f in "$HS_ROOT"/寒霜*.md "$HS_ROOT"/gpt-*.md "$HS_ROOT"/gpt-6-astra-v1/*.md; do
    [ -f "$f" ] || continue
    cat "$f" >>"$CORPUS_FILE"
  done
  CORPUS_READY=1
}

# 文件里最长的 8 行（≥20 字符），一行一个
longest_lines() {
  awk '
    length($0) >= 20 { n++; len[n] = length($0); line[n] = $0 }
    END {
      for (i = 1; i <= 8; i++) {
        best = 0; bi = 0
        for (j = 1; j <= n; j++) {
          if (used[j] != 1 && len[j] > best) { best = len[j]; bi = j }
        }
        if (bi == 0) break
        used[bi] = 1
        print line[bi]
      }
    }
  ' "$1"
}

# 是不是「寒霜注入产物」：先看硬标记（lib.sh 的 hs_is_artifact，全目标共用一份特征串），
# 再看内容比对（旧版无标记注入只能靠这一层认出来）。判定错就是丢用户数据，两层都要。
is_artifact() {
  local f="$1" lines hit=0 l
  [ -f "$f" ] || return 1
  hs_is_artifact "$f" && return 0
  corpus_build
  [ -s "$CORPUS_FILE" ] || return 1
  lines="$(longest_lines "$f")"
  [ -n "$lines" ] || return 1
  while IFS= read -r l; do
    [ -n "$l" ] || continue
    if grep -Fq -- "$l" "$CORPUS_FILE" 2>/dev/null; then
      hit=$((hit + 1))
      [ "$hit" -ge 3 ] && return 0
    fi
  done <<<"$lines"
  return 1
}

# 惰性匹配备份命名：^(.+?)\.(bak|backup)([_.-].*)?$ → 输出「点号前」的部分。
# $2 = 后缀的 ERE（默认 bak|backup）
backup_base() {
  # 注意：local 会把整条命令的词先展开完再赋值，所以同一条 local 里不能引用前一个变量
  local name="$1"
  local re="${2:-^(bak|backup)([_.-].*)?\$}"
  local i=1
  local rest
  local n="${#name}"
  while [ "$i" -lt "$n" ]; do
    if [ "${name:$i:1}" = "." ]; then
      rest="${name:$((i + 1))}"
      if [[ "$rest" =~ $re ]]; then
        printf '%s' "${name:0:$i}"
        return 0
      fi
    fi
    i=$((i + 1))
  done
  return 1
}

# 摘掉注入块后只剩空白 / 残缺注释（例如注入时把文件截断留下的 "<!--"）时，
# 视为「这份文件本来就是我们建的」，应当还原备份而不是留下这点垃圾。
# 对应 PS 的 Test-Trivial：^(<!--|-->|<!---->|\s)*$
is_trivial() {
  local s="$1"
  # 同 lib.sh 的 hs_is_artifact：${s//[[:space:]]/} 在大字符串上是 O(n²)，
  # 11KB 要 6 秒多。改用 tr（fork 一次约 10ms），并只在短内容上做。
  if [ "${#s}" -lt 4096 ] && [ -z "$(printf '%s' "$s" | tr -d '[:space:]')" ]; then
    return 0
  fi
  s="${s//<!--/}"
  s="${s//-->/}"
  [ -z "$s" ] && return 0
  return 1
}

# 「本工具在注入前留的主文件备份，且主文件已经还原干净」—— 两者同时成立时备份已无用途。
# 两道硬条件，缺一不可（对应 PS 的 Test-SpentBackup）：
#   1) 命名必须是本工具的格式：<主文件>.backup-<8位日期> / .bak_<8位日期> …
#   2) 主文件必须已不含任何注入痕迹
spent_backup() {
  local path="$1" dir name base mainPath t
  dir="${path%/*}"
  name="${path##*/}"
  base="$(backup_base "$name" '^(bak|backup)[-_.][0-9]{8}')" || return 1
  # 只认本工具真正会注入的那两个主文件。别的名字一律不碰 ——
  # `<名>.bak-<8位数字>` 是很常见的备份命名，按格式匹配会把用户/别家的备份卷进来。
  [ "$base" = "AGENTS.md" ] || [ "$base" = "CLAUDE.md" ] || return 1
  mainPath="$dir/$base"
  [ -f "$mainPath" ] || return 1
  t="$(hs_read "$mainPath")"
  case "$t" in
    *寒霜破甲注入* | *HANSHUANG-INJECT* | *CTF-LAB-2.0*) return 1 ;;
  esac
  return 0
}

# managed-prompts 里找一份「干净的原文件备份」（最新的优先），找不到返回 1
clean_mp_backup() {
  local home="$1"
  local base="$2"
  local mp="$home/managed-prompts"
  local f t best="" best_t=-1
  [ -d "$mp" ] || return 1
  for f in "$mp/$base".bak*; do
    [ -f "$f" ] || continue
    [ "$(hs size "$f")" -gt 0 ] || continue
    is_artifact "$f" && continue
    t="$(hs mtime "$f")"
    if [ "$t" -gt "$best_t" ]; then
      best_t="$t"
      best="$f"
    fi
  done
  [ -n "$best" ] || return 1
  printf '%s' "$best"
}

# 去掉首尾空白（PS 的 .Trim()，只处理整串两端，不动中间行的缩进）
trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# 只去尾部空白（PS 的 .TrimEnd()）
trim_end() {
  local s="$1"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# ---- 性能：热循环里一律不 spawn 外部命令、也不起子 shell ----
# 本机实测（Windows git bash）：一次外部命令 ~0.6s，一次 $(函数) 子 shell fork ~0.3s。
# 技能树有 200+ 个目录，逐个 basename/cmp 会把脚本拖到两分钟以上。
# 所以取文件名/目录名/比内容全部内联成 bash 内建写法：
#   basename → ${p##*/}     dirname → ${p%/*}
#   比内容   → same_file()（$(<file) 是内建快路径，不 fork）
# 两个文件内容是否一致（PS 版用 Get-FileHash 比对 SKILL.md / 随附包）
same_file() {
  local x y
  [ -f "$1" ] && [ -f "$2" ] || return 1
  x="$(<"$1")"
  y="$(<"$2")"
  [ "$x" = "$y" ]
}

# 目录是否为空
dir_empty() {
  local f
  for f in "$1"/* "$1"/.[!.]*; do
    [ -e "$f" ] || continue
    return 1
  done
  return 0
}

# file:/// 形式的 workspace 路径还原成真实路径（对应 [uri]::UnescapeDataString）
url_decode() {
  local s="$1" out="" hex ch
  while [ -n "$s" ]; do
    case "$s" in
      %[0-9A-Fa-f][0-9A-Fa-f]*)
        hex="${s#%}"
        hex="${hex:0:2}"
        ch="$(printf "\\x$hex")"
        out="$out$ch"
        s="${s#%??}"
        ;;
      *)
        out="$out${s:0:1}"
        s="${s:1}"
        ;;
    esac
  done
  printf '%s' "$out"
}

# «## Memory Block» 段是否已经是空的（对应 PS 的 (?s)## Memory Block\s*\r?\n\r?\n\s*\r?\n）
memory_block_empty() {
  awk '
    /## Memory Block/ { state = 1; next }
    state == 1 { if ($0 ~ /^[[:space:]]*$/) state = 2; else state = 0; next }
    state == 2 { if ($0 ~ /^[[:space:]]*$/) { found = 1; exit } else state = 0 }
    END { exit(found == 1 ? 0 : 1) }
  ' "$1"
}

# -----------------------------------------------------------------------------
# 单项执行（对应 PS 的 switch ($p.Kind)）
# 成功返回 0；失败返回 1 并把原因写进全局 ERR。
# 认不出的类别绝不删 —— 曾经因为类别字符串不一致掉进 default 把该「还原」的目标
# 直接删了。宁可报错，不许猜。
# -----------------------------------------------------------------------------
apply_item() {
  local kind="$1" path="$2" src="$3"
  local home base clean aside left
  case "$kind" in
    '恢复原文（用安装前备份）')
      [ -f "$src" ] || { ERR="备份不存在: $src"; return 1; }
      cp -f "$src" "$path" 2>/dev/null || { ERR="还原失败: $path"; return 1; }
      rm -f "$src" 2>/dev/null || { ERR="删除备份失败: $src"; return 1; }
      ;;
    '删除（备份本身是旧注入）')
      rm -f "$path" 2>/dev/null || { ERR="删除失败: $path"; return 1; }
      ;;
    '注入文件（摘除后仅剩垃圾）')
      # 先试着找一份干净备份还原，找不到才删
      home="${path%/*}"
      base="${path##*/}"
      clean="$(clean_mp_backup "$home" "$base")" || clean=""
      if [ -n "$clean" ]; then
        cp -f "$clean" "$path" 2>/dev/null || { ERR="还原失败: $path"; return 1; }
        rm -f "$clean" 2>/dev/null
      else
        rm -f "$path" 2>/dev/null || { ERR="删除失败: $path"; return 1; }
      fi
      ;;
    '注入文件（无标记但内容是提示词）')
      aside="$path.inject-$(hs_stamp)"
      mv -f "$path" "$aside" 2>/dev/null || { ERR="挪走失败: $path"; return 1; }
      home="${path%/*}"
      base="${path##*/}"
      clean="$(clean_mp_backup "$home" "$base")" || clean=""
      if [ -n "$clean" ]; then
        cp -f "$clean" "$path" 2>/dev/null || { ERR="还原失败: $path"; return 1; }
        rm -f "$clean" 2>/dev/null
      fi
      ;;
    '注入块')
      find_markers "$path" || return 0   # 无完整标记块：不动这个文件
      left="$(trim "$(hs_strip_block "$path" "$MK_HIT_BEGIN" "$MK_HIT_END")")"
      if [ -n "$left" ]; then
        printf '%s\n' "$left" | hs write "$path" || { ERR="写入失败: $path"; return 1; }
      fi
      ;;
    '提示词指针行')
      # 只删「值指向本工具 managed-prompts」的行。指向别处的是用户自己的配置，必须保留 ——
      # 无条件删会把用户自己配的 model_instructions_file 一起删掉。
      awk '
        {
          if ($0 ~ /^[[:space:]]*model_instructions_file[[:space:]]*=/) {
            if ($0 ~ /managed-prompts/) next
          }
          print
        }
      ' "$path" >"$(hs_tmp)/ptr.toml" 2>/dev/null || { ERR="读取失败: $path"; return 1; }
      cp -f "$(hs_tmp)/ptr.toml" "$path" 2>/dev/null || { ERR="写入失败: $path"; return 1; }
      ;;
    '记忆注入章节')
      awk '
        /^## / { if ($0 ~ /寒霜注入/) { skip = 1; next } else { skip = 0 } }
        skip != 1 { print }
      ' "$path" >"$(hs_tmp)/mem1.md" 2>/dev/null || { ERR="读取失败: $path"; return 1; }
      awk 'BEGIN { blank = 0 } /^$/ { blank++; if (blank <= 1) print; next } { blank = 0; print }' \
        "$(hs_tmp)/mem1.md" >"$(hs_tmp)/mem2.md" || { ERR="处理失败: $path"; return 1; }
      left="$(trim_end "$(<"$(hs_tmp)/mem2.md")")"
      printf '%s\n' "$left" | hs write "$path" || { ERR="写入失败: $path"; return 1; }
      ;;
    'WorkBuddy 记忆块')
      # WorkBuddyGuard 写入后会 chmod 444，先解只读
      chmod u+w "$path" 2>/dev/null
      awk '
        BEGIN { state = 0 }
        state == 0 { print; if ($0 ~ /^## Memory Block/) state = 1; next }
        state == 1 { if ($0 ~ /^[[:space:]]*$/) state = 2; next }
        state == 2 {
          if ($0 ~ /^---/) { print ""; print; state = 3; next }
          state = 1; next
        }
        state == 3 { print }
      ' "$path" >"$(hs_tmp)/wb.md" 2>/dev/null || { ERR="读取失败: $path"; return 1; }
      cp -f "$(hs_tmp)/wb.md" "$path" 2>/dev/null || { ERR="写入失败: $path"; return 1; }
      ;;
    # 整份就是提示词 / 就是本工具建的 —— 单文件删除类
    'WorkBuddy state' | 'WorkBuddy 全局记忆（注入产物）' | '注入副产物（内容是提示词）' \
    | 'DSH 注入文件' | 'Cursor 规则文件' | 'Cursor 规则文件（旧版）' | 'Cursor 安装状态' \
    | '程序本体备份（已无还原需求）' | '主文件备份（已还原，备份无用）' | '本工具生成的说明文件')
      rm -f "$path" 2>/dev/null || { ERR="删除失败: $path"; return 1; }
      ;;
    # 整份就是提示词 / 就是本工具建的 —— 目录删除类
    '提示词文件' | '清空目录' | '随附包（确认是本工具的）' | '随附包备份' | '技能（确认是本工具的）')
      rm -rf "$path" 2>/dev/null || { ERR="删除失败: $path"; return 1; }
      ;;
    *)
      ERR="未知的清理类别，已跳过（不做任何删除）: $kind -> $path"
      return 1
      ;;
  esac
  return 0
}

# -----------------------------------------------------------------------------
# 目标 Home
# -----------------------------------------------------------------------------
# Codex 配置目录。不能写死 ~/.codex：用户可能把 CODEX_HOME 指到别处。
# PS 版还会遍历所有固定盘找 .codex —— macOS 没有盘符，那一段删掉。
CODEX_HOME_DIR=""
if [ -n "${CODEX_HOME:-}" ] && [ -d "$CODEX_HOME" ]; then
  CODEX_HOME_DIR="$CODEX_HOME"
else
  CODEX_HOME_DIR="$HOME/.codex"
fi

HOME_KEYS=(); HOME_PATHS=(); HOME_N=0
add_home() {
  HOME_KEYS[$HOME_N]="$1"
  HOME_PATHS[$HOME_N]="$2"
  HOME_N=$((HOME_N + 1))
}
want codex && add_home codex "$CODEX_HOME_DIR"
want zcode && add_home zcode "$HOME/.zcode"
want claude && add_home claude "$HOME/.claude"
want dsh && add_home dsh "$HOME/.dsh"

hs_log "=== 清除全部注入提示词 [$MODE] ==="
hs_log ''

# -----------------------------------------------------------------------------
# 1. managed-prompts：提示词实体 + 安装前备份
# -----------------------------------------------------------------------------
hs_log '[1/5] managed-prompts（提示词实体 + 安装前备份）'
i=0
while [ "$i" -lt "$HOME_N" ]; do
  k="${HOME_KEYS[$i]}"
  h="${HOME_PATHS[$i]}"
  i=$((i + 1))
  mp="$h/managed-prompts"
  [ -e "$mp" ] || continue

  ENT=(); ENT_N=0
  for f in "$mp"/* "$mp"/.*; do
    [ -e "$f" ] || continue
    bn="${f##*/}"
    [ "$bn" = "." ] && continue
    [ "$bn" = ".." ] && continue
    ENT[$ENT_N]="$f"
    ENT_N=$((ENT_N + 1))
  done
  [ "$ENT_N" -gt 0 ] || continue

  en=0
  while [ "$en" -lt "$ENT_N" ]; do
    f="${ENT[$en]}"
    en=$((en + 1))
    bn="${f##*/}"
    # 备份命名：<原文名>.bak / .bak_20260101 / .backup-xxx
    base="$(backup_base "$bn")" || base=""
    if [ -n "$base" ]; then
      target="$h/$base"
      if is_artifact "$f"; then
        # 备份自己就是旧注入：还原它等于没卸载，直接删
        plan_add '删除（备份本身是旧注入）' "$f" ''
      else
        restore_add "$target"
        plan_add '恢复原文（用安装前备份）' "$target" "备份源: $bn" "$f"
      fi
      continue
    fi
    plan_add '提示词文件' "$f" "$k / $bn"
  done
  plan_add '清空目录' "$mp" "$k / 清空后若为空则删除"
done

# -----------------------------------------------------------------------------
# 2. AGENTS.md / CLAUDE.md：摘标记块；摘完只剩垃圾的就还原备份
# -----------------------------------------------------------------------------
hs_log '[2/5] 标记块（AGENTS.md / CLAUDE.md）'
MK_PATH=(); MK_BEGIN=(); MK_END=(); MK_ALT_BEGIN=(); MK_ALT_END=(); MK_N=0
MK_HIT_BEGIN=''; MK_HIT_END=''; MK_HIT_INFO=''
add_marked() {
  want "$1" || return 0
  MK_PATH[$MK_N]="$2"
  MK_BEGIN[$MK_N]="$3"
  MK_END[$MK_N]="$4"
  MK_ALT_BEGIN[$MK_N]="${5:-}"
  MK_ALT_END[$MK_N]="${6:-}"
  MK_N=$((MK_N + 1))
}
add_marked codex "$CODEX_HOME_DIR/AGENTS.md" '<!-- 寒霜破甲注入开始' '<!-- 寒霜破甲注入结束 -->'
# DSH 两套标记都要认：install-dsh.ps1（源脚本记录的）用「寒霜破甲注入开始」，
# 而本仓库 macOS 的 install-dsh.sh 写的是 <!-- HANSHUANG-INJECT:BEGIN -->。
# 两套都是本工具自己的标记，多认一套只会更干净，不会碰到用户内容。
add_marked dsh "$HOME/.dsh/AGENTS.md" '<!-- 寒霜破甲注入开始' '<!-- 寒霜破甲注入结束 -->' \
                                        'HANSHUANG-INJECT:BEGIN' 'HANSHUANG-INJECT:END'
add_marked zcode "$HOME/.zcode/AGENTS.md" '<!-- 寒霜破甲注入开始' '<!-- 寒霜破甲注入结束 -->'
add_marked claude "$HOME/.claude/CLAUDE.md" 'HANSHUANG-INJECT:BEGIN' 'HANSHUANG-INJECT:END'

# 找出某个文件命中的标记对，命中则设好全局 MK_HIT_BEGIN / MK_HIT_END / MK_HIT_INFO
find_markers() {
  local path="$1" mk=0 info
  MK_HIT_BEGIN=''
  MK_HIT_END=''
  MK_HIT_INFO=''
  while [ "$mk" -lt "$MK_N" ]; do
    if [ "${MK_PATH[$mk]}" = "$path" ]; then
      info="$(hs_find_block "$path" "${MK_BEGIN[$mk]}" "${MK_END[$mk]}")"
      if [ "$info" != "none" ]; then
        MK_HIT_BEGIN="${MK_BEGIN[$mk]}"
        MK_HIT_END="${MK_END[$mk]}"
        MK_HIT_INFO="$info"
        return 0
      fi
      if [ -n "${MK_ALT_BEGIN[$mk]}" ]; then
        info="$(hs_find_block "$path" "${MK_ALT_BEGIN[$mk]}" "${MK_ALT_END[$mk]}")"
        if [ "$info" != "none" ]; then
          MK_HIT_BEGIN="${MK_ALT_BEGIN[$mk]}"
          MK_HIT_END="${MK_ALT_END[$mk]}"
          MK_HIT_INFO="$info"
          return 0
        fi
      fi
      return 1
    fi
    mk=$((mk + 1))
  done
  return 1
}

# 文件里是否存在任一「开始标记」（用来区分「有开始标记但无结束标记」）
has_begin_marker() {
  local path="$1" mk=0
  while [ "$mk" -lt "$MK_N" ]; do
    if [ "${MK_PATH[$mk]}" = "$path" ]; then
      hs_contains "$path" "${MK_BEGIN[$mk]}" && return 0
      if [ -n "${MK_ALT_BEGIN[$mk]}" ]; then
        hs_contains "$path" "${MK_ALT_BEGIN[$mk]}" && return 0
      fi
      return 1
    fi
    mk=$((mk + 1))
  done
  return 1
}

m=0
while [ "$m" -lt "$MK_N" ]; do
  path="${MK_PATH[$m]}"
  m=$((m + 1))
  [ -f "$path" ] || continue
  restore_has "$path" && continue   # 已由备份还原处理

  if find_markers "$path"; then
    left="$(hs_strip_block "$path" "$MK_HIT_BEGIN" "$MK_HIT_END")"
    if is_trivial "$left"; then
      plan_add '注入文件（摘除后仅剩垃圾）' "$path" '删除文件'
    else
      trimmed="$(trim "$left")"
      plan_add '注入块' "$path" "摘除 ${MK_HIT_INFO##* } 字节，保留你自己的 ${#trimmed} 字节"
    fi
  elif has_begin_marker "$path"; then
    # END 必须从 BEGIN 之后开始找。找不到就当作「没有完整的注入块」，一个字节都不动 ——
    # 早期写法是「找不到 END 就取文件尾」，那会把用户写在标记之后的内容整段删掉。
    keep_add "有开始标记但无结束标记，保留原样（不动一个字节）：$path"
  elif is_artifact "$path"; then
    plan_add '注入文件（无标记但内容是提示词）' "$path" '整份挪走'
  else
    keep_add "无注入标记，保留原样：$path"
  fi
done

# -----------------------------------------------------------------------------
# 3. config.toml：只在真有指向提示词的行时才动
# -----------------------------------------------------------------------------
hs_log '[3/5] config.toml 提示词指针'
CT=(); CT_N=0
want codex && { CT[$CT_N]="$CODEX_HOME_DIR/config.toml"; CT_N=$((CT_N + 1)); }
want claude && { CT[$CT_N]="$HOME/.claude/config.toml"; CT_N=$((CT_N + 1)); }

c=0
while [ "$c" -lt "$CT_N" ]; do
  ct="${CT[$c]}"
  c=$((c + 1))
  [ -f "$ct" ] || continue
  t="$(hs_read "$ct")"
  total=0
  hits=""
  hits_n=0
  while IFS= read -r line; do
    total=$((total + 1))
    if [[ "$line" =~ ^[[:space:]]*model_instructions_file[[:space:]]*= ]]; then
      hits_n=$((hits_n + 1))
      if [ -z "$hits" ]; then hits="$total"; else hits="$hits,$total"; fi
    fi
  done <<<"$t"
  if [ "$hits_n" -eq 0 ]; then
    keep_add "无提示词指针，整文件保留（$total 行）：$ct"
  else
    plan_add '提示词指针行' "$ct" "删除第 $hits 行，其余 $((total - hits_n)) 行原样保留"
  fi
done

# -----------------------------------------------------------------------------
# 3.5 Cursor：固定文件名的注入规则文件（install-cursor 写的就这几个）
# -----------------------------------------------------------------------------
if want cursor; then
  hs_log '[3.5/5] Cursor 注入规则文件'
  RULE_FILE='寒霜注入.mdc'
  APPSUP="$(hs_appsupport)"

  CAND=(); CAND_N=0
  add_cand() {
    local p="$1" j=0
    [ -n "$p" ] || return 0
    while [ "$j" -lt "$CAND_N" ]; do
      [ "${CAND[$j]}" = "$p" ] && return 0
      j=$((j + 1))
    done
    CAND[$CAND_N]="$p"
    CAND_N=$((CAND_N + 1))
  }

  # (a) 全局规则目录：官方读 $HOME/.cursor/rules；旧版/变体还会看 APPDATA 与 LOCALAPPDATA
  #     （macOS 上这两个都落在 ~/Library/Application Support）
  add_cand "$HOME/.cursor/rules/$RULE_FILE"
  add_cand "$APPSUP/Cursor/User/rules/$RULE_FILE"
  add_cand "$APPSUP/Cursor/rules/$RULE_FILE"

  # (a2) 安装时记下的路径清单。install-cursor 把每次写过的路径存进
  #      ~/Library/Application Support/Cursor/hs-install-state.json 的 writtenPaths ——
  #      那是「确定写过」的记录，比反解 workspaceStorage 可靠：项目被删/挪走、
  #      或 Cursor 清掉了 workspace 记录时，只剩这份清单还认得它们。
  #      state 本身也是本工具写的，一并销掉。
  ST="$APPSUP/Cursor/hs-install-state.json"
  if [ -f "$ST" ]; then
    plan_add 'Cursor 安装状态' "$ST" ''
    while IFS= read -r w; do
      [ -n "$w" ] || continue
      p="$w"
      [ -d "$p" ] && p="$p/$RULE_FILE"
      [ -e "$p" ] && add_cand "$p"
    done <<<"$(hs_state_list "$ST" 'writtenPaths')"
  fi

  # (b) 项目级：Cursor 打开过的每个项目 -> {项目}/.cursor/rules/<规则文件>。
  #     项目清单没有落库，只能从 workspaceStorage 的 workspace.json 反解。
  WS_ROOT="$APPSUP/Cursor/User/workspaceStorage"
  if [ -d "$WS_ROOT" ]; then
    for wd in "$WS_ROOT"/*/; do
      [ -d "$wd" ] || continue
      ws_json="${wd%/}/workspace.json"
      [ -f "$ws_json" ] || continue
      loc="$(hs_json_get "$ws_json" 'folder')"
      [ -n "$loc" ] || loc="$(hs_json_get "$ws_json" 'workspace')"
      [ -n "$loc" ] || continue
      case "$loc" in
        file:///*) loc="${loc#file:///}" ;;
      esac
      loc="$(url_decode "$loc")"
      [ -d "$loc" ] && add_cand "$loc/.cursor/rules/$RULE_FILE"
    done
  fi

  # (c) 盘符根祖先规则：Windows 上放在盘符根 = 该盘任意目录打开都会自动加载。
  #     macOS 没有盘符，这一段删掉。

  j=0
  while [ "$j" -lt "$CAND_N" ]; do
    f="${CAND[$j]}"
    j=$((j + 1))
    [ -e "$f" ] && plan_add 'Cursor 规则文件' "$f" ''
  done

  # (d) 旧版往用户主目录写过 .cursorrules；只在内容确实带注入痕迹时才动
  legacy="$HOME/.cursorrules"
  if [ -f "$legacy" ] && is_artifact "$legacy"; then
    plan_add 'Cursor 规则文件（旧版）' "$legacy" ''
  fi
fi

# -----------------------------------------------------------------------------
# 4. 记忆文件里的提示词注入
# -----------------------------------------------------------------------------
hs_log '[4/5] 记忆文件注入'
mem_summary="$CODEX_HOME_DIR/memories/memory_summary.md"
if want codex && [ -f "$mem_summary" ]; then
  n_hits="$(awk '/^## / && /寒霜注入/ { n++ } END { print n + 0 }' "$mem_summary")"
  if [ "$n_hits" -gt 0 ]; then
    plan_add '记忆注入章节' "$mem_summary" "删除 $n_hits 个章节"
  else
    keep_add "无寒霜注入章节：$mem_summary"
  fi
fi

# WorkBuddy 档案路径自适应：先读 state，读不到才限深扫 $HOME
WB_HOMES=(); WB_N=0
if want workbuddy; then
  WB_HOMES[0]="$HOME/.workbuddy-ai"
  WB_HOMES[1]="$HOME/.workbuddy"
  WB_N=2
fi

ARCHIVES=(); ARCHIVES_N=0
add_archive() {
  local p="$1" j=0
  [ -n "$p" ] || return 0
  while [ "$j" -lt "$ARCHIVES_N" ]; do
    [ "${ARCHIVES[$j]}" = "$p" ] && return 0
    j=$((j + 1))
  done
  ARCHIVES[$ARCHIVES_N]="$p"
  ARCHIVES_N=$((ARCHIVES_N + 1))
}

w=0
while [ "$w" -lt "$WB_N" ]; do
  wh="${WB_HOMES[$w]}"
  w=$((w + 1))
  st="$wh/.hanshuang-state.json"
  if [ -f "$st" ]; then
    plan_add 'WorkBuddy state' "$st" ''
    while IFS= read -r a; do add_archive "$a"; done <<<"$(hs_state_list "$st" 'archives')"
    add_archive "$(hs_json_get "$st" 'archive')"
    mdir="$(hs_json_get "$st" 'memoryDir')"
    if [ -n "$mdir" ] && [ -d "$mdir" ]; then
      for f in "$mdir"/*_memory.md; do
        [ -f "$f" ] || continue
        add_archive "$f"
      done
    fi
  fi
  # 不论有没有 state，都把该 Home 的 memory 目录整个收进来。
  # 只读 state 会漏：一个 Home 有 state、另一个没有时，没有 state 那个的档案会被跳过。
  md="$wh/memory"
  if [ -d "$md" ]; then
    for f in "$md"/*_memory.md "$md"/.[!.]*_memory.md; do
      [ -f "$f" ] || continue
      add_archive "$f"
    done
    # 档案的备份与临时副本。WorkBuddy 写档案走 tmp+rename，异常中断会留下
    # <名>.bak.tmp.<pid>.<ts>.<rand>，里面是清空前的 Memory Block 内容 —— 也就是提示词本身。
    # 它们在 memory/ 子目录下，第 4.5 节 (a) 的「Home 根目录」扫描够不着，所以在这里单独收。
    for f in "$md"/* "$md"/.[!.]*; do
      [ -f "$f" ] || continue
      bn="${f##*/}"
      case "$bn" in
        *.bak-inject) continue ;;
        *.bak | *.bak[_.-]* | *.tmp | *.tmp[_.-]*) : ;;
        *) continue ;;
      esac
      [ "$(hs size "$f")" -lt 2097152 ] || continue
      if is_artifact "$f"; then
        plan_add '注入副产物（内容是提示词）' "$f" "workbuddy / $bn"
      else
        keep_add "备份不含提示词，保留：$f"
      fi
    done
  fi
done

# 限深扫盘只是「state 读不到」时的兜底。指定了别的目标时根本不该跑 ——
# 否则 -Targets codex 也会去扫盘找 WorkBuddy 档案。
# 只在「用户确实装了 WorkBuddy」时才做（PS 版遍历所有卷，macOS 改成只扫 $HOME）。
wb_installed=0
w=0
while [ "$w" -lt "$WB_N" ]; do
  [ -d "${WB_HOMES[$w]}" ] && wb_installed=1
  w=$((w + 1))
done
if want workbuddy && [ "$ARCHIVES_N" -eq 0 ] && [ "$wb_installed" -eq 1 ]; then
  hs_log "  未找到 WorkBuddy state，限深 $SCAN_DEPTH 层扫描 \$HOME ..."
  while IFS= read -r f; do
    [ -n "$f" ] && add_archive "$f"
  done <<<"$(find "$HOME" -maxdepth "$SCAN_DEPTH" -name '*_memory.md' -type f 2>/dev/null)"
  [ "$ARCHIVES_N" -gt 0 ] || hs_log '  没扫到 *_memory.md'
fi

# WorkBuddy 的全局记忆与注入前备份（.bak-inject）：和 managed-prompts 的 .bak 同理，
# .bak-inject 是注入前原文，要「还原」而不是删掉，否则用户的 MEMORY.md 就永久丢了
w=0
while [ "$w" -lt "$WB_N" ]; do
  wh="${WB_HOMES[$w]}"
  w=$((w + 1))
  [ -d "$wh" ] || continue
  while IFS= read -r bak; do
    [ -n "$bak" ] || continue
    [ -f "$bak" ] || continue
    bn="${bak##*/}"
    target="${bak%/*}/${bn%.bak-inject}"
    if is_artifact "$bak"; then
      plan_add '删除（备份本身是旧注入）' "$bak" ''
      # 备份都是旧注入了，说明这份文件历来就是我们写的：目标若还是注入内容就一并清掉，
      # 否则「零提示词」会失败（实测 MEMORY.md 被这种旧备份还原成了提示词正文）。
      if [ -f "$target" ] && is_artifact "$target"; then
        plan_add 'WorkBuddy 全局记忆（注入产物）' "$target" '整份删除'
      fi
    else
      plan_add '恢复原文（用安装前备份）' "$target" "备份源: $bn" "$bak"
    fi
  done <<<"$(find "$wh" -maxdepth 2 -name '*.bak-inject' -type f 2>/dev/null)"

  file_mem="$wh/MEMORY.md"
  if [ -f "$file_mem" ] && [ ! -f "$file_mem.bak-inject" ]; then
    if is_artifact "$file_mem"; then
      plan_add 'WorkBuddy 全局记忆（注入产物）' "$file_mem" ''
    else
      keep_add "MEMORY.md 无注入痕迹，保留：$file_mem"
    fi
  fi
done

a=0
while [ "$a" -lt "$ARCHIVES_N" ]; do
  arch="${ARCHIVES[$a]}"
  a=$((a + 1))
  [ -f "$arch" ] || continue
  hs_contains "$arch" '## Memory Block' || continue
  if memory_block_empty "$arch"; then
    keep_add "Memory Block 已是空段：$arch"
    continue
  fi
  plan_add 'WorkBuddy 记忆块' "$arch" '清空 Memory Block 内容（档案文件本身保留）'
done

# -----------------------------------------------------------------------------
# 4.5 注入副产物：备份文件 / 随附包 / 技能树
#
# 这些不是「注入点」，而是注入过程本身的产物 —— 但里面装的往往就是提示词正文。
# 判定一律走 is_artifact（按内容判定，不看文件名），所以用户自己的备份不会被误删。
# -----------------------------------------------------------------------------
hs_log '[4.5/5] 注入副产物（备份 / 随附包 / 技能树）'

# (a) 各 Home 根目录下的备份与临时文件。
#     覆盖命名：<名>.backup-<时间戳> / <名>.bak / <名>.bak_<时间戳> / <名>.bak-<后缀>
#     / <名>.inject-<时间戳> / <名>.bak.tmp.<pid>.<ts>.<rand>
#     .bak-inject 不在此列 —— 那是 WorkBuddy 的用户原文备份，第 4 节已按「还原」处理。
#     超过 2MB 的跳过：那体量不可能是提示词正文。
i=0
while [ "$i" -lt "$HOME_N" ]; do
  k="${HOME_KEYS[$i]}"
  h="${HOME_PATHS[$i]}"
  i=$((i + 1))
  [ -d "$h" ] || continue
  for f in "$h"/* "$h"/.[!.]*; do
    [ -f "$f" ] || continue
    bn="${f##*/}"
    case "$bn" in
      *.bak-inject) continue ;;
      *.backup | *.backup[_.-]* | *.bak | *.bak[_.-]* | *.inject | *.inject[_.-]* | *.tmp | *.tmp[_.-]*) : ;;
      *) continue ;;
    esac
    [ "$(hs size "$f")" -lt 2097152 ] || continue
    if is_artifact "$f"; then
      plan_add '注入副产物（内容是提示词）' "$f" "$k / $bn"
      planned_add "$f" >/dev/null
    elif spent_backup "$f"; then
      # 本工具在注入前留的主文件备份，而主文件现在已还原干净 → 它只是保险，使命已完成。
      # 主文件还带着注入时 spent_backup 返回 false，备份会走下面的 Keep 留着。
      plan_add '主文件备份（已还原，备份无用）' "$f" "$k / $bn"
      planned_add "$f" >/dev/null
    else
      keep_add "备份不含提示词，保留：$f"
    fi
  done
done

# (a2) ZCode 程序本体备份：install-zcode 在 patch zcode.cjs 之前留的副本，
#      一次安装一份。它们不含提示词正文，但同属本工具的产物，体量还最大。
#
#      ★ 删之前必须确认三件事，缺一不可 —— 备份是还原 zcode.cjs 的唯一依据，
#        而 install-zcode 卸载时无论还原成功与否都会删掉 install-state.json，
#        所以「state 没了」并不能推出「已经还原过了」。删错就是把 ZCode 弄成永久注入态。
#        1) install-state.json 已不存在（卸载器跑过了）
#        2) 能找到 zcode.cjs（ZCode 还装着）
#        3) zcode.cjs 本身已不含注入标记
#      任何一条不满足就原样保留，只打一行说明。
if want zcode; then
  zc_home="$HOME/.zcode"
  ZC_BACKUPS=(); ZC_N=0
  if [ -d "$zc_home" ]; then
    for f in "$zc_home"/zcode.cjs.backup-*; do
      [ -f "$f" ] || continue
      ZC_BACKUPS[$ZC_N]="$f"
      ZC_N=$((ZC_N + 1))
    done
  fi
  if [ "$ZC_N" -gt 0 ]; then
    # 定位 zcode.cjs。PS 版先问运行中的进程、再试 Program Files 等常见位置；
    # macOS 的 ZCode 安装布局没有可靠依据，改成「候选列表 + HS_ZCODE_CJS 覆盖」，
    # 找不到就保守保留（与 PS 版「未找到 → 保留」的结论一致）。
    zc_cjs=""
    for cand in "${HS_ZCODE_CJS:-}" \
                "$HOME/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs" \
                "/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs" \
                "/Applications/ZCode/resources/glm/zcode.cjs" \
                "$(hs_appsupport)/ZCode/resources/glm/zcode.cjs"; do
      [ -n "$cand" ] || continue
      if [ -f "$cand" ]; then
        zc_cjs="$cand"
        break
      fi
    done
    if [ -f "$zc_home/install-state.json" ]; then
      keep_add "install-state.json 仍在（卸载器没跑过），$ZC_N 份本体备份保留"
    elif [ -z "$zc_cjs" ]; then
      keep_add "zcode.cjs 未找到（ZCode 没装或在自定义目录），$ZC_N 份本体备份保守保留"
    elif hs_contains "$zc_cjs" 'CTF-LAB-2.0'; then
      keep_add "zcode.cjs 仍含注入标记，$ZC_N 份本体备份保留（那是唯一还原依据）：$zc_cjs"
    else
      j=0
      while [ "$j" -lt "$ZC_N" ]; do
        plan_add '程序本体备份（已无还原需求）' "${ZC_BACKUPS[$j]}" "zcode / ${ZC_BACKUPS[$j]##*/}"
        j=$((j + 1))
      done
    fi
  fi
fi

# (b) DSH 的具名注入文件：install-dsh 写在 Home 根下、名字固定，
#     既不是标记块也不叫 .bak，旧的扫描规则全都够不着。
if want dsh; then
  for n in 'prompt-inject.md' 'shield-protocol.md' 'dsh-prompt-inject.json'; do
    p="$HOME/.dsh/$n"
    [ -f "$p" ] || continue
    restore_has "$p" && continue   # 已由 managed-prompts 的备份还原处理
    plan_add 'DSH 注入文件' "$p" "$n"
    planned_add "$p" >/dev/null
  done
fi

# (c) 随附包（bundle）：装在 Home 根下、但【不在 skills/ 树内】。
#     删除条件：目录名与随包一致 **且** SKILL.md 内容逐字节相同（防止误删用户同名目录）。
bundle_src="$HS_ROOT/codex-bundle-v5"
if want codex && [ -d "$bundle_src" ]; then
  for d in "$bundle_src"/*/; do
    [ -d "$d" ] || continue
    d="${d%/}"
    dn="${d##*/}"
    installed="$CODEX_HOME_DIR/$dn"
    if [ -e "$installed" ]; then
      a="$d/SKILL.md"
      b="$installed/SKILL.md"
      if same_file "$a" "$b"; then
        plan_add '随附包（确认是本工具的）' "$installed" "$dn / SKILL.md 与随包一致"
        planned_add "$installed" >/dev/null
      else
        keep_add "随附包同名目录但内容与随包不符，保留：$installed"
      fi
    fi
    # 覆盖安装前建的备份目录：<名>.bak-<时间戳>（install 的 Install-Bundles 所建）
    for bk in "$CODEX_HOME_DIR/$dn".bak-*/; do
      [ -d "$bk" ] || continue
      if planned_add "${bk%/}"; then
        plan_add '随附包备份' "${bk%/}" ''
      fi
    done
  done
fi

# (d) 技能树：<Home>/skills/<名>，以及 DSH 的 <Home>/skills-disabled/<名>。
#     删除条件：目录名与随包技能库一致 **且** SKILL.md 内容逐字节相同 ——
#     用户自己装的同名技能必须留下。
dsh_skill_lib="$HS_ROOT/dsh-lazy-pack-v5/materials/skills"
[ -d "$dsh_skill_lib" ] || dsh_skill_lib="${HS_ROOT%/*}/dsh-lazy-pack-v5/materials/skills"
SKILL_LIBS=("$HS_ROOT/codex-skills" "$HS_ROOT/codex-skills-v4" "$HS_ROOT/codex-skills-v5" "$dsh_skill_lib")
SKILL_LIBS_N=4

# workbuddy 的两个数据目录不在 $HOME_KEYS 里（它的注入点是单独处理的），但技能树的
# 清理逻辑完全一样，这里补进来 —— 漏掉的话 WorkBuddy 里装的技能卸载后一个都清不掉。
SK_HOMES=(); SK_NAMES=(); SK_HOME_N=0
i=0
while [ "$i" -lt "$HOME_N" ]; do
  SK_HOMES[$SK_HOME_N]="${HOME_PATHS[$i]}"
  SK_NAMES[$SK_HOME_N]="${HOME_KEYS[$i]}"
  SK_HOME_N=$((SK_HOME_N + 1))
  i=$((i + 1))
done
if want workbuddy; then
  SK_HOMES[$SK_HOME_N]="$HOME/.workbuddy-ai"; SK_NAMES[$SK_HOME_N]='workbuddy-intl'; SK_HOME_N=$((SK_HOME_N + 1))
  SK_HOMES[$SK_HOME_N]="$HOME/.workbuddy";    SK_NAMES[$SK_HOME_N]='workbuddy-cn';   SK_HOME_N=$((SK_HOME_N + 1))
fi

h_i=0
while [ "$h_i" -lt "$SK_HOME_N" ]; do
  k="${SK_NAMES[$h_i]}"
  h="${SK_HOMES[$h_i]}"
  h_i=$((h_i + 1))
  for sub in 'skills' 'skills-disabled'; do
    sk="$h/$sub"
    [ -d "$sk" ] || continue
    li=0
    while [ "$li" -lt "$SKILL_LIBS_N" ]; do
      lib="${SKILL_LIBS[$li]}"
      li=$((li + 1))
      [ -d "$lib" ] || continue
      for d in "$lib"/*/; do
        [ -d "$d" ] || continue
        d="${d%/}"
        dn="${d##*/}"
        dst="$sk/$dn"
        [ -d "$dst" ] || continue
        planned_has "$dst" && continue
        a="$d/SKILL.md"
        b="$dst/SKILL.md"
        if same_file "$a" "$b"; then
          plan_add '技能（确认是本工具的）' "$dst" "$k / $sub / $dn"
          planned_add "$dst" >/dev/null
        else
          keep_add "skills 下同名但内容不符，保留：$dst"
        fi
      done
    done
    # skills-disabled 下本工具写的说明文件（内容里点名了「寒霜破甲工具」，据此认领）
    rd="$sk/README.txt"
    if [ -f "$rd" ] && hs_contains "$rd" '寒霜破甲工具'; then
      plan_add '本工具生成的说明文件' "$rd" "$k / $sub"
    fi
  done
done

# -----------------------------------------------------------------------------
# 5. 报告
# -----------------------------------------------------------------------------
hs_log '[5/5] 汇总'
hs_log ''
if [ "$KEPT_N" -gt 0 ]; then
  hs_log '--- 保留（不是提示词，原样不动） ---'
  i=0
  while [ "$i" -lt "$KEPT_N" ]; do
    hs_log "  ${KEPT[$i]}"
    i=$((i + 1))
  done
  hs_log ''
fi
if [ "$PLAN_N" -eq 0 ]; then
  hs_log '没有发现任何注入提示词残留。'
  exit 0
fi
if [ "$LIST_ONLY" -eq 1 ]; then
  # 只吐路径，供其它脚本解析
  i=0
  while [ "$i" -lt "$PLAN_N" ]; do
    printf '%s\n' "${PLAN_PATH[$i]}"
    i=$((i + 1))
  done
  exit 0
fi
hs_log "--- 待清除 $PLAN_N 项 ---"
i=0
while [ "$i" -lt "$PLAN_N" ]; do
  hs_log "  [${PLAN_KIND[$i]}] ${PLAN_PATH[$i]} ${PLAN_NOTE[$i]}"
  i=$((i + 1))
done

if [ "$APPLY" -ne 1 ]; then
  hs_log ''
  hs_log 'DRY-RUN 结束，未改动任何东西。确认后加 -Apply 执行。'
  exit 0
fi

hs_log ''
hs_log '--- 开始清除 ---'
fail=0
i=0
while [ "$i" -lt "$PLAN_N" ]; do
  kind="${PLAN_KIND[$i]}"
  path="${PLAN_PATH[$i]}"
  src="${PLAN_SRC[$i]}"
  i=$((i + 1))
  ERR=""
  if apply_item "$kind" "$path" "$src"; then
    hs_log "  OK   [$kind] $path"
  else
    fail=$((fail + 1))
    hs_log "  FAIL [$kind] $path :: $ERR"
  fi
done

# managed-prompts 清空后若已为空，目录本身也删掉
i=0
while [ "$i" -lt "$HOME_N" ]; do
  mp="${HOME_PATHS[$i]}/managed-prompts"
  i=$((i + 1))
  if [ -d "$mp" ]; then
    if dir_empty "$mp"; then
      rmdir "$mp" 2>/dev/null && hs_log "  OK   [空目录] $mp"
    fi
  fi
done

hs_log ''
hs_log "清除完成，失败 $fail 项。"
if [ "$fail" -gt 0 ]; then exit 1; fi
exit 0
