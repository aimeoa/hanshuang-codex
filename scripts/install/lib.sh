#!/usr/bin/env bash
# lib.sh — 寒霜 macOS 版公共函数库
#
# 所有 install-*.sh 与 clear-injected-prompts.sh 都 source 本文件，保证：
#   · 注入标记的匹配规则只有一份（改一处，全目标生效）
#   · 技能库的安装/清理判定只有一份（不会出现某个目标误删用户技能）
#   · 状态文件格式统一
#
# 用法：  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
#
# 兼容 macOS 自带 bash 3.2：不使用关联数组、mapfile、${var,,} 等 4.x 特性。

set -u

HS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 项目根：开发态是仓库根目录，打包后是 <App>.app/Contents/Resources
HS_ROOT="${HS_ROOT:-$(cd "$HS_LIB_DIR/../.." && pwd)}"
HS_LIB_JS="$HS_LIB_DIR/hs-lib.cjs"

# 注入标记（正则源串，交给 node 编译；用单引号避免 shell 吃掉反斜杠）
HS_MARK_BEGIN='<!--[^\r\n]*寒霜破甲[^\r\n]*注入开始[^\r\n]*-->'
HS_MARK_END='<!--[^\r\n]*寒霜破甲[^\r\n]*注入结束[^\r\n]*-->'
HS_INJ_BEGIN='<!--[^\r\n]*HANSHUANG-INJECT:BEGIN[^\r\n]*-->'
HS_INJ_END='<!--[^\r\n]*HANSHUANG-INJECT:END[^\r\n]*-->'
HS_CURSOR_MARK='<!-- HANSHUANG-CURSOR-INJECT -->'

# ---------- 基础 ----------

hs_die() {
  printf '寒霜工具错误: %s\n' "$*" >&2
  exit 1
}

hs_log() { printf '%s\n' "$*"; }
hs_warn() { printf '%s\n' "$*" >&2; }

# node 解析顺序：主进程注入的 HS_NODE → PATH 里的 node
hs_node() {
  if [ -n "${HS_NODE:-}" ] && [ -x "${HS_NODE}" ]; then
    printf '%s' "$HS_NODE"
    return 0
  fi
  command -v node 2>/dev/null && return 0
  command -v nodejs 2>/dev/null && return 0
  hs_die "找不到 node 可执行文件（打包版应由主进程注入 HS_NODE）"
}

hs() { "$(hs_node)" "$HS_LIB_JS" "$@"; }

# 临时目录，退出时清理。
# 注意：必须在 source 时就把路径定下来，不能用 $(hs_tmp) 取值 —— 命令替换跑在子 shell 里，
# 在那里新建的目录和注册的 trap 都传不回父进程，结果每次调用都换一个新目录。
HS_TMP="$(mktemp -d "${TMPDIR:-/tmp}/hanshuang.XXXXXX")"
hs_cleanup() { [ -n "${HS_TMP:-}" ] && rm -rf "$HS_TMP"; }
trap hs_cleanup EXIT

hs_tmp() { printf '%s' "$HS_TMP"; }

# ---------- 文件探测 ----------
#
# 这几个必须用 bash 内建，**不能**包成 node 调用。
# 它们出现在「遍历很多文件」的热路径里（卸载清扫会逐个文件判断是不是注入产物），
# 而单次 node 启动约 60ms —— 几百个文件就是几十秒到几分钟，表现为「卡在执行中」。
# 实测：把 is_artifact 里的 node 调用换成内建后，同一个目录从卡死变成秒级完成。

hs_exists() { [ -e "$1" ]; }
hs_isfile() { [ -f "$1" ]; }
hs_isdir() { [ -d "$1" ]; }

hs_mkdir() { mkdir -p -- "$1"; }

# ---------- 文本读写 ----------

# 读文件内容；不存在或不是普通文件时输出空（与 hs-lib.cjs 的 read 行为一致）
hs_read() { [ -f "$1" ] && cat -- "$1"; return 0; }

# 从 stdin 读入写到文件（自动建父目录），不追加换行
hs_write() { hs write "$1"; }

# 写文本并在末尾补一个换行（PowerShell 版多数写入都是 TrimEnd + NewLine）
hs_write_nl() {
  printf '%s' "$1" | hs write "$2"
  printf '\n' >>"$2"
}

# 归一化后的正文（CRLF→LF，去首尾空白）
hs_norm() { hs norm "$1"; }

# 文件正文是否与「提示词文件正文」一致（两者都归一化后比）
hs_eq_prompt() { hs eq-text "$1" "$2" >/dev/null 2>&1; }

# 文件是否包含某个字面串。纯 bash，不 fork node —— 同样在热路径上。
hs_contains() {
  local t
  t="$(hs_read "$1")"
  [[ "$t" == *"$2"* ]]
}

hs_stamp() { hs stamp; }
hs_now() { hs now; }

# ---------- 注入块 ----------

# 输出 "start len"，没有块输出 "none"
hs_find_block() { hs block-find "$1" "$2" "$3"; }

hs_has_block() { [ "$(hs_find_block "$1" "$2" "$3")" != "none" ]; }

# 去掉块，块外内容原样保留
hs_strip_block() { hs block-strip "$1" "$2" "$3"; }

# 有块换块内，没块追加
hs_splice_block() { hs block-splice "$1" "$2" "$3" "$4"; }

# 寒霜提示词特征串：老版本是「整份覆盖」式注入，不留标记，只能靠内容认出来
HS_SIGNATURES=(
  'HANSHUANG-INJECT'
  '寒霜破甲注入开始'
  '拒绝话术全清单'
  '激活词'
  '寒霜'
  'SES-OS'
  '样例 A：给另一 AI'
  'CTF Lab'
  'CTF-LAB-2.0'
)

# 判断一份文件是不是「寒霜注入产物」：带注入标记或命中特征串。
# 用途：别把早先的注入产物当成「原始备份」还原回去（那样卸载等于没卸）。
hs_is_artifact() {
  local f="$1"
  hs_isfile "$f" || return 1
  local t
  t="$(hs_read "$f")"
  [ -n "$t" ] || return 1

  # 「整份都是空白 = 不是注入产物」这个判断，**绝对不能**写成 ${t//[[:space:]]/}：
  # bash 的括号表达式全局替换在大字符串上是 O(n²) 级别的，实测一个 11KB 的文件
  # 要 6.4 秒 —— 卸载清扫会逐个文件调用本函数，于是整个脚本卡到超时（用户看到
  # 的就是界面一直「执行中」）。
  # 这里只对短内容做一次 tr 判断（fork 一个进程约 10ms，比 6.4 秒快 600 倍）；
  # 4KB 以上的文件必然有实质内容，不值得为它再付一次 fork 的代价。
  if [ "${#t}" -lt 4096 ] && [ -z "$(printf '%s' "$t" | tr -d '[:space:]')" ]; then
    return 1
  fi

  local sig
  for sig in "${HS_SIGNATURES[@]}"; do
    if [[ "$t" == *"$sig"* ]]; then return 0; fi
  done
  return 1
}

# 仅当文件不存在时备份一次（对齐 PowerShell 版的「首次注入前备份」）
hs_backup_once() {
  local f="$1" bak="$2"
  if [ ! -f "$bak" ] && [ -f "$f" ]; then
    hs mkdir "$(dirname "$bak")"
    cp -f "$f" "$bak"
    hs_log "Backed up original $(basename "$f")"
  fi
}

# ---------- 技能库 ----------
# 全部下沉到 hs-lib.cjs 里一次完成：每个技能都起一次 node 的话，
# 63 个技能 × 5 次调用 ≈ 2 分钟，会直接撞上主进程的超时。

# 随包分发的技能名（去重），每行一个
hs_shipped_skill_names() { hs skills-shipped "$HS_ROOT"; }

# 安装技能库；stdout = 本次安装的技能名（每行一个）
hs_install_skills() { hs skills-install "$1" "$2"; }

# 清理上一版遗留：$1=上次清单文件 $2=本次清单文件 $3=目标目录；stdout = 已删技能名
hs_prune_stale_skills() { hs skills-prune "$1" "$2" "$3" "$HS_ROOT"; }

# 卸载：只删「上次安装清单 ∩ 随包技能库」；stdout = 已删技能名
hs_remove_skills() { hs skills-remove "$1" "$2" "$HS_ROOT"; }

# 逗号分隔展示（日志用）
hs_join_commas() { printf '%s' "$1" | tr '\n' ',' | sed 's/,$//; s/,/, /g'; }

# ---------- 状态文件 ----------

hs_json_get() { hs json-get "$1" "$2"; }

# 把逐行文本写进 <file> 的 <key> 数组
hs_json_array() { hs json-array "$1" "$2"; }

hs_json_write() { hs json-write "$1"; }

hs_json_set() { hs json-set "$1" "$2" "$3"; }

# 读 <stateFile> 里 <key> 的数组，每行一个（缺失则无输出）
hs_state_list() {
  local f="$1" k="$2"
  [ -f "$f" ] || return 0
  hs_json_get "$f" "$k"
}

# ---------- 参数解析 ----------
# 与 PowerShell 版同名的开关：-SourcePrompt x / -Uninstall / -NoSkills ...
# 解析结果放进 HS_ARG_<name>（名字里的 - 换成 _）与布尔变量。
HS_ARGS=""
hs_parse_args() {
  HS_ARGS="$*"
  while [ $# -gt 0 ]; do
    case "$1" in
      -*)
        local key
        key="HS_ARG_$(printf '%s' "$1" | sed 's/^-//; s/-/_/g')"
        # 下一个参数不是开关 → 当作值
        if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then
          eval "$key=\$2"
          shift 2
        else
          eval "$key=1"
          shift
        fi
        ;;
      *) shift ;;
    esac
  done
}

# 取参数值（未给则返回默认值 $2）
hs_arg() {
  local name="HS_ARG_$(printf '%s' "$1" | sed 's/^-//; s/-/_/g')"
  local v="${!name:-}"
  if [ -z "$v" ]; then printf '%s' "${2:-}"; else printf '%s' "$v"; fi
}

# 开关是否打开
hs_flag() {
  local name="HS_ARG_$(printf '%s' "$1" | sed 's/^-//; s/-/_/g')"
  [ -n "${!name:-}" ]
}

# 分号分隔的列表 → 逐行输出
hs_split_semicolon() {
  printf '%s' "$1" | tr ';' '\n'
}

# ---------- 平台目录 ----------

hs_home() { printf '%s' "$HOME"; }

# macOS 的 Application Support 目录
hs_appsupport() { printf '%s/Library/Application Support' "$HOME"; }
