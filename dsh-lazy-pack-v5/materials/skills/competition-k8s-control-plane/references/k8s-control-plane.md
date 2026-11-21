# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# K8s Control Plane Checklist

## First Pass

- Namespaces, service accounts, kubeconfigs, tokens, Roles, ClusterRoles, bindings
- Admission webhooks, mutating or validating policy, controllers, operators, CRDs
- Secrets, ConfigMaps, projected volumes, generated Jobs, and owner references

## Trust Chain To Reconstruct

1. Principal or token identified
2. RBAC or admission edge established
3. Object create, patch, or read action performed
4. Controller or scheduler turns object into workload state
5. Secret, route, workload, or artifact effect observed

## Evidence To Keep Together

- Principal side: service account, token source, namespace, binding, verb, resource
- Mutation side: object manifest, admission change, controller output, owner refs
- Effect side: mounted secret, env var, spawned pod, reachable route, or recovered artifact

## Common Pitfalls

- Stopping at a RoleBinding without proving the resulting API action
- Explaining pod behavior without showing which cluster object created it
- Mixing static YAML and live cluster objects without accounting for admission or controller drift
