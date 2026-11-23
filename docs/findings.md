# Aura v0.2.0 上看到的行为

下面都是在 `aura 0.2.0` 的 linux-x86_64 release 包上复现的。aura-perf 用工作区绕开，没有改 Aura。

## 1. `evo:trial` 的 apply 和 `evo:default-apply` 元数不一致

`std/evo-core` 里 `evo:commit!` 调用 `(apply-fn s cand)`，`evo:default-apply` 的参数就是 `(s c)`。`evo:trial` 调用的是 `(apply-fn cand)`，只有一个参数。

把 `evo:default-apply` 直接交给 `evo:trial` 时，审计日志是：

```
ROLLBACK  trial-error: ... arity mismatch: apply-fn expects 2 arguments, got 1
```

live workspace 没有被改。aura-perf 的 trial 使用单参数 apply。这是 v0.2.0 `lib/std/evo-core.aura` 里 trial 和 commit 两条路径不一致。

## 2. `preset=dev` 下子 workspace 拒绝 mutation

`aura --preset dev` 打印 `sandbox=restricted caps=mutate,read,write`。Workspace 0 上 `mutate:rebind` 成功。`evo:trial` 切到 `workspace :create` 出来的子 workspace 之后，同一次 `mutate:rebind` 返回：

```
(cow-refused mutate:rebind: COW refused (read-only layer) . 0)
```

`evo:trial` 记 `ROLLBACK`，`live-unchanged` 为真。`AURA_SANDBOX=off` 之后同一种 trial 的 status 是 `ok`，子 workspace 里的改写生效，父指纹不变。

`std/evo-core` 的注释写了 restricted / `aura soft` 只给 workspace 0 mutate。`preset=dev` 仍然是 restricted sandbox，所以 forked worldline 上的改写要显式关掉 sandbox。示例脚本因此导出 `AURA_SANDBOX=off`。

## 3. `aura-executable-path` 不是 `aura` 启动器

在这份 release 包里 `(aura-executable-path)` 是 `.../rt/ld.so`。环境变量 `AURA_BIN` 才是 `bin/aura`。用前者再起子进程不会跑 Aura 程序。trial 启动器用 `AURA_BIN`，缺省才退回 `PATH` 上的 `aura`。

## 4. 子进程 evo 日志里的 KEEP 不是 live KEEP

`mutate:rebind` 成功时引擎会写一条 `decision=KEEP`。这发生在 trial 子进程的 workspace 里，进程结束就没了。同一条 trial 日志里的 `evo:trial` 记录是 `TRIAL` / `isolated`，`live-before` 等于 `live-after`。父进程指纹在 parallel trial 前后不变。

算 KEEP / ROLLBACK 以父进程 `out/report.txt` 的 `decisions` 行为准，不要把 `out/trials/*.jsonl` 里的 rebind KEEP 加进去。

## 5. `std/string` 的 `string-trim` 只去掉空格

`string-trim` 只判断字符码 32。`read-file` 读到的 `/proc/sys/kernel/perf_event_paranoid` 带换行，trim 之后仍会把换行留在字符串里，打进报告就会多出一个空行。aura-perf 自己去掉 `<= 32` 的字符，不依赖这个函数。

## 6. workspace 的 mutate typecheck 看不见宿主绑定

`set-code` 装入的 define 如果直接调用宿主里已经 `require` 的 `perf:mine`，下一步 `mutate:rebind` 的 selective typecheck 会拒绝 mutation，原因是 `unbound variable: perf:mine`。把 `(require …)` 写进被 `set-code` 的源码也不行：`require` 自己被报成未绑定变量。

把查询过程作为值放进调用参数（策略里 `(let ((mine (hash-ref ctx "mine"))) (mine profile))`）可以通过这次 typecheck，rebind 返回 `#t`。aura-perf 的 `perf-strategy` 因此从 `ctx` 取 `mine`，不在 workspace 源码里写宿主函数名。

## 7. `set-code` 之后，restricted sandbox 里 `engine:metrics` 会 SIGABRT

`AURA_SANDBOX` 不是 `off` 时，`set-code` + `eval-current` 之后再调 `(engine:metrics)` 或 `(engine-metrics:group "compile")`，进程收到 SIGABRT，`try` 接不住。`AURA_SANDBOX=off` 时同一调用返回 compile 组计数。示例脚本因此一直导出 `AURA_SANDBOX=off`。`perf:compile-snap` 在 sandbox 不是 `off` 时直接返回 `available=0`，不去碰那个原语。

## 8. Aura `main` 的命名 `let` 不可重入

支持的构建是 `aura 0.2.0`，commit `cf7353373`（tag v0.2.0）。在这份构建上，同一个命名 `let` 连调两次，每次都按自己的参数算：`(sum 3)`、`(sum 7)`、`(sum 2)` 得到 `3`、`21`、`1`。

Aura `main` 从 [#5102](https://github.com/cybrid-systems/aura/pull/5102)（`6aa43942a`，为 CLI fiber 整数循环加的闭包元数据缓存）起，这个循环在单线程路径上不可重入。第二次调用交回第一次的结果。issue 在 `245e05589` 上复现。`perf:parse-cpu-totals` 和 `perf:strip-noise` 都是这种循环。不探测的话，运行时在走到下标时抛出 `string-ref: index out of bounds`，源码位置落在被索引的字符串字面量上。`aura-perf sysinfo` 和 `aura-perf check` 走同一条路径，在这份构建上退出非 0。

上游：https://github.com/cybrid-systems/aura/issues/5116

aura-perf 不改 Aura。`tests/runtime_probe.aura` 用上面的三次 `sum` 做探测。v0.2.0 上打印 `named-let-reentrant`。坏的构建上，错误文本带这次的 `aura -V`（`AURA_PERF_BUILD`）、三次调用的实际值、支持的版本和上游链接。解析器的 `perf:char-at` 在下标越界且探测失败时抛同一段文本；探测通过时，越界仍是带下标和长度的 `string-ref: index out of bounds`。`aura-perf test` 在 `aura test` 非 0 时再打一行构建号。探测失败不会把别的失败记成通过，suite 继续跑完。

## 9. 工作区源码里的科学计数法浮点字面量被写成非法文本

`(current-source :workspace)` 把最短写法是科学计数法的浮点写成 `<科学计数法>.0`：

| 值 | 最短写法 | unparse 写出来的 |
|---|---|---|
| `0.0001` | `1e-04` | `1e-04.0` |
| `0.00001` | `1e-05` | `1e-05.0` |
| `1e20` | `1e+20` | `1e+20.0` |

`1e-04.0` 不是一个数：reader 读出 `1e-04`，再读出 `.0` 两个 literal，form 的元数就变了。

```sh
cat > /tmp/aurashow.aura <<'EOF'
(set-code "(define (f x) (<= x 0.0001))")
(eval-current)
(display (f 0.0))
(display (current-source :workspace))
EOF
AURA_SANDBOX=off aura --preset dev /tmp/aurashow.aura
```

```
#f
(define f (lambda (x) (<= x 1e-04.0)))
```

同一个程序写成文件（不 set-code）答案是 `#t`。`(<= 0.0 0.0001)` 在 round trip 之后从 `#t` 变成 `#f`，`(list 1.0 0.0001)` 变成三个元素。

`AURA_SANDBOX=off` 时 mutation 路径自己会重新 parse 这段文本，于是 `set-code` 装进去的程序算出来的值和源码不一样，而且不报错。round trip 在任何 sandbox 模式下都是坏的。

上游：https://github.com/cybrid-systems/aura/issues/5295

aura-perf 不改 Aura。目标程序自己带 oracle 时，这条是目标自己的事：把会写成科学计数法的字面量换成位相同的写法即可（`0.0001` 写成 `(/ 1.0 10000.0)`，`(equal? 0.0001 (/ 1.0 10000.0))` 是 `#t`）。

## 10. `evo:trial` 里的 `mutate:rebind` 把变参 define 变成定参

```sh
cat > /tmp/auravar.aura <<'EOF'
(require "std/evo-core" all:)
(set-code "(define (f a . rest) (list a rest)) (define (g x) (+ x 1))")
(eval-current)
(define body "(define (g x) (+ x 2))")
(define cand (evo:candidate body (hash "target" "g" "thought" "x")))
(define evaluate (lambda (c) (hash "status" "ok" "objectives" (hash "heldout-ms" 1) "constraints" (hash "checksum" 0) "behavior" (hash "mismatches" 0))))
(define apply-candidate (lambda (c) (let ((rb (mutate:rebind "g" body "t"))) (if (eq? rb #t) (begin (eval-current) #t) rb))))
(define tr (evo:trial cand (hash "apply" apply-candidate "timeout-ms" 60000 "evaluate" evaluate)))
(display (f 1 2 3))
EOF
AURA_SANDBOX=off aura --preset dev /tmp/auravar.aura
```

```
arity mismatch: f expects 2 arguments, got 3
```

变参标记丢了：`(define (f a . rest) ...)` 之后 `f` 只收两个参数。trial 的 status 还是 `ok`，报错出现在之后调用 `f` 的时候，而且 outlives 这个 trial：父 workspace 也坏了。

同一个 rebind 在 trial 之外是好的，`AURA_SANDBOX` 不是 `off` 时 trial 也是好的。

上游：https://github.com/cybrid-systems/aura/issues/5296

这条挡住了 aura-perf 对带变参函数的目标：每个候选的 checksum 都以 `car: not a pair` 失败，看起来像候选写错了，其实不是。aura-runner 的 `lib/phys.aura` 有 `(define (piece k x w h y . rest) ...)`，所以它的每个候选都这样失败。

## 11. `evo:trial` 把违反约束的 trial 记成 `infeasible`

Aura #5255 起（nightly `b242f5a8c` 上确认），evaluate 的结果违反硬约束时 `evo:trial` 给的 status 是 `infeasible`，不再是 `ok`：`constraints` 里有一项大于 0 就是。aura-perf 的 worker 只声明一条约束 `checksum`，所以 checksum 不过的候选现在写成：

```
candidate wrong-scale ROLLBACK reason=infeasible: checksum heldout-ms=-1 ref-ms=349 ...
```

aura-perf 原先把 status 不是 `ok` 的 trial 一律当成「trial 没跑完」。于是全新的一次运行（`out/memory.json` 还不存在，`wrong-scale` 进了 trial）在第一轮之后停下：

```
strategy ROLLBACK reason=trial-infrastructure
kernel unchanged
verdict intend-met=0
```

CI 上看不出来：前一步的 bus 测试先把 `wrong-scale` 和 `redundant-pass` 记进了负例，autotune 那一步把它们跳过了。

aura-perf 不改 Aura。`perf:judged?` 把 `ok` 和 `infeasible` 都读成「对候选有了结论」；`perf:result-reject` 对 `infeasible` 给出 `checksum`（和 #5255 之前的报告一字不差），别的约束保留 trial 自己的话；`perf:any-infra?` 不再把它算成基础设施故障。`tests/infeasible_test.aura` 和 `tests/checksum_round_test.py` 盯着这条。
