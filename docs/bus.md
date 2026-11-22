# aura-perf on the Aura bus (#10, aura#5128)

The round's CCT, hypotheses and verdicts go on the target workspace's
bus; the file report stays as the human-facing view. Enabled by the
spec's `"bus"` hash (`"workspace" N`) or `AURA_PERF_BUS_WORKSPACE=N`.
Without either, every bus function is a no-op and the round runs
exactly as before.

## Lifecycle

Two modes, chosen by the spec's `"bus"` hash `"host"` key or
`AURA_PERF_BUS_HOST`:

**Self-host (default, v0.3.0 behavior).** The perf parent owns the seed
workspace, so it **hosts** the bus (`bus:host`) and attaches as the perf
peer: role 1, caps `read|publish|trial|keep|rollback` (31) — perf
*accepts* constraints, it does not write them.

**Attach-only (aura-perf#27, aura v0.3.1).** When the workspace is hosted
by an external tool (aura-redis), set `"host" #f` in the spec's `"bus"`
hash or `AURA_PERF_BUS_HOST=0`. perf skips `bus:host` and only
`bus:attach`es to the external host with caps `read|publish|trial` (7):
it mines signals and proposes candidates, it explicitly does **not**
request or hold `keep` / `rollback` / `constraint-write`. The judge
(aura-harness) decides; perf never KEEPs its own proposals. The attach
line names the mode and granted caps:
`bus attached ws=N role=perf session=S mode=attach-only caps=7`.

In self-host mode the coordinator lives in the perf process, so the bus
only outlives the round while that process stays up (aura-perf#28). After
the report is written, `perf:bus-linger` keeps the host serving for a
**linger window** (default 60s): harness or maintainer attaches and
queries the same audit and image. The window ends on its deadline or on
stdin EOF (a supervising runner closes stdin to end it early); then the
host unhosts and the round exits with the verdict's code. Configure:
`AURA_PERF_BUS_LINGER_S=N` or the spec's `"bus"` hash `"linger-s" N`;
`0` disables the window (exit right after the report, the pre-#28
behavior). In attach-only mode there is no local host: `perf:bus-linger`
is a no-op, the external host keeps serving, and the pending proposals
perf left await the judge.

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

## Signals and evidence proposals (attach-only, aura-perf#27)

`perf:bus-subscribe-signals` subscribes the host's metrics channel
(`bus:subscribe` + `bus:query`), reads the CCT hotspots aggregate
(`bus:hotspots`), and returns the latest metrics rows `((key value) …)`.
A failed read (host gone, permission) is reported, not fatal.

`perf:bus-propose bus node source workload seed verifier` publishes one
pure-policy candidate for the judge:

1. `bus:trial` on the patches channel opens a pending worldline;
2. `bus:publish-source` appends the candidate define source to the image
   string table; `bus:publish-patch` with `bus:source-field` names the
   target define node (the host projects nodes; the node id comes from
   the spec's `"bus-node"` or the host's node projection);
3. `bus:candidate-digest` computes the coordinator's FNV-1a digest of the
   trial's committed patch bytes;
4. `bus:bind-evidence` binds the five-tuple: baseline = the workspace
   generation the host reported (0 for a fresh host that has KEPT
   nothing; each live KEEP advances it by one; the spec's `"bus"` hash
   `"baseline"` carries a non-zero value), candidate = the digest,
   workload = the workload id, seed = the replay seed, verifier = the
   proposer version — all nonzero.

The function returns the worldline id and perf does **not** keep: the
loan stays outstanding with the pending worldline and the judge decides
(scoped grant → KEEP with evidence re-check → canary observation). A perf
disconnect or crash lets the coordinator roll the pending trial back
automatically. In the round, attach-only candidates are proposed here and
their verdict line reads `verdict=proposed`; `perf:bus-verdict` never
calls KEEP/ROLLBACK without the bits.

Failures are records, not crashes: `loan-exhausted`, `image-full`,
`constraint-rejected` and host disconnects (`transport-failed`) are
reported as `bus <step> failed: <code> (<message>)` lines and the round
continues (or exits cleanly); the coordinator reclaims loans and rolls
back pending worldlines on disconnect.

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

Then `perf:bus-linger` serves the bus for the linger window (default 60s,
`AURA_PERF_BUS_LINGER_S` / spec `"linger-s"`; 0 disables). The report and
evidence files are already on disk when the window opens, so a downstream
tool can read the files and the bus in either order. The window ends on
its deadline or stdin EOF; the host unhosts and the process exits with the
verdict's code. A crash during the window is a disconnect: pending trials
roll back, committed evidence dies with the process — the window is a
serve period, not a persistence guarantee (aura-perf#28).

## Report lines

```
bus attached ws=992 role=perf session=1
bus cct-records 9
bus-hypothesis flatten-fast key=1 base-ms=7709
bus-worldline flatten-fast wl=1 verdict=kept|rolled|constraint-rejected: <why>
bus audit-events 23 ws=992
bus detached (host lingers for harness/maintainer)
```

The report is written before the window opens. The window's own lines go
to stdout when it opens and closes (and stay in the run buffer):

```
bus host serving ws=992 linger-s=60 (EOF on stdin ends the window)
bus host closed (linger window ended)
```

## Tests

`tests/bus_test.aura` (golden-matched): host + perf peer, CCT and
hypothesis publication, kept/rolled verdicts, the shared audit; then an
expert peer attaches, installs `allow-small` and reads perf's audit,
and the next perf KEEP (200 ms) is rejected by it — the constraint
gate, end to end, in one process (self-host mode unchanged).

`tests/bus_attach_test.py` (needs a bus-capable `AURA_BIN`): a separate
aura process hosts the workspace (`bus:host` + `set-code` choose-fn +
node projection + a baseline metric); perf attaches attach-only with
caps 7, consumes the host signals, proposes a source-carrier patch with
the five-tuple evidence, and the test verifies the worldline is pending
(state 0, not kept) and perf's granted caps carry no keep bit.

`tests/bus_linger_test.py` (needs a bus-capable `AURA_BIN`): a real
round hosts the bus, a witness peer attaches DURING the linger window and
reads the round's committed metrics/audit; stdin EOF ends the window early
and unhosts; `AURA_PERF_BUS_LINGER_S=0` exits right after the report.
