# aura-perf

给 agent 用的优化运行时。证据、试验、门和策略都是 Aura 值，在同一条 worldline 上 KEEP 或 ROLLBACK。被优化的是目标程序（本仓库的示例是一个链表下标扫描）。Aura 是运行时，不是被剖析的对象。

## 试一下

一条命令跑完测量、挖掘、试验、门控和报告。不需要虚拟环境，不需要配置文件，默认也不需要 API key（可选的模型提议者要，见「模型提议者」）。需要 [Aura v0.2.0](https://github.com/cybrid-systems/aura/releases/tag/v0.2.0)（nightly `cf7353373`）。`perf` 可用时用它的 task-clock；没有二进制或没有 PMU 时改用 region timer，并在报告里写明，不把缺的计数器写成 0。

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

## 外部目标

`autotune` 和 `recheck` 接一个可选的 spec 路径。没有路径就跑内置的 sum-scan
例子；有路径，那个文件就是 spec，运行留在调用者的目录里，所以 spec 可以直接
点名目标程序自己的文件：

```sh
cd my-project
aura-perf autotune perf/spec.aura
```

spec 就是一个普通的 Aura 文件。它 require 运行时（仓库根目录在这次运行的
`AURA_PATH` 上），然后调 `(perf:autotune spec)`：

```scheme
(require "lib/perf/loop" all:)
(require "lib/perf/util" all:)

; 目标程序：seed 装进 workspace，候选 rebind 的 define 就在那个 module 里
(define seed-path "perf/out/seed.aura")
(perf:write-text seed-path
  (string-append (perf:read-text "lib/target.aura") "\n"
                 (perf:read-text "perf/workload.aura")))

; oracle：目标自己的形状，不是「输入之和」
(define golden (string-split (perf:read-text "perf/golden.txt") "\n"))
(define (oracle xs) (list-ref golden (- (length xs) 1)))

(define spec
  (hash "label" "my-target"          ; 报告第一行
        "seed-path" seed-path
        "worker" (getenv "AURA_PERF_WORKER")
        "target" "hot-define"          ; null 候选 rebind 的那个 define
        "kernel" "bench-kernel"
        "out-dir" "perf/out"
        "heldout-n" 2
        "repeats" 5
        "min-speedup-pct" 20
        "intend" (hash "min-faster-pct" 10 "checksum" #t
                        "budget" 4 "protected" '())
        "call" (lambda (xs) (bench-kernel xs))
        "regions-fn" regions            ; 要计时的 define 和它们的 stack
        "inputs" (lambda (n) (make-cases n))
        "oracle" oracle
        "check-inputs" (lambda () (list (make-cases 1)))
        "count-defines" #t              ; 要不要每条 worldline 的树
        "catalog" catalog))
```

几点：

- **seed 是目标程序。** 运行时把它 `set-code` 进 workspace，所以候选 rebind 的
  define（`step`、`collide`、……）就住在运行时改的那个 module 里。
- **oracle 是目标自己的形状。** `inputs` 造输入，`oracle` 给出这次运行该得到的
  值，`check-inputs` 是 checksum 用的那几组。`check-inputs` 可以是一个过程：
  外部目标的输入常常要用目标自己的 define 造，而那些 define 只有 seed 装好之后
  才在 workspace 里。
- **门比的是 null 候选。** null 候选把目标 rebind 成它自己的原样，所以参照和候选
  付的是同一笔 rebind 的税（report 里是 `rebind-penalty-ms`）。目标的 define 如果不在
  seed 里而在别的 module（aura-redis 的 `src/` ✓），spec 用 `null-genome` 给出那段源码 ✓。
- **参照物按候选自己的 define 建。** catalog 里每条候选可以 rebind 另一条 define，
  那它的参照物就得是**那条 define** 的 null，不是 spec 的 `target` 的 null：一次
  rebind 本身就值好几倍（Aura runtime 上实测 2.26×），参照物没有 rebind 候选改的
  那条 define，比较就不是同一件事了。spec 用 `null-genomes`（target → 源码的表）
  或 `null-genome-fn`（target → 源码的过程）给出别的 define 的原样；seed 里定义的
  define 运行时自己从 seed 的文本里取。报告里每条候选都写着它对的是哪条参照物：
  `candidate ... ref-ms=... ref-target=...`，每条 null 也单独一行，并带着它自己的
  `rebind-penalty-ms`。
- **没有参照物的候选被拒绝。** 候选改的那条 define 没有可 rebind 的 null（spec
  没给函数体，或者函数体调用了本 module 的 private define）时，门不能默默拿别的
  define 的 null 当参照物：这条候选记 `ROLLBACK reason=reference-missing`，报告里
  写 `null-candidate target=... heldout-ms=-1 missing`。
- **每条 worldline 的树由目标自己量。** seed 可以定义
  `(perf-worldline-measure kernel xs)`：它知道自己的 define 的元数，所以能装上
  计数器、跑一次 kernel、把每个 define 的调用次数和毫秒连同自己的 stack 报回来。
  没有这个约定的目标没有这张树，报告写 `measured=0`。
- **上一次跑过的东西，这一次不重试。** 每次跑完，失败的负例（哪个想法在哪个热点上
  失败过）写到 `<out-dir>/memory.json`；下一次跑先读它，同一个热点上已经失败的想法
  直接跳过（报告里的 `negative-skip`），预算留给还没试过的。spec 可以用 `memory-path`
  换一个位置。
- **矿工不认名字。** `repeated-index-walk` 的判据是「热叶子比它同一个父节点下的
  兄弟加起来还贵 `ratio` 倍」，`protected` 来自 spec 的 intend。
- **地板可以按位点算。** 候选改的是一个 define，能赢的是那个 define 的一小片。
  intend 里的 `site-min-faster-pct` 是**按位点**的地板：候选改的那个 define（或
  catalog 条目里的 `site`）在自己的 worldline 树上快过这个百分比，门就认。整
  个目标的地板（`min-faster-pct`）仍然是第二道。报告里有一行 `site ... base-ms=
  ... cand-ms=... floor-pct=...`，每条候选行还有 `site-floor=0|1`（1 = 程序地板
  没过，是 site 地板把它留下的）。
- **两边在同一个进程里量。** worker 在候选的同一个子进程里先把 target rebind 成
  它自己的函数体（null）量一遍，再 rebind 成候选量一遍：参照物和候选于是差
  「候选本身」这一件事。跨进程的两个数还差机器的负载和分配历史（同一段代码跨进程
  能差 6%，同一个进程里只差 0.3%）。
  代价：null 先量，所以在**带 LLVM JIT 的构建**上，null 吃的是那次测量的预热
  （JIT 爬 tier），读出来偏慢，地板会偏袒候选。报告里两个参照都写出来：
  `null-candidate heldout-ms`（null job 自己那个进程量的）和候选行的 `ref-ms`
  （候选进程里量的），差得远时以 job 的那个为准。所以 job 里带 `null-genome`，worker 要把它
  量出来写进结果的 `base-cct` 和 `null-heldout-ms`；不提供这两个值的 worker 仍
  然能用（运行时退回那条 define 的 null job 的树）。
- **几毫秒上的百分比不算数。** site 地板还要求绝对差值站得住（10 ms）：10% 的地板
  要 100 ms 的 base，20% 的地板要 50 ms。


## 模型提议者

默认不联网、不读密钥，候选都来自 `perf:rule-propose`。把三个环境变量给出以后，同一轮会多问一次模型（经 `std/llm` 的 `llm:chat`，OpenAI 兼容协议）：

```sh
export LLM_API_KEY=…                              # 密钥只放环境
export LLM_BASE_URL=https://api.minimax.cn/v1
export LLM_MODEL=MiniMax-M3.1-Flash
aura-perf autotune
```

- **模型看到的只是文本。** 报告里那几行 `hotspot … self-ms= … calls= … stack=…` 和 `counter …`，门要比的数（基线中位和样本、参照物、地板），这一轮可以 rebind 的 define 的源码（protected 的标出来），catalog 里已有的想法，这个热点上失败过的想法。没有截图，也没有 data URL。接上提议者，就是把这些文本发给 `LLM_BASE_URL` 那一端，目标源码也在其中。
- **模型的回答是一份 JSON**：`{"candidates":[{"id":…,"target":…,"thought":…,"genome":…}]}`。`genome` 是那一个 define 的完整替换源码。运行时只取这四个字段，回答里其余的（`keep`、`decision`、`heldout-ms`）一概丢下：它们到不了门。
- **模型没有 KEEP 权。** 候选进同一轮 trial，过同一道门：checksum、protected、held-out、地板、总线上的约束。对的才留，错的照样 `ROLLBACK reason=checksum`。一条模型候选失败（写错、更慢、装不上）只是它自己的 ROLLBACK，规则路径的下一轮照常。
- **不占 intend 的预算。** 一次运行最多 trial `"llm"` 的 `budget` 条模型候选（缺省 2），和 intend 的 `budget` 分开记：`budget-used` 是规则路径的 trial 数，`llm-budget-used` 是模型的。
- **调用预算。** `reasoning_effort=low`，`max_tokens` 8192（模型先想再写，想的部分也算在里面；这台机器上 low 用了 180–470 个 reasoning token），一次调用 120 秒超时。`LLM_TIMEOUT` 改超时。spec 的 `"llm"` hash 可以改 `budget`、`max-tokens`、`timeout`，或换一个和 `llm:chat` 同契约的 `chat` 过程；`budget` 为 0 是关掉。
- **不是候选的回答不进 trial。** target 不在可 rebind 的 define 里、`genome` 不是恰好一个同名同参数的 `(define …)`、点名了有副作用的原语（`shell`、`write-file`、`set!`、`eval`……）、和 catalog 里某条只差排版：各记一行 `llm-rejected <序号> <原因>`。protected 的 define 由封了印的那道边界拒绝（`expert-refuse`）。
- **降级。** 没有密钥是 `llm-proposer no-provider`；只有密钥、没有端点或模型是 `no-endpoint`，密钥不会被发到 std/llm 的缺省厂商；端点不通或调用失败，`llm-proposer` 那一行写传输层自己的错误。三种情况规则路径照常走。
- **密钥不落盘。** 它不出现在任何报告行，也不出现在 `out/` 下的任何文件里。

报告里多出来的几行（接 MiniMax 跑内置例子的一次）：

```
llm-proposer ok model=MiniMax-M3.1-Flash ms=41821 candidates=1 rejected=1
llm-candidate llm-unroll-sum-scan-by-two-46b6277c target=bench-kernel thought=Unroll the bounded scan by two elements to reduce loop-condition and recursive-call overhead ...
llm-rejected 2 not-one-define
round 1 candidates linear-scan,llm-unroll-sum-scan-by-two-46b6277c
candidate llm-unroll-sum-scan-by-two-46b6277c PASS reason=gate-pass heldout-ms=264 ref-ms=337 ...
kernel KEEP id=linear-scan heldout-ms=8
llm-budget-used 1
```

模型那条过了门（264 ms 对参照 337 ms），同一轮里 `linear-scan` 更快（8 ms），KEEP 的是 `linear-scan`。判定是门给的。另外两次模型看了证据回答 `{"candidates":[]}`，报告写 `llm-proposer no-candidates`。

`aura-perf test` 用本机的假 provider 跑真实的一轮（`tests/llm_proposer_test.py`）：对的候选被门 KEEP，错的连同回答里的 `"keep": true` 一起被 checksum 打回、规则路径接着 KEEP 自己的，端点不通时这一轮和没有 provider 的那一轮相同；每一轮都逐个文件查密钥。

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
