#!/usr/bin/env bash
# install-zcode.sh — ZCode 破甲注入（macOS）
#
# 对齐 install-zcode.ps1 的全部行为：
#   · AGENTS.md：整份覆盖为提示词，覆盖前带时间戳备份
#   · 全局记忆：从完整版提示词生成 cli/memories/global/memory/seagull-agents.md，
#     并改写同目录 MEMORY.md 索引；顺带把 v2/setting.json 的 memoryEnabled 从
#     false 打开成 true（记下「我们动过」，卸载时还回去）
#   · 技能库：同步到 ~/.zcode/skills，按上次清单清理旧版遗留
#   · -PatchSystemPrompt：改 ZCode 的 resources/glm/zcode.cjs（u9o / s9o / Xlt），
#     改前带时间戳备份；卸载时按 state 备份或 zcode.cjs.backup-* 还原
#   · install-state.json 记录全部产物；卸载时无论还原成功与否都删掉它
#   · 部分失败也要正确报错：HAD_ERROR 决定退出码（0 全成功 / 1 有失败 / 2 卸载有残留）
#
# 用法：
#   ./install-zcode.sh -SourcePrompt /path/寒霜v4.md -MemorySourcePrompt /path/寒霜v4.md \
#                      -SkillsSource codex-skills-v4 -PatchSystemPrompt
#   ./install-zcode.sh -Uninstall
#
# macOS 移植说明：
#   · %APPDATA% / %LOCALAPPDATA%  → $HOME/Library/Application Support
#   · 注册表卸载项、盘符扫描       → macOS 无此概念，改扫 /Applications 与 ~/Applications
#   · Get-Process / Get-CimInstance → pgrep / ps -ax -o command
#   · 路径分隔符一律 /

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

ZCODE_HOME_ARG="$(hs_arg -ZcodeHome '')"
SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
MEMORY_SOURCE_PROMPT="$(hs_arg -MemorySourcePrompt '')"
SKILLS_SOURCE="$(hs_arg -SkillsSource '')"
WORKSPACE_PATH="$(hs_arg -WorkspacePath '')"

# PowerShell 版的 $script:hadError：非致命步骤失败也置位，最后用它决定退出码
HAD_ERROR=0
zc_partial_fail() { HAD_ERROR=1; hs_warn "!! $*"; }

# ---------- 路径解析 ----------

if [ -z "$ZCODE_HOME_ARG" ]; then
  ZCODE_HOME="$HOME/.zcode"
else
  ZCODE_HOME="$ZCODE_HOME_ARG"
fi
# 相对路径 → 绝对路径（对齐 [System.IO.Path]::GetFullPath）
case "$ZCODE_HOME" in
  /*) ;;
  *) ZCODE_HOME="$PWD/$ZCODE_HOME" ;;
esac

CLI_ROOT="$ZCODE_HOME/cli"
AGENTS_PATH="$ZCODE_HOME/AGENTS.md"
STATE_PATH="$ZCODE_HOME/install-state.json"
SETTING_PATH="$ZCODE_HOME/v2/setting.json"
BOT_STATE_PATH="$ZCODE_HOME/v2/bot-state.v2.json"

# 提示词源：默认取脚本旁的 寒霜v1.2.md（完整版）/ AGENTS.md
if [ -z "$SOURCE_PROMPT" ]; then
  for f in "$HS_ROOT/寒霜v1.2.md" "$HS_ROOT/AGENTS.md" "$(dirname "$HS_ROOT")/AGENTS.md"; do
    if [ -f "$f" ]; then SOURCE_PROMPT="$f"; break; fi
  done
fi
[ -n "$SOURCE_PROMPT" ] && [ -f "$SOURCE_PROMPT" ] ||
  hs_die "Prompt file not found. Pass -SourcePrompt or place AGENTS.md next to this script."

# 记忆源：完整版提示词（寒霜v1.2.md），包装成 seagull-agents.md 记忆
if [ -z "$MEMORY_SOURCE_PROMPT" ]; then
  MEMORY_SOURCE_PROMPT="$HS_ROOT/寒霜v1.2.md"
  [ -f "$MEMORY_SOURCE_PROMPT" ] || MEMORY_SOURCE_PROMPT="$SOURCE_PROMPT"
fi

# 工作区路径（决定记忆目录 hash）：优先从 zcode bot-state 读取实际工作区。
# 注意：本脚本里 WorkspacePath 只用于日志展示，记忆目录是全局的。
if [ -z "$WORKSPACE_PATH" ] && [ -f "$BOT_STATE_PATH" ]; then
  # PowerShell 用 ConvertFrom-Json 取 bots.*.workspacePath 的第一个；
  # lib.sh 的 json-get 只支持顶层字段，这里用 sed 取第一个 workspacePath 字面量。
  WORKSPACE_PATH="$(sed -n 's/.*"workspacePath"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$BOT_STATE_PATH" | head -1)"
fi
if [ -z "$WORKSPACE_PATH" ]; then
  # 对齐 PowerShell 的 Split-Path -Parent $PSScriptRoot（脚本所在仓库根的上一级）
  WORKSPACE_PATH="$(dirname "$HS_ROOT")"
fi
case "$WORKSPACE_PATH" in
  /*) ;;
  *) WORKSPACE_PATH="$PWD/$WORKSPACE_PATH" ;;
esac

# 记忆目录：全局（zcode.cjs 已 patch 为固定加载 memories/global/memory）
MEMORY_ROOT="$CLI_ROOT/memories/global/memory"

# 【已废弃】旧的「是否已注入」判断标记。
#
# 原实现用 'CTF-LAB-2.0' 当特征串，但这个串**不在任何一份随包提示词里**
# （实测 寒霜v3/v4/v4-claude/v5 全部 0 处），所以它从写下那天起就没生效过：
#   · 重复安装永远不去重；
#   · 卸载时「系统提示词仍被注入 → 从备份还原」这条分支永远走不到。
# 现在统一改用 zc_cjs_patched()（由 zcode-patch.cjs 判定真实状态）。
# 这里保留常量只是为了让 diff 可读，代码里已不再引用。
CJS_MARKER_DEPRECATED='CTF-LAB-2.0'

# 系统提示词补丁的执行器（node 程序，见文件头注释）
ZC_PATCHER="$HS_LIB_DIR/zcode-patch.cjs"

# ---------- 本脚本新增的辅助函数（lib.sh 里没有，故写在这里） ----------

# 系统提示词是否已被 patch。
#
# 旧实现用固定标记串 'CTF-LAB-2.0' 判断，而那个串**根本不在任何随包提示词里**
# （实测 0 处），所以「已注入」永远判定为否 —— 既导致重复安装不去重，
# 也让卸载时的还原分支永远走不到。现在改由 zcode-patch.cjs 判定：
#   能读到默认身份声明 = 干净；读不到但能读到提示词特征 = 已 patch。
zc_cjs_patched() {
  local f="$1"
  [ -f "$f" ] || return 1
  local st
  st="$("$(hs_node)" "$ZC_PATCHER" check "$f" "${MEMORY_SOURCE_PROMPT:-}" 2>/dev/null |
    sed -n 's/^STATE=//p')"
  [ "$st" = "patched" ]
}

# 文本是否命中注入特征（对齐 PowerShell 的 -match 'CTF-LAB|寒霜|Seagull'）
zc_is_injected() {
  local t="$1"
  [[ "$t" == *CTF-LAB* || "$t" == *寒霜* || "$t" == *Seagull* ]]
}

# stdin 文本 → JSON/JS 字符串字面量（含双引号），对齐 ConvertTo-Json -Compress。
# 只转义必要字符（\ " TAB CR LF），其余字节（含中文）原样透传。
# 刻意不用 awk 逐行拼接：awk 的 RS 处理会因平台/locale 吞掉 CR（gawk-on-Windows 实测），
# 用 bash 的 ${var//} 做纯字节替换才与 PowerShell 的 ReadAllText 结果一致。
# 注意：与 hs_read 一样，命令替换会吃掉末尾换行（PS 会保留）——只影响文件最后一字节。
zc_js_string() {
  # 用 $'...'（ANSI-C 引用）取特殊字符：$(printf '\n') 会被命令替换吃掉换行
  local s bs='\' bs2='\\' q='"' q2='\"'
  local tab=$'\t' tab2='\t' cr=$'\r' cr2='\r' lf=$'\n' lf2='\n'
  s="$(cat)"
  s="${s//"$bs"/"$bs2"}"
  s="${s//"$q"/"$q2"}"
  s="${s//"$tab"/"$tab2"}"
  s="${s//"$cr"/"$cr2"}"
  s="${s//"$lf"/"$lf2"}"
  printf '"%s"' "$s"
}

# 逐行文本 → JSON 字符串数组（对齐 ConvertTo-Json 的数组输出，空行忽略）
zc_json_array_of_lines() {
  awk 'BEGIN { printf "[" } { if ($0 == "") next; printf "%s\"%s\"", (n++ ? "," : ""), $0 } END { printf "]" }'
}

# 去掉尾部的空行/空白行（对齐 PowerShell 的 .TrimEnd()）
zc_trim_end_lines() {
  awk '{ a[++n] = $0 } END { while (n > 0 && a[n] ~ /^[[:space:]]*$/) n--; for (i = 1; i <= n; i++) print a[i] }'
}

# 自动探测 ZCode 的系统提示词文件（resources/glm/zcode.cjs）
# macOS 等价物说明：
#   · Get-Process  → pgrep / ps -ax -o command
#   · 注册表卸载项 → macOS 无此概念，跳过
#   · 盘符扫描     → macOS 无此概念，改为扫 /Applications 与 ~/Applications 一级目录
zc_find_system_prompt() {
  local pid="" line="" exe="" cand="" root="" d=""

  # 0. 显式覆盖。测试时必须走这条，否则会直接改到 /Applications 里的真实 ZCode；
  #    对装在非常规路径的机器也用得上。
  if [ -n "${HS_ZCODE_CJS:-}" ] && [ -f "$HS_ZCODE_CJS" ]; then
    printf '%s' "$HS_ZCODE_CJS"
    return 0
  fi

  # 1. 从运行中的 ZCode 进程定位
  if command -v pgrep >/dev/null 2>&1; then
    pid="$(pgrep -x ZCode 2>/dev/null | head -1)"
    [ -n "$pid" ] || pid="$(pgrep -f 'ZCode.app/Contents/MacOS/ZCode' 2>/dev/null | head -1)"
  fi
  if [ -n "$pid" ]; then
    line="$(ps -ax -o pid=,command= 2>/dev/null |
      awk -v p="$pid" '$1 == p { $1 = ""; sub(/^[ \t]+/, ""); print; exit }')"
    exe="${line%% *}"
    if [ -n "$exe" ]; then
      # <App>.app/Contents/MacOS/ZCode → <App>.app/Contents/Resources/glm/zcode.cjs
      cand="$(dirname "$(dirname "$exe")")/Resources/glm/zcode.cjs"
      if [ -f "$cand" ]; then printf '%s' "$cand"; return 0; fi
    fi
  fi

  # 2. 常见安装位置
  for cand in \
    /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs \
    "$HOME/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs" \
    "$(hs_appsupport)/ZCode/resources/glm/zcode.cjs" \
    /Applications/ZCode/resources/glm/zcode.cjs; do
    if [ -f "$cand" ]; then printf '%s' "$cand"; return 0; fi
  done

  # 3. 兜底：扫应用目录下一级子目录
  for root in /Applications "$HOME/Applications"; do
    [ -d "$root" ] || continue
    for d in "$root"/*; do
      [ -d "$d" ] || continue
      cand="$d/Contents/Resources/glm/zcode.cjs"
      if [ -f "$cand" ]; then printf '%s' "$cand"; return 0; fi
    done
  done
  printf ''
}

SYSTEM_PROMPT_PATH=""
if hs_flag -PatchSystemPrompt || hs_flag -Uninstall; then
  SYSTEM_PROMPT_PATH="$(zc_find_system_prompt)"
fi

# ---------- 卸载 ----------

if hs_flag -Uninstall; then
  if [ ! -f "$STATE_PATH" ]; then
    state_exists=0
  else
    state_exists=1
  fi

  # 1. 恢复 AGENTS.md：优先 state 备份，其次按「最老 → 最新」找第一份干净备份
  #    （反复注入过的电脑上，后面的备份本身也带注入标记，越老的越接近原文件）
  restored_agents=0
  agents_backup=""
  : >"$(hs_tmp)/agents-cands.txt"
  if [ "$state_exists" -eq 1 ]; then
    sb="$(hs_json_get "$STATE_PATH" agentsBackup)"
    [ -n "$sb" ] && printf '%s\n' "$sb" >>"$(hs_tmp)/agents-cands.txt"
  fi
  for f in "$ZCODE_HOME"/AGENTS.md.backup-*; do
    [ -f "$f" ] && printf '%s\n' "$f" >>"$(hs_tmp)/agents-cands.txt"
  done
  while IFS= read -r cand; do
    [ -n "$cand" ] || continue
    [ -f "$cand" ] || continue
    if ! zc_is_injected "$(hs_read "$cand")"; then agents_backup="$cand"; break; fi
  done <"$(hs_tmp)/agents-cands.txt"

  if [ -n "$agents_backup" ]; then
    if cp -f "$agents_backup" "$AGENTS_PATH"; then
      hs_log "Restored original AGENTS.md from backup: $agents_backup"
      restored_agents=1
    else
      hs_warn "卸载失败: 无法从 $agents_backup 恢复 AGENTS.md"
      exit 1
    fi
  elif [ -f "$AGENTS_PATH" ]; then
    if zc_is_injected "$(hs_read "$AGENTS_PATH")"; then
      # 所有备份都已被注入覆盖（首次注入早于备份机制）→ 只能删除注入文件
      rm -f "$AGENTS_PATH"
      hs_log "Deleted injected AGENTS.md (no clean backup available)"
      restored_agents=1
    else
      hs_log "AGENTS.md is not ours, kept as-is"
    fi
  fi

  # 2. 删除安装的记忆文件（只删我们装的）
  installed_memories=""
  if [ "$state_exists" -eq 1 ]; then
    installed_memories="$(hs_state_list "$STATE_PATH" installedMemories)"
  fi
  if [ -n "$installed_memories" ]; then
    printf '%s\n' "$installed_memories" | while IFS= read -r m; do
      [ -n "$m" ] || continue
      p="$MEMORY_ROOT/$m"
      if [ -e "$p" ]; then
        rm -f "$p"
        hs_log "Removed memory: $m"
      fi
    done
    # 重建 MEMORY.md 索引（去掉已删文件的指针）
    index_path="$MEMORY_ROOT/MEMORY.md"
    if [ -f "$index_path" ]; then
      work="$(hs_tmp)/MEMORY.md"
      cp -f "$index_path" "$work"
      printf '%s\n' "$installed_memories" | while IFS= read -r m; do
        [ -n "$m" ] || continue
        grep -vF "]($m)" "$work" >"$work.next" 2>/dev/null
        mv -f "$work.next" "$work"
      done
      zc_trim_end_lines <"$work" | hs_write "$index_path"
    fi
  fi

  # 2.5 删除安装的技能（只删我们装的）
  if [ "$state_exists" -eq 1 ]; then
    installed_skills="$(hs_state_list "$STATE_PATH" installedSkills)"
    if [ -n "$installed_skills" ]; then
      printf '%s\n' "$installed_skills" | while IFS= read -r s; do
        [ -n "$s" ] || continue
        p="$ZCODE_HOME/skills/$s"
        if [ -e "$p" ]; then
          rm -rf "$p"
          hs_log "Removed skill: $s"
        fi
      done
    fi
  fi

  # 2.6 还原 setting.json 的 memoryEnabled。
  #     安装时我们把它从 false 改成了 true（为了让它读注入的记忆文件），
  #     但那是改用户的配置 —— 只在我们确实改过（state 有记录）时才还回去，
  #     用户自己开的记忆功能不动。
  if [ "$state_exists" -eq 1 ] && [ "$(hs_json_get "$STATE_PATH" memoryEnabledChanged)" = "true" ]; then
    if [ -f "$SETTING_PATH" ]; then
      if grep -Eq '"memoryEnabled"[[:space:]]*:[[:space:]]*true' "$SETTING_PATH"; then
        sed -E 's/"memoryEnabled"[[:space:]]*:[[:space:]]*true/"memoryEnabled": false/g' \
          "$SETTING_PATH" >"$(hs_tmp)/setting.json" &&
          cp -f "$(hs_tmp)/setting.json" "$SETTING_PATH" &&
          hs_log "Restored setting.json: memoryEnabled -> false"
      fi
    fi
  fi

  # 3. 恢复系统提示词（关键修复：state 缺 systemPromptPath 时必须重新探测，
  #    否则被 patch 的 zcode.cjs 残留 → 卸载后还是注入状态）
  cjs_fixed=1
  if [ -n "$SYSTEM_PROMPT_PATH" ] && [ -f "$SYSTEM_PROMPT_PATH" ]; then
    if zc_cjs_patched "$SYSTEM_PROMPT_PATH"; then
      cjs_backup=""
      sb=""
      if [ "$state_exists" -eq 1 ]; then
        sb="$(hs_json_get "$STATE_PATH" systemPromptBackup)"
      fi
      if [ -n "$sb" ] && [ -f "$sb" ]; then
        cjs_backup="$sb"
      else
        # state 缺备份时：取 ~/.zcode 下最近的 zcode.cjs.backup-*（不含注入痕迹的）
        # 文件名带 yyyyMMdd-HHmmss，倒序排序即「最新优先」
        ls -1 "$ZCODE_HOME"/zcode.cjs.backup-* 2>/dev/null | sort -r >"$(hs_tmp)/cjs-baks.txt"
        while IFS= read -r f; do
          [ -f "$f" ] || continue
          if ! zc_cjs_patched "$f"; then cjs_backup="$f"; break; fi
        done <"$(hs_tmp)/cjs-baks.txt"
      fi
      if [ -n "$cjs_backup" ] && [ -f "$cjs_backup" ]; then
        cp -f "$cjs_backup" "$SYSTEM_PROMPT_PATH"
        hs_log "Restored system prompt -> $SYSTEM_PROMPT_PATH"
      else
        cjs_fixed=0
        hs_warn "!! 系统提示词仍含注入内容，但未找到可用备份。请到 $SYSTEM_PROMPT_PATH 手动恢复，或重装 ZCode。"
      fi
    else
      hs_log "System prompt is clean, nothing to restore"
    fi
  else
    hs_log "System prompt file not found (ZCode 可能已卸载/换位置), skipped"
  fi

  # 无论还原成功与否都删掉 install-state.json（既有行为）
  rm -f "$STATE_PATH"

  # 4. 卸载结果校验（供上层 UI 显示真实状态）
  verify=""
  if [ -f "$AGENTS_PATH" ]; then
    zc_is_injected "$(hs_read "$AGENTS_PATH")" && verify="$verify; AGENTS.md 仍含注入内容"
  fi
  if [ -e "$MEMORY_ROOT/seagull-agents.md" ]; then
    verify="$verify; 记忆文件 seagull-agents.md 仍存在"
  fi
  if [ -n "$SYSTEM_PROMPT_PATH" ] && [ -f "$SYSTEM_PROMPT_PATH" ]; then
    zc_cjs_patched "$SYSTEM_PROMPT_PATH" &&
      verify="$verify; 系统提示词 zcode.cjs 仍被注入"
  fi
  if [ -n "$verify" ]; then
    hs_warn "残留: ${verify#; }"
    exit 2
  fi
  hs_log "Uninstalled. Restart ZCode to apply."
  exit 0
fi

# ---------- 安装 ----------

hs_log "=== ZCode 一键安装工具 ==="
hs_log "ZCode home:    $ZCODE_HOME"
hs_log "Prompt source: $SOURCE_PROMPT"
hs_log "Memory source: $MEMORY_SOURCE_PROMPT"
hs_log "Workspace:     $WORKSPACE_PATH"
hs_log "Memory target: $MEMORY_ROOT"
hs_log ""

# 1. 备份并安装 AGENTS.md
AGENTS_BACKUP=""
if [ -f "$AGENTS_PATH" ]; then
  AGENTS_BACKUP="$ZCODE_HOME/AGENTS.md.backup-$(hs_stamp)"
  if cp -f "$AGENTS_PATH" "$AGENTS_BACKUP"; then
    hs_log "[1/4] Backed up existing AGENTS.md -> $AGENTS_BACKUP"
  else
    zc_partial_fail "备份 AGENTS.md 失败: $AGENTS_PATH -> $AGENTS_BACKUP"
    AGENTS_BACKUP=""
  fi
fi
hs_mkdir "$ZCODE_HOME"
if ! cp -f "$SOURCE_PROMPT" "$AGENTS_PATH"; then
  hs_warn "安装失败: 无法写入 $AGENTS_PATH"
  exit 1
fi
hs_log "[1/4] Installed prompt -> $AGENTS_PATH"

# 2. 安装记忆（从完整版提示词生成 seagull-agents.md）
INSTALLED_MEMORIES=""
MEMORY_ENABLED_CHANGED=0   # 记下「我们动过 setting.json」，卸载时才知道要还回去
if [ -f "$MEMORY_SOURCE_PROMPT" ]; then
  hs_mkdir "$MEMORY_ROOT"
  # 开启 zcode 记忆功能（setting.json 的 memoryEnabled）
  if [ -f "$SETTING_PATH" ]; then
    if grep -Eq '"memoryEnabled"[[:space:]]*:[[:space:]]*false' "$SETTING_PATH"; then
      if sed -E 's/"memoryEnabled"[[:space:]]*:[[:space:]]*false/"memoryEnabled": true/g' \
        "$SETTING_PATH" >"$(hs_tmp)/setting.json" &&
        cp -f "$(hs_tmp)/setting.json" "$SETTING_PATH"; then
        MEMORY_ENABLED_CHANGED=1
        hs_log "      Memory enabled: setting.json -> true"
      else
        zc_partial_fail "改写 setting.json 失败: $SETTING_PATH"
      fi
    fi
  fi

  MEM_NAME='seagull-agents.md'
  MEM_PATH="$MEMORY_ROOT/$MEM_NAME"
  MEM_DESC='海鸥完整配置（CTF-LAB-2.0 Seagull Edition）——身份、路由、交付标准'
  PROMPT_TEXT="$(hs_read "$MEMORY_SOURCE_PROMPT")"
  MEM_TEXT="$(printf '%s\n%s\n%s\n%s\n%s\n\n%s' \
    '---' 'name: seagull-agents' "description: $MEM_DESC" 'metadata:' '  type: reference' "$PROMPT_TEXT")"
  if printf '%s' "$MEM_TEXT" | hs_write "$MEM_PATH"; then
    INSTALLED_MEMORIES="$MEM_NAME"
    # 更新 MEMORY.md 索引
    index_path="$MEMORY_ROOT/MEMORY.md"
    index_line="- [seagull-agents]($MEM_NAME) - $MEM_DESC"
    work="$(hs_tmp)/MEMORY.md"
    : >"$work"
    if [ -f "$index_path" ]; then
      # 对齐 PowerShell Get-Content：按行读、丢掉空行、去掉 CR
      grep -v '^[[:space:]]*$' "$index_path" 2>/dev/null | tr -d '\r' |
        grep -vF "]($MEM_NAME)" >>"$work"
    fi
    printf '%s\n' "$index_line" >>"$work"
    if hs_write "$index_path" <"$work"; then
      hs_log "[2/4] Installed memory -> $MEM_PATH"
      hs_log "      Index updated: MEMORY.md"
    else
      zc_partial_fail "更新 MEMORY.md 索引失败: $index_path"
    fi
  else
    zc_partial_fail "写入记忆文件失败: $MEM_PATH"
  fi
else
  hs_log "[2/4] No memory source at $MEMORY_SOURCE_PROMPT, skipped"
fi

# 先读上一次安装写下的技能清单（新版装完要按它清理旧版遗留）
prev_skills=""
[ -f "$STATE_PATH" ] && prev_skills="$(hs_state_list "$STATE_PATH" installedSkills)"
printf '%s\n' "$prev_skills" >"$(hs_tmp)/prev-skills.txt"

# 2.5 同步技能到 zcode（默认 codex-skills，V4 可传 codex-skills-v4）
INSTALLED_SKILLS=""
if [ -z "$SKILLS_SOURCE" ]; then
  skills_src="$HS_ROOT/codex-skills"
else
  skills_src="$HS_ROOT/$SKILLS_SOURCE"
fi
SKILLS_TARGET="$ZCODE_HOME/skills"
if [ -d "$skills_src" ]; then
  hs_mkdir "$SKILLS_TARGET"
  if installed="$(hs_install_skills "$skills_src" "$SKILLS_TARGET")"; then
    INSTALLED_SKILLS="$installed"
  else
    zc_partial_fail "同步技能库失败: $skills_src -> $SKILLS_TARGET"
    installed=""
  fi
  printf '%s\n' "$installed" >"$(hs_tmp)/cur-skills.txt"
  stale="$(hs_prune_stale_skills "$(hs_tmp)/prev-skills.txt" "$(hs_tmp)/cur-skills.txt" "$SKILLS_TARGET")"
  if [ -n "$stale" ]; then
    hs_log "[2.5/4] Pruned $(printf '%s\n' "$stale" | grep -c .) stale skills from previous version"
  fi
  hs_log "[2.5/4] Synced $(printf '%s\n' "$INSTALLED_SKILLS" | grep -c .) skills -> $SKILLS_TARGET"
else
  printf '' >"$(hs_tmp)/cur-skills.txt"
  hs_log "[2.5/4] No codex-skills dir, skipped"
fi

# 3. 可选：patch 系统提示词
#
# 交给 zcode-patch.cjs（node）执行。为什么不在 bash 里做：
#   · zcode.cjs 是压缩后的 14MB 单行 JS，bash 的字符串裁剪在这种规模下又慢、
#     又容易在多字节中文下标上错位 —— 一旦错位就是写坏 ZCode 本体；
#   · 清空 beforeDefault 数组需要「字符串感知的括号配对」，bash 做不到。
#
# 锚点也换了。旧实现锚的是**压缩后的变量名**（function u9o / function Alt /
# s9o / Xlt），而 ZCode 3.14.4 重新压缩后这些名字全变了：
#   · `function Alt` 根本不存在   → 前置条件不成立，整步被跳过
#   · `function u9o` 还在，但已是无关函数（workflow 作用域判断）
# 现在锚的是**字符串字面量**（"You are ZCode, an interactive coding agent"）
# 和**键名**（beforeDefault），变量名靠正则现读，换版本不会失效。
SYSTEM_PROMPT_BACKUP=""
if hs_flag -PatchSystemPrompt && [ -n "$SYSTEM_PROMPT_PATH" ] && [ -f "$SYSTEM_PROMPT_PATH" ]; then
  if zc_cjs_patched "$SYSTEM_PROMPT_PATH"; then
    hs_log "[3/4] System prompt already patched, skipped"
  else
    # 只在「干净」时备份：已打过补丁的文件当备份没有还原价值
    SYSTEM_PROMPT_BACKUP="$ZCODE_HOME/zcode.cjs.backup-$(hs_stamp)"
    cp -f "$SYSTEM_PROMPT_PATH" "$SYSTEM_PROMPT_BACKUP" ||
      zc_partial_fail "备份系统提示词失败: $SYSTEM_PROMPT_PATH"

    patch_out="$("$(hs_node)" "$ZC_PATCHER" apply "$SYSTEM_PROMPT_PATH" "$MEMORY_SOURCE_PROMPT" 2>&1)"
    patch_rc=$?
    printf '%s\n' "$patch_out" |
      grep -E '^(ACTION_|CLI_VAR|CLI_PROMPT_CHARS|GUIDE_ARRAY_LEN_BEFORE)' |
      sed 's/^/      /' || true

    if [ "$patch_rc" -eq 0 ]; then
      hs_log "[3/4] Replaced system prompt with Seagull config -> $SYSTEM_PROMPT_PATH"
      hs_log "      Backup: $SYSTEM_PROMPT_BACKUP"
    else
      # 关键：不能再静默跳过。旧实现在这里只打一行 skipped 就继续跑，
      # 用户看到的是「安装成功」，但系统提示词其实一个字都没改。
      zc_partial_fail "系统提示词补丁未完全生效（锚点缺失，ZCode 版本可能又变了）"
      hs_warn "      提示词 + 记忆 + 技能已注入，仅系统提示词这一层没打上。"
    fi
  fi
elif hs_flag -PatchSystemPrompt; then
  hs_log "[3/4] 未找到 ZCode 系统提示词文件（提示词 + 记忆 + 技能已注入，仅系统提示词未 patch）"
  hs_log "      若 ZCode 装在非常规路径，请先启动一次 ZCode 再重新注入"
else
  hs_log "[3/4] System prompt patch skipped (use -PatchSystemPrompt)"
fi

# 4. 记录安装状态
hs_mkdir "$ZCODE_HOME"
hs_json_set "$STATE_PATH" installedAt "$(hs_now)"
hs_json_set "$STATE_PATH" zcodeHome "$(printf '%s' "$ZCODE_HOME" | zc_js_string)"
hs_json_set "$STATE_PATH" agentsPath "$(printf '%s' "$AGENTS_PATH" | zc_js_string)"
if [ -n "$AGENTS_BACKUP" ]; then
  hs_json_set "$STATE_PATH" agentsBackup "$(printf '%s' "$AGENTS_BACKUP" | zc_js_string)"
else
  hs_json_set "$STATE_PATH" agentsBackup 'null'
fi
hs_json_set "$STATE_PATH" memoryRoot "$(printf '%s' "$MEMORY_ROOT" | zc_js_string)"
hs_json_set "$STATE_PATH" installedMemories "$(printf '%s\n' "$INSTALLED_MEMORIES" | zc_json_array_of_lines)"
hs_json_set "$STATE_PATH" installedSkills "$(printf '%s\n' "$INSTALLED_SKILLS" | zc_json_array_of_lines)"
if [ -n "$SYSTEM_PROMPT_PATH" ]; then
  hs_json_set "$STATE_PATH" systemPromptPath "$(printf '%s' "$SYSTEM_PROMPT_PATH" | zc_js_string)"
else
  hs_json_set "$STATE_PATH" systemPromptPath 'null'
fi
if [ -n "$SYSTEM_PROMPT_BACKUP" ]; then
  hs_json_set "$STATE_PATH" systemPromptBackup "$(printf '%s' "$SYSTEM_PROMPT_BACKUP" | zc_js_string)"
else
  hs_json_set "$STATE_PATH" systemPromptBackup 'null'
fi
if [ "$MEMORY_ENABLED_CHANGED" -eq 1 ]; then
  hs_json_set "$STATE_PATH" memoryEnabledChanged 'true'
else
  hs_json_set "$STATE_PATH" memoryEnabledChanged 'false'
fi
hs_log "[4/4] State saved -> $STATE_PATH"
hs_log ""
hs_log "=== 安装完成 ==="
hs_log "重启 ZCode 生效。"
hs_log "卸载：运行本脚本加 -Uninstall 参数。"

# 部分失败也要正确报错：用 hadError 决定退出码
if [ "$HAD_ERROR" -ne 0 ]; then
  hs_warn "部分步骤失败（见上方 !! 行），退出码 1"
  exit 1
fi
exit 0
