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
