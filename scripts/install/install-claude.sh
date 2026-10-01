#!/usr/bin/env bash
# install-claude.sh — Claude Code 破甲注入（macOS）
#
# 对齐 install-claude.ps1 的全部行为：
#   · 注入方式：带标记的块（<!-- HANSHUANG-INJECT:BEGIN prompt=x.md --> ... END）
#     用户自己写的内容一律保留，首次注入前备份原文件
#   · 已有块只换块内内容；整份文件本来就是提示词（含老版本无标记覆盖式注入）才整份改写
#   · 卸载只按标记摘块；摘完为空则还原干净备份，找不到干净备份就删掉
#   · 技能库：只删「上次安装清单 ∩ 随包技能库」的技能，用户自建技能一条不沾
#
# 用法：
#   ./install-claude.sh -SourcePrompt /path/寒霜v4.md -SkillsSource codex-skills-v4 \
#                       -KnownPrompts "/a.md;/b.md"
#   ./install-claude.sh -Uninstall

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
CLAUDE_HOME="$(hs_arg -ClaudeHome '')"
SKILLS_SOURCE="$(hs_arg -SkillsSource '')"
KNOWN_PROMPTS="$(hs_arg -KnownPrompts '')"

[ -n "$CLAUDE_HOME" ] || CLAUDE_HOME="$HOME/.claude"

CLAUDE_MD="$CLAUDE_HOME/CLAUDE.md"
MANAGED_DIR="$CLAUDE_HOME/managed-prompts"
BACKUP_PATH="$MANAGED_DIR/CLAUDE.md.bak"
MARKER_END='<!-- HANSHUANG-INJECT:END -->'

if [ -z "$SKILLS_SOURCE" ]; then
  SKILLS_SRC="$HS_ROOT/codex-skills"
else
  SKILLS_SRC="$HS_ROOT/$SKILLS_SOURCE"
fi
SKILLS_TARGET="$CLAUDE_HOME/skills"
SKILLS_MANIFEST_KEY='installedSkills'
STATE_PATH="$MANAGED_DIR/install-state.json"

# 找一份「干净的」原始 CLAUDE.md 备份（最新的优先）：
# 覆盖各家备份命名，排除注入产物与空文件；找不到返回空。
clean_claude_backup() {
  local cands=() c t best="" best_t=-1
  for c in "$CLAUDE_HOME"/CLAUDE.md.bak "$CLAUDE_HOME"/CLAUDE.md.bak_* \
           "$CLAUDE_HOME"/CLAUDE.md.backup-* "$CLAUDE_HOME"/CLAUDE.md.hanshuang.bak \
           "$BACKUP_PATH"; do
    [ -f "$c" ] || continue
    [ "$c" = "$CLAUDE_MD" ] && continue
    [ "$(hs size "$c")" -gt 0 ] || continue
    hs_is_artifact "$c" && continue
    cands+=("$c")
  done
  for c in "${cands[@]:-}"; do
    [ -n "$c" ] || continue
    t="$(hs mtime "$c")"
    if [ "$t" -gt "$best_t" ]; then best_t="$t"; best="$c"; fi
  done
  [ -n "$best" ] && printf '%s' "$best"
}

# 把注入产物挪到一边留证，文件名带时间戳
aside_name() { printf '%s/CLAUDE.md.inject-%s' "$CLAUDE_HOME" "$(hs_stamp)"; }

# ---------- 卸载 ----------

if hs_flag -Uninstall; then
  if [ -f "$CLAUDE_MD" ]; then
    if hs_has_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END"; then
      # 摘掉注入块，块外用户内容原样保留
      left="$(hs_strip_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END")"
      left="$(printf '%s' "$left" | sed -e 's/[[:space:]]*$//')"
      if [ -z "$left" ]; then
        # 摘完什么都不剩 = 这份文件本来就是我们建的
        clean="$(clean_claude_backup)"
        if [ -n "$clean" ]; then
          cp -f "$clean" "$CLAUDE_MD"
          hs_log "Restored original CLAUDE.md from $(basename "$clean")"
        else
          rm -f "$CLAUDE_MD"
          hs_log "Removed injected CLAUDE.md"
        fi
      else
        printf '%s\n' "$left" | hs write "$CLAUDE_MD"
        hs_log "Removed injected block from CLAUDE.md (user content kept)"
      fi
    elif hs_is_artifact "$CLAUDE_MD"; then
      # 没有标记、但内容就是寒霜提示词（老版本覆盖式注入留下的）
      aside="$(aside_name)"
      mv -f "$CLAUDE_MD" "$aside"
      clean="$(clean_claude_backup)"
      if [ -n "$clean" ]; then
        cp -f "$clean" "$CLAUDE_MD"
        hs_log "Restored original CLAUDE.md from $(basename "$clean") (stale injection kept at $(basename "$aside"))"
      else
        hs_log "Removed stale injected CLAUDE.md (kept a copy at $(basename "$aside"))"
      fi
    else
      hs_log "No injection found, nothing to do"
    fi
  else
    hs_log "No CLAUDE.md found, nothing to do"
  fi

  # 删除同步安装的 skills
  if [ -f "$STATE_PATH" ]; then
    prev="$(hs_state_list "$STATE_PATH" "$SKILLS_MANIFEST_KEY")"
    if [ -n "$prev" ]; then
      printf '%s\n' "$prev" >"$(hs_tmp)/prev-skills.txt"
      removed="$(hs_remove_skills "$(hs_tmp)/prev-skills.txt" "$SKILLS_TARGET")"
      if [ -n "$removed" ]; then
        hs_log "Removed managed skills: $(hs_join_commas "$removed")"
      else
        hs_log "No managed skills to remove"
      fi
    fi
    rm -f "$STATE_PATH"
  fi
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
  [ -n "$SOURCE_PROMPT" ] || hs_die "No .md prompt file found in $HS_ROOT"
fi

[ -f "$SOURCE_PROMPT" ] || hs_die "Prompt file not found: $SOURCE_PROMPT"

hs mkdir "$CLAUDE_HOME"
hs mkdir "$MANAGED_DIR"

PROMPT_TEXT="$(hs_read "$SOURCE_PROMPT")"
MARKER_BEGIN="<!-- HANSHUANG-INJECT:BEGIN prompt=$(basename "$SOURCE_PROMPT") -->"
BLOCK="$(printf '%s\n%s\n%s' "$MARKER_BEGIN" "$PROMPT_TEXT" "$MARKER_END")"

existing=""
[ -f "$CLAUDE_MD" ] && existing="$(hs_read "$CLAUDE_MD")"
norm_existing="$(printf '%s' "$existing" | sed -e 's/\r$//' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
norm_body="$(printf '%s' "$PROMPT_TEXT" | sed -e 's/\r$//' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

is_prompt_only=0
if [ -n "$norm_existing" ]; then
  if [ "$norm_existing" = "$norm_body" ]; then
    is_prompt_only=1
  else
    # 去掉已有注入块之后再比：老版本写下的「块内只有提示词」也算
    outside="$(hs_strip_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END" 2>/dev/null)"
    outside="$(printf '%s' "$outside" | sed -e 's/[[:space:]]//g')"
    if [ -f "$CLAUDE_MD" ] && hs_has_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END" && [ -z "$outside" ]; then
      is_prompt_only=1
    fi
    if [ "$is_prompt_only" -eq 0 ] && [ -n "$KNOWN_PROMPTS" ]; then
      while IFS= read -r k; do
        [ -n "$k" ] || continue
        [ -f "$k" ] || continue
        if hs_eq_prompt "$CLAUDE_MD" "$k"; then is_prompt_only=1; break; fi
      done < <(hs_split_semicolon "$KNOWN_PROMPTS")
    fi
  fi
fi

if hs_has_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END"; then
  # 已有注入块：只换块内内容，块外的用户内容原样保留
  hs_splice_block "$CLAUDE_MD" "$HS_INJ_BEGIN" "$HS_INJ_END" <(printf '%s' "$BLOCK") | hs write "$CLAUDE_MD"
  printf '\n' >>"$CLAUDE_MD"
  hs_log "Updated injected block in CLAUDE.md (user content kept)"
elif [ -z "$norm_existing" ] || [ "$is_prompt_only" -eq 1 ]; then
  printf '%s\n' "$BLOCK" | hs write "$CLAUDE_MD"
  hs_log "Injected prompt -> $CLAUDE_MD"
elif hs_is_artifact "$CLAUDE_MD"; then
  aside="$(aside_name)"
  mv -f "$CLAUDE_MD" "$aside"
  printf '%s\n' "$BLOCK" | hs write "$CLAUDE_MD"
  hs_log "Replaced stale injection -> $CLAUDE_MD (stale copy kept at $(basename "$aside"))"
else
  # 用户自己的内容：仅首次备份原文件，再把块追加到末尾
  hs_backup_once "$CLAUDE_MD" "$BACKUP_PATH"
  { printf '%s\n\n%s\n' "$(printf '%s' "$existing" | sed -e 's/[[:space:]]*$//')" "$BLOCK"; } | hs write "$CLAUDE_MD"
  hs_log "Appended injected block -> $CLAUDE_MD (original content kept)"
fi

# 先读上一次安装写下的技能清单（新版装完要按它清理旧版遗留）
prev_skills="$(hs_state_list "$STATE_PATH" "$SKILLS_MANIFEST_KEY")"
[ -n "$prev_skills" ] && printf '%s\n' "$prev_skills" >"$(hs_tmp)/prev-skills.txt" || : >"$(hs_tmp)/prev-skills.txt"

installed="$(hs_install_skills "$SKILLS_SRC" "$SKILLS_TARGET")"
if [ -n "$installed" ]; then
  hs_log "Installed skills: $(hs_join_commas "$installed")"
fi
printf '%s\n' "$installed" >"$(hs_tmp)/cur-skills.txt"

stale="$(hs_prune_stale_skills "$(hs_tmp)/prev-skills.txt" "$(hs_tmp)/cur-skills.txt" "$SKILLS_TARGET")"
if [ -n "$stale" ]; then
  hs_log "Pruned stale skills from previous version: $(hs_join_commas "$stale")"
fi

# 写回状态：只记录本次实际安装的技能名
hs mkdir "$MANAGED_DIR"
hs_json_array "$STATE_PATH" "$SKILLS_MANIFEST_KEY" <"$(hs_tmp)/cur-skills.txt"
