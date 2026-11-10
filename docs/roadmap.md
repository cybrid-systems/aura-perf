# Roadmap

MVP 只做仓库级 CPU 优化：证据进 Aura，搜索和门控跑在 workspace 上，proposer 可替换但不连模型。下面是中期顺序，不把还没跑的东西算进当前结果。

## 1. Evolving Agent Teams 风格的优化团队

接 [aura-harness](https://github.com/cybrid-systems/aura-harness) 和 [hephaestus](https://github.com/cybrid-systems/hephaestus) 已有的分工，而不是再写一套外层循环。

- **Solver**：在 live 策略下跑一批任务，留下轨迹（现在的 sum-scan 只有一条 kernel）。
- **Proposer**：读失败轨迹和当前策略源码，一次只改一个 `define`。`perf:llm-propose` 留着，默认仍是 `perf:rule-propose` / harness 里那种 `prop:grammar`。
- **Scope guard**：热点策略、预算、checksum oracle 分开放。Oracle 和 held-out 输入不进可写 workspace。
- **Forked worldline + held-out 门**：继续用 `evo:trial`（或 harness 验证过的 snapshot 模式）。分数只来自 proposer 没见过的输入。
- **审计**：沿用 `evo:record!` / `AURA_EVO_LOG`，重启后能用 `aura evo log --lineage` 追到根。
- **策略演化**：`perf-strategy` 这种 workspace `define` 变成团队的一个角色（选热点、选 mutation 族、分预算），和其他角色一样被 trial，而不是只在 kernel KEEP 之前改一次。

Hephaestus 这边要接的是它已经在测的东西：热点作为一等对象、负载下的 rebind、性能计数进语义，而不是把数值库搬进来。

## 2. Kernel 任务

CPU 闭环稳定之后再碰 kernel，仍然先隔离评测、再谈设备。

- **任务**：KernelBench 一类的算子（matmul、softmax、layernorm、reduction），评测协议对齐 [aura-kernel-agents](https://github.com/cybrid-systems/aura-kernel-agents)：契约先于计时、错误输出不算分、最终结果用新输入复测。
- **表示**：调度 / kernel 继续是 Aura 源码，`mutate:rebind` + `ast:snapshot` / `ast:restore`。文本基线（模型直接写 C）留在 kernel-agents 那种对照里，不混进 aura-perf 的 KEEP 计数。
- **下沉**：[aura-kernel-sink](https://github.com/cybrid-systems/aura-kernel-sink) 的路径是识别热点之后把函数换成 C `.so` 薄封装。aura-perf 只提供“哪一段值得沉、沉了有没有过 held-out 门”；`aot:reload` / FFI 仍由 sink 负责。
- **设备**：没有 GPU 的环境不做 SOL-ExecBench 数字。有设备之后再把同一套 gate 接到真实 kernel 计时上。

## 3. Warpline 一类的 trace

把采样栈接进现有的 profile 值，而不是换一套优化循环。

- 新的 collector 读 Warpline / 类似的 warp 或指令 trace，填同一套字段：`hotspots`、`stacks`、`counters`。
- `perf:hotspots` / `perf:delta` 不用改调用方。策略只看见名字、self 时间和栈，不看见 trace 原文。
- Trace 来源要写进 `tools` 状态。解析失败就记原因，不要用 region timer 的数冒充硬件采样。

## 明确还不做

- 不在这个仓库里改 Aura 本身。v0.2.0 上碰到的行为记在 [findings.md](findings.md)。
- 不下载、不安装 LLVM。C 侧如果要 `-pg` 或后续的 C kernel，用系统里已有的 C 编译器，并在报告里写清有没有跑到。
- 不把 LLM 调用做成默认路径。
