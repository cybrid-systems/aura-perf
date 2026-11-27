# Roadmap

定位见 [capabilities.md](capabilities.md)。aura-perf 是 agent 的优化运行时：证据、假设、门和审计都是 Aura 值。被优化的是用户的程序（本仓库示例是一个链表扫描），不是 Aura 解释器。

## 现在

`aura-perf autotune` 跑完一轮。每个 worldline 有一棵 CCT，可以查询哪次 mutation 去掉了同一条热前缀且没有把代价挪走；每个 trial 还带 compile/mutate/jit/arena 的 engine 差分（`trial-engine`，候选行 `rebuild=`），重编译和测量分开写。初始 profile 可以由 spec 的 `profile-command` 在一个 batch child 里量完所有 region（`measure=batch-child`），不再为每个 region 起一个进程。self-host 模式下每轮 trial 是 bus 上的一张 task：post + 10 分钟 lease + complete/fail（`bus-task open/close`）；attach-only 不发 task，judge 拥有任务板。打开 `task-workers` 后，每个候选 job 也是任务，worker 子进程自己 `bus:claim` 后执行并 complete/fail；judge 仍在 perf 父进程。目标没写 `perf-worldline-measure` 时，运行时用 `lib/perf/probe.aura` 从 seed 的顶层 define 自动生成同一组探针；报告用 `cct-source=auto-probe` 标明，目标自己的测量仍然优先。负例按 `class` + `hot-node` 记住。分类阈值和 catalog 顺序是策略基因，走 KEEP / ROLLBACK。intend 封在门里。没有 perf 二进制时 CCT 用 region timer 的毫秒，并写明硬件计数器没有读。`aura-perf sysinfo` 和 `aura-perf check` 把这台机器的 CPU、内存、NUMA、中断和工具有无收成可查询的值。

`autotune` 和 `recheck` 也可以带一个外部项目的 spec，目标和 region 都由目标项目自己给（见 README 的「外部目标」）。

## 业务要什么

下面这些数字是在 [aura-runner](https://github.com/cybrid-systems/aura-runner) 的物理路径上量到的（`perf/` 里的两个 spec，aarch64，没有 perf binary，走 region timer）。

**服务器 tick 和公平性门走的是同一段物理。** 物理那条路：

```
hotspot bench-kernel self-ms=636 calls=1     share=47
hotspot collide      self-ms=373 calls=600   share=27
hotspot step-poppers self-ms=94 calls=600   share=6
hotspot nudge-flyers self-ms=91 calls=600    share=6
hotspot over-gap?    self-ms=73 calls=600    share=5
hotspot pxs          self-ms=45 calls=18000  share=3
hotspot pset         self-ms=41 calls=7800   share=3
```

autopilot（公平性门那条路）：

```
hotspot autopilot-kernel self-ms=6858 calls=1   share=77
hotspot step             self-ms=872  calls=900 share=9
hotspot autopilot-press  self-ms=336  calls=900 share=3
hotspot collide          self-ms=280  calls=900 share=3
hotspot next-hazard      self-ms=157  calls=900 share=1
hotspot dodge-flyer      self-ms=82   calls=900 share=0
hotspot dodge-block      self-ms=81   calls=900 share=0
hotspot flyer-blocking?  self-ms=72   calls=900 share=0
hotspot block-ahead?     self-ms=67   calls=900 share=0
```

三件事是业务要的：

1. **一处改动，两条路都赚。** autopilot 的时间有大约六成在 `step` 里（`collide` 是里面最热的一块），服务器 tick 也是同一段代码。改 `collide` / `step` 一次，tick 和公平性门一起快。aura-perf 现在按「目标程序」分 spec，看不出这种共享。
2. **一个 define 的改动最多只能赢目标的一小块。** 上面物理那条路里，最热的单点 `collide` 占 27%；收紧窗口这种改法最多赢它的一部分，也就是个位数百分比。现在 `intend` 的 `min-faster-pct` 是**整个目标**的地板（20%），所以这类改动永远过不了门 —— 门把「改对了地方」判成「没赢」。
3. **行为不变要由目标自己的门来证。** aura-runner 的门是 `aura test` 的 golden（物理轨迹逐字节相同），不是「输入求和」。aura-perf 的 oracle 已经交给目标给（`inputs` / `oracle` / `check-inputs`），但门还是只能比对一个自定义的摘要；目标自己的测试命令（`aura test`）应该能直接当 checksum 用。

## 工具：aura 有、aura-perf 还没用上的

- **类型门当便宜的预筛。** ✅ 做了：`(mutate :check)` 在父进程 dry-run parse + typecheck，失败记 `type-gate`，不写 job、不起子进程、不花 held-out；构建没有这个原语时退回 trial。
- **JIT 的预热税。** 一次 rebind 会让 JIT 重编译，实测 40–60% 的税（见 findings 的历史条目）。held-out 的第一个样本带着这段税，中位数能盖住，但报告会应该把「null 候选的时间」和「mutation 自己的效果」分开写：候选时间 − null 时间 = mutation 的效果，null 时间 − 基线 = rebind 的税。现在 null 候选已经在跑，门也用它，但报告没有把三段拆开。
- **稳态而不是第一个样本。** held-out 应该丢掉第一次（预热）再取中位，并把丢掉的那次写在报告里。
- **目标自己的测试命令当 checksum。** spec 可以给一条命令（`aura test`），运行时的门跑它、读它的退出码和 golden 差异。
- **`ast:snapshot` / `ast:restore`** 已经在用（回滚 ✓）；**`evo:trial`** 已经在用（worldline ✓）；**`orch:parallel`** 已经在用（一轮候选并行 ✓）；**`engine:metrics`** 已经在用（KEEP 的编译计数 ✓）。
- **fiber**：LLM proposer 那一路（`perf:llm-propose` 已经接上 std/llm，aura-perf#29）现在和 headroom probes 用 `orch:parallel` 并行，join 后才进第一轮；`orch` 不可用时顺序执行。
- **`ast:unparse` / `current-source`** 的 round trip 现在是坏的（findings 9、10）：那是 Aura 的两条 P0，aura-perf 不改 Aura，但目标程序要知道（目标可以把会写成科学计数法的字面量换掉）。

## 策略：aura-perf 该怎么变

按「能不能让上面那三件业务要求成立」排。

### 1. 地板按位点算，不按整个目标算 —— ✅ 做了

intend 现在可以带一个按位点的地板 `site-min-faster-pct`。位点的两段时间都来自
worldline 树（基线那棵和候选那棵），所以两边是同一种量；候选 catalog 条目可以写
`site`（默认是它 rebind 的那个 define）。报告里有一行 `site <name> base-ms=…
cand-ms=… floor-pct=…`。整个目标的地板留成第二道。

门、决定、best-passing 的挑选、失败名单、commit 之后的复核和最后的 verdict 问的是
同一个问题（程序地板或位点地板），所以「PASS」和「KEEP」不会各说各话。rebind 的税是
程序层面的东西，位点地板也回答它。

`tests/site_floor_test.aura` 钉住它：程序没快 20% 但位点快了 30% 的候选过门，位点
不够快的不过，位点没被量的不过。sum-scan 的例子 verdict 不变。

在 aura-runner 的物理目标上，这个地板第一次真的判出了一个 KEEP：

```
candidate collide-slack PASS reason=gate-pass
site collide base-ms=461 cand-ms=339 floor-pct=20
kernel KEEP id=collide-slack heldout-ms=1339
compile-delta world-rebuilt=0 cascade-full=0 body-only=2 relower-full=36
```

### 2. 一个候选可以是一组改动 —— ✅ 做了

catalog 条目现在可以带 `genomes`（一组 `(target, genome)`，或 target → genome 的 hash）。worker 先按 `null-mutations` 量整组 null 的 base，再把整组 candidate 依次 `mutate:rebind`，最后只 `eval-current` 一次；任何一条失败，整条 worldline 回滚。类型门逐条 dry-run，protected 和引用检查按组，位点地板按组求和。报告 `ref-target=a+b`、`site a+b base-ms=… cand-ms=…`。测试：`tests/candidate_set_round_test.py`；sum-scan 自己的 KEEP / ROLLBACK 不变。

### 3. 天花板探针：先量「这个位点最多能快多少」—— 部分做了

已做：autotune 在每轮预算前跑 headroom job，在自己的 worldline 里把位点的当前绑定 `set!` 成便宜 stub，跑一次 kernel 再恢复；和 fresh baseline child 比较。报告写 `site-headroom <site> base-ms=… free-ms=… headroom-pct=…`，候选行带 `headroom-pct`；stub 让 kernel 抛错时写 `site-headroom-unavailable`。kernel 和 protected 位点默认不探，`headroom-max` 限制数量，`headroom #f` 关闭。

策略已经用上：候选按 `headroom-pct` 从高到低排（`headroom-order #f` 关闭），`headroom-min-pct` 让上限不够的候选不进这一轮（`headroom-skip`），不占预算。没余量的位点也写进跨次负例：上限低于 `headroom-forget-pct` 时记 `headroom-no-room`，下一次报告 `headroom-remembered` 并跳过探针。

### 4. 便宜的 screen 量位点，不量整个目标 —— 做了

screen 的同一轮里量 screen 输入的 worldline 树，决策读候选位点（组求和）对 null base 的同一组位点；base 没有位点时退回整 kernel。候选行带 `screen-site-ms` / `screen-base-site-ms`，`screen-pruned` 不再花 held-out。

还剩下噪声：位点目前只量一次；量几次取中位数是 seed 自己的事（`perf-worldline-measure` 是目标写的），运行时把地板和噪声分开即可。

### 4b. 基线和候选要交错着量

基线在跑的开头量一次 ✗，候选在一轮之后量 ✗ —— 机器的负载在这中间变了 ✗，两个数
不是同一个时刻的 ✗。aura-runner 那次跑出来的基线是 1313 ms / 1388 ms / 1400 ms 三
个不同的值 ✗。null 候选（门自己的参照 ✓）应该每一轮都重测 ✓，那一轮的候选就对着同一
时刻的参照比 ✓。

### 5. 门把三段时间拆开 —— ✅ 做了

基线（未 rebind）、null 候选（rebind 到自身）、候选（rebind 到新写法）三段时间都在报告里，并写明：mutation 的效果 = 候选 − null，rebind 的税 = null − 基线。`split <id> raw-ms=… null-ms=… cand-ms=… mutation-effect-ms=… rebind-tax-ms=…`；候选行和 audit evidence 也带这两个差值。用户在 aura-runner 上看到的正是这个区分：`pxs-listref` 那个候选「慢 35%」其实全是 rebind 的税。

### 6. checksum 走目标自己的门

spec 给一条命令和它的 golden，运行时跑它、读退出码。aura-runner 的门是 `aura test`（物理轨迹逐字节相同）；现在的做法是目标自己写一份摘要当 oracle，等于把门重写一遍。

验收：一个 spec 只给命令就能有 checksum；oracle 的形式（摘要）仍然是备选。

### 7. 假设从 catalog 来 —— ✅ 做了

`perf:mine` 现在优先用 profile 上的 `catalog`：每条 catalog 条目带自己的 `target` / `site`、`expect`、`counter`，class 只决定顺序；gene 的 order waste 也读这张表。没有 catalog 的 profile 才回退到内置的 sum-scan 四个 id。sum-scan 的 catalog 补了 `expect` / `counter`，报告不变；外部目标不再看到 sum-scan 的假设 id。测试：`tests/hypotheses_test.aura`。

### 8. 负例按位点记 —— ✅ 做了

负例**跨次**累积了（每次跑完写 `<out-dir>/memory.json`，下一次跑先读回来，已经失败
过的想法直接跳过，预算留给没试过的 ✓），键也从 `(class, hot-node)` 换成了
`(site, hot-node)`：class 是矿工的结果，会跟着机器的噪声动，同一个目标两次跑可能
被分成不同的 class，按 class 记的负例就漏了。aura-runner 的物理目标上就是这个：
两次跑的 class 一个是 `flat-hot` 一个是 `repeated-index-walk`，按位点记才拦得住。

### 9. LLM proposer 的契约扩到一组改动

`perf:llm-propose` 接上了模型（aura-perf#29）：一条候选就是一条 catalog 条目，一个 define，从文本证据提出来，由同一道门判。契约仍然假设一个候选一个 define。模型提的往往是「这几处一起改」，所以候选 hash 要能带一组，模型返回的也要是同一份 hash（一个 define ✓，扩到一组还没）。

## 顺序

1. ~~地板按位点算（1）~~ ✅ + screen 量位点（4）：第一条已经做了，第二条还没。
2. 天花板探针（3）+ 负例按位点（8）：让策略知道预算该花在哪。
3. 候选是一组改动（2）+ 门拆三段时间（5）：让「几处一起改」这种真实形态可判。
4. checksum 走目标自己的门（6）+ 假设从 catalog 来（7）：让目标和运行时的约定只写一遍。
5. LLM proposer（9）。

## 接着做

- ~~把 `/proc/PID/schedstat` 接进 trial~~ ✅：runqueue wait、timeslice、context switch
  的差值已进候选行和报告，不需要 root。
- ~~USE 的 CPU/内存/调度层~~ ✅：`aura-perf use` 输出 utilization/saturation/errors，
  内存饱和看 vmstat 活动而不是 swap 占用。
- perf sched / ftrace / bpftrace 需要权限，先走 doctor 的 ask 行；它们的 adapter 还没接。
- 语义火焰：节点可以是策略阶段或规则。
- `perf c2c` / `perf mem` / `perf sched` 现在只探测子命令在不在；`aura-perf doctor` 明确写 `wired=no`。PMU 可用时才采样，并仍不把缺测写成 0。
- bpftrace / bcc 只在已经安装时登记，不附带脚本；`doctor` 报告 `probe-only`，安装命令显式列出。
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
- 不替目标程序发明业务指标。门槛、oracle、protected、catalog 都由目标给；运行时只负责量、判、记、留证据。
