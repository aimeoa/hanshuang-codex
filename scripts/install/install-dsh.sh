#!/usr/bin/env bash
# install-dsh.sh — DeepSeek Harness（DSH）破甲注入（macOS）
#
# 对齐 install-dsh.ps1 的全部行为：
#   · ~/.dsh/AGENTS.md：整体覆盖为「带标记的提示词」
#       <!-- HANSHUANG-INJECT:BEGIN --> ... <!-- HANSHUANG-INJECT:END -->
#     懒人包模式写成 <!-- HANSHUANG-INJECT:BEGIN pack=dsh-lazy-pack-v5 -->（保留）
#   · 首次注入前把原文件备份进 ~/.dsh/managed-prompts/AGENTS.md.bak，卸载时还原
#   · 技能库同步到 ~/.dsh/skills：夹层提升 / BOM 剥离 / 非合规清理 / 上下文瘦身
#   · -KitRoot 懒人包模式：提示词取 <KitRoot>/materials/AGENTS.md、技能取
#     <KitRoot>/materials/skills，另附 shield-protocol.md / prompt-inject.md /
#     dsh-prompt-inject.json（模板 upsert 与还原）
#   · ~/.dsh/managed-prompts/install-state.json 记录 installedSkills / kit /
#     kitFiles / prompt
#   · 卸载：还原或删除 AGENTS.md、包专属文件、按清单删技能，最后落墓碑记录
#
# 用法：
#   ./install-dsh.sh -SourcePrompt /path/寒霜v4-claude.md -SkillsSource codex-skills-v4
#   ./install-dsh.sh -DshHome /tmp/x -KitRoot /path/dsh-lazy-pack-v5
#   ./install-dsh.sh -Uninstall
#
# 本脚本自带的辅助函数（lib.sh 里没有，也不打算往 lib.sh 加；下面都有注释说明用途）：
#   dsh_starts_fm / dsh_has_frontmatter  SKILL.md frontmatter 校验（对齐 PS 的正则判定）
#   dsh_list_skill_dirs / dsh_list_valid_skill_dirs
#   dsh_shipped_names                    随包技能白名单：lib 的 hs_shipped_skill_names
#                                        只覆盖 codex-skills*，不含懒人包技能库
#   dsh_prune_stale_skills / dsh_remove_skills
#   dsh_install_skills                   hs_install_skills + 夹层提升 / BOM / 瘦身
#   dsh_json_str / dsh_tpl_items / dsh_prompt_inject_upsert / dsh_prompt_inject_clean
#                                        dsh-prompt-inject.json 的模板写入与还原

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

hs_parse_args "$@"

SOURCE_PROMPT="$(hs_arg -SourcePrompt '')"
DSH_HOME="$(hs_arg -DshHome '')"
SKILLS_SOURCE="$(hs_arg -SkillsSource '')"
KIT_ROOT="$(hs_arg -KitRoot '')"

# DSH 的全局记忆文件是 <DshHome>/AGENTS.md，技能目录是 <DshHome>/skills
[ -n "$DSH_HOME" ] || DSH_HOME="$HOME/.dsh"

AGENTS_MD="$DSH_HOME/AGENTS.md"
MANAGED_DIR="$DSH_HOME/managed-prompts"
BACKUP_PATH="$MANAGED_DIR/AGENTS.md.bak"
MARKER='<!-- HANSHUANG-INJECT:BEGIN -->'
MARKER_END='<!-- HANSHUANG-INJECT:END -->'
KIT_NAME='dsh-lazy-pack-v5'

# ---------- 懒人包定位 ----------

# 未显式传 -KitRoot 时，自动找随包分发的懒人包目录（打包后在 Resources/ 下）。
# 包的位置有两种：随打包进 Resources（与仓库根同级），或开发时与项目目录平级的
# 兄弟目录 —— 后者少了父目录那一跳，只按仓库根找会在卸载（不带 -KitRoot）时落空。
dsh_kit_at() {
  [ -n "$1" ] || return 1
  [ -f "$1/materials/AGENTS.md" ]
}

PACKAGE_ROOT="$KIT_ROOT"
if [ -z "$PACKAGE_ROOT" ]; then
  for cand in "$HS_ROOT/$KIT_NAME" \
              "$(dirname "$HS_ROOT")/$KIT_NAME" \
              "$(dirname "$(dirname "$HS_ROOT")")/$KIT_NAME"; do
    if dsh_kit_at "$cand"; then PACKAGE_ROOT="$cand"; break; fi
  done
fi
if [ -z "$PACKAGE_ROOT" ] && [ -n "${HS_DSH_KIT:-}" ]; then
  dsh_kit_at "$HS_DSH_KIT" && PACKAGE_ROOT="$HS_DSH_KIT"
fi
IS_KIT=0
[ -n "$PACKAGE_ROOT" ] && IS_KIT=1

KIT_PROMPT=''
SHIELD_SRC=''
INJECT_SRC=''
COFFEE_SRC=''
if [ "$IS_KIT" = 1 ]; then
  KIT_PROMPT="$PACKAGE_ROOT/materials/AGENTS.md"
  [ -f "$KIT_PROMPT" ] || hs_die "KitRoot 里找不到 materials/AGENTS.md: $PACKAGE_ROOT"
  SHIELD_SRC="$PACKAGE_ROOT/materials/shield-protocol.md"
  INJECT_SRC="$PACKAGE_ROOT/prompts/operator-config-v5.md"
  COFFEE_SRC="$PACKAGE_ROOT/prompts/cold-coffee.md"
fi

# 包相关路径不分模式都要先算出来：卸载时不会传 -KitRoot，$IS_KIT 为假，
# 但还原/清理包文件仍然要用这些路径。
SHIELD_DST="$DSH_HOME/shield-protocol.md"
SHIELD_BAK="$MANAGED_DIR/shield-protocol.md.bak"
INJECT_DST="$DSH_HOME/prompt-inject.md"
INJECT_CFG="$DSH_HOME/dsh-prompt-inject.json"
INJECT_BAK="$MANAGED_DIR/prompt-inject.md.bak"
CFG_BAK="$MANAGED_DIR/dsh-prompt-inject.json.bak"

MARKER_BEGIN="$MARKER"
[ "$IS_KIT" = 1 ] && MARKER_BEGIN="<!-- HANSHUANG-INJECT:BEGIN pack=$KIT_NAME -->"

if [ -z "$SKILLS_SOURCE" ]; then
  SKILLS_SRC="$HS_ROOT/codex-skills"
else
  SKILLS_SRC="$HS_ROOT/$SKILLS_SOURCE"
fi
# 懒人包模式：技能取包内 materials/skills，忽略 -SkillsSource
[ "$IS_KIT" = 1 ] && SKILLS_SRC="$PACKAGE_ROOT/materials/skills"
SKILLS_TARGET="$DSH_HOME/skills"
SKILLS_MANIFEST_KEY='installedSkills'
TPL_KEY='templates'
# 本包注册进 dsh-prompt-inject.json 的模板 id（卸载时只摘这两个，用户自建模板保留）
TPL_ID_MAIN='pojia-default'
TPL_ID_COFFEE='cold-coffee'

# ---------- 技能辅助 ----------

# 首行是否 frontmatter（对齐 PS 的 $raw.StartsWith('---')）
dsh_starts_fm() {
  [ -f "$1" ] || return 1
  [ "$(head -c 3 "$1")" = '---' ]
}

# 是否「合规技能」：首行 --- + 闭合 --- + frontmatter 里有 name/description
dsh_has_frontmatter() {
  [ -f "$1" ] || return 1
  awk '
    NR == 1 {
      if (substr($0, 1, 3) != "---") { bad = 1; exit }
      next
    }
    bad { exit }
    /^---/ { closed = 1; exit }
    {
      if ($0 ~ /^name:[ \t]*[^ \t]/) has_name = 1
      if ($0 ~ /^description:[ \t]*[^ \t]/) has_desc = 1
    }
    END { exit (closed && has_name && has_desc) ? 0 : 1 }
  ' "$1"
}

# 目录下含 SKILL.md 的技能名（每行一个）
dsh_list_skill_dirs() {
  local d="$1" x
  [ -d "$d" ] || return 0
  for x in "$d"/*/; do
    [ -d "$x" ] || continue
    [ -f "${x%/}/SKILL.md" ] || continue
    basename "${x%/}"
  done
}

# 同上，但要求 SKILL.md 合规（夹层技能用它筛）
dsh_list_valid_skill_dirs() {
  local d="$1" x
  [ -d "$d" ] || return 0
  for x in "$d"/*/; do
    [ -d "$x" ] || continue
    dsh_has_frontmatter "${x%/}/SKILL.md" || continue
    basename "${x%/}"
  done
}

# 随包分发的技能名（去重），每行一个。
# lib.sh 的 hs_shipped_skill_names 只覆盖 codex-skills*，不含懒人包技能库 ——
# 少了懒人包那一半，切换版本/卸载时包内技能永远删不掉，所以这里并上。
# 三处 base 与 PS 的 Get-ShippedSkillNames 一致（仓库根 / 上级 / 上上级）。
dsh_shipped_names() {
  {
    hs_shipped_skill_names
    # node 的输出没有结尾换行，不补一个会把最后一个 codex 技能名和第一个包内技能名粘在一起
    printf '\n'
    for base in "$HS_ROOT" "$(dirname "$HS_ROOT")" "$(dirname "$(dirname "$HS_ROOT")")"; do
      dsh_list_skill_dirs "$base/$KIT_NAME/materials/skills"
      dsh_list_valid_skill_dirs "$base/$KIT_NAME/materials/skills/skills"
    done
    if [ -n "$PACKAGE_ROOT" ]; then
      dsh_list_skill_dirs "$PACKAGE_ROOT/materials/skills"
      dsh_list_valid_skill_dirs "$PACKAGE_ROOT/materials/skills/skills"
    fi
  } | sed '/^[[:space:]]*$/d' | LC_ALL=C sort -u
}

# 清理上一版遗留：候选 = 上次安装清单 ∩ 随包技能库 ∩ 当前不再分发。
# 只删同时满足三条的目录 —— 用户自己放进来的技能一条都不沾。
# （逻辑与 hs_prune_stale_skills 相同，只是白名单换成含懒人包的 dsh_shipped_names）
dsh_prune_stale_skills() {
  local prev="$1" cur="$2" dst="$3" name
  [ -f "$prev" ] || return 0
  dsh_shipped_names >"$(hs_tmp)/dsh-shipped.txt"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    grep -Fxq "$name" "$(hs_tmp)/dsh-shipped.txt" || continue
    [ -f "$cur" ] && grep -Fxq "$name" "$cur" && continue
    [ -f "$dst/$name/SKILL.md" ] || continue
    rm -rf "$dst/$name"
    printf '%s\n' "$name"
  done <"$prev"
}

# 卸载：只删「上次安装清单 ∩ 随包技能库」
dsh_remove_skills() {
  local list="$1" dst="$2" name
  [ -f "$list" ] || return 0
  dsh_shipped_names >"$(hs_tmp)/dsh-shipped.txt"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    grep -Fxq "$name" "$(hs_tmp)/dsh-shipped.txt" || continue
    [ -e "$dst/$name" ] || continue
    rm -rf "$dst/$name"
    printf '%s\n' "$name"
  done <"$list"
}

# 同步技能库；技能名逐行写进 $1（不能用 stdout —— 函数里的日志也走 stdout）。
# 基础同步复用 lib 的 hs_install_skills（跳过未变的技能 + preserveTimestamps），
# 后面四步是 PS 版 Install-Skills 独有、lib 没有的：夹层提升 / 夹层残留清理 /
# BOM 剥离与非合规技能清理 / 上下文瘦身。
dsh_install_skills() {
  local out="$1" name nd dest raw moved=0
  : >"$out"
  [ -d "$SKILLS_SRC" ] || return 0
  hs_install_skills "$SKILLS_SRC" "$SKILLS_TARGET" >"$out"
  # hs_install_skills 的输出没有结尾换行，直接 append 会把提升的技能名粘到上一行
  [ -s "$out" ] && printf '%s\n' "$(cat "$out")" >"$out"

  # 包内 skills 目录里还套了一层主控目录（materials/skills/skills）：
  # 它自己的 SKILL.md 没有 frontmatter，DSH 会整层拒收，里面独有的技能就永远加载不到。
  # 这里把该层里合规的技能提升到顶层，其余（旧格式 / 无 SKILL.md）跳过。
  local nested="$SKILLS_SRC/skills"
  if [ -d "$nested" ]; then
    for nd in "$nested"/*/; do
      [ -d "$nd" ] || continue
      nd="${nd%/}"
      name="$(basename "$nd")"
      dsh_has_frontmatter "$nd/SKILL.md" || continue
      dest="$SKILLS_TARGET/$name"
      [ -e "$dest" ] && continue          # 顶层已有同名，跳过
      cp -R "$nd" "$dest" || hs_die "复制技能失败: $nd"
      printf '%s\n' "$name" >>"$out"
    done
    # 夹层本身不是有效技能包，删掉，避免 ~/.dsh/skills 下留一堆加载不到的目录
    rm -rf "$SKILLS_TARGET/skills"
    # 夹层里的旧格式目录（SKILL.md 没有 frontmatter）会被 DSH 拒收；只要顶层有同名
    # 目录且同样不合规，就一并清掉，免得用户看到一堆「装了但用不了」的技能。
    for nd in "$nested"/*/; do
      [ -d "$nd" ] || continue
      dest="$SKILLS_TARGET/$(basename "${nd%/}")"
      [ -d "$dest" ] || continue
      [ -f "$dest/SKILL.md" ] || continue
      dsh_starts_fm "$dest/SKILL.md" && continue
      rm -rf "$dest"
    done
  fi

  # 收尾：清掉带 SKILL.md 但没 frontmatter 的目录（旧版懒人包遗留的夹层技能），
  # 同时把 SKILL.md 开头的 UTF-8 BOM 去掉：有 BOM 时首行不是 "---"，
  # frontmatter 会被当成正文，技能同样加载不到。
  for name in "$SKILLS_TARGET"/*/; do
    [ -d "$name" ] || continue
    name="${name%/}"
    local sk="$name/SKILL.md"
    [ -f "$sk" ] || continue
    if [ "$(head -c 3 "$sk" | od -An -tx1 | tr -d ' \n')" = 'efbbbf' ]; then
      tail -c +4 "$sk" >"$sk.tmp" && mv -f "$sk.tmp" "$sk"
      hs_log "Stripped BOM: $(basename "$name")"
    fi
    if ! dsh_starts_fm "$sk"; then
      rm -rf "$name"
      hs_log "Removed non-loadable skill dir: $(basename "$name")"
    fi
  done

  # 上下文瘦身：DSH 每轮都会把「技能目录」（名字+说明）塞进系统提示词，
  # 这两类属于窄场景/纯文档，装完后移进 skills-disabled 停用（可随时搬回）：
  #   competition-*               CTF 竞技场窄场景
  #   eni-redteam-*-detail-pack   标注 [DOCUMENTATION ONLY] 的边界说明
  local disabled="$DSH_HOME/skills-disabled"
  for name in "$SKILLS_TARGET"/*/; do
    [ -d "$name" ] || continue
    name="${name%/}"
    raw="$(basename "$name")"
    case "$raw" in
      competition-*) ;;
      eni-redteam-*-detail-pack) ;;
      *) continue ;;
    esac
    hs mkdir "$disabled"
    [ -e "$disabled/$raw" ] && rm -rf "$disabled/$raw"
    mv "$name" "$disabled/$raw" 2>/dev/null || continue
    moved=$((moved + 1))
  done
  [ "$moved" -gt 0 ] && hs_log "Context-trimmed skills moved to skills-disabled: $moved items"
}

# ---------- dsh-prompt-inject.json 辅助 ----------

# stdin → JSON 字符串字面量（含首尾引号）。文本里可能带引号/反斜杠/换行/制表符，
# 交给 node 转义不方便（值嵌在 templates[i].text 里），这里用 awk 逐行转义。
dsh_json_str() {
  awk '
    BEGIN { printf "\"" }
    {
      if (NR > 1) printf "\\n"
      line = $0
      gsub(/\\/, "\\\\", line)
      gsub(/"/, "\\\"", line)
      gsub(/\t/, "\\t", line)
      gsub(/\r/, "", line)
      printf "%s", line
    }
    END { print "\"" }
  '
}

# 取出 <cfg> 顶层 templates 数组，丢掉 id 落在 <排除列表> 里的元素，
# 其余压成「一行一个 JSON 对象」输出。
# 退出码 3 = 文件不是合法 JSON 对象（调用方决定兜底策略，对齐 PS 的 try/catch）。
dsh_tpl_items() {
  local cfg="$1" excl="$2"
  [ -f "$cfg" ] || return 0
  awk -v excl=" $excl " '
    function compact(s,   n, i, c, out, instr, esc) {
      n = length(s); out = ""; instr = 0; esc = 0
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (instr) {
          out = out c
          if (esc) esc = 0
          else if (c == "\\") esc = 1
          else if (c == "\"") instr = 0
          continue
        }
        if (c == "\"") { instr = 1; out = out c; continue }
        if (c == " " || c == "\t" || c == "\n" || c == "\r") continue
        out = out c
      }
      return out
    }
    function topval(s, key,   n, i, c, j, cc, e, k, v, w, cw, dd, ws) {
      n = length(s); i = 1; d = 0
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == "\"") {
          j = i + 1; e = 0
          while (j <= n) {
            cc = substr(s, j, 1)
            if (e) e = 0
            else if (cc == "\\") e = 1
            else if (cc == "\"") break
            j++
          }
          k = j + 1
          while (k <= n) { ws = substr(s, k, 1); if (ws == " " || ws == "\t" || ws == "\n" || ws == "\r") k++; else break }
          if (d == 1 && substr(s, k, 1) == ":" && substr(s, i + 1, j - i - 1) == key) {
            v = k + 1
            while (v <= n) { ws = substr(s, v, 1); if (ws == " " || ws == "\t" || ws == "\n" || ws == "\r") v++; else break }
            if (substr(s, v, 1) == "\"") {
              w = v + 1; e = 0
              while (w <= n) {
                cw = substr(s, w, 1)
                if (e) e = 0
                else if (cw == "\\") e = 1
                else if (cw == "\"") break
                w++
              }
              return substr(s, v + 1, w - v - 1)
            }
            w = v; dd = 0
            while (w <= n) {
              cw = substr(s, w, 1)
              if (cw == "{" || cw == "[") dd++
              else if (cw == "}" || cw == "]") { if (dd == 0) break; dd-- }
              else if (cw == "," && dd == 0) break
              w++
            }
            return substr(s, v, w - v)
          }
          i = j + 1
          continue
        }
        if (c == "{" || c == "[") d++
        else if (c == "}" || c == "]") d--
        i++
      }
      return ""
    }
    { text = text $0 "\n" }
    END {
      n = length(text)
      i = 1
      while (i <= n) { c = substr(text, i, 1); if (c == " " || c == "\t" || c == "\n" || c == "\r") i++; else break }
      if (substr(text, i, 1) != "{") exit 3
      d = 0; i = 1; vs = 0
      while (i <= n) {
        c = substr(text, i, 1)
        if (c == "\"") {
          j = i + 1; e = 0
          while (j <= n) {
            cc = substr(text, j, 1)
            if (e) e = 0
            else if (cc == "\\") e = 1
            else if (cc == "\"") break
            j++
          }
          k = j + 1
          while (k <= n) { ws = substr(text, k, 1); if (ws == " " || ws == "\t" || ws == "\n" || ws == "\r") k++; else break }
          if (d == 1 && substr(text, k, 1) == ":" && substr(text, i + 1, j - i - 1) == "templates") {
            v = k + 1
            while (v <= n) { ws = substr(text, v, 1); if (ws == " " || ws == "\t" || ws == "\n" || ws == "\r") v++; else break }
            vs = v
            break
          }
          i = j + 1
          continue
        }
        if (c == "{" || c == "[") d++
        else if (c == "}" || c == "]") d--
        i++
      }
      if (vs == 0 || substr(text, vs, 1) != "[") exit 0
      i = vs + 1
      while (i <= n) {
        while (i <= n) { c = substr(text, i, 1); if (c == " " || c == "\t" || c == "\n" || c == "\r" || c == ",") i++; else break }
        if (i > n || substr(text, i, 1) == "]") break
        st = i; dd = 0; instr = 0; esc = 0; j = i
        while (j <= n) {
          cc = substr(text, j, 1)
          if (instr) {
            if (esc) esc = 0
            else if (cc == "\\") esc = 1
            else if (cc == "\"") instr = 0
            j++
            continue
          }
          if (cc == "\"") { instr = 1; j++; continue }
          if (cc == "{" || cc == "[") { dd++; j++; continue }
          if (cc == "}" || cc == "]") { dd--; j++; if (dd == 0) break; continue }
          if (cc == "," && dd == 0) break
          j++
        }
        jend = (substr(text, j, 1) == ",") ? j - 1 : j
        item = substr(text, st, jend - st + 1)
        citem = compact(item)
        idv = topval(citem, "id")
        if (idv == "" || index(excl, " " idv " ") == 0) print citem
        i = jend + 1
      }
    }
  ' "$cfg"
}

# 写入/更新一个注入模板：已存在同名 id 就覆盖内容，其他模板与 sessions 原样保留。
# $1=cfg $2=模板 id $3=模板名 $4=模板文本文件 $5=是否设为默认(1/0)
dsh_prompt_inject_upsert() {
  local cfg="$1" tid="$2" tname="$3" tfile="$4" make_default="$5"
  local items new_obj sess dflt
  items="$(hs_tmp)/dsh-tpl-items.txt"
  : >"$items"
  # 同名 id 先丢掉，再把新对象追加到末尾（等价于 PS 的 upsert）。
  # cfg 不是合法 JSON 时 dsh_tpl_items 退出码为 3（对齐 PS 把坏文件当没有），这里忽略。
  dsh_tpl_items "$cfg" "$tid" >>"$items" || :
  new_obj="{\"id\":$(printf '%s' "$tid" | dsh_json_str),\"name\":$(printf '%s' "$tname" | dsh_json_str),\"text\":$(dsh_json_str <"$tfile"),\"order\":1}"
  printf '%s\n' "$new_obj" >>"$items"
  # json-array-of-objects 只替换 templates 键，sessions / 其他键不动
  hs json-array-of-objects "$cfg" "$TPL_KEY" <"$items" || hs_die "写入 $cfg 失败"
  sess="$(hs_json_get "$cfg" sessions)"
  [ -n "$sess" ] || sess='{}'
  hs_json_set "$cfg" sessions "$sess"
  dflt="$(hs_json_get "$cfg" defaultTemplate)"
  if [ -z "$dflt" ] && [ "$make_default" = 1 ]; then dflt="$tid"; fi
  hs_json_set "$cfg" defaultTemplate "$dflt"
}

# 卸载：只摘掉本包注册的模板，用户自建模板保留；defaultTemplate 指向本包模板则清空
dsh_prompt_inject_clean() {
  local cfg="$1" items sess dflt
  items="$(hs_tmp)/dsh-tpl-items.txt"
  if ! dsh_tpl_items "$cfg" "$TPL_ID_MAIN $TPL_ID_COFFEE" >"$items"; then
    hs_log "Failed to clean dsh-prompt-inject.json, left as-is"
    return 0
  fi
  hs json-array-of-objects "$cfg" "$TPL_KEY" <"$items" || {
    hs_log "Failed to clean dsh-prompt-inject.json, left as-is"
    return 0
  }
  sess="$(hs_json_get "$cfg" sessions)"
  [ -n "$sess" ] || sess='{}'
  hs_json_set "$cfg" sessions "$sess"
  dflt="$(hs_json_get "$cfg" defaultTemplate)"
  case "$dflt" in
    "$TPL_ID_MAIN" | "$TPL_ID_COFFEE") dflt='' ;;
  esac
  hs_json_set "$cfg" defaultTemplate "$dflt"
  hs_log "Removed kit templates from dsh-prompt-inject.json"
}

# 懒人包模式的非技能文件部署（shield 载荷 + 注入模板）。
# 每个文件首次部署前备份进 managed-prompts，卸载时还原。
# 注意：shield 的备份顺序照抄 PS 原脚本（先 Copy 覆盖、再备份），
# 也就是说 shield-protocol.md 的 .bak 存的是刚部署的载荷而不是原文件 ——
# 这里保持对等，不改语义。
dsh_install_kit_files() {
  local out="$1"
  : >"$out"
  cp -f "$SHIELD_SRC" "$SHIELD_DST" || hs_die "复制 shield-protocol.md 失败"
  printf '%s\n' 'shield-protocol.md' >>"$out"
  [ -f "$SHIELD_BAK" ] || cp -f "$SHIELD_DST" "$SHIELD_BAK"
  if [ -f "$INJECT_DST" ]; then
    [ -f "$INJECT_BAK" ] || cp -f "$INJECT_DST" "$INJECT_BAK"
  fi
  cp -f "$INJECT_SRC" "$INJECT_DST" || hs_die "复制 prompt-inject.md 失败"
  printf '%s\n' 'prompt-inject.md' >>"$out"
  if [ -f "$INJECT_CFG" ] && [ ! -f "$CFG_BAK" ]; then
    cp -f "$INJECT_CFG" "$CFG_BAK"
  fi
  dsh_prompt_inject_upsert "$INJECT_CFG" "$TPL_ID_MAIN" 'pojia' "$INJECT_SRC" 1
  printf '%s\n' 'dsh-prompt-inject.json' >>"$out"
  if [ -f "$COFFEE_SRC" ] && [ -f "$INJECT_CFG" ]; then
    dsh_prompt_inject_upsert "$INJECT_CFG" "$TPL_ID_COFFEE" '冷咖啡' "$COFFEE_SRC" 0
  fi
}

# ---------- 提示词与状态路径 ----------

STATE_PATH="$MANAGED_DIR/install-state.json"

# 读上一次安装的状态：技能清单（决定卸载/清理要收哪些技能）
PREV_SKILLS="$(hs_state_list "$STATE_PATH" "$SKILLS_MANIFEST_KEY")"

# ---------- 卸载 ----------

if hs_flag -Uninstall; then
  TMPD="$(hs_tmp)"

  # 0. 重复卸载兜底：上一次卸载如果在清理途中失败，状态文件可能已丢，
  # 但 marker 还在 —— 此时按「随包分发的技能 ∩ 技能目录里存在的」重建清单，
  # 否则残留的技能与包文件再也没人认领（点第二次「卸载」也清不掉）。
  if [ -z "$PREV_SKILLS" ]; then
    dsh_shipped_names >"$TMPD/dsh-shipped.txt"
    : >"$TMPD/dsh-leftover.txt"
    while IFS= read -r nm; do
      [ -n "$nm" ] || continue
      [ -e "$SKILLS_TARGET/$nm" ] && printf '%s\n' "$nm" >>"$TMPD/dsh-leftover.txt"
    done <"$TMPD/dsh-shipped.txt"
    if [ -s "$TMPD/dsh-leftover.txt" ]; then
      PREV_SKILLS="$(cat "$TMPD/dsh-leftover.txt")"
      hs_log "Recovered skill inventory from disk: $(wc -l <"$TMPD/dsh-leftover.txt" | tr -d ' ') items"
    fi
  fi

  # 1. 恢复/删除注入的提示词
  CUR_TEXT=''
  [ -f "$AGENTS_MD" ] && CUR_TEXT="$(hs_read "$AGENTS_MD")"
  # $CUR_IS_KIT 必须取自「覆盖前的原文」，第 2 步的包文件处理全靠它
  CUR_IS_KIT=0
  case "$CUR_TEXT" in *"pack=$KIT_NAME"*) CUR_IS_KIT=1 ;; esac

  if [ -f "$BACKUP_PATH" ]; then
    cp -f "$BACKUP_PATH" "$AGENTS_MD" || hs_die "还原 AGENTS.md 失败"
    rm -f "$BACKUP_PATH"
    hs_log "Restored original AGENTS.md"
  elif hs_has_block "$AGENTS_MD" "$HS_INJ_BEGIN" "$HS_INJ_END"; then
    rm -f "$AGENTS_MD"
    hs_log "Removed injected AGENTS.md"
  else
    hs_log "No injection found, nothing to do"
  fi

  # 2. 懒人包专属文件：仅当当前注入的确实是懒人包时处理
  if [ "$CUR_IS_KIT" = 1 ]; then
    if [ -f "$SHIELD_BAK" ]; then
      cp -f "$SHIELD_BAK" "$SHIELD_DST" || hs_die "还原 shield-protocol.md 失败"
      rm -f "$SHIELD_BAK"
      hs_log "Restored original shield-protocol.md"
    elif [ -f "$SHIELD_DST" ]; then
      rm -f "$SHIELD_DST"
      hs_log "Removed shield-protocol.md"
    fi
    if [ -f "$INJECT_BAK" ]; then
      cp -f "$INJECT_BAK" "$INJECT_DST" || hs_die "还原 prompt-inject.md 失败"
      rm -f "$INJECT_BAK"
      hs_log "Restored original prompt-inject.md"
    elif [ -f "$INJECT_DST" ]; then
      rm -f "$INJECT_DST"
      hs_log "Removed prompt-inject.md"
    fi
    if [ -f "$INJECT_CFG" ]; then
      if [ -f "$CFG_BAK" ]; then
        cp -f "$CFG_BAK" "$INJECT_CFG" || hs_die "还原 dsh-prompt-inject.json 失败"
        rm -f "$CFG_BAK"
        hs_log "Restored original dsh-prompt-inject.json"
      else
        dsh_prompt_inject_clean "$INJECT_CFG"
      fi
    fi
  fi

  # 3. 删除同步安装的 skills（清单已在前面读好，这里不再依赖状态文件）
  printf '%s\n' "$PREV_SKILLS" >"$TMPD/dsh-prev-skills.txt"
  if [ -n "$PREV_SKILLS" ]; then
    REMOVED="$(dsh_remove_skills "$TMPD/dsh-prev-skills.txt" "$SKILLS_TARGET")"
    if [ -n "$REMOVED" ]; then
      hs_log "Removed managed skills: $(hs_join_commas "$REMOVED")"
    else
      hs_log "No managed skills to remove"
    fi
  else
    hs_log "No managed skills to remove"
  fi

  # 4. 落墓碑记录：全部清理跑完才写，中途出错时状态文件仍在，重跑卸载还能接着清
  rm -f "$STATE_PATH"
  MARK_OK=1
  hs_json_set "$STATE_PATH" uninstalled true || MARK_OK=0
  printf '%s\n' "$PREV_SKILLS" | hs_json_array "$STATE_PATH" "$SKILLS_MANIFEST_KEY" || MARK_OK=0
  [ "$MARK_OK" = 1 ] || hs_log "Failed to write uninstall marker, next run will recover from disk"
  exit 0
fi

# ---------- 安装 ----------

# 提示词定位放在卸载之后：卸载不需要提示词文件，PS 版把它放在前面，
# 脚本目录下没有 .md 时会让 -Uninstall 直接失败（install-claude.sh 也是先处理卸载）。
# 懒人包模式下提示词固定取包内 materials/AGENTS.md
[ "$IS_KIT" = 1 ] && SOURCE_PROMPT="$KIT_PROMPT"
if [ -z "$SOURCE_PROMPT" ]; then
  # 兜底：取仓库根下第一个 .md（glob 本身按名字排序）
  for f in "$HS_ROOT"/*.md; do
    [ -f "$f" ] || continue
    SOURCE_PROMPT="$f"
    break
  done
  [ -n "$SOURCE_PROMPT" ] || hs_die "No .md prompt file found in $HS_ROOT"
fi
[ -f "$SOURCE_PROMPT" ] || hs_die "Prompt file not found: $SOURCE_PROMPT"

hs mkdir "$DSH_HOME"
hs mkdir "$MANAGED_DIR"

# 备份原始 AGENTS.md（仅首次注入时备份），然后整体覆盖为提示词内容。
# 注意：DSH 的 AGENTS.md 是 DSH 全局记忆的唯一文件，其他工具写进去的内容
# 会一并被覆盖 —— 原文件已存进 managed-prompts，卸载即可完整还原。
CUR_AGENTS=''
if [ -f "$AGENTS_MD" ]; then
  CUR_AGENTS="$(hs_read "$AGENTS_MD")"
  CUR_IS_KIT=0
  case "$CUR_AGENTS" in *"pack=$KIT_NAME"*) CUR_IS_KIT=1 ;; esac
  if hs_has_block "$AGENTS_MD" "$HS_INJ_BEGIN" "$HS_INJ_END"; then
    if [ "$CUR_IS_KIT" != "$IS_KIT" ]; then
      # 换模式了（单文件版 <-> 懒人包版）：备份必须留「注入前的原文件」。
      # 若当前文件是上一轮注入的产物，把它写回备份等于丢掉原文件，所以只在备份
      # 不存在时才写。
      if [ ! -f "$BACKUP_PATH" ]; then
        cp -f "$AGENTS_MD" "$BACKUP_PATH"
        hs_log "Injection mode changed, recorded pre-injection backup"
      else
        hs_log "Injection mode changed, keeping original pre-injection backup"
      fi
    else
      hs_log "AGENTS.md already injected, updating content"
    fi
  elif [ ! -f "$BACKUP_PATH" ]; then
    # 只在当前文件「不是本工具注入的产物」时才存为原始备份（走到这里说明没有标记块）。
    # 少了这个判断，一旦备份被删（或前一次卸载失败），重装会把刚注入的内容写成备份，
    # 之后卸载就会「还原」成注入态、甚至当作无原始文件删掉。
    cp -f "$AGENTS_MD" "$BACKUP_PATH"
    hs_log "Backed up original AGENTS.md"
  fi
else
  hs_log "No existing AGENTS.md, creating new"
fi

# 整体覆盖：AGENTS.md 只保留注入的提示词（去 BOM + 去末尾换行，对齐 PS 的 Read-Utf8/TrimEnd）
PROMPT_TEXT="$(hs_read "$SOURCE_PROMPT")"
PROMPT_TEXT="${PROMPT_TEXT#$'\xef\xbb\xbf'}"
PROMPT_TEXT="${PROMPT_TEXT%$'\r'}"
{
  printf '%s\n' "$MARKER_BEGIN"
  printf '%s\n' "$PROMPT_TEXT"
  printf '%s\n' "$MARKER_END"
} | hs write "$AGENTS_MD" || hs_die "写入 AGENTS.md 失败: $AGENTS_MD"
hs_log "Injected prompt -> $AGENTS_MD"

# 同步安装 skills
INSTALLED_FILE="$(hs_tmp)/dsh-installed.txt"
dsh_install_skills "$INSTALLED_FILE"
INSTALLED_SKILLS="$(cat "$INSTALLED_FILE")"
if [ -n "$INSTALLED_SKILLS" ]; then
  hs_log "Installed skills: $(hs_join_commas "$INSTALLED_SKILLS")"
fi

# 清掉上一版遗留、新版技能库里已移除的技能
printf '%s\n' "$PREV_SKILLS" >"$(hs_tmp)/dsh-prev-skills.txt"
STALE="$(dsh_prune_stale_skills "$(hs_tmp)/dsh-prev-skills.txt" "$INSTALLED_FILE" "$SKILLS_TARGET")"
if [ -n "$STALE" ]; then
  hs_log "Pruned stale skills from previous version: $(hs_join_commas "$STALE")"
fi

# 懒人包模式：额外部署 shield 载荷与注入模板（非技能文件另记账）
KIT_FILES_FILE="$(hs_tmp)/dsh-kit-files.txt"
: >"$KIT_FILES_FILE"
if [ "$IS_KIT" = 1 ]; then
  dsh_install_kit_files "$KIT_FILES_FILE"
  KIT_FILES="$(cat "$KIT_FILES_FILE")"
  if [ -n "$KIT_FILES" ]; then
    hs_log "Deployed kit files: $(hs_join_commas "$KIT_FILES")"
  fi
  hs_log "提示：prompt-inject.md 与 dsh-prompt-inject.json 需装 dsh-prompt-inject 插件才注入系统提示词；AGENTS.md 与 shield-protocol.md 无需插件。"
fi

# 状态文件：每次安装整体重写（PS 版也是新建 hashtable，不合并旧键）
rm -f "$STATE_PATH"
hs_json_array "$STATE_PATH" "$SKILLS_MANIFEST_KEY" <"$INSTALLED_FILE"
if [ "$IS_KIT" = 1 ]; then
  hs_json_set "$STATE_PATH" kit true
else
  hs_json_set "$STATE_PATH" kit false
fi
hs_json_array "$STATE_PATH" kitFiles <"$KIT_FILES_FILE"
hs_json_set "$STATE_PATH" prompt "$(basename "$SOURCE_PROMPT")"
hs_log "DSH injection complete"
