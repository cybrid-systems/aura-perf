# aura-perf on the Aura bus (#10, aura#5128)

The round's CCT, hypotheses and verdicts go on the target workspace's
bus; the file report stays as the human-facing view. Enabled by the
spec's `"bus"` hash (`"workspace" N`) or `AURA_PERF_BUS_WORKSPACE=N`.
Without either, every bus function is a no-op and the round runs
exactly as before.

## Lifecycle

The perf parent owns the seed workspace, so it **hosts** the bus
(`bus:host`, aura ≥ the #5128 wiring) and attaches as the perf peer:
role 1, caps `read|publish|trial|keep|rollback` (31) — perf *accepts*
constraints, it does not write them. One peer is served at a time by
the current host; after `perf:bus-finish` detaches, the host keeps
serving, so harness or maintainer attaches next and queries the same
audit and image. Simultaneous multi-peer attachment is the aura-side
follow-up (see docs/bus.md there).

Workers stay on the internal job exchange (`out/jobs`, `out/trials`) —
that is one tool's own mechanics. The bus is the **inter-tool** main
path: CCT, hypotheses, verdicts and the audit no longer need temp files
to be seen by the other tools.

## Channel mapping

The image carries immediates, not text; the mapping is:

| channel | what perf writes |
|---|---|
| cct | one record per profile name, published in stack order so parent indices point backward; `mid` = rolling name hash (×31, mod 999999937, low 62 bits); `node` = -1; `samples` = calls; `self-ns` = self-ms × 1e6. A hypothesis adds a mark record: `mid` = hash(candidate id), samples 1. |
| metrics | hypothesis key K (1, 2, … per round) → the base-ms the candidate must beat; the report line `bus-hypothesis <id> key=K base-ms=N` names the pair. Summary: 900001 → before-ms, 900002 → after-ms. |
| worldlines | one `bus:trial` per trialable candidate; the verdict is `bus:keep` (value = heldout-ms) or `bus:rollback`. |
| patches | at finish, `bus:project-patches` then `bus:project-worldlines` project the round's real committed mutations (order matters: patches first, so worldline records carry patch ranges). |

## Constraints are accepted, never bypassed

`bus:keep` runs the coordinator's current constraint set. A rejection
(`constraint-rejected`) downgrades the candidate to ROLLBACK with
reason `bus-constraint-rejected` in the report, the memory and the
file audit — the same path a gate failure takes. There is no local
switch that skips the bus gate; `AURA_SANDBOX=off` does not affect an
attached session (aura's delivered semantics).

## Exit semantics

`perf:bus-finish` publishes the summary, projects the mutations, says
the audit count, and detaches. The coordinator rolls back whatever the
session left pending and reclaims its loans (the delivered disconnect
semantics) — un-KEEP'd trial changes do not outlive the tool.

## Report lines

```
bus attached ws=992 role=perf session=1
bus cct-records 9
bus-hypothesis flatten-fast key=1 base-ms=7709
bus-worldline flatten-fast wl=1 verdict=kept|rolled|constraint-rejected: <why>
bus audit-events 23 ws=992
bus detached (host stays for harness/maintainer)
```

## Tests

`tests/bus_test.aura` (golden-matched): host + perf peer, CCT and
hypothesis publication, kept/rolled verdicts, the shared audit; then an
expert peer attaches, installs `allow-small` and reads perf's audit,
and the next perf KEEP (200 ms) is rejected by it — the constraint
gate, end to end, in one process.
