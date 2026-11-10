# aura-perf 的特有能力

aura-perf 是给 agent 用的优化运行时。剖析和调优是 workspace 里的程序，不是给人看的性能工具。调用方不看火焰图、不读一段塞进 prompt 的 perf 文本、也不在网页上点批准。Agent 调用的是返回 Aura 值的原语；专家要加约束时，写的是同一套 EDSL，进同一条 worldline 和同一份审计。

对比基线是：通用 coding agent，把外部 profiler 的文本贴进 prompt，再用外层脚本一轮轮改文件。那种循环里，证据不是可查询的值，mutation 没有类型门和精确回滚，反馈不能做差分或归因，harness 是冻住的 prompt，长 horizon 容易停在局部最优。下面每条能力都是这条基线做不到、或做不干净、而把过程放进 Aura workspace 才成立的。

状态分三种：已实现（本仓库示例跑过）、部分（原语在，闭环还没盖全）、未开始。

## 已实现，本轮在跑

### 1. 证据是可查询的值，策略直接调用

Agent 不接收报告。一次采集得到一个 profile 值，里面有 `cct`（调用上下文树）、`hotspots`、`counters`。树节点是**被优化程序的 define**，字段是 `inclusive-ms` / `exclusive-ms`（这里来自该 define 工作负载的 `perf stat` task-clock）、`calls`、`stack`、`page-faults`。没有像素宽度。

策略代码自己调用：

- `(perf:mine profile)` → `class`、`hot-node`、`site`、`prefix`、`hypotheses`
- `(perf:hot-child profile)` → task-clock 最高的可比较 callee
- `(perf:cct-hot-prefix cct)`、`(perf:cct-actionable cct threshold protected)`、`(perf:cct-delta before after)`

`perf-strategy` 是 workspace 里的 define。它从 `ctx` 取出 `mine` 和 `profile`，调用矿工，再决定 catalog 顺序。host 不把「热点名叫 k-ref」写死进策略；策略不查询，就看不到 `repeated-index-walk`，也就不会排出会失败的候选。

度量：策略返回的 `class` / `hot-node` / `prefix` 必须和 perf 行一致；关 perf 时退回 region timer，同一条查询路径仍返回一个 child。

依赖：workspace `define`、`perf stat` 进 Aura hash、策略 `mutate:rebind`。

### 2. 调用上下文树对齐到可 rebind 的 define

人从火焰图读出「宽的是热点」。Agent 需要的是：热栈帧就是下一步可以安全 mutation 的那个 define。

本轮的树是目标程序自己的调用关系，不是解释器 C++ 符号，也不是源文件行号：

- 前缀 `bench-kernel > k-ref`：热叶子是 `k-ref`（反复 `list-ref`）
- 可行动位点是它的可变祖先 `bench-kernel`。叶子在专家的 protected 列表里，不能 rebind
- `(perf:cct-actionable … '(k-ref k-length))` 只留下 `bench-kernel`

下一步是对这个位点 trial 一条 genome，不是生成补丁说明。

度量：`perf:mine` 的 `hot-node` 与 `site` 分开；protected 叶子不会进入 trial。

依赖：CCT 值、专家 intend 里的 `protected`、`mutate:rebind` 的 target。

### 3. 自动矿工 + 可执行假设

矿工不做 exclusive 排序然后交出一个函数名。`repeated-index-walk` 的判定是结构的：同一父节点下，`k-ref` 的 task-clock 超过 `k-length` 的两倍。分类对应一组**可 trial 的假设**，每条有 id、位点、预期（哪一个门会怎么判）、要动的计数器：

| id | 位点 | 预期 |
|---|---|---|
| `specialize-k-ref` | `k-ref` | 保护边界拒绝，不 trial |
| `wrong-scale` | `bench-kernel` | checksum 失败 |
| `redundant-pass` | `bench-kernel` | 正确但 task-clock 不降 |
| `linear-scan` | `bench-kernel` | task-clock 下降 |

LLM proposer 仍然只是插口。它如果要参与，必须填进同一张候选 hash，不能只返回一段建议。

度量：一次运行里至少一条假设被拒绝、一条 checksum 失败、一条无加速、一条 KEEP，且 KEEP 后的 CCT 差分方向和 `expect` 一致。

依赖：规则 catalog、`perf:split-protected`、`orch:parallel` + `evo:trial`、held-out 门。

### 4. 全自动调优

`(perf:autotune spec)` 是唯一入口。调用方给出 intend（最低加速、checksum、预算、protected）和目标程序，不再逐步推。运行时自己挖、提议、并行 trial、KEEP 或 ROLLBACK、再采一棵树，直到 intend 成立或候选耗尽。

intend 本身是 hash，不是 prompt 里的愿望：

```
(hash "min-faster-pct" 10 "checksum" #t "budget" 4
      "protected" (list "k-ref" "k-length"))
```

停止条件写在这份值里。`intend-met` 由 held-out 中位时间算，不由模型声称。预算是实际 launch 的 trial 数。

和 PerfAgent 一类外层脚本的差别：没有第二套 Python 循环在「人盯着」推下一轮。策略顺序、保护边界、门限都在这次进程的 workspace 和 spec 里，审计能回溯。

度量：`intend-met`、`budget-used`、`decisions KEEP/ROLLBACK`、held-out 前后中位。结论行把两次中位、样本数和极差写在比值后面，例如 `speedup-x=81.25 (325ms->4ms n=5 spread=120->0ms)`。进程退出码跟 `intend-met` 一致：成立是 0，不成立非 0。

依赖：`evo:trial`、`ast:snapshot` / `ast:restore`、`mutate:rebind`、`evo:record!`。

### 5. KEEP 之后立刻再采一棵树

KEEP 不重启 agent。同一个进程里：

- held-out 计时在 live 的 `bench-kernel` 上重跑（定义已经被 `eval-current` 换成线性扫描）
- `perf stat -p <本进程>` 在 KEEP 之后再罩一次这三次调用，得到 `perf-live-after-task-clock-ms`
- 对**同一个目标程序**的 linear 形态再跑一次 `perf stat`，和 KEEP 前的 `bench-kernel` 节点做 `(perf:cct-delta before after)`

差分是下一轮策略的输入，不是两张红蓝图。本轮示例在假设被确认后停止（intend 已满足）。热前缀 `k-ref` 从后树上消失，`bench-kernel` 的 task-clock 下降，才打印 `hypothesis-confirmed`。

度量：`cct-delta` 的 `delta-ms` 为负，且 live task-clock 下降。region timer 的 `perf:delta` 同时留下 define 级毫秒差，两套数不要混成一个单位。没有 perf 时不打印 live task-clock，改由 worldline 查询打印 `hypothesis-confirmed`。

依赖：hot-update（`mutate:rebind` + `eval-current`）、同一 PID 上的 `perf stat`（二进制可用时）、CCT 差分。

### 6. 专家用 EDSL 加约束，不看图审批

默认无人值守。需要领域判断时，专家写的是可执行规范，和自动调优读同一份值：

- `protected`：这些 define 不能 trial。`specialize-k-ref` 会被 `expert-refuse`，并记一条 ROLLBACK / `protected-define`，不消耗正确性预算之外的评测（它不进 worldline trial）
- `min-faster-pct` 和 checksum 是门，策略改不掉
- catalog 和 `perf-strategy` 的顺序本身是 workspace 代码，失败后被 `mutate:rebind` 改成只留还没失败的假设，失败则 `ast:restore`

没有审批网页。专家若要手试一条思路，用同一套 `evo:trial` 即可，结果进同一条 `AURA_EVO_LOG`。边界拒绝是已经跑过的那一步。intend 和策略基因在 `examples/sum-scan/policy.aura`，改完执行 `aura-perf recheck`。

度量：`expert-refuse` 行出现，且随后的 trial 名单里没有该 id。

### 7. 每个 worldline 一棵 CCT

Trial 子进程在 checksum 通过之后，用一次便宜的 region 计数把 `k-ref` / `k-length` 的调用次数记进那条 worldline 的 CCT。父进程调用 `(perf:cct-worldline-query before after prefix)`，得到 `prefix-removed`、`cost-moved`、`moved-to`。`(perf:cct-cleared …)` 回答「哪次 mutation 去掉了同一条热前缀，且没有把代价挪到别的 define」。差分摘要写进该候选的 `evo:record!` evidence（`cct-delta`）。KEEP 之后若 `perf:should-continue?` 为真，用新树再 `perf:mine`；示例里线性扫描是 `continue 0`。

度量：`cleared` 行点名候选；`worldline` 行给出 measured / prefix-removed / cost-moved。空树是 `measured=0`，不算「前缀被删掉」。

### 8. 负例按 class + hot-node

`(perf:neg-remember mem class hot idea reason)` 记下失败的想法。`(perf:neg-blocked? …)` 在同一热点上拒绝原样重提；热点或 class 变了，同一 id 可以再提。`perf:round-candidates` 会过滤，并打印 `negative-skip`。这和「从 order 里删掉 id」同时存在，过滤才是按热点的那一层。

### 9. 策略基因走同一条 KEEP / ROLLBACK

分类比（默认 2）、`actionable-ms`、catalog 顺序是基因。`(perf:select-gene profile genes seal)` 逐个给 KEEP 或 ROLLBACK：`intend-bypass`、`misclassify`、`no-actionable-site`、`no-signal`、`empty-order`，胜者才 `mutate:rebind` `perf-strategy`。输家不改 live 定义。基因不能把 checksum 关掉、不能把最低加速调低、不能缩短 protected。

### 10. intend 是门，不是提示

`(perf:intend-seal spec)` 取出 checksum、`min-faster-pct`、protected、budget。试验用的百分比是 seal 和 spec 里更严的那个。`force-keep` 不参与 `perf:accept?`。预算是实际 launch 的 kernel trial 数，基因判定不占这份预算。

### 11. 便宜筛选，再花 held-out

Checksum 失败的候选不做 held-out。正确的候选先在 `screen-n` 上计一次。只有屏幕时间明显更差（慢过两倍，并且慢过 baseline 加 slack）才 `screen-pruned`。活下来的才跑 held-out。屏幕读数是 0 时放行，交给 held-out 门拒绝更慢的结果。

### 12. 机器层库存和建议

`perf:sysinfo` 读 `/proc`、`/sys`，并在二进制存在时探测 `perf`、`lscpu`、`lsmem`、`numactl`、`dmidecode`、`bpftrace`。支持的 perf 事件和 `<not supported>` 分开记。`perf c2c` 只记录子命令在不在，不编造 hit。`perf:advice` 把程序热点和机器层分开：NUMA 节点数、单 socket、IPI 计数来自 `/proc/interrupts`，cache-line sharing 在 c2c 没采样时是 `skipped`。`aura-perf check` 默认采样 1 秒（`AURA_PERF_CHECK_SEC` 可加长），给出 CPU / 磁盘扇区 / 网卡字节 / IPI 的差分。

KEEP 时若 `AURA_SANDBOX=off`，读 compile 组的 `cascade_full_count` 和 `module_dirty_recompiles`。示例里 `world-rebuilt=0`。这是证据，不是另一道会把正确加速打回去的门。

## 部分

### 观察、试探、证明、提交是同一语言

Trial 在子进程的 `evo:trial` 里做，live 指纹不变；过门才在父进程 snapshot → rebind → 再测，失败则 restore。KEEP 只认 gate。`(perf:intend-seal …)` 把 checksum、最低加速和 protected 收成一次运行里改不掉的值。类型检查仍会拒绝 typecheck 失败的 genome。

### 计数器 join 到节点

有 perf 时，task-clock、cpu-clock、page-faults、context-switches 在 profile 的 `counters` 里。硬件事件不支持就列入 `events-unsupported`，不写成 0。没有 perf 二进制时，CCT 节点上的毫秒来自 region timer，报告里写明硬件计数器没有读。page-faults 在各 define 上几乎一样，不拿来选热点。

### 机器层探针还没采样

`perf c2c`、`perf mem`、`perf sched` 只回答子命令是否存在。cache-to-cache、SPE、跨 die 的命中数没有测到就是 `skipped`，没有 0。bpftrace 未安装就不运行。

## 未开始

- **语义火焰**：代价归到 intent、策略阶段、规则，而不只是 define 名。
- **Kernel / C 下沉**：`aura-kernel-sink` 作为 autotune 的一种假设。没有 GPU 就不报 SOL。
- **Warpline 等 trace**：另一种 CCT 采样源，填同一套 `perf:cct-*` 查询。
- **跨运行的机器层负例**：同一次 autotune 里的负例已经按热点记住；机器建议还没有自己的跨次记忆。

## 实施顺序

1. 已做：目标程序的测量 → CCT → `perf:mine` → 策略基因 → protected 拒绝 → 并行 trial（每条 worldline 一棵 CCT）→ KEEP → 负例按 class + hot-node → intend 门。
2. 已做：`aura-perf sysinfo` 和 `aura-perf check` 把机器库存收成 Aura 值。缺工具就写 skipped。
3. 下一步：语义火焰，然后才是 kernel 下沉、c2c 采样和外部 trace。

不要做的：HTML/SVG 火焰图、perf script 原文进模型、给人看的仪表盘或审批页。
