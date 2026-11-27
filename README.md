# aura-perf

Evidence-driven performance work for agents and humans.

Two modes:

- **Aura targets** (`autotune`): mine a profile, trial candidates in isolated worldlines, keep or roll back through a deterministic gate.
- **Any native process** (`profile`): `perf`-based hotspots for Redis, PostgreSQL, a game server, a batch binary. No Aura project, no API key.

Runs on a **pinned Aura nightly**. No virtualenv, no config file, no LLM required.

## Install

One command:

```sh
curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-perf/main/install.sh | sh
aura-perf
```

The installer clones the repo, installs the Aura nightly pinned in
[`baseline/aura-baseline.json`](baseline/aura-baseline.json), and links
`aura-perf` into `~/.local/bin`.

From a checkout, the same install:

```sh
git clone https://github.com/cybrid-systems/aura-perf.git
cd aura-perf && ./install.sh
```

Use an existing nightly instead of downloading:

```sh
AURA_BIN=/path/to/aura ./install.sh
```

Requirements: `sh`, `curl`, `tar`, `python3`, and `git` for the curl
installer. `perf` is optional and only used by `profile`. Override the
install directory with `AURA_PERF_DIR`, the bin directory with `PREFIX`.

## Quick start

```sh
aura-perf                 # autotune the built-in sum-scan example
aura-perf help            # verbs and environment
aura-perf test            # value tests + round tests
```

No LLM key is needed. If `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`
are unset, autotune uses the rule proposer only. Unset is the default and
is fully supported.

## Profile any process

```sh
# attach to a running server
aura-perf profile --pid "$(pgrep -n redis-server)" --seconds 10

# or launch a command under perf for N seconds
aura-perf profile --seconds 10 -- ./my-benchmark --arg
```

Outputs, in the current directory:

- `out/profile.txt` — top self symbols, DSO summary, counters
- `out/profile.json` — the same top rows for agents
- `out/perf.data` — raw `perf` data

Example with Redis:

```sh
redis-server --port 6390 --save '' --appendonly no &
aura-perf profile --pid "$(pgrep -n redis-server)" --seconds 10
```

This needs a usable `perf` on the machine. If the PMU does not expose a
counter, it is reported as `<not supported>`; nothing is invented.
`perf record -p` may require `perf_event_paranoid` or root.

**Boundary:** `profile` finds hotspots for any native program. `autotune`
needs an Aura target (a seed with rebindable Aura defines and an oracle);
it does not rewrite C/C++/Redis code. Use `profile` to locate a Redis
bottleneck, then optimize that project in its own language.

## Autotune an Aura target

The default run uses `examples/sum-scan`:

```sh
aura-perf
cat out/report.txt
```

With an external Aura spec:

```sh
cd my-project
aura-perf autotune perf/spec.aura
```

A spec is a normal Aura file: seed source, timed regions, inputs, oracle,
protected defines, catalog. See
[`docs/capabilities.md`](docs/capabilities.md) and the example in
[`examples/sum-scan/main.aura`](examples/sum-scan/main.aura).

The report's first line is the verdict, e.g.:

```text
verdict intend-met=1 KEEP=3 ROLLBACK=6 speedup-x=81.25 (325ms->4ms n=5 spread=120->0ms)
```

Exit code matches the verdict: `0` when `intend-met=1`, non-zero otherwise.
`aura-perf recheck` re-applies the saved round without re-profiling.

## Optional model proposer

The model only proposes; the checksum, protected set, held-out floor and
budget still decide. Enable it with three variables:

```sh
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.minimax.cn/v1
export LLM_MODEL=MiniMax-M3.1-Flash
aura-perf autotune
```

Leave them unset to run without any network call. Keys are never written
to reports or `out/`.

## Commands

| command | what it does |
|---|---|
| `aura-perf` | `autotune` the built-in example |
| `aura-perf autotune [spec]` | profile, mine, trial, gate |
| `aura-perf recheck [spec]` | re-judge the saved round |
| `aura-perf profile --pid PID` | native `perf` profile for any process |
| `aura-perf sysinfo` | machine inventory |
| `aura-perf check` | 1s CPU/disk/network/interrupt deltas |
| `aura-perf doctor [--install]` | evidence-source readiness, exact install and permission commands |
| `aura-perf test` | runtime and round tests |
| `aura-perf install` | install nightly if needed, link the command |

## Environment

| variable | default |
|---|---|
| `AURA_BIN` | installed pinned nightly, then `aura` on `PATH` |
| `AURA_PATH` | resolved from the Aura binary |
| `PERF_BIN` | auto-detected usable `perf` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | unset; no model call |
| `AURA_PERF_DOCTOR_GROUPS` | groups `doctor --install` may install (default: non-optional) |
| `AURA_PERF_DIR` | `~/.local/share/aura-perf` for the curl installer |
| `PREFIX` | `~/.local/bin` |

More: [`docs/capabilities.md`](docs/capabilities.md),
[`docs/bus.md`](docs/bus.md), [`docs/roadmap.md`](docs/roadmap.md).
