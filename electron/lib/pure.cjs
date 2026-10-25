"use strict";
/*
  纯函数模块（无 Electron / 无全局状态），从 main.cjs 抽出来，唯一目的是可单测。

  由 ../main.cjs 通过 require("./lib/pure.cjs") 使用；
  由 ../../tools/verify-fixes.mjs 直接 require 做回归测试。
*/

/**
   判断一段字节是否是合法 UTF-8。

   注意末尾最多 3 个字节可能是被 chunk 边界切断的多字节字符（中文一个字 3 字节），
   直接丢给 fatal 解码器会误判成「不是 UTF-8」，所以判定前先截掉不完整的尾巴。
*/
function sniffUtf8(buf) {
  let end = buf.length;
  for (let i = buf.length - 1; i >= Math.max(0, buf.length - 4); i--) {
    const b = buf[i];
    if ((b & 0xc0) === 0x80) continue; // 续字节，继续往前找首字节
    if ((b & 0x80) === 0) break; // ASCII，结尾完整
    const need = b >= 0xf0 ? 4 : b >= 0xe0 ? 3 : 2;
    if (buf.length - i < need) end = i;
    break;
  }
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(buf.subarray(0, end));
    return true;
  } catch {
    return false;
  }
}

/**
   流式控制台解码器。

   原版每收到一个 chunk 就把累积的全部字节重新解码一遍（O(n²)），
   30 分钟的 Seep 部署输出几十 MB 时主进程会明显卡顿。
   这里：头 4 KB 嗅探一次编码，之后用同一个 TextDecoder 以 stream 模式增量解码。
*/
function createConsoleDecoder() {
  let impl = null;
  let pending = [];
  let pendingLen = 0;

  /** 判定编码，返回攒下来的原始字节。 */
  const settle = () => {
    const head = Buffer.concat(pending);
    pending = [];
    pendingLen = 0;
    impl = sniffUtf8(head) ? new TextDecoder("utf-8") : new TextDecoder("gbk");
    return head;
  };

  return {
    push(buf) {
      if (impl) return impl.decode(buf, { stream: true });
      pending.push(buf);
      pendingLen += buf.length;
      if (pendingLen < 4096) return ""; // 样本太少，先攒着
      const head = settle();
      return impl.decode(head, { stream: true });
    },
    /** 收尾：把 stream 里残留的半个字符吐出来。 */
    end() {
      try {
        if (!impl) {
          const head = settle(); // settle() 内部会设置 impl
          return impl.decode(head);
        }
        return impl.decode();
      } catch {
        return "";
      }
    },
  };
}

/**
   从 config.toml 文本里删掉所有 [[skills.config]] 块（含正文）。

   原版写法：
     text.replace(/^\[\[skills\.config\]\]\s*$[\s\S]*?(?=^\[\[|$)/gm, "")
   lookahead 里的 $ 在 m 标志下匹配「任意行尾」，非贪婪量词一遇到行尾就停下，
   结果只删掉了表头这一行，正文 path= / enabled= 全部留下，
   变成上一张表的成员 —— 用户点一次「保存技能开关」就把 config.toml 写坏了。

   这里改成按行切块：命中表头进入跳过态，遇到下一个以 [ 开头的行退出跳过。
*/
function stripSkillBlocks(text) {
  const out = [];
  let skipping = false;
  for (const line of String(text == null ? "" : text).split(/\r?\n/)) {
    if (/^\[\[skills\.config\]\]\s*$/.test(line)) {
      skipping = true;
      continue;
    }
    if (skipping && /^\s*\[/.test(line)) skipping = false;
    if (!skipping) out.push(line);
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").replace(/\s+$/, "") + "\n";
}

/** 拼出一段 [[skills.config]] 块（路径用 JSON.stringify 转义，天然是合法 TOML 基本字符串）。 */
function skillBlock(skillPath, enabled) {
  return `\n[[skills.config]]\npath = ${JSON.stringify(String(skillPath).replace(/\\/g, "/"))}\nenabled = ${
    enabled ? "true" : "false"
  }\n`;
}

module.exports = { sniffUtf8, createConsoleDecoder, stripSkillBlocks, skillBlock };
