# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 12-payment — 支付、订单与票务业务逻辑

| 信号 | Technique |
|---|---|
| 通用订单/金额/状态机 | [payment-logic.md](payment-logic.md) |
| 参数篡改、类型混淆、零元购 | [payment-bypass.md](payment-bypass.md) |
| 回调、异步、幂等与竞态 | [payment-callback-async.md](payment-callback-async.md) |
| 余额/quota 共享行写入、Lost Update、乐观锁冲突 | [payment-race-lost-update.md](payment-race-lost-update.md) |
| 订单邮件退信、游客查询与卡密 IDOR | [payment-email-bounce-idor.md](payment-email-bounce-idor.md) |
| 支付平台/CMS/网关指纹 | [platform-fingerprints.md](platform-fingerprints.md) |
| PHP 支付实现 | [payment-php.md](payment-php.md) |
| 订阅与续费 | [payment-subscription.md](payment-subscription.md) |
| 数字商品/IAP | [payment-digital-goods.md](payment-digital-goods.md) |
| 抢票、project/screen/SKU、prepare/create、ptoken/ctoken | [ticket-rush-api-reversing.md](ticket-rush-api-reversing.md) |

白盒参考源码固定在 `../../sources/`，Technique 只保留可复用模型和验证步骤。
