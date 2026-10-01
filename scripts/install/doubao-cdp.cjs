"use strict";
/*
  doubao-cdp.cjs — 豆包破甲用的最小 CDP 客户端（无第三方依赖）

  为什么需要它：install-doubao.ps1 用 .NET 的 ClientWebSocket 驱动 CDP，
  bash 自己做不了 WebSocket。所以把「选目标 → 建连 → Runtime.evaluate」
  这一段下沉到 node（lib.sh 的 hs_node 已提供 node 路径）。

  自己按 RFC6455 实现最小客户端：握手 + 文本帧编解码 + 分片重组 + ping/pong，
  不引任何 npm 包（打包后只有 Electron 自带 node，装不了依赖）。

  子命令：
    target --port 9222 --wait 60 --out <file>            选对话页调试目标
    get    --port 9222 [--ws <url>] --out <file>         读云端全局记忆
    set    --port 9222 [--ws <url>] --content-file f --out <file>   整份覆盖写云端全局记忆

  输出：一个扁平 JSON 对象写到 --out（不给则打到 stdout），键固定为
    target: {ok,type,url,ws}
    get:    {ok,status,len,content,raw}     （对齐 PowerShell 里 JS 的返回结构）
    set:    {ok,status,chars,body}          （chars = 源文件 UTF-16 码元数）
  失败（连不上 CDP / 页面异常）走 stderr + 退出码 1，不编造结果。

  注意：页面级 fetch 失败不算「脚本失败」——和 PowerShell 版一致，它只把
  ok=false / status=-1 填进结果，由调用方决定怎么报。
*/

const http = require("node:http");
const crypto = require("node:crypto");
const fs = require("node:fs");

// ---------- 参数 ----------

const argv = process.argv.slice(2);
const cmd = argv[0];
const opt = { port: 9222, wait: 0, ws: "", contentFile: "", out: "" };

for (let i = 1; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--port") opt.port = parseInt(argv[++i], 10) || 9222;
  else if (a === "--wait") opt.wait = parseInt(argv[++i], 10) || 0;
  else if (a === "--ws") opt.ws = argv[++i] || "";
  else if (a === "--content-file") opt.contentFile = argv[++i] || "";
  else if (a === "--out") opt.out = argv[++i] || "";
}

function die(msg) {
  process.stderr.write(String(msg) + "\n");
  process.exit(1);
}

function emit(obj) {
  const text = JSON.stringify(obj);
  if (opt.out) {
    try {
      fs.writeFileSync(opt.out, text, "utf8");
    } catch (e) {
      die("写结果文件失败: " + e.message);
    }
  } else {
    process.stdout.write(text);
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ---------- HTTP：取 /json/list ----------

function httpGetJson(path) {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: "127.0.0.1", port: opt.port, path, timeout: 10000 },
      (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch {
            reject(new Error("非 JSON 响应: " + data.slice(0, 120)));
          }
        });
      },
    );
    req.on("timeout", () => req.destroy(new Error("HTTP 超时")));
    req.on("error", reject);
  });
}

// 目标优先级（对齐 PowerShell 的 Select-DoubaoTarget）：
//   doubao-chat/chat → doubao-launcher/chat → www.doubao.com 的 iframe → 任意 www.doubao.com
// 绝不选 doubao://doubao-background（后台页调接口只会返回 HTML）
function selectTarget(list) {
  if (!Array.isArray(list)) return null;
  const usable = list.filter((t) => t && t.url && t.webSocketDebuggerUrl);
  const pats = ["doubao-chat/chat", "doubao-launcher/chat"];
  for (const p of pats) {
    const t = usable.find((x) => x.url.includes(p));
    if (t) return t;
  }
  const iframe = usable.find((x) => x.type === "iframe" && x.url.includes("www.doubao.com"));
  if (iframe) return iframe;
  return usable.find((x) => x.url.includes("www.doubao.com")) || null;
}

async function waitForTarget(seconds) {
  const deadline = Date.now() + seconds * 1000;
  for (;;) {
    try {
      const t = selectTarget(await httpGetJson("/json/list"));
      if (t) return t;
    } catch {
      /* 端口还没通 / 还没建页面，继续等 */
    }
    if (Date.now() >= deadline) return null;
    await sleep(1000);
  }
}

// ---------- WebSocket（RFC6455 最小实现）----------

const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

function wsConnect(wsUrl) {
  return new Promise((resolve, reject) => {
    let u;
    try {
      u = new URL(wsUrl);
    } catch (e) {
      reject(new Error("webSocketDebuggerUrl 非法: " + wsUrl));
      return;
    }
    const key = crypto.randomBytes(16).toString("base64");
    const req = http.request({
      host: u.hostname,
      port: u.port || 80,
      path: (u.pathname || "/") + (u.search || ""),
      headers: {
        Connection: "Upgrade",
        Upgrade: "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": key,
        Host: u.host,
      },
    });
    req.on("upgrade", (res, socket, head) => {
      const expect = crypto
        .createHash("sha1")
        .update(key + WS_GUID)
        .digest("base64");
      if (res.headers["sec-websocket-accept"] !== expect) {
        socket.destroy();
        reject(new Error("WebSocket 握手校验失败"));
        return;
      }
      resolve({ socket, head });
    });
    req.on("response", (res) => reject(new Error("WebSocket 握手失败: HTTP " + res.statusCode)));
    req.on("error", reject);
    req.end();
  });
}

function encodeFrame(payload, opcode) {
  const data = Buffer.isBuffer(payload) ? payload : Buffer.from(String(payload), "utf8");
  const len = data.length;
  let header;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[1] = 0x80 | len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[1] = 0x80 | 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 0x80 | 127;
    header.writeUInt32BE(Math.floor(len / 4294967296), 2);
    header.writeUInt32BE(len % 4294967296, 6);
  }
  header[0] = 0x80 | (opcode || 0x1); // FIN + opcode，客户端必须带掩码
  const mask = crypto.randomBytes(4);
  const masked = Buffer.alloc(len);
  for (let i = 0; i < len; i++) masked[i] = data[i] ^ mask[i % 4];
  return Buffer.concat([header, mask, masked]);
}

// 增量帧解析器：返回 (chunk) => void，消息重组后回调 onMessage
function makeParser(send, onMessage) {
  let buf = Buffer.alloc(0);
  let frags = [];
  let fragOp = 0;
  return (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const b0 = buf[0];
      const b1 = buf[1];
      const fin = (b0 & 0x80) !== 0;
      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < off + 2) return;
        len = buf.readUInt16BE(off);
        off += 2;
      } else if (len === 127) {
        if (buf.length < off + 8) return;
        const hi = buf.readUInt32BE(off);
        const lo = buf.readUInt32BE(off + 4);
        len = hi * 4294967296 + lo;
        off += 8;
      }
      let maskKey = null;
      if (masked) {
        if (buf.length < off + 4) return;
        maskKey = buf.slice(off, off + 4);
        off += 4;
      }
      if (buf.length < off + len) return;
      let payload = buf.slice(off, off + len);
      buf = buf.slice(off + len);
      if (maskKey) {
        const p = Buffer.alloc(len);
        for (let i = 0; i < len; i++) p[i] = payload[i] ^ maskKey[i % 4];
        payload = p;
      }
      if (opcode === 0x9) {
        // ping → pong（同 payload）
        send(encodeFrame(payload, 0xa));
        continue;
      }
      if (opcode === 0xa) continue; // pong
      if (opcode === 0x8) {
        onMessage({ type: "close" });
        return;
      }
      if (opcode === 0x0) {
        frags.push(payload);
      } else {
        fragOp = opcode;
        frags = [payload];
      }
      if (fin) {
        const full = Buffer.concat(frags);
        frags = [];
        onMessage({ type: "message", opcode: fragOp, text: full.toString("utf8") });
      }
    }
  };
}

// Runtime.evaluate 一次，返回页面里表达式的值（awaitPromise + returnByValue）
function evaluate(wsUrl, expression, timeoutMs) {
  return wsConnect(wsUrl).then(
    ({ socket, head }) =>
      new Promise((resolve, reject) => {
        let done = false;
        const timer = setTimeout(() => {
          finish(reject, new Error("CDP 响应超时"));
        }, timeoutMs);
        function finish(fn, v) {
          if (done) return;
          done = true;
          clearTimeout(timer);
          try {
            socket.destroy();
          } catch {
            /* ignore */
          }
          fn(v);
        }
        const send = (buf) => socket.write(buf);
        const parse = makeParser(send, (msg) => {
          if (msg.type === "close") {
            finish(reject, new Error("CDP 连接被关闭"));
            return;
          }
          if (msg.type !== "message") return;
          let m;
          try {
            m = JSON.parse(msg.text);
          } catch {
            return;
          }
          if (!m || m.id !== 1) return;
          if (m.error) {
            finish(reject, new Error("CDP 错误: " + JSON.stringify(m.error)));
            return;
          }
          const r = m.result || {};
          if (r.exceptionDetails) {
            const d = r.exceptionDetails;
            finish(
              reject,
              new Error(
                "页面异常: " +
                  (d.text || "") +
                  " / " +
                  ((d.exception && d.exception.description) || ""),
              ),
            );
            return;
          }
          finish(resolve, r.result ? r.result.value : undefined);
        });
        socket.on("data", parse);
        socket.on("error", (e) => finish(reject, e));
        socket.on("close", () => finish(reject, new Error("CDP 连接提前关闭")));
        if (head && head.length) parse(head);
        send(
          encodeFrame(
            JSON.stringify({
              id: 1,
              method: "Runtime.evaluate",
              params: {
                expression,
                awaitPromise: true,
                returnByValue: true,
                userGesture: true,
                timeout: timeoutMs,
              },
            }),
          ),
        );
      }),
  );
}

// ---------- 页面内脚本（与 PowerShell 版逐字对齐）----------

const JS_GET = `(async()=>{
  try {
    const r = await fetch("https://www.doubao.com/alice/generaltask/memory/get_agentsmd", {method:"POST",
      headers:{"content-type":"application/json"}, body:"{}", credentials:"include"});
    const txt = await r.text();
    let j = null; try { j = JSON.parse(txt); } catch(e) {}
    const c = (j && j.data && j.data.content) || "";
    return JSON.stringify({ok: r.status === 200 && !!j, status: r.status, len: c.length,
                           content: c, raw: j ? "" : txt.slice(0, 200)});
  } catch(e) { return JSON.stringify({ok:false, status:-1, len:0, content:"", raw:"ERR "+e.message}); }
})()`;

function jsSet(b64) {
  return `(async()=>{
  try {
    const content = new TextDecoder().decode(Uint8Array.from(atob("${b64}"), c=>c.charCodeAt(0)));
    const r = await fetch("https://www.doubao.com/alice/generaltask/memory/set_agentsmd", {method:"POST",
      headers:{"content-type":"application/json"}, body: JSON.stringify({content}), credentials:"include"});
    const t = await r.text();
    return JSON.stringify({status: r.status, body: t.slice(0, 300)});
  } catch(e) { return JSON.stringify({status:-1, body:"ERR "+e.message}); }
})()`;
}

// ---------- 主流程 ----------

const TIMEOUT_MS = 120000;

async function resolveWs() {
  if (opt.ws) return opt.ws;
  const t = await waitForTarget(opt.wait);
  if (!t) {
    die(
      "等不到豆包对话页的调试目标（" +
        opt.wait +
        " 秒）：端口 " +
        opt.port +
        " 上没有 www.doubao.com / doubao-chat 目标，确认豆包已登录并打开主界面",
    );
  }
  return t.webSocketDebuggerUrl;
}

async function main() {
  if (cmd === "target") {
    const t = await waitForTarget(opt.wait);
    if (!t) {
      die("等不到豆包对话页的调试目标（" + opt.wait + " 秒）");
    }
    emit({ ok: true, type: t.type || "", url: t.url || "", ws: t.webSocketDebuggerUrl });
    return;
  }

  if (cmd === "get") {
    const ws = await resolveWs();
    const raw = await evaluate(ws, JS_GET, TIMEOUT_MS);
    let j;
    try {
      j = JSON.parse(raw);
    } catch {
      die("页面返回不是 JSON: " + String(raw).slice(0, 200));
    }
    emit({
      ok: !!j.ok,
      status: typeof j.status === "number" ? j.status : -1,
      len: typeof j.len === "number" ? j.len : 0,
      content: j.content || "",
      raw: j.raw || "",
    });
    return;
  }

  if (cmd === "set") {
    if (!opt.contentFile) die("set 需要 --content-file");
    let b64;
    let chars = 0;
    try {
      // 先按 utf8 读一次拿字符数：JS 的 String.length 与 PowerShell 的 .Length
      // 同为 UTF-16 码元数，中文提示词用字节数会对不上
      const text = fs.readFileSync(opt.contentFile, "utf8");
      chars = text.length;
      b64 = Buffer.from(text, "utf8").toString("base64");
    } catch (e) {
      die("读内容文件失败: " + e.message);
    }
    const ws = await resolveWs();
    const raw = await evaluate(ws, jsSet(b64), TIMEOUT_MS);
    let j;
    try {
      j = JSON.parse(raw);
    } catch {
      die("页面返回不是 JSON: " + String(raw).slice(0, 200));
    }
    emit({
      ok: true,
      status: typeof j.status === "number" ? j.status : -1,
      chars,
      body: j.body || "",
    });
    return;
  }

  die("未知子命令: " + String(cmd) + "（可用 target / get / set）");
}

main().catch((e) => die(e && e.message ? e.message : String(e)));
