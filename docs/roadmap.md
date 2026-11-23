# Roadmap

定位见 [capabilities.md](capabilities.md)。aura-perf 是 agent 的优化运行时：证据、假设、门和审计都是 Aura 值。被优化的是用户的程序（本仓库示例是一个链表扫描），不是 Aura 解释器。

## 现在

`aura-perf autotune` 跑完一轮。每个 worldline 有一棵 CCT，可以查询哪次 mutation 去掉了同一条热前缀且没有把代价挪走。负例按 `class` + `hot-node` 记住。分类阈值和 catalog 顺序是策略基因，走 KEEP / ROLLBACK。intend 封在门里。没有 perf 二进制时 CCT 用 region timer 的毫秒，并写明硬件计数器没有读。`aura-perf sysinfo` 和 `aura-perf check` 把这台机器的 CPU、内存、NUMA、中断和工具有无收成可查询的值。

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

- **类型门当便宜的预筛。** `mutate:rebind` 自己过 selective typecheck，类型不过的候选连计时都不该跑。现在候选是直接进 trial 的。
- **JIT 的预热税。** 一次 rebind 会让 JIT 重编译，实测 40–60% 的税（见 findings 的历史条目）。held-out 的第一个样本带着这段税，中位数能盖住，但报告会应该把「null 候选的时间」和「mutation 自己的效果」分开写：候选时间 − null 时间 = mutation 的效果，null 时间 − 基线 = rebind 的税。现在 null 候选已经在跑，门也用它，但报告没有把三段拆开。
- **稳态而不是第一个样本。** held-out 应该丢掉第一次（预热）再取中位，并把丢掉的那次写在报告里。
- **目标自己的测试命令当 checksum。** spec 可以给一条命令（`aura test`），运行时的门跑它、读它的退出码和 golden 差异。
- **`ast:snapshot` / `ast:restore`** 已经在用（回滚 ✓）；**`evo:trial`** 已经在用（worldline ✓）；**`orch:parallel`** 已经在用（一轮候选并行 ✓）；**`engine:metrics`** 已经在用（KEEP 的编译计数 ✓）。
- **fiber**：LLM proposer 那一路（`perf:llm-propose` 已经接上 std/llm，aura-perf#29；调用还是同步的）应该跑在 fiber 上，不占门的时间。
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

### 2. 一个候选可以是一组改动

catalog 里现在一条候选改一个 define。业务上的「让游戏更快」常常是几处一起改（`collide` 的窗口 + 每帧重建列表的两处 = 物理那条路的一半）。候选的 genome 应该是一组 `(target, genome)`，worker 一起 apply，回滚也一起回。

验收：a 条候选能同时改几个 define；sum-scan 的例子 KEEP / ROLLBACK 构成不变。

### 3. 天花板探针：先量「这个位点最多能快多少」

把一个 define 换成空实现，跑一次 trial，得到的差值就是这个位点能拿到的**上限**。策略据此决定预算花在哪：上限小的位点不值得试，负例里也该记「这个位点没有余量」（现在负例只记「这个想法在这个热点上失败过」）。

这是 aura-perf 现在最缺的一样东西：它能说「这个想法失败了」，不能说「这个位点没救了」。

验收：报告里每个候选带一个上限数字；策略能用上限排序；上限低于某个阈值的位点不进候选。

### 4. 便宜的 screen 量位点，不量整个目标 —— 还差一半

位点的地板已经用上了 ✓（位点的时间来自 worldline 树 ✓），但 screen 还在量整个
kernel ✗，而且位点的时间只量了一次 ✗：机器一忙，位点的数字就抖（aura-runner 那次
461→339 赢、下一次 543→526 就输了 ✗）。量几次取中位数，是 seed 自己的事
（`perf-worldline-measure` 是目标写的 ✓），运行时只要把位点的地板和噪声分开 ✓。

### 4b. 基线和候选要交错着量

基线在跑的开头量一次 ✗，候选在一轮之后量 ✗ —— 机器的负载在这中间变了 ✗，两个数
不是同一个时刻的 ✗。aura-runner 那次跑出来的基线是 1313 ms / 1388 ms / 1400 ms 三
个不同的值 ✗。null 候选（门自己的参照 ✓）应该每一轮都重测 ✓，那一轮的候选就对着同一
时刻的参照比 ✓。

### 4. 便宜的 screen 量位点，不量整个目标

screen 现在量整个 kernel，位点上 25% 的赢在噪声里看不见。screen 应该量热叶子的那个 region（region timer 已经按 define 分开了 ✓），于是「这个位点快了 25%」在便宜的一轮就能看见。

验收：screen 的毫秒是位点的毫秒，报告写明是哪个 region；sum-scan 的 screen 结论不变。

### 5. 门把三段时间拆开

基线（未 rebind）、null 候选（rebind 到自身）、候选（rebind 到新写法）三段时间都在报告里，并写明：mutation 的效果 = 候选 − null，rebind 的税 = null − 基线。用户在 aura-runner 上看到的正是这个区分：`pxs-listref` 那个候选「慢 35%」其实全是 rebind 的税。

### 6. checksum 走目标自己的门

spec 给一条命令和它的 golden，运行时跑它、读退出码。aura-runner 的门是 `aura test`（物理轨迹逐字节相同）；现在的做法是目标自己写一份摘要当 oracle，等于把门重写一遍。

验收：一个 spec 只给命令就能有 checksum；oracle 的形式（摘要）仍然是备选。

### 7. 假设从 catalog 来

`perf:hypotheses` 现在返回的是 sum-scan 那四个 id。catalog 的每一条本来就可以带自己的 `expect`（门会怎么判、要动哪个计数器），假设应该就是 catalog 的那些条目，class 只决定顺序。

验收：外部目标的 class 不是 sum-scan 的假设 id；sum-scan 的报告不变。

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
- 不替目标程序发明业务指标。门槛、oracle、protected、catalog 都由目标给；运行时只负责量、判、记、留证据。
