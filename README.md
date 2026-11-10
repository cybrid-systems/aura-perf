# aura-perf

给 agent 用的优化运行时。剖析和调优是 Aura workspace 里的程序：证据是可查询的值，假设是可 trial 的候选，KEEP / ROLLBACK 和审计在同一条 worldline 上。不是给人看的 profiler，也不生成火焰图。

被优化的是目标程序。这个仓库的示例是一个链表下标扫描。Aura 是这个过程跑在上面的 runtime，不是被剖析的对象。

特有能力写在 [docs/capabilities.md](docs/capabilities.md)。

## 跑示例

需要 [Aura v0.2.0](https://github.com/cybrid-systems/aura/releases/tag/v0.2.0)。不需要 LLVM，不需要模型 key。Linux `perf` 用发行版的 `linux-tools` 二进制（`/usr/bin/perf` 在内核版本对不上时会拒绝；`scripts/find-perf.sh` 会找 `/usr/lib/linux-tools/*/perf`）。

```sh
sh scripts/run-example.sh
aura test
```

`perf:autotune` 读一份 intend（最低加速、checksum、哪些 define 不能动），自己挖热点、提假设、并行 trial，直到达标或候选用尽。

## 这次实测

Aura 0.2.0，x86_64。`perf` 是 `perf version 6.8.12`（`linux-tools-6.8.0-149-generic`），跑在内核 `6.12.113+` 上。软件事件可用。内核没有 PMU（`unsupported p6 CPU model 207 … software events only`），所以 `cycles`、`instructions`、`cache-misses`、`branches` 是 `<not supported>`，没有写成 0。选热点用的是目标程序各 define 的 `task-clock`。

`perf stat`（每个 define 单独跑 3 次，`n=4000`，含进程启动）：

| define | task-clock |
|---|---|
| `k-length` | 62.84 ms |
| `k-ref` | 294.58 ms |
| `bench-kernel`（优化前） | 317.59 ms |
| `bench-kernel`（KEEP 之后的线性扫描） | 75.86 ms |

策略调用 `perf:mine` 得到 `class=repeated-index-walk`，热叶子 `k-ref`，可改位点 `bench-kernel`，前缀 `bench-kernel>k-ref`。`k-ref` 在 intend 的 protected 列表里，`specialize-k-ref` 被拒绝，没有 trial。

随后并行 trial：

- `wrong-scale` ROLLBACK，checksum 4 处不一致
- `redundant-pass` ROLLBACK，held-out 466 ms，比基线慢
- 策略 KEEP 为只留 `linear-scan`
- `linear-scan` PASS，held-out 5 ms，kernel KEEP

Held-out（`0..5999`，5 次中位）从 162 ms 到 5 ms，**32.40x**。`intend-met 1`（门槛是至少快 10%）。`budget-used 3`。KEEP=2（策略 + kernel），ROLLBACK=3（保护边界 1 次 + 两次失败 trial）。`perf record` 对优化前的目标采了 **58** 个 `cpu-clock` 样本，样本数进 profile，解释器符号不作为热点名。

KEEP 之后同一进程再罩一次 `perf stat`：live task-clock 从 235.81 ms 降到 26.19 ms（各 3 次 `n=4000`）。CCT 差分里 `k-ref` 从后树上消失，`bench-kernel` 的 task-clock 下降 241.73 ms，于是 `hypothesis-confirmed`。

完整记录在运行后的 `out/report.txt`。
