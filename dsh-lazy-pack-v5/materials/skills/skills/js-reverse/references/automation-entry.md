# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 自动化入口

推荐开场顺序：

1. `js-reverse_new_page` 或 `js-reverse_navigate_page` 打开页面
2. `js-reverse_list_network_requests` 看最近请求
3. `js-reverse_get_request_initiator` 找调用栈
4. `js-reverse_list_scripts` 建立脚本范围
5. `js-reverse_search_in_sources` 搜请求路径、参数名、函数名
6. 必要时 `js-reverse_break_on_xhr` 或 `js-reverse_set_breakpoint_on_text`

默认不要一上来就猜 `window`、`document`、`navigator` 该怎么补。
