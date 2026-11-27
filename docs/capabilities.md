# aura-perf 的特有能力

aura-perf 是给 agent 用的优化运行时。剖析和调优是 workspace 里的程序，不是给人看的性能工具。调用方不看火焰图、不读一段塞进 prompt 的 perf 文本、也不在网页上点批准。Agent 调用的是返回 Aura 值的原语；专家要加约束时，写的是同一套 EDSL，进同一条 worldline 和同一份审计。

对比基线是：通用 coding agent，把外部 profiler 的文本贴进 prompt，再用外层脚本一轮轮改文件。那种循环里，证据不是可查询的值，mutation 没有类型门和精确回滚，反馈不能做差分或归因，harness 是冻住的 prompt，长 horizon 容易停在局部最优。下面每条能力都是这条基线做不到、或做不干净、而把过程放进 Aura workspace 才成立的。

状态分三种：已实现（本仓库示例跑过）、部分（原语在，闭环还没盖全）、未开始。

## 已实现，本轮在跑

### 0. 目标是自己给的

spec 是目标项目和运行时之间的那份约定，运行时按它工作：

| spec 键 | 意思 | 缺省 |
|---|---|---|
| `seed-path` | 目标程序的源码（seed 装进 workspace） | 无 |
| `kernel` | 被测量的那个 define 的名字 | `target` |
| `target` | null 候选 rebind 的 define | `bench-kernel` |
| `call` | 被计时的 kernel：`(call inputs)` | 无 |
| `inputs` | `(n -> inputs)` | `perf:range` |
| `oracle` | `(inputs -> expected)` | `perf:sum-ref` |
| `check-inputs` | checksum 用的那几组输入（列表或过程） | sum-scan 的几组 |
| `regions-fn` | 要计时的 define 和它们的 stack | 无 |
| `catalog` | 候选：id、target、genome、thought；或 `genomes` 一组 `(target, genome)`（也接受 target → genome 的 hash），一条候选一次改多个 define | 无 |
| `intend` | 最低加速、checksum、预算、protected | 无 |
| `headroom` | 跑不跑天花板探针；`#f` 关闭 | `#t` |
| `headroom-max` | 一次最多探几个热点位点 | 6 |
| `headroom-stub` / `headroom-stubs` | 替换位点的表达式（全局或 target → 表达式） | `"0"` |
| `headroom-order` | 候选按上限从高到低排（未知的留在后面） | `#t` |
| `headroom-min-pct` | 上限低于这个百分比的候选不进这一轮 | 无（不过滤） |
| `genes` | 策略基因 | 无 |
| `count-defines` | 要不要每条 worldline 的树（`#t` 或 define 名字的列表） | `#f` |
| `null-genome` | null 候选的源码（目标 rebind 成自己）；目标的 define 不在 seed 里时用 | 从 seed 的文本里取 |
| `null-genomes` | 别的 define 的 null 源码：target → 源码的表。catalog 里每条候选可以 rebind 另一条 define，那条 define 的 null 才是它的参照物 | 从 seed 的文本里取 |
| `null-genome-fn` | 别的 define 的 null 源码：`(target -> 源码)` 的过程 | 无 |
| `label` | 报告第一行的名字 | `sum-scan` |
| `worker` | 跑一个候选的子进程脚本 | `examples/sum-scan/worker.aura` |
| `llm` | 模型提议者的选项：`budget`（一次运行 trial 几条模型候选）、`max-tokens`、`timeout`（秒）、`chat`。密钥、端点和模型来自环境（`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`） | `budget` 2、`max-tokens` 8192、`timeout` 120、std/llm 的 `llm:chat` |

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

矿工不做 exclusive 排序然后交出一个函数名。`repeated-index-walk` 的判定是结构的：热叶子（热前缀的最后一个 define）比它**同一个父节点下的兄弟加起来**还贵 `ratio` 倍。名字不在这条规则里：sum-scan 的例子恰好是 `k-ref` 和 `k-length` 并排，别的目标是它自己的 define 和它自己的兄弟。`protected` 也来自 spec，不写死。

分类对应一组**可 trial 的假设**，每条有 id、位点、预期（哪一个门会怎么判）、要动的计数器（下面这组是 sum-scan 的 catalog）：

| id | 位点 | 预期 |
|---|---|---|
| `specialize-k-ref` | `k-ref` | 保护边界拒绝，不 trial |
| `wrong-scale` | `bench-kernel` | checksum 失败 |
| `redundant-pass` | `bench-kernel` | 正确但 task-clock 不降 |
| `linear-scan` | `bench-kernel` | task-clock 下降 |

LLM proposer 已经接上模型（13）：它的候选就是上面这张表里的一条 catalog 条目，由同一道门判，不是一段建议。

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

候选自己失败（结果不对、更慢）是候选的 ROLLBACK，一轮接着走下一轮；只有 trial 本身没跑完（worker 崩了、超时、隔离不住）才是这一轮的 `trial-infrastructure`。Aura #5255 起，checksum 不过的 trial 状态是 `infeasible`：它量过了，结论是候选违反了约束，运行时按前一种读。

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

Trial 子进程在 checksum 通过之后，量出那条 worldline 的树。**树优先由目标程序自己量**：seed 可以定义 `(perf-worldline-measure kernel xs)`，它知道自己的 define 的元数，所以能装上计数器、跑一次 kernel、把每个 define 的调用次数和毫秒连同它自己的 stack 报回来。运行时只补上根（它量的那个 kernel）并建树。spec 用 `count-defines` 决定要不要这张树，也可以点名要哪些 define（`#t` = seed 报的全部）。

目标没写 `perf-worldline-measure` 时，运行时生成同样的探针（`lib/perf/probe.aura`）：从 seed 的顶层 define 里取过程名（`count-names` 点名时只用那几条），用一次 `eval` 装上一组 `set!` 包装（`set!` 改的是候选 rebind 之后的当前值），跑一次 kernel，读回调用次数、self-ms 和自己的 stack，再把每个绑定恢复。kernel 本身不包，根由运行时补；非过程绑定跳过。这是 Aura 的 workspace 自己在当探针：没有 perf 二进制、没有 PMU、没有第二次进程。报告里 `cct-source=target` 表示目标自己量的，`cct-source=auto-probe` 表示运行时生成的；`measured=0` 仍是「这条 worldline 没有树」。

自动探针的毫秒是 `monotonic-ms`，调用次数精确、self-ms 是毫秒分辨率；包装本身给每次调用加一帧和一次 apply，所以绝对毫秒偏大。读法是树形、调用次数和相对份额，不是把自动探针的毫秒当 perf 的 task-clock。目标自己写的测量仍然优先，因为它知道自己的元数和哪些 define 属于树。

父进程调用 `(perf:cct-worldline-query before after prefix)`，得到 `prefix-removed`、`cost-moved`、`moved-to`。`(perf:cct-cleared …)` 回答「哪次 mutation 去掉了同一条热前缀，且没有把代价挪到别的 define」。差分摘要写进该候选的 `evo:record!` evidence（`cct-delta`）。KEEP 之后若 `perf:should-continue?` 为真，用新树再 `perf:mine`；示例里线性扫描是 `continue 0`。

度量：`cleared` 行点名候选；`worldline` 行给出 measured / prefix-removed / cost-moved / cct-source。空树是 `measured=0`，不算「前缀被删掉」。目标自己的测量和自动探针都没有产出时，报告如实写 `measured=0`。

### 8. 负例按 class + hot-node，跨次累积

`(perf:neg-remember mem class hot idea reason)` 记下失败的想法。`(perf:neg-blocked? …)` 在同一热点上拒绝原样重提；热点或 class 变了，同一 id 可以再提。`perf:round-candidates` 会过滤，并打印 `negative-skip`。这和「从 order 里删掉 id」同时存在，过滤才是按热点的那一层。

负例**跨次**累积：跑完写在 `<out-dir>/memory.json`（spec 可以用 `memory-path` 换位置），
下一次跑先读回来。于是第二次跑同一个目标，不再把预算花在已经失败过的想法上：
`memory-loaded 3`，`negative-skip wrong-scale`、`negative-skip redundant-pass`，
`budget-used` 从 3 降到 1，结论不变。

键是**位点**（热叶子）和想法，不是 class。class 是矿工的结果，会跟着机器的噪声动：
同一个目标两次跑可能被分成不同的 class，按 class 记的负例就漏了。记录里仍然留着
当时的 class，报告里看得到。

### 9. 策略基因走同一条 KEEP / ROLLBACK

分类比（默认 2）、`actionable-ms`、catalog 顺序是基因。`(perf:select-gene profile genes seal)` 逐个给 KEEP 或 ROLLBACK：`intend-bypass`、`misclassify`、`no-actionable-site`、`no-signal`、`empty-order`，胜者才 `mutate:rebind` `perf-strategy`。输家不改 live 定义。基因不能把 checksum 关掉、不能把最低加速调低、不能缩短 protected。

### 10. intend 是门，不是提示

`(perf:intend-seal spec)` 取出 checksum、`min-faster-pct`、protected、budget。试验用的百分比是 seal 和 spec 里更严的那个。`force-keep` 不参与 `perf:accept?`。预算是实际 launch 的 kernel trial 数，基因判定不占这份预算。

intend 还可以带一个**按位点的地板** `site-min-faster-pct`。候选改的是一个 define，
它能赢的是那个 define 拥有的一小片；整个目标的地板会把「改对了地方」判成「没赢」。
位点的两段时间都来自 worldline 树：基线那棵和候选那棵，所以两边是同一种量。候选
catalog 条目可以写 `site`（默认是它 rebind 的那个 define）：改一个谓词的候选，赢的
是调用方的时间。报告里有一行 `site <name> base-ms=… cand-ms=… floor-pct=…`。

held-out 中位是 0 ms 也算数：候选比计时器的分辨率还快时，参照物大于 0 它就是过了地板的加速。以前 `perf:speedup-ok?` 把 0 当成没有读数，最快的改写（把列表直接交给 `apply +`）反而按 `no-speedup` 打回。参照物是 0 时没有可比的，仍是 `no-speedup`。这时结论行的 `speedup-x` 是 `na`，括号里照旧是两次中位。

### 10b. checksum 比的是同一个程序

子进程把 job 当 JSON 读 ✗，而 JSON 不保留「读回来变成整数」的浮点（5.0 变成 5 ✗）。
父进程在自己的输入上算期望值 ✗、子进程在 JSON 那个输入上算结果 ✗ —— 两边其实是两个
程序 ✗。现在输入先走一遍同样的 round trip ✓，期望值再算 ✓，两边是同一个值 ✓。

### 10c. 一个候选是一组改动

catalog 条目可以带 `genomes`：一组 `(target, genome)`，或 target → genome 的 hash。运行时把每条候选归一成 `mutations`，之后再没有「单 target」和「多 target」两条路：

- **一个 worldline 应用整组。** worker 先按 `null-mutations` 把每个 target rebind 成它自己的函数体、量一次 base；再把整组 candidate 依次 `mutate:rebind`，最后只 `eval-current` 一次。任何一条 rebind 失败，整条 worldline 回滚，不会留下半组改动。
- **参照物是同一组。** 候选的 `null-heldout-ms` 是「所有 target 都 rebind 成自己」的那次测量，和候选付同一笔 rebind 税；`ref-target=bench-kernel+k-ref` 写在候选行上。
- **类型门逐条 dry-run。** `(mutate :check)` 对每条 mutation 各跑一次；跨 mutation 的签名变化仍由 trial 里的 `mutate:rebind` 做最后 typecheck。
- **protected 检查组。** 组里任何一个 target 在 protected 列表里，整条候选 `expert-refuse`，不会只改一半。
- **位点地板按组求和。** `site` 默认是组里每个 target；报告写 `site bench-kernel+k-ref base-ms=… cand-ms=…`。base 树缺一个位点是没有量到（floor 不成立），候选树缺一个位点是候选不再调用它（算 0），所以「把热叶子整个删掉」这种组不会因为位点消失而失败。
- **引用检查按组。** 组里任何一个 target 没有可 rebind 的 null 体，整条候选 `reference-missing`，不会拿别的 target 的 null 凑参照。

### 10d. 天花板探针

在花钱试候选之前，先量「这个位点最多能赢多少」。headroom job 不是候选：它在自己的 worldline 里把某个 define 的**当前绑定**用 `set!` 换成一个便宜的 varargs stub（默认 `(lambda args 0)`），跑一次 kernel，再恢复绑定；和同批次的 fresh baseline child 比较，差值就是上限。

- **不改 live，也不进 gate。** 探针是诊断，不占 intend 的预算，不 KEEP，不写负例。
- **报每个位点。** `site-headroom k-ref base-ms=… free-ms=… headroom-pct=…`；stub 让 kernel 抛错时写 `site-headroom-unavailable <site> reason=…`，不把 0 ms 当赢。
- **报每个候选的上限。** 候选行的 `headroom-pct` 是它改的位点（组候选是各位点之和）的上限，分母是探针自己的 baseline；它回答「这个方向最多值多少」，不是「这个候选一定赢」。
- **内核和 protected 不探。** 默认排除 kernel（把 kernel 换成 stub 永远是 100%）和 intend 的 protected 位点。
- **上限进策略。** 有探针的候选按 `headroom-pct` 从高到低排（未知的留在后面；`headroom-order #f` 关掉）；`headroom-min-pct N` 让上限低于 N% 的候选直接不进这一轮，报告写 `headroom-skip <id> headroom-pct=… floor-pct=…`，不占预算。
- 探针数量由 `headroom-max` 限制（默认 6）；`headroom #f` 关闭；`headroom-stub` / `headroom-stubs` 换 stub 表达式。

### 11. 便宜筛选，再花 held-out

Checksum 失败的候选不做 held-out。正确的候选先在 `screen-n` 上计一次，**同时在同一 child 里量这次 screen 输入的 worldline 树**（目标自己的 `perf-worldline-measure`，没有就用 auto-probe）。screen 决策读候选的位点（组候选是各位点之和）对 null base 的同一组位点：只有位点明显更差（慢过两倍，并且慢过 base 加 slack）才 `screen-pruned`。base 树没有位点时退回整 kernel 的 `screen-ms`。活下来的才跑 held-out。候选行带 `screen-site-ms=… screen-base-site-ms=…`，报告写明 `screen-site=<site>`；位点快了但整 kernel 没动，screen 也能看见。

### 12. 机器层库存和建议

`perf:sysinfo` 读 `/proc`、`/sys`，并在二进制存在时探测 `perf`、`lscpu`、`lsmem`、`numactl`、`dmidecode`、`bpftrace`。支持的 perf 事件和 `<not supported>` 分开记。`perf c2c` 只记录子命令在不在，不编造 hit。`perf:advice` 把程序热点和机器层分开：NUMA 节点数、单 socket、IPI 计数来自 `/proc/interrupts`，cache-line sharing 在 c2c 没采样时是 `skipped`。`aura-perf check` 默认采样 1 秒（`AURA_PERF_CHECK_SEC` 可加长），给出 CPU / 磁盘扇区 / 网卡字节 / IPI 的差分。

KEEP 时若 `AURA_SANDBOX=off`，读 compile 组的 `cascade_full_count` 和 `module_dirty_recompiles`。示例里 `world-rebuilt=0`。这是证据，不是另一道会把正确加速打回去的门。

### 13. 模型提议者只提议

`perf:llm-propose` 经 `std/llm` 的 `llm:chat` 问一次模型（aura-perf#29）。接线（三个环境变量）和调用预算写在 README 的「模型提议者」里。这里是边界：

- **证据是文本。** 报告自己打印的 `hotspot` / `counter` 行、门要比的数、可 rebind 的 define 的源码、catalog 和这个热点上的负例。不送图，不塞 data URL，也不交 perf script 原文。
- **回答只变成候选 hash。** `id`、`target`、`genome`、`thought`、`proposer`。回答里的判定字段不复制，所以到不了门。
- **和规则候选走同一条路。** 封了印的 protected 边界、负例记忆、trial 子进程、checksum、held-out、地板、总线上的约束。模型没有 KEEP 权。
- **是加法。** 模型候选出自己的 allowance（spec 的 `llm` hash `budget`，缺省 2），不动 intend 的预算；一条模型候选的失败不算规则路径的 trial 基础设施故障，第二轮照常。
- **进 trial 之前的检查。** target 是这一轮可 rebind 的 define；`genome` 恰好是一个同名同参数的 `(define …)`，没有第二个顶层 form；不点名有副作用的原语（`shell`、`write-file`、`set!`、`eval`……），带命名空间的名字只能是证据里出现过的 define；和 catalog 里某条只差排版的是重复。这是卫生检查，不是边界：边界仍然是 checksum 和 held-out。
- **密钥不落盘。** 传输层的错误文本和模型的句子进报告之前，密钥被换成 `[redacted]`。

度量：报告的 `llm-proposer`、`llm-candidate`、`llm-rejected`、`llm-budget-used` 行。测试：`tests/llm_propose_test.aura`（提议者本身，chat 是传入的过程，不碰网络）、`tests/llm_round_test.aura`（候选怎么进一轮）、`tests/llm_proposer_test.py`（真实的一轮，对面是本机的假 provider）。

### 14. 非 Aura 目标的原生 profile

`aura-perf profile --pid PID --seconds N`（或 `-- COMMAND`）对任意进程跑
`perf record`，输出当前目录的 `out/profile.txt`、`out/profile.json` 和
`out/perf.data`。它不需要 Aura 二进制、workspace 或 LLM；Redis、Postgres、
游戏服务器和批处理二进制都能用。PMU 不支持的计数器写成 `<not supported>`，
不写成 0。

边界：`profile` 只给证据。`autotune` 要能 `mutate:rebind` 目标 define，
所以只对 Aura 目标做自动 trial / KEEP / ROLLBACK；Redis 的 C 代码不会在这里
被改写。先用 native profile 找到瓶颈，再在目标自己的语言里改。

## 部分

### 观察、试探、证明、提交是同一语言

Trial 在子进程的 `evo:trial` 里做，live 指纹不变；过门才在父进程 snapshot → rebind → 再测，失败则 restore。KEEP 只认 gate。`(perf:intend-seal …)` 把 checksum、最低加速和 protected 收成一次运行里改不掉的值。

类型门在 trial 之前：`(mutate :check target genome)` 在父进程里读 workspace、在 call-local 存储里 parse + typecheck、什么都不写。不过的候选是 `candidate <id> ROLLBACK reason=type-gate`，没有 job 文件、没有子进程、没有 screen、没有 held-out；诊断单独一行 `type-gate <id> <tag>: <message>`，audit 里也有。它不占 intend 的预算，但当轮就进 `refused`，下一轮不会再排。构建上没有 `mutate:check` 时返回 `unavailable`，候选照旧进 trial，不把「门不可用」当成「候选错了」。

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
4. 已做：模型提议者经 `std/llm` 接上，候选是 catalog 条目，走同一道门，没有 KEEP 权（13）。

不要做的：HTML/SVG 火焰图、perf script 原文进模型、给人看的仪表盘或审批页。
