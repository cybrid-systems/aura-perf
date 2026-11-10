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

度量：`intend-met`、`budget-used`、`decisions KEEP/ROLLBACK`、held-out 前后中位。

依赖：`evo:trial`、`ast:snapshot` / `ast:restore`、`mutate:rebind`、`evo:record!`。

### 5. KEEP 之后立刻再采一棵树

KEEP 不重启 agent。同一个进程里：

- held-out 计时在 live 的 `bench-kernel` 上重跑（定义已经被 `eval-current` 换成线性扫描）
- `perf stat -p <本进程>` 在 KEEP 之后再罩一次这三次调用，得到 `perf-live-after-task-clock-ms`
- 对**同一个目标程序**的 linear 形态再跑一次 `perf stat`，和 KEEP 前的 `bench-kernel` 节点做 `(perf:cct-delta before after)`

差分是下一轮策略的输入，不是两张红蓝图。本轮示例在假设被确认后停止（intend 已满足）。热前缀 `k-ref` 从后树上消失，`bench-kernel` 的 task-clock 下降，才打印 `hypothesis-confirmed`。

度量：`cct-delta` 的 `delta-ms` 为负，且 live task-clock 下降。region timer 的 `perf:delta` 同时留下 define 级毫秒差，两套数不要混成一个单位。

依赖：hot-update（`mutate:rebind` + `eval-current`）、同一 PID 上的 `perf stat`、CCT 差分。

### 6. 专家用 EDSL 加约束，不看图审批

默认无人值守。需要领域判断时，专家写的是可执行规范，和自动调优读同一份值：

- `protected`：这些 define 不能 trial。`specialize-k-ref` 会被 `expert-refuse`，并记一条 ROLLBACK / `protected-define`，不消耗正确性预算之外的评测（它不进 worldline trial）
- `min-faster-pct` 和 checksum 是门，策略改不掉
- catalog 和 `perf-strategy` 的顺序本身是 workspace 代码，失败后被 `mutate:rebind` 改成只留还没失败的假设，失败则 `ast:restore`

没有审批网页。专家若要手试一条思路，用同一套 `evo:trial` 即可，结果进同一条 `AURA_EVO_LOG`。本轮没有单独的「专家 fork 一条 worldline」演示，边界拒绝是已经跑过的那一步。

度量：`expert-refuse` 行出现，且随后的 trial 名单里没有该 id。

## 部分

### 观察、试探、证明、提交是同一语言

Trial 在子进程的 `evo:trial` 里做，live 指纹不变；过门才在父进程 snapshot → rebind → 再测，失败则 restore。Agent 改文件绕不开这道门，因为 KEEP 只认 gate。类型检查会拒绝 typecheck 失败的 genome。还没有一个 `(perf:intend …)` 运行时对象把「checksum 不变且 ≥1.1×」变成引擎强制的规范；现在是 spec hash + `perf:speedup-ok?`。

### 多 worldline 的树群

多个候选由 `orch:parallel` 同时 trial，各自一份 `out/trials/<id>.jsonl`。父进程只在全部返回后选 KEEP。还没有「每个 trial 一棵 CCT，查询哪次 mutation 砍掉了同一热前缀且没有把代价挪走」。现在的差分是 KEEP 前的树对 KEEP 后的树，挂在同一次运行的审计上，不是候选之间的树对比。

### Provenance 给下一个 agent 读

`evo:record!` 和引擎的 `mutate:rebind` 行在 `out/evo.jsonl`。字段有 decision、reason、heldout-ms、mismatches、id。下一轮策略通过 `failed` id 列表不再原样重提。还没有把 CCT 哈希写进证据，也没有按热点检索历史负例的原语；负例就是本轮的 refused/ROLLBACK id。

### 计数器 join 到节点

`perf stat` 的 task-clock、cpu-clock、page-faults、context-switches 在 profile 的 `counters` 里，节点上有 task-clock 和 page-faults。`engine:metrics` 的 eval/jit/mutate 差分也在 counters。硬件事件 `cycles`、`instructions`、`cache-misses` 在这台没有 PMU 的内核上是 `<not supported>`，不会写成 0。page-faults 在各 define 上几乎一样（进程启动占主导），不能用来选热点；选热点的是 task-clock。

### 策略自身可演化

失败假设从 `perf-strategy` 的 order 里删掉，新源码再 `eval-current`。新源码仍然调用 `mine`。这是 harness 的一次 KEEP。还没有把分类阈值、特征权重做成基因再搜索。

## 未开始

- **语义火焰**：代价归到 intent、策略阶段、规则，而不只是 define 名。方便 agent 优化自己的 harness。需要阶段标记进 CCT 节点。
- **增量编译反馈**：KEEP 时读 `compile:*` 的 partial relower / dirty 计数，确认 trial 没有整包重编。原语在 `engine:metrics`，还没接进门控。
- **候选之间的 CCT 差分**挂到 evo 血缘：每个 worldline 采一棵树，查询「热前缀被砍且没有搬家」。
- **Kernel / C 下沉**：`aura-kernel-sink` 作为 autotune 的一种假设（「纯计算 define → 下沉」），走同一道 checksum 和回滚。不是本轮的事。
- **Warpline 等 trace**：另一种 CCT 采样源，填同一套节点，不另做报告。

## 实施顺序

1. 已做：目标程序的 `perf stat` / `perf record` → CCT → `perf:mine` → 策略消费 → protected 拒绝 → 并行 trial → KEEP → 再采树并 `perf:cct-delta` → `perf:autotune` 报 intend。
2. 下一步：每个 trial 一棵 CCT，差分挂上候选 id；负例按 `hot-node` + `class` 检索，而不只是 id 字符串。
3. 把分类阈值和 catalog 顺序收成可再 trial 的策略基因。
4. intend 升成运行时检查的规范，类型门和 checksum 门都不能被策略关掉。
5. 语义火焰（阶段 / 规则节点），然后才是 kernel 下沉和外部 trace。

不要做的：HTML/SVG 火焰图、perf script 原文进模型、给人看的仪表盘或审批页。
