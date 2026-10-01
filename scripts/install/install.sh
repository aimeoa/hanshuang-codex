#!/usr/bin/env bash
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
# install.sh — Codex 破甲注入（macOS，对齐 install.ps1）
#
# 对齐 install.ps1 的全部行为：
#   · 把提示词复制到 <CodexHome>/managed-prompts/，并在 config.toml 写入 model_instructions_file
#     （原行先记进状态文件，卸载时按它还原）
#   · -InjectAgents：往 <CodexHome>/AGENTS.md 注入带标记的块
#     已有块只换块内；正文与提示词一致的（含老式无标记覆盖式注入）整份改写；用户自己的内容先备份再追加
#   · 卸载：按标记摘 AGENTS.md 的块、还原 config.toml、删除历次提示词 / 状态文件 / 随附包
#   · 技能库：只删「上次安装清单 ∩ 随包技能库」的技能，用户自建技能一条不沾
#   · -NoSkills：只写提示词，不动 skills 目录里已有的任何东西
#   · 非寒霜 skills 通过 config.toml 的 [[skills.config]] 条目禁用，卸载时还原
#
# 用法：
#   ./install.sh -SourcePrompt /path/寒霜v4.md -SkillsSource codex-skills-v4 \
#                -BundleSource codex-bundle-v5 -InjectAgents
#   ./install.sh -Uninstall

hs_parse_args "$@"

CODEX_HOME_ARG="$(hs_arg -CodexHome '')"
SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
SKILLS_SOURCE="$(hs_arg -SkillsSource '')"
BUNDLE_SOURCE="$(hs_arg -BundleSource '')"
AGENTS_KNOWN="$(hs_arg -AgentsKnown '')"

# ---------- 定位 Codex 主目录 ----------
# macOS 只有两级：-CodexHome / $CODEX_HOME → ~/.codex（PowerShell 版的逐盘符扫描没有意义）
if [ -n "$CODEX_HOME_ARG" ]; then
  CODEX_HOME="$CODEX_HOME_ARG"
elif [ -n "${CODEX_HOME:-}" ]; then
  CODEX_HOME="$CODEX_HOME"
else
  CODEX_HOME="$HOME/.codex"
fi

CONFIG_PATH="$CODEX_HOME/config.toml"
MANAGED_DIR="$CODEX_HOME/managed-prompts"
STATE_PATH="$MANAGED_DIR/install-state.json"
SKILLS_TARGET="$CODEX_HOME/skills"
SKILLS_MANIFEST_KEY='installedSkills'
AGENTS_PATH="$CODEX_HOME/AGENTS.md"
AGENTS_BEGIN='<!-- 寒霜破甲注入开始'
AGENTS_END='<!-- 寒霜破甲注入结束 -->'
MEM_SUMMARY="$CODEX_HOME/memories/memory_summary.md"

if [ -z "$SKILLS_SOURCE" ]; then
  SKILLS_SRC="$HS_ROOT/codex-skills"
else
  SKILLS_SRC="$HS_ROOT/$SKILLS_SOURCE"
fi

# 卸载时 -SourcePrompt 通常为空，targetPrompt 只能靠状态文件里的记录
if [ -n "$SOURCE_PROMPT" ]; then
  TARGET_PROMPT="$MANAGED_DIR/$(basename "$SOURCE_PROMPT")"
else
  TARGET_PROMPT="$MANAGED_DIR"
fi

# ---------- 通用小工具 ----------

# 去掉文本末尾空白（对齐 PowerShell 的 .TrimEnd()）
trim_end_pipe() {
  local t
  t="$(cat)"
  t="${t%"${t##*[![:space:]]}"}"
  printf '%s' "$t"
}

# 去掉文本首尾空白（对齐 PowerShell 的 .Trim()）
trim_all_pipe() {
  local t
  t="$(cat)"
  t="${t#"${t%%[![:space:]]*}"}"
  t="${t%"${t##*[![:space:]]}"}"
  printf '%s' "$t"
}

# stdin 文本 TrimEnd 后写文件，末尾补一个换行（对齐 WriteAllText(x, t.TrimEnd() + NL)）
write_trimmed() {
  local t
  t="$(cat)"
  t="${t%"${t##*[![:space:]]}"}"
  printf '%s\n' "$t" | hs write "$1"
}

# JSON 字符串字面量（路径里一般没有引号/反斜杠，仍按最坏情况转义）
json_str() { printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; }

# 把文件里的字面串 $2 全部替换成 $3。用 index 定位，避开正则与转义地雷。
# 不做「是否包含」预检 —— 调用方负责先用 grep 筛过，否则每个文件起一次 node 太慢。
replace_literal_now() {
  local f="$1" from="$2" to="$3" tmp
  [ -n "$from" ] || return 0
  tmp="$(hs_tmp)/replace.$$"
  HS_FROM="$from" HS_TO="$to" awk '
    { line = $0; n = length(ENVIRON["HS_FROM"]); out = ""
      while ((p = index(line, ENVIRON["HS_FROM"])) > 0) {
        out = out substr(line, 1, p - 1) ENVIRON["HS_TO"]
        line = substr(line, p + n)
      }
      print out line }
  ' "$f" >"$tmp"
  hs write "$f" <"$tmp"
}

replace_literal() {
  hs_contains "$1" "$2" || return 0
  replace_literal_now "$1" "$2" "$3"
}

# 列出目录下含 SKILL.md 的子目录名（每行一个）
list_skill_dirs() {
  local d="$1" x
  [ -d "$d" ] || return 0
  for x in "$d"/*/; do
    [ -d "$x" ] || continue
    [ -f "$x/SKILL.md" ] || continue
    basename "$x"
  done | sort
}

# 读 config.toml 里 enabled = false 且 path 形如 .../skills/<name>/SKILL.md 的技能名
list_disabled_skills() {
  [ -f "$CONFIG_PATH" ] || return 0
  awk '
    function flush(   q, n, a, name, parent) {
      if (blk_path != "" && blk_enabled == "false") {
        q = blk_path; gsub(/\\/, "/", q)
        n = split(q, a, "/")
        if (n >= 3) {
          name = a[n - 1]; parent = a[n - 2]
          if (name != "" && parent == "skills" && name != "skills") print name
        }
      }
      blk_path = ""; blk_enabled = ""
    }
    /^[[:space:]]*\[\[skills\.config\]\][[:space:]]*$/ { flush(); inblk = 1; next }
    {
      if (inblk) {
        if ($0 ~ /^[[:space:]]*path[[:space:]]*=[[:space:]]*"/) {
          s = $0; sub(/^[[:space:]]*path[[:space:]]*=[[:space:]]*"/, "", s); sub(/".*/, "", s)
          if (blk_path == "") blk_path = s
        } else if ($0 ~ /^[[:space:]]*enabled[[:space:]]*=[[:space:]]*(true|false)/) {
          s = $0; sub(/^[[:space:]]*enabled[[:space:]]*=[[:space:]]*/, "", s); sub(/[^a-z].*/, "", s)
          if (blk_enabled == "") blk_enabled = s
        }
      }
    }
    END { flush() }
  ' "$CONFIG_PATH"
}

# 重写 config.toml 的技能启用状态：
#   · 只摘掉 path 指向本工具 skills 目录的 [[skills.config]] 块，用户自己配的条目原样保留
#   · 再按 $1（每行一个技能名）追加 enabled = false 条目
set_skills_enabled_state() {
  [ -f "$CONFIG_PATH" ] || return 0
  local names_file="$1" prefix kept
  prefix="$(printf '%s' "$SKILLS_TARGET" | tr '\\' '/' | sed -e 's:/*$::')/"
  kept="$(HS_PREFIX="$prefix" awk '
    function is_ours(q,   t) {
      t = q; gsub(/\\/, "/", t)
      return (tolower(substr(t, 1, length(ENVIRON["HS_PREFIX"]))) == tolower(ENVIRON["HS_PREFIX"]))
    }
    function flush(   s) {
      if (buf == "") return
      if (index(buf, "[[skills.config]]") == 1) {
        if (match(buf, /path[ \t]*=[ \t]*"[^"]*"/)) {
          s = substr(buf, RSTART, RLENGTH)
          sub(/^path[ \t]*=[ \t]*"/, "", s); sub(/"$/, "", s)
          if (is_ours(s)) { buf = ""; return }
        }
      }
      printf "%s", buf
      buf = ""
    }
    /^\[\[skills\.config\]\][[:space:]]*$/ { flush(); buf = $0 "\n"; next }
    { buf = buf $0 "\n" }
    END { flush() }
  ' "$CONFIG_PATH" | trim_end_pipe)"
  {
    printf '%s\n' "$kept"
    if [ -f "$names_file" ]; then
      while IFS= read -r n; do
        [ -n "$n" ] || continue
        if [ "$n" != "skills" ]; then
          printf '[[skills.config]]\npath = "%s/%s/SKILL.md"\nenabled = false\n' \
            "$(printf '%s' "$SKILLS_TARGET" | tr '\\' '/')" "$n"
        fi
      done <"$names_file"
    fi
  } | hs write "$CONFIG_PATH"
}

# 禁用 skills 目录里所有非本次管理的技能，返回被禁用的技能名
disable_non_managed_skills() {
  local managed_file="$1" all to_disable
  all="$(list_skill_dirs "$SKILLS_TARGET")"
  if [ -z "$all" ]; then
    to_disable=""
  elif [ -s "$managed_file" ]; then
    to_disable="$(printf '%s\n' "$all" | grep -Fxv -f "$managed_file" || true)"
  else
    to_disable="$all"
  fi
  printf '%s\n' "$to_disable" >"$(hs_tmp)/to-disable.txt"
  set_skills_enabled_state "$(hs_tmp)/to-disable.txt"
  printf '%s' "$to_disable"
}

# 复制一棵目录树。内容一致就跳过（对齐 Test-TreeCurrent 的「up-to-date, skipped」）
copy_tree() {
  local src="$1" dest="$2"
  if [ -d "$dest" ] && diff -rq "$src" "$dest" >/dev/null 2>&1; then
    hs_log "  up-to-date, skipped: $(basename "$dest")"
    return 0
  fi
  rm -rf "$dest"
  hs mkdir "$dest"
  cp -Rp "$src/." "$dest/"
}

# 随附包：装在 $CodexHome 下、但不在 skills/ 树内的支持目录（如 breaker-kit）。
# 目标已存在且不是上次寒霜装的，先整目录改名备份，绝不静默吃掉用户文件。
# 结果写进 $(hs_tmp)/bundles.txt（日志不能走 stdout，否则会被命令替换当成清单吃掉）
install_bundles() {
  local src="$1" src_dir name dest bak d out
  out="$(hs_tmp)/bundles.txt"
  : >"$out"
  [ -n "$src" ] || return 0
  src_dir="$HS_ROOT/$src"
  [ -d "$src_dir" ] || return 0
  for d in "$src_dir"/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    dest="$CODEX_HOME/$name"
    if [ -e "$dest" ] && ! printf '%s\n' "$prev_bundles" | grep -Fxq -e "$name"; then
      bak="$dest.bak-$(hs_stamp)"
      mv -f "$dest" "$bak"
      hs_log "Backed up existing $name -> $(basename "$bak")"
    fi
    copy_tree "$d" "$dest"
    printf '%s\n' "$name" >>"$out"
  done
}

# ---------- 卸载 ----------

if hs_flag -Uninstall; then
  had_state=0
  [ -f "$STATE_PATH" ] && had_state=1

  prev_skills="$(hs_state_list "$STATE_PATH" "$SKILLS_MANIFEST_KEY")"
  prev_bundles="$(hs_state_list "$STATE_PATH" installedBundles)"
  prev_disabled="$(hs_state_list "$STATE_PATH" previousDisabledSkills)"

  # 还原 config.toml 的 model_instructions_file：能还原原行就还原，否则整行删掉
  if [ -f "$CONFIG_PATH" ]; then
    cfg="$(cat "$CONFIG_PATH")"
    had_line="$(hs_json_get "$STATE_PATH" hadLine)"
    prev_line="$(hs_json_get "$STATE_PATH" previousLine)"
    is_own_prev=0
    case "$prev_line" in *managed-prompts*) is_own_prev=1 ;; esac
    if [ "$had_line" = "true" ] && [ -n "$prev_line" ] && [ "$is_own_prev" -eq 0 ]; then
      cfg="$(printf '%s\n' "$cfg" | HS_NL="$prev_line" awk '
        !d && /^[[:space:]]*model_instructions_file[[:space:]]*=/ { print ENVIRON["HS_NL"]; d = 1; next }
        { print }')"
    else
      cfg="$(printf '%s\n' "$cfg" | awk '
        !d && /^[[:space:]]*model_instructions_file[[:space:]]*=/ { d = 1; next }
        { print }')"
    fi
    printf '%s' "$cfg" | write_trimmed "$CONFIG_PATH"
  fi

  # 删除历次提示词文件（状态文件里记的清单优先，没记录才退回派生路径）
  prompt_files="$(hs_state_list "$STATE_PATH" promptHistory)"
  tp="$(hs_json_get "$STATE_PATH" targetPrompt)"
  if [ -n "$tp" ]; then
    if [ -n "$prompt_files" ]; then prompt_files="$prompt_files
$tp"; else prompt_files="$tp"; fi
  fi
  if [ -z "$prompt_files" ]; then
    prompt_files="$TARGET_PROMPT"
  fi
  printf '%s\n' "$prompt_files" | awk 'NF && !seen[$0]++' | while IFS= read -r f; do
    [ -f "$f" ] && rm -f "$f"
  done

  # 摘掉 AGENTS.md 里的注入块：只按标记删除，用户自己的内容原样保留
  if [ -f "$AGENTS_PATH" ]; then
    if hs_has_block "$AGENTS_PATH" "$HS_MARK_BEGIN" "$HS_MARK_END"; then
      left="$(hs_strip_block "$AGENTS_PATH" "$HS_MARK_BEGIN" "$HS_MARK_END" | trim_all_pipe)"
      if [ -z "$left" ]; then
        rm -f "$AGENTS_PATH"
        hs_log "Removed injected AGENTS.md (it only held the prompt)"
      else
        printf '%s\n' "$left" | hs write "$AGENTS_PATH"
        hs_log "Removed injected block from AGENTS.md"
      fi
    fi
  fi

  rm -f "$STATE_PATH"

  # 只移除寒霜安装的 skills，绝不动其他 skills
  if [ -n "$prev_skills" ]; then
    printf '%s\n' "$prev_skills" >"$(hs_tmp)/prev-skills.txt"
    hs_remove_skills "$(hs_tmp)/prev-skills.txt" "$SKILLS_TARGET" >/dev/null
    hs_log "Removed managed skills: $(hs_join_commas "$prev_skills")"
  fi
  # 移除随附包（skills 树之外的自有目录）
  if [ -n "$prev_bundles" ]; then
    printf '%s\n' "$prev_bundles" | while IFS= read -r b; do
      [ -n "$b" ] || continue
      [ "$b" = "." ] && continue
      [ "$b" = ".." ] && continue
      [ -e "$CODEX_HOME/$b" ] && rm -rf "$CODEX_HOME/$b"
    done
    hs_log "Removed managed bundles: $(hs_join_commas "$prev_bundles")"
  fi

  # 清除 Codex 记忆注入段（memory_summary.md 中标题含「寒霜注入」的章节）
  if [ -f "$MEM_SUMMARY" ]; then
    if mem_old="$(cat "$MEM_SUMMARY")" && \
       mem_new="$(printf '%s\n' "$mem_old" | awk '
         /^## / { skip = (index($0, "寒霜注入") > 0) }
         { if (!skip) print }' | awk '
         BEGIN { b = 0 }
         /^[[:space:]]*$/ { b++; if (b <= 1) print ""; next }
         { b = 0; print }')"; then
      if [ "$(printf '%s' "$mem_new" | trim_all_pipe)" != "$(printf '%s' "$mem_old" | trim_all_pipe)" ]; then
        printf '%s' "$mem_new" | write_trimmed "$MEM_SUMMARY"
        hs_log "Removed injected Codex memory blocks"
      fi
    else
      hs_log "Memory cleanup skipped"
    fi
  fi

  # 恢复安装前的 skills 启用状态
  restore_list=""
  if [ -n "$prev_disabled" ]; then
    restore_list="$(printf '%s\n' "$prev_disabled" | grep -vx -e 'skills' | grep -v '^[[:space:]]*$' || true)"
  fi
  printf '%s\n' "$restore_list" >"$(hs_tmp)/restore-disabled.txt"
  set_skills_enabled_state "$(hs_tmp)/restore-disabled.txt"
  if [ -n "$restore_list" ]; then
    hs_log "Restored previous disabled skills: $(hs_join_commas "$restore_list")"
  else
    hs_log "All non-managed skills re-enabled"
  fi

  if [ "$had_state" -eq 1 ] && [ -d "$MANAGED_DIR" ] && [ -z "$(ls -A "$MANAGED_DIR" 2>/dev/null)" ]; then
    rmdir "$MANAGED_DIR" 2>/dev/null || true
  fi
  hs_log "Uninstalled managed prompt from $CODEX_HOME"
  exit 0
fi

# ---------- 安装 ----------

if [ -z "$SOURCE_PROMPT" ]; then
  for f in "$HS_ROOT"/*.md; do
    [ -f "$f" ] || continue
    SOURCE_PROMPT="$f"
    break
  done
  [ -n "$SOURCE_PROMPT" ] || hs_die "No .md prompt file found in $HS_ROOT"
fi
[ -f "$SOURCE_PROMPT" ] || hs_die "Prompt file not found: $SOURCE_PROMPT"

TARGET_PROMPT="$MANAGED_DIR/$(basename "$SOURCE_PROMPT")"

hs mkdir "$CODEX_HOME"
hs mkdir "$MANAGED_DIR"

config_existed=0
[ -f "$CONFIG_PATH" ] && config_existed=1
config_text=""
[ -f "$CONFIG_PATH" ] && config_text="$(cat "$CONFIG_PATH")"
previous_line="$(printf '%s\n' "$config_text" | grep -m1 -E '^[[:space:]]*model_instructions_file[[:space:]]*=' | tr -d '\r' || true)"

cp -f "$SOURCE_PROMPT" "$TARGET_PROMPT"

# 提示词里的 __CODEX_HOME__ 按本机实际安装位置展开
codex_home_fwd="$(printf '%s' "$CODEX_HOME" | tr '\\' '/')"
if hs_contains "$TARGET_PROMPT" '__CODEX_HOME__'; then
  replace_literal "$TARGET_PROMPT" '__CODEX_HOME__' "$codex_home_fwd"
  hs_log "Prompt paths   : __CODEX_HOME__ -> $codex_home_fwd"
fi

# config.toml 写入 model_instructions_file
config_prompt_path="$(printf '%s' "$TARGET_PROMPT" | tr '\\' '/')"
escaped_path="$(printf '%s' "$config_prompt_path" | sed -e 's/"/\\"/g')"
new_line="model_instructions_file = \"$escaped_path\""
if printf '%s\n' "$config_text" | grep -qE '^[[:space:]]*model_instructions_file[[:space:]]*='; then
  config_text="$(printf '%s\n' "$config_text" | HS_NL="$new_line" awk '
    !d && /^[[:space:]]*model_instructions_file[[:space:]]*=/ { print ENVIRON["HS_NL"]; d = 1; next }
    { print }')"
else
  config_text="$new_line
$config_text"
fi
printf '%s' "$config_text" | write_trimmed "$CONFIG_PATH"

# ---------- AGENTS.md 注入（-InjectAgents）----------
# Codex 原生会读 <CodexHome>/AGENTS.md 作为全局指令；config.toml 里的
# model_instructions_file 会被 Codex 自己重写 config.toml 时丢掉，所以额外写一份。
# 用带标记的块，卸载时按标记摘除，绝不整体吞掉用户自己的内容。
if hs_flag -InjectAgents; then
  body="$(hs_read "$TARGET_PROMPT" | trim_end_pipe)"
  block="$(printf '%s\n%s\n%s' "$AGENTS_BEGIN · $(basename "$TARGET_PROMPT") -->" "$body" "$AGENTS_END")"
  printf '%s\n' "$block" >"$(hs_tmp)/agents-block.txt"

  # 正文和要装的一模一样 = 这份 AGENTS.md 已经就是提示词本身
  # （用户手工贴过，或装了另一份提示词），可以直接整份换成带标记的块
  is_prompt_only=0
  if [ -f "$AGENTS_PATH" ]; then
    if hs_eq_prompt "$AGENTS_PATH" "$TARGET_PROMPT"; then
      is_prompt_only=1
    elif [ -n "$AGENTS_KNOWN" ]; then
      while IFS= read -r k; do
        [ -n "$k" ] || continue
        [ -f "$k" ] || continue
        if hs_eq_prompt "$AGENTS_PATH" "$k"; then is_prompt_only=1; break; fi
      done < <(hs_split_semicolon "$AGENTS_KNOWN")
    fi
  fi

  if hs_has_block "$AGENTS_PATH" "$HS_MARK_BEGIN" "$HS_MARK_END"; then
    # 已注入过：只换标记之间那一段，标记外的内容原样保留
    hs_splice_block "$AGENTS_PATH" "$HS_MARK_BEGIN" "$HS_MARK_END" "$(hs_tmp)/agents-block.txt" \
      | write_trimmed "$AGENTS_PATH"
    agents_result='updated'
  elif [ ! -s "$AGENTS_PATH" ] || [ "$is_prompt_only" -eq 1 ]; then
    # 空文件 / 只有提示词正文：整份写成带标记的块
    printf '%s\n' "$block" | hs write "$AGENTS_PATH"
    if [ "$is_prompt_only" -eq 1 ]; then agents_result='replaced-manual'; else agents_result='created'; fi
  else
    # 用户自己的 AGENTS.md：先备份，再把块追加到末尾（不动原有内容）
    bak="$CODEX_HOME/AGENTS.md.backup-$(hs_stamp)"
    cp -f "$AGENTS_PATH" "$bak"
    existing="$(hs_read "$AGENTS_PATH" | trim_end_pipe)"
    { printf '%s\n\n%s\n' "$existing" "$block"; } | hs write "$AGENTS_PATH"
    agents_result="appended (backup: $(basename "$bak"))"
  fi
  hs_log "Injected into AGENTS.md: $agents_result -> $AGENTS_PATH"
fi

# 先读上一次安装写下的清单（新版装完要按它清理旧版遗留）
prev_skills="$(hs_state_list "$STATE_PATH" "$SKILLS_MANIFEST_KEY")"
prev_bundles="$(hs_state_list "$STATE_PATH" installedBundles)"
prev_prompt_history="$(hs_state_list "$STATE_PATH" promptHistory)"
prev_target="$(hs_json_get "$STATE_PATH" targetPrompt)"

# 提示词历史：managed-prompts 下凡是我们写进去的都记下来，换版本时清掉上一份
prompt_history="$prev_prompt_history"
if [ -z "$prompt_history" ] && [ -n "$prev_target" ]; then
  prompt_history="$prev_target"
fi
if ! printf '%s\n' "$prompt_history" | grep -Fxq -e "$TARGET_PROMPT"; then
  if [ -n "$prompt_history" ]; then
    prompt_history="$prompt_history
$TARGET_PROMPT"
  else
    prompt_history="$TARGET_PROMPT"
  fi
fi
printf '%s\n' "$prompt_history" | while IFS= read -r old; do
  [ -n "$old" ] || continue
  [ "$old" = "$TARGET_PROMPT" ] && continue
  if [ -f "$old" ]; then
    rm -f "$old"
    hs_log "Removed previous prompt: $(basename "$old")"
  fi
done

# 记录安装前的禁用状态（用于卸载恢复）；必须在禁用动作之前读
list_disabled_skills >"$(hs_tmp)/prev-disabled.txt"

if hs_flag -NoSkills; then
  # 只写提示词：不装技能、不装随附包、也不清理或禁用 skills 目录里已有的任何技能。
  # 上次安装的清单原样带进 state —— 那是寒霜装过的东西，卸载时仍要能清干净。
  hs_log "Skills disabled (-NoSkills): prompt only, existing skills left untouched"
  installed_skills="$prev_skills"
  installed_bundles="$prev_bundles"
else
  installed_skills="$(hs_install_skills "$SKILLS_SRC" "$SKILLS_TARGET")"
  if [ -n "$installed_skills" ]; then
    hs_log "Installed skills: $(hs_join_commas "$installed_skills")"
  fi

  # 清掉上一版遗留、新版技能库里已移除的技能
  printf '%s\n' "$prev_skills" >"$(hs_tmp)/prev-skills.txt"
  printf '%s\n' "$installed_skills" >"$(hs_tmp)/cur-skills.txt"
  stale_skills="$(hs_prune_stale_skills "$(hs_tmp)/prev-skills.txt" "$(hs_tmp)/cur-skills.txt" "$SKILLS_TARGET")"
  if [ -n "$stale_skills" ]; then
    hs_log "Pruned stale skills from previous version: $(hs_join_commas "$stale_skills")"
  fi

  # 部署随附包到 $CodexHome/<name>（skills 树之外，避免被技能发现机制扫到）
  install_bundles "$BUNDLE_SOURCE"
  installed_bundles="$(cat "$(hs_tmp)/bundles.txt")"
  if [ -n "$installed_bundles" ]; then
    hs_log "Installed bundles: $(hs_join_commas "$installed_bundles")"
  fi

  # 应用随附包内的提示词路径占位符替换（__CODEX_HOME__ -> 实际路径，正斜杠）
  printf '%s\n' "$installed_bundles" | while IFS= read -r b; do
    [ -n "$b" ] || continue
    [ -d "$CODEX_HOME/$b" ] || continue
    find "$CODEX_HOME/$b" -type f -name '*.md' -exec grep -l '__CODEX_HOME__' {} + 2>/dev/null \
      | while IFS= read -r mf; do
          replace_literal_now "$mf" '__CODEX_HOME__' "$codex_home_fwd"
        done
  done

  # 禁用所有非寒霜 skills（只装了提示词时不能走这里，否则会把用户自己的技能全禁用）
  printf '%s\n' "$installed_skills" >"$(hs_tmp)/managed-skills.txt"
  disabled_now="$(disable_non_managed_skills "$(hs_tmp)/managed-skills.txt")"
  if [ -n "$disabled_now" ]; then
    hs_log "Disabled non-managed skills: $(hs_join_commas "$disabled_now")"
  fi
fi

# ---------- 状态文件 ----------
hs mkdir "$MANAGED_DIR"
hs_json_set "$STATE_PATH" installedAt "$(json_str "$(hs_now)")"
hs_json_set "$STATE_PATH" configPath "$(json_str "$CONFIG_PATH")"
hs_json_set "$STATE_PATH" targetPrompt "$(json_str "$TARGET_PROMPT")"
printf '%s\n' "$prompt_history" | hs_json_array "$STATE_PATH" promptHistory
if [ "$config_existed" -eq 1 ]; then
  hs_json_set "$STATE_PATH" configExisted "true"
else
  hs_json_set "$STATE_PATH" configExisted "false"
fi
if [ -n "$previous_line" ]; then
  hs_json_set "$STATE_PATH" hadLine "true"
  hs_json_set "$STATE_PATH" previousLine "$(json_str "$previous_line")"
else
  hs_json_set "$STATE_PATH" hadLine "false"
  hs_json_set "$STATE_PATH" previousLine "null"
fi
printf '%s\n' "$installed_skills" | hs_json_array "$STATE_PATH" installedSkills
printf '%s\n' "$installed_bundles" | hs_json_array "$STATE_PATH" installedBundles
hs_json_array "$STATE_PATH" previousDisabledSkills <"$(hs_tmp)/prev-disabled.txt"

hs_log "Installed prompt: $TARGET_PROMPT"
hs_log "Updated config:   $CONFIG_PATH"
hs_log "Restart Codex to load the configured instruction file."
exit 0
