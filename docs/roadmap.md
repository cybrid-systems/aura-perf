# Roadmap

定位见 [capabilities.md](capabilities.md)。aura-perf 是 agent 的优化运行时：证据、假设、门和审计都是 Aura 值。被优化的是用户的程序（本仓库示例是一个链表扫描），不是 Aura 解释器。

## 现在

`./run.sh autotune` 跑完一轮。每个 worldline 有一棵 CCT，可以查询哪次 mutation 去掉了同一条热前缀且没有把代价挪走。负例按 `class` + `hot-node` 记住。分类阈值和 catalog 顺序是策略基因，走 KEEP / ROLLBACK。intend 封在门里。没有 perf 二进制时 CCT 用 region timer 的毫秒，并写明硬件计数器没有读。`./run.sh sysinfo` 和 `./run.sh check` 把这台机器的 CPU、内存、NUMA、中断和工具有无收成可查询的值。

## 接着做

- 语义火焰：节点可以是策略阶段或规则。
- `perf c2c` / `perf mem` / `perf sched` 现在只探测子命令在不在。PMU 可用时才采样，并仍不把缺测写成 0。
- bpftrace / bcc 只在已经安装时登记，不附带脚本。
- 机器层建议的跨次负例（现在的负例记的是同一次 autotune 里的程序热点）。
- KernelBench 式算子和 [aura-kernel-sink](https://github.com/cybrid-systems/aura-kernel-sink) 的 C 下沉，作为一种假设接进 autotune。没有 GPU 就不报 SOL。
- Warpline 一类 trace 作为另一种 CCT 来源。

[aura-harness](https://github.com/cybrid-systems/aura-harness) / [hephaestus](https://github.com/cybrid-systems/hephaestus) 的多角色循环，是策略基因的宿主，不是另一套外层 Python。

增量编译计数已经写进 KEEP 的证据（`world-rebuilt`、`cascade-full`、`body-only`）。示例里 `world-rebuilt=0`。它还不是一道失败就打回正确加速的门。

## 不做

- 不在这里改 Aura。v0.2.0 上的行为记在 [findings.md](findings.md)。
- 不安装 LLVM。
- 不做火焰图、HTML 报告、审批网页。
- 不把 perf script 原文交给模型。默认 proposer 是规则；LLM 插口必须返回和规则相同的候选 hash。
