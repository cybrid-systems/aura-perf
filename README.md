# aura-perf

Aura 上的 agent-native 性能优化工作流。优化过程跑在 Aura workspace 里：profiler 证据是可查询的数据，候选是对可变 `define` 的 mutation，在 forked worldline 上做正确性校验和 held-out 计时，过门才 `KEEP`，否则按 snapshot 精确 `ROLLBACK`，全过程进 `evo` 审计日志。

这不是另一个“写 CUDA 的 agent”。CPU 闭环先跑通；GPU / kernel 在 [docs/roadmap.md](docs/roadmap.md)。

## 这个 MVP 做什么

- 把 Linux `perf`（没有就退到 region timer、`/proc/self/stat` 和 `engine:metrics`）收成 Aura 结构，用 `perf:hotspots`、`perf:stacks`、`perf:counters`、`perf:delta` 查询。`gprof` 文本也能解析；没有 `gmon.out` 时不会假装跑过。
- 候选由可替换的 proposer 产生。默认是确定性的 `perf:rule-propose`。`perf:llm-propose` 是接口，不联网、不读 API key。
- 每个候选在子进程里用 `evo:trial` 做 forked worldline。父进程的 workspace 指纹在 trial 期间不变。
- 评分只用 held-out 输入（`range(6000)` 的中位耗时）。正确性是和 workspace 外面的 oracle 做 checksum。门限是至少快 20%。
- 策略本身是 workspace 里的 `perf-strategy`。失败的 mutation 会从它的源码里删掉，再 `KEEP` 这条策略，然后才允许改 kernel。
- 同一轮的多个候选用 `orch:parallel` 起子进程。

## 运行

需要 [Aura v0.2.0](https://github.com/cybrid-systems/aura/releases/tag/v0.2.0)（`aura` 在 `PATH` 上，或设置 `AURA_BIN`）。不需要 LLVM，不需要模型 key。

Forked worldline 里的 `mutate:rebind` 在 `preset=dev` 的 restricted sandbox 下会被 `cow-refused`。脚本会设 `AURA_SANDBOX=off`。见 [docs/findings.md](docs/findings.md)。

```sh
sh scripts/run-example.sh
aura test
```

示例是 `examples/sum-scan`：对一条链表做下标求和（每次 `list-ref` 都从头走）。策略先看到热点 `k-ref`，按源码里的顺序试两个坏候选，再把策略改成只留线性扫描。

## 实测（Aura 0.2.0，x86_64，无 perf）

Held-out 是 `0..5999` 求和，5 次取中位。同一次运行里：

| | 中位耗时 | 样本 (ms) |
|---|---|---|
| 优化前 `bench-kernel` | 160 ms | 159, 160, 160, 159, 160 |
| `wrong-scale` | 未计时 | checksum 4 处不一致，ROLLBACK |
| `redundant-pass` | 468 ms | 正确但更慢，ROLLBACK |
| `linear-scan` KEEP 之后 | 5 ms | 5, 6, 5, 6, 5 |

加速比 **32.00x**（160/5）。决策 **KEEP=2**（策略一次、kernel 一次）、**ROLLBACK=2**。Trial 期间 live fingerprint 不变。Profile 上 `bench-kernel` 从 71 ms 到 4 ms，没被改写的 `k-ref` 仍是 79 ms。

同一台机器再跑一次是 159 ms → 5 ms（31.80x），KEEP/ROLLBACK 仍是 2/2。

`perf` 不在 `PATH` 上（`perf_event_paranoid=2`），这次的热点来自 region timer，计数器来自 `/proc/self/stat` 和 `engine:metrics`。第一轮两个候选的 trial 耗时是 3 ms 和 2830 ms，`orch:parallel` 的墙钟是 2977 ms，跟慢的那次走，没有把两次相加。

完整记录在运行后的 `out/report.txt`。上面这次的正文：

```
aura-perf sum-scan
tools perf=missing gprof=/usr/bin/gprof gmon=no-gmon paranoid=2
note perf: binary not on PATH; workload counters fall back to /proc self stat and engine:metrics
note gprof: binary present, no gmon.out in the working directory; gprof was not applied to this run
note hotspots: independently timed regions (monotonic-ms). Shares are of that sum, not a hardware sample.
note stacks: caller chains declared with each region, not a sampled stack trace.
hotspot k-ref self-ms=79 calls=4000 share=52 source=region-timer stack=bench-kernel>k-ref
hotspot bench-kernel self-ms=71 calls=1 share=47 source=region-timer stack=bench-kernel
hotspot k-length self-ms=0 calls=1 share=0 source=region-timer stack=bench-kernel>k-length
counter eval.hotpath_eval_flat_calls=187894
counter jit.jit_deopt_on_mutate_total=0
counter mutate.mutate_batches_started_total=0
counter proc.stime-ticks=0
counter proc.utime-ticks=61
hottest k-ref
hot-child k-ref
strategy-order wrong-scale redundant-pass linear-scan
llm-proposer no-provider
baseline-heldout-ms 160 samples=159,160,160,159,160
round 1 candidates wrong-scale,redundant-pass
round-wall-ms 2977 round-dur-sum-ms 2833 jobs 2
live-fingerprint-during-trials 904851032 -> 904851032 unchanged
candidate wrong-scale ROLLBACK reason=checksum mismatches=4 heldout-ms=-1 mismatches=4 live-unchanged=1 trial-applied=1 dur-ms=3
candidate redundant-pass ROLLBACK reason=no-speedup heldout-ms=468 mismatches=0 live-unchanged=1 trial-applied=1 dur-ms=2830
strategy KEEP order linear-scan
round 2 candidates linear-scan
round-wall-ms 166 round-dur-sum-ms 47 jobs 1
live-fingerprint-during-trials 2486708681 -> 2486708681 unchanged
candidate linear-scan PASS reason=gate-pass heldout-ms=5 mismatches=0 live-unchanged=1 trial-applied=1 dur-ms=47
kernel KEEP id=linear-scan heldout-ms=5
after-heldout-ms 5 samples=5,6,5,6,5
speedup-x 32.00
profile-elapsed-before-ms 605 profile-elapsed-after-ms 332
delta bench-kernel before-ms=71 after-ms=4 delta-ms=-67
delta k-length before-ms=0 after-ms=0 delta-ms=0
delta k-ref before-ms=79 after-ms=79 delta-ms=0
decisions KEEP=2 ROLLBACK=2
mutation-records 10
evo-records 7
```

## 布局

| 路径 | 作用 |
|---|---|
| `lib/perf/profile.aura` | 采集和 `perf` / `gprof` / `/proc` 解析 |
| `lib/perf/query.aura` | `perf:hotspots` `perf:stacks` `perf:counters` `perf:delta` |
| `lib/perf/propose.aura` | 规则 proposer 和 LLM 插口 |
| `lib/perf/trial.aura` | `orch:parallel` 子进程 trial |
| `lib/perf/loop.aura` | profile → propose → gate → KEEP / ROLLBACK |
| `examples/sum-scan/` | 可变的 kernel、策略和三条候选 |
| `tests/` | 解析、查询、proposer、门限。不依赖墙钟 |

审计在 `out/evo.jsonl`（父进程）和 `out/trials/*.jsonl`（每次 `evo:trial`）。子进程日志里的 `mutate:rebind KEEP` 是 fork 内部的改写，进程退出即丢；live 是否保留只看父进程的 `decisions` 行。
