# Roadmap

定位见 [capabilities.md](capabilities.md)。aura-perf 是 agent 的优化运行时：证据、假设、门和审计都是 Aura 值。被优化的是用户的程序（本仓库示例是一个链表扫描），不是 Aura 解释器。

## 现在

`perf:autotune` 对示例目标跑完一轮：perf 测量 define 级 task-clock，建成 CCT，策略调用 `perf:mine`，保护边界拒绝改叶子，并行 trial 两条会失败的假设，KEEP 线性扫描，再采一棵树做差分。硬件 PMU 不在的机器上用软件事件，并写明哪些事件 `<not supported>`。

## 接着做

1. 每个 worldline 一棵 CCT。查询「哪次 mutation 去掉了同一条热前缀，且代价没有挪到别的 define」。差分记在该候选的 evo 证据里。
2. 负例按 `class` + `hot-node` 检索，而不只丢掉同名 id。同一热点不再原样重提。
3. 分类阈值和 catalog 顺序收成可 trial 的策略基因，和 kernel 走同一套 KEEP / ROLLBACK。
4. intend 变成运行时规范：checksum、最低加速、protected 都不能被策略改掉。

## 再往后

- 语义火焰：节点可以是策略阶段或规则，agent 用它优化 harness，而不是只看用户 define。
- 增量编译计数进门控，确认一次 rebind 没有整包重编。
- KernelBench 式算子和 [aura-kernel-sink](https://github.com/cybrid-systems/aura-kernel-sink) 的 C 下沉，作为一种假设接进 autotune。契约和 checksum 仍然先于计时。没有 GPU 就不报 SOL 分数。
- Warpline 一类 trace 作为另一种 CCT 来源，填同一套 `perf:cct-*` 查询。不另做给人看的报告。

[aura-harness](https://github.com/cybrid-systems/aura-harness) / [hephaestus](https://github.com/cybrid-systems/hephaestus) 的多角色循环，是上面第 3 步的宿主，不是另一套外层 Python。

## 不做

- 不在这里改 Aura。v0.2.0 上的行为记在 [findings.md](findings.md)。
- 不安装 LLVM。
- 不做火焰图、HTML 报告、审批网页。
- 不把 perf script 原文交给模型。默认 proposer 是规则；LLM 插口必须返回和规则相同的候选 hash。
