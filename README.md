# aura-perf

给 agent 用的优化运行时。证据、试验、门和策略都是 Aura 值，在同一条 worldline 上 KEEP 或 ROLLBACK。被优化的是目标程序（本仓库的示例是一个链表下标扫描）。Aura 是运行时，不是被剖析的对象。

## 试一下

一条命令跑完测量、挖掘、试验、门控和报告。不需要虚拟环境，不需要 API key，不需要配置文件。需要 [Aura v0.2.0](https://github.com/cybrid-systems/aura/releases/tag/v0.2.0)（nightly `cf7353373`）。`perf` 可用时用它的 task-clock；没有二进制或没有 PMU 时改用 region timer，并在报告里写明，不把缺的计数器写成 0。

命令装上以后，**在任何目录**都能跑：

```sh
git clone https://github.com/cybrid-systems/aura-perf.git
cd aura-perf && ./bin/aura-perf install     # 链到 ~/.local/bin（可用 PREFIX 改）
aura-perf                                  # 等价于 aura-perf autotune
```

不想装也行：在 checkout 里 `./run.sh <verb>` 和 `aura-perf <verb>` 完全等价（`run.sh` 就是命令的包装）。

这个仓库只保证 v0.2.0。Aura `main` 上命名 `let` 不能重入：同一个循环第二次调用交回第一次的结果，回归来自 [#5102](https://github.com/cybrid-systems/aura/pull/5102)（`6aa43942a`），记在 [aura#5116](https://github.com/cybrid-systems/aura/issues/5116)。`aura-perf test` 会先跑 `tests/runtime_probe.aura`。探测失败时，输出里有这次的 `aura -V`、期望的 `(sum 3) (sum 7) (sum 2) = 3 21 1`，以及上游链接。解析器在下标越界时也报这一段，而不是一句落在字符串字面量上的 `string-ref: index out of bounds`。探测通过之后，其余断言照常跑；真失败仍然失败。

```sh
aura-perf
```

`aura-perf` 就是 `aura-perf autotune`。报告在 `out/report.txt`，第一行是结论，例如 `verdict intend-met=1 KEEP=3 ROLLBACK=6 speedup-x=81.25 (325ms->4ms n=5 spread=120->0ms)`。`speedup-x` 是两次 held-out 中位的比值。括号里是这两次中位（毫秒）、样本数 `n`，以及样本极差（最大减最小，`基线->优化后`）。同一台机器上基线中位会漂，极差写在结论行上。后面每个拒绝一行原因（`checksum`、`protected`、`screen-pruned`、`no-speedup`、`intend-bypass`、`misclassify` 等）。

退出码跟结论一致。`autotune` 在 `intend-met=1` 时是 0，否则非 0。`recheck` 没有 `out/evidence.json` 时非 0，并提示先跑 `aura-perf autotune`。未知动词非 0。`help`、`sysinfo`、`check` 是 0。

改 `examples/sum-scan/policy.aura` 里的 intend 或策略基因之后，用上次写下的 `out/evidence.json` 重判门，不重新剖析，也不重建 workspace：

```sh
aura-perf recheck
```

其他命令：

```sh
aura-perf help       # 动词、每条需要什么（root、PMU、哪个工具）
aura-perf sysinfo    # 这台机器的库存 → out/sysinfo.txt 和 out/sysinfo.json
aura-perf check      # 约 1 秒的 CPU / 磁盘 / 网络 / 中断差分。加长：AURA_PERF_CHECK_SEC=60 aura-perf check
aura-perf test       # aura test
```

`aura-perf help` 不需要 aura 二进制；其余动词需要 `aura` 在 PATH 上（或 `AURA_BIN` 指向它）。
`sysinfo` 和 `check` 不需要 root。DMI、`perf`、`numactl`、`dmidecode`、`bpftrace` 缺了就记 `skipped` 或 `missing`。

特有能力的清单在 [docs/capabilities.md](docs/capabilities.md)。

## 这次实测

Aura 0.2.0，x86_64。这台机器没有可用的 `perf` 二进制（`/usr/bin/perf` 不在，`scripts/find-perf.sh` 没找到能读 task-clock 的 ELF），所以没有 PMU 数字，也没有 `perf record` 样本。热点毫秒来自 region timer。`k-length` 的单次测量落到 0 ms，2 倍阈值因此没有判成 `repeated-index-walk`，class 是 `flat-hot`，热叶子仍是 `k-ref`，位点是 `bench-kernel`。

Held-out（`0..5999`，5 次中位）从 311 ms 到 11 ms，**28.27×**。`intend-met 1`（门槛至少快 10%；试验门用的是更严的 20%）。`budget-used 3`。KEEP=3（两次策略 rebind + kernel），ROLLBACK=6。

判定：

- `gene-ratio-8` ROLLBACK，`dominated`（sibling 时钟是 0，和 ratio 2 分到同一个 class）
- `gene-high-threshold` ROLLBACK，`no-actionable-site`
- `gene-drop-checksum` ROLLBACK，`intend-bypass`（基因关不掉 checksum）
- `specialize-k-ref` ROLLBACK，`protected`
- `wrong-scale` ROLLBACK，checksum 4 处不一致
- `redundant-pass` ROLLBACK，`screen-pruned`（`screen-n=800` 的基线是 5 ms，没有花 held-out）
- `linear-scan` KEEP，held-out 11 ms

`linear-scan` 的 worldline：`prefix-removed=1` `cost-moved=0`，`cleared linear-scan`，`continue 0`，`hypothesis-confirmed`。负例查询：同一热点上 `wrong-scale` 被挡住，换一个 hot-node 则不被挡住。KEEP 时 compile 计数 `world-rebuilt=0` `cascade-full=0` `body-only=2` `relower-full=1`。

`./run.sh recheck` 对这份 evidence 重判：`recheck intend-met=1 KEEP=2 ROLLBACK=6 speedup-x=… (前中位ms->后中位ms n=… spread=…)`。重判只评基因和保存下来的候选，不重放中途那次策略 rebind，所以 KEEP 比完整运行少 1。比值后面同样是两次中位、样本数和极差；evidence 里留着 `before-samples` / `after-samples`。

`./run.sh sysinfo`：`arch=x86_64`，4 CPU，1 socket，SMT 关，1 个 NUMA 节点，内存 16387328 KiB，THP `madvise`，大页 0。BIOS `skipped`（`/sys/class/dmi/id` 读不到）。`perf c2c` / `numactl` / `dmidecode` / `bpftrace` 都是 missing。IPI 的 RES / CAL / TLB 来自 `/proc/interrupts` 的实数，不是估计。`./run.sh check` 接着采样 1 秒：`cpu-class=idle`（user 3%，iowait 0%，idle 96%），磁盘扇区增量 0，这一秒的 IPI 增量是 RES=2 CAL=71 TLB=1。没有 cache-to-cache 命中数，也没有 SOL。

有 perf 的机器上，同一条路径改用各 define 的 task-clock。硬件事件 `<not supported>` 时只记名字，不写成 0。

## 这些论文里拿来用的部分

下面只记 aura-perf 收进运行时的想法。不比较、也不引用它们报告的加速比。

- [PRAGMA](https://arxiv.org/abs/2511.06345)（A Profiling-Reasoned Multi-Agent Framework for Automatic Kernel Optimization）：剖析留在循环里。CCT 和 `perf:mine` 的 class 是可查询的值，KEEP 的候选带着自己的树。
- [AutoPass](https://arxiv.org/abs/2606.20373)（Evidence-Guided LLM Agents for Compiler Performance Tuning）：不把编译器当黑盒。策略查询 CCT、位点和约束，而不是读一段工具原文。
- [ACCLAIM](https://arxiv.org/abs/2604.04238)（Agentic Code Optimization via Compiler-LLM Cooperation）：一层失败就 ROLLBACK。策略基因先判，过不了门就不花 kernel 预算。
- [KernelBrain](https://arxiv.org/abs/2608.02611)（Coarse-to-Fine, Budget-Aware Search for Agentic GPU Kernel Optimization）：先用 region timer 筛，held-out 只花在活下来的候选上。
- [KernelArc](https://arxiv.org/abs/2608.17071)（A Multi-Agent Framework for GPU Kernel Optimization）：并行 worldline。KEEP / ROLLBACK 由确定性的门决定。
- [KernelBand](https://proceedings.mlr.press/v306/ran26b.html)（KernelBand: Steering LLM-based Kernel Optimization via Hardware-Aware Multi-Armed Bandits，ICML 2026）：同一热点上失败过的想法不再重提。
- [CAKE](https://arxiv.org/abs/2608.12629)（Compiler–Agent Co-Design for Frontier Kernel Evolution）：反复失败变成负例规则和可 trial 的策略基因，不是改一段提示。
- [KernelOPT](https://arxiv.org/abs/2609.30059)（Dispatch-Aware Agentic Search for GPU Kernel Optimization）：checksum、protected、最低加速都要过。一个都不过就留下基线。
- [Astra](https://arxiv.org/abs/2509.07506)（A Multi-Agent System for GPU Kernel Performance Optimization）：测量、判定、rebind、再测，在同一次进程里。
- [STARK](https://arxiv.org/abs/2510.16996)（Strategic Team of Agents for Refining Kernels）：下一轮读的是 class、decision、reason，不是 perf 原文。
- [KernelBench](https://proceedings.mlr.press/v267/ouyang25a.html)（KernelBench: Can LLMs Write Efficient GPU Kernels?，ICML 2025）：正确性和加速一起算，`intend-met` 即此。没有 GPU，就不报 SOL。
