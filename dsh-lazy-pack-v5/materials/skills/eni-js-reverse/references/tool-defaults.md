# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 工具默认值

- `js-reverse_list_network_requests`：先看第一页默认结果，不足再翻页
- `js-reverse_search_in_sources`：默认 `excludeMinified=true`
- `js-reverse_get_script_source`：只读小片段，整份源码优先配合 `js-reverse_save_script_source`
- `js-reverse_break_on_xhr`：只填能稳定命中的 URL 片段
- `js-reverse_get_paused_info`：默认先看 `frameIndex=0`
