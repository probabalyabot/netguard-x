# NetGuard-X

A gatekeeper for network configuration commands, built for commands written by an LLM agent.
Every proposed command is simulated against a live model of the network before anything changes.
Safe commands are executed and checkpointed, unusual ones are held for a person, and unsafe ones are
rejected with an explanation of what would break and why.

Scope: static routing and ACLs, deterministic hop-by-hop forwarding. No NAT, no dynamic routing
protocols, no live device access. "Executing" a command updates the in-memory model only.

## Status

| Part | State |
|------|-------|
| Verification engine (simulate, diff, root cause, explanation, risk, verdict) | Built |
| Gatekeeper (live model, verify-then-execute, human hold, checkpoints, rollback) | Built |
| Incremental verification (re-simulate only affected traffic) | Built |
| Evaluation harness (generated networks, command streams, baselines) | Built |
| Confidence-aware escalation | Not built |
| Rewriting an unsafe command into the nearest safe one, minimal rollback | Not built |
| LLM agent as the command source (commands are synthetic today) | Not built |

## Run

Run everything from this folder (the one that contains `netguardx/`).

    pip install -r requirements.txt
    python -m netguardx serve            # UI + API at http://127.0.0.1:8000
    python -m netguardx verify netguardx/examples/basic.json
    python -m netguardx analyze netguardx/examples/basic.json netguardx/examples/changes/route-via-r3.json
    python -m netguardx eval --sites 4 8 16 --commands 100 --seed 1 --out eval-results/run1
    python -m pytest -q tests            # 114 tests

`analyze` exits with code 1 when the verdict is NOT_RECOMMENDED, so it can gate a CI pipeline.
Flags: `--json`, `--out FILE`, `--no-probes`, `--weights '{"broken_flows": 25}'`.
See GUIDE.md for a walkthrough of the UI and of what each result means. The UI and GUIDE.md cover
the verification engine only; the gatekeeper has no screen yet.

## The gatekeeper

```python
from netguardx import Gatekeeper, IncrementalVerifier

gk = Gatekeeper(network, verifier=IncrementalVerifier())
decision = gk.propose(changes)          # a command from the agent
```

| Verdict from verification | Outcome | What happens |
|---|---|---|
| SAFE | `EXECUTED` | The live model is updated and a checkpoint with the inverse changes is stored |
| REVIEW | `HELD` | Nothing changes until `gk.approve(id)` or `gk.deny(id)` |
| NOT_RECOMMENDED | `REJECTED` | The live model is untouched; the report says what would break |
| Command does not apply | `INVALID` | For example, editing a route that does not exist |

- If the model has changed since a command was held, `approve` verifies it again first.
- `gk.rollback(to_seq)` undoes every checkpoint after `to_seq`; `0` restores the initial model.
- The agent cannot add or delete policies, so it cannot remove the rule it is about to break.
  A person can, through `gk.propose_as_operator(changes)`, which is still verified.

## Incremental verification

Full verification re-simulates every traffic class in both the current and the changed network.
`IncrementalVerifier` returns the same report while re-simulating only what the change can affect.

The rule: a device decides what to do with a packet from its own routes, ACL and links. A change
touches a known set of devices. Traffic whose current path never visits one of them takes the same
path afterwards. For a route change, the destination must also lie inside the changed prefix.

The verifier keeps the live model's traces and an index from each device to the traffic crossing
it, and carries both forward when a command is executed. The changed network and its forwarding
tables are also built by replacing only what the change touches.

Measured on one run (100 commands per network, seed 1, 30% fault rate, probes on):

| Sites (nodes) | Full, median | Incremental, median | Speed-up | Traffic re-simulated | Reports that differ |
|---|---|---|---|---|---|
| 2 (14) | 5.0 ms | 1.4 ms | 3.6x | 30.8% | 0 |
| 4 (26) | 22.8 ms | 2.3 ms | 9.7x | 16.4% | 0 |
| 8 (51) | 111.8 ms | 5.7 ms | 19x | 10.6% | 0 |
| 16 (101) | 255.2 ms | 9.0 ms | 28x | 5.3% | 0 |
| 32 (201) | 399.1 ms | 9.5 ms | 42x | 3.6% | 0 |

Read these with the limits below in mind.

## Evaluation harness

`python -m netguardx eval` generates a network of each requested size, generates one seeded stream
of commands, and replays that stream through five strategies:

| Arm | Rejects a command when |
|---|---|
| `none` | never |
| `lint` | it introduces a route whose next hop cannot be used |
| `reachability` | a flow that was delivered stops being delivered |
| `full` | the gatekeeper with full verification says NOT_RECOMMENDED |
| `incremental` | the gatekeeper with incremental verification says NOT_RECOMMENDED |

Per arm it reports commands executed, rejected, held and invalid; unsafe commands executed; safe
commands rejected; steps during which the network had a violated policy or a lost flow; check time
(median and 95th percentile); and, for the gatekeeper arms, the share of traffic re-simulated and
the number of reports that differ from full verification. `--out DIR` writes `summary.json` and
`steps.csv`.

Whether a command is unsafe is decided by full verification against the state it is proposed in.
The `full` arm is therefore safe by construction; the comparison is about what the weaker checks
let through and what each check costs.

## Limits of the current results

- One seed on one machine. No repeated runs or confidence intervals yet.
- Exposure probes are capped at 2000 per verification, so on larger networks they cover only part
  of the endpoint pairs.
- Check time covers verification only. Executing a command still copies the whole network.
- The 95th-percentile time of the incremental verifier is several times its median on the larger
  networks, and the first command pays for building the cache. After a rollback the cache is rebuilt.
- Unsafe-command counts for the weak arms are undercounts: once a network is broken, later damage is
  treated as already present.
- The risk weights are starting points, not calibrated values.

## Modules

| Step | Module |
|------|--------|
| Data model (devices, links, routes, ACLs, flows, policies, 10 change operations) | `models.py` |
| Forwarding simulation (ACL -> longest-prefix match -> next hop; loop / blackhole / ACL drop detection) | `network.py` |
| Apply changes to a copy, produce inverse changes and per-change effects | `changes.py` |
| Baseline policy verification, traffic classes, exposure probes | `verify.py` |
| Differential analysis: first divergent hop, root-cause attribution, propagation chains, impact graph, rollback | `impact.py` |
| Transparent weighted risk score (weights configurable) | `risk.py` |
| Evidence-only explanation templates (no LLM, cannot state unobserved facts) | `explain.py` |
| Gatekeeper: live model, verify-then-execute loop, human hold, checkpoints, rollback | `gatekeeper.py` |
| Incremental verifier: cached traces, re-simulation of affected traffic only | `incremental.py` |
| Evaluation: generated networks, seeded command streams, baseline arms and metrics | `eval/` |
| Rule-based text -> change/policy drafting (the seam where an LLM plugs in) | `nlp.py` |
| Markdown report | `report.py` |
| FastAPI service and single-file web UI | `api.py`, `static/index.html` |

A React frontend lives in `frontend/` (see `frontend/README.md`). The original single-file UI at `/` still works.

API: `GET /api/health`, `GET /api/examples`, `POST /api/verify`, `POST /api/simulate`,
`POST /api/diff`, `POST /api/interpret`, `POST /api/eval/run`.

## Example scenarios (`netguardx/examples/changes/`)

| File | Expected verdict |
|------|------------------|
| `route-via-r3.json` (bypasses the firewall) | NOT_RECOMMENDED, critical |
| `open-firewall.json` (broad ALLOW rule) | NOT_RECOMMENDED, critical |
| `remove-r1-r2.json` (leaves a dangling route) | NOT_RECOMMENDED |
| `route-loop.json` | NOT_RECOMMENDED |
| `backup-link.json` (path changes, still allowed) | REVIEW |
| `safe-metric.json` | SAFE |
