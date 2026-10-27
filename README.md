# NetGuard-X

A gatekeeper for network configuration commands, built for commands written by an LLM agent.
Every proposed command is simulated against a live model of the network before anything changes.
Safe commands are executed and checkpointed, unusual ones are held for a person, and unsafe ones are
rejected with an explanation of what would break and why. Commands can be given as JSON, typed in
plain English, or pasted as Cisco-style `ip route` lines.

Scope: static routing and ACLs, deterministic hop-by-hop forwarding. No NAT, no dynamic routing
protocols, no live device access. "Executing" a command updates the in-memory model only.

## Status

| Part | State |
|------|-------|
| Verification engine (simulate, diff, root cause, explanation, risk, verdict) | Built |
| Gatekeeper (live model, verify-then-execute, human hold, checkpoints, rollback) | Built |
| Incremental verification (re-simulate only affected traffic) | Built |
| Evaluation harness (generated networks of 50–75+ devices, seeds, overhead and scaling metrics) | Built |
| Command parser (plain English and Cisco lines → checked changes; `draft`, `session`) | Built (rule-based) |
| Confidence-aware escalation | Not built |
| Rewriting an unsafe command into the nearest safe one, minimal rollback | Not built |
| LLM agent as the command source (commands are synthetic or typed today) | Not built |

## Run

Run everything from this folder (the one that contains `netguardx/`). For the web UI, see RUN.md.

    pip install -r requirements.txt
    python -m netguardx serve            # API (and the original UI) at http://127.0.0.1:8000
    python -m netguardx verify netguardx/examples/basic.json
    python -m netguardx analyze netguardx/examples/basic.json netguardx/examples/changes/route-via-r3.json
    python -m netguardx draft netguardx/examples/basic.json "block ssh from USER to DB on FW"
    python -m netguardx session netguardx/examples/basic.json test-scripts/session.txt
    python -m netguardx session netguardx/examples/enterprise.json test-scripts/enterprise-session.txt
    python -m netguardx eval --devices 50 63 75 --commands 100 --seeds 1 2 3 --out eval-results/run1
    python -m pytest -q tests            # 474 tests
    cd frontend && npm test              # 26 tests

`analyze` exits with code 1 when the verdict is NOT_RECOMMENDED, so it can gate a CI pipeline.
Flags: `--json`, `--out FILE`, `--no-probes`, `--weights '{"broken_flows": 25}'`.
GUIDE.md walks through the original single-file UI; the React UI in `frontend/` is described in
`frontend/README.md` and RUN.md.

## Typing changes

The parser (`netguardx/nlp/`) is rule-based, not a language model. It turns text into the same
schema-checked changes as the JSON files, and checks every draft against the network before anyone
sees it. **[SYNTAX.md](SYNTAX.md)** is the full guide: every pattern, examples on both networks, and
what each error means.

| Kind | Examples |
|---|---|
| Routes | "change the route on R1 for 10.0.5.0/24 to R3", "send DB traffic on R1 via R3", "add a route on R1 to 10.0.7.0/24 via R3 with metric 20", "remove the default route on R1", "set the metric of R1's default route to 50", "point R2 at R1 for 10.0.5.0/24" |
| Cisco lines | `R1(config)#` on one line, then `ip route 10.0.7.0 255.255.255.0 R3 20` and `no ip route 0.0.0.0 0.0.0.0 INET` below it (`R1#`, `on R1:` and `configure R1` work too) |
| Links | "connect R2 and R3 with cost 5", "cable FW to BACKUP", "remove the link between R1 and R2" |
| ACL rules | "block ssh from USER to DB on FW", "allow https from any to APP on FW at the top", "delete rule 2 on FW", "remove the rule on FW that allows APP to DB" |
| Requirements | "APP must reach DB through FW on port 5432", "USER must never reach DB", "delete policy P3" |

- Devices can be named by id, label, address (`10.255.0.3`) or role when there is only one ("the
  firewall"). A misspelt device gets a suggestion: "unknown device FWW (did you mean FW?)".
- Services by name (ssh, https, dns, postgres, …) or as `tcp/8080`, `udp 53`, `port 443`.
- Rule numbers and positions count from 1, as people read an ACL; the JSON `rule_index` and
  `position` fields stay 0-based.
- A device as a route destination ("DB traffic") means the router's most specific route covering
  it; the parser never edits a default route silently and asks for the prefix instead.
- An `ip route` line for a prefix that already has a route adds a second route, as a router would;
  to replace a next hop, say "change … to …". Cisco `access-list` syntax is not supported.
- Each draft is checked in order, on top of the ones before it, so a later line can use what an
  earlier one created. One that cannot apply is reported with the engine's reason.

`draft` prints the drafts as JSON (`--file` for several lines; `--analyze` for the impact report).
`session` sends a file of commands, one per line, or commands typed live with `-`, through the
gatekeeper, printing how each line was understood and whether it was EXECUTED, HELD, REJECTED or
NOT UNDERSTOOD. A session acts as the AI agent, so policy edits are refused by the policy lock;
`--operator` acts as a person. A line with anything not understood is refused whole, and a line
that names an unknown device never falls back to a config header's device. In the React UI the
same parser drives the Drafter on the Change analysis screen.

**Parse rate.** The parser drafts exactly the expected changes for 80 of 80 entries in
`tests/nlp_corpus.json` (`python -m netguardx.nlp.score tests/nlp_corpus.json`) and 30 of 30 in
`tests/nlp_corpus_enterprise.json` on the 60-device network (add
`--network netguardx/examples/enterprise.json`). Both were written alongside the grammar, so they
measure coverage, not accuracy. An accuracy figure needs a
held-out set written by someone who has not read the grammar; that is pending.

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
- Each decision reports `verify_ms` (the gatekeeper's overhead) and, when executed, `commit_ms`.

## Incremental verification

Full verification re-simulates every traffic class in both the current and the changed network.
`IncrementalVerifier` returns the same report while re-simulating only what the change can affect.

The rule: a device decides what to do with a packet from its own routes, ACL and links. A change
touches a known set of devices. Traffic whose current path never visits one of them takes the same
path afterwards. For a route change, the destination must also lie inside the changed prefix.

The verifier keeps the live model's traces and an index from each device to the traffic crossing
it, and carries both forward when a command is executed. The changed network and its forwarding
tables are also built by replacing only what the change touches.

An early single run (100 commands per network, seed 1, 30% fault rate, probes capped at 2000):

| Sites (devices) | Full, median | Incremental, median | Speed-up | Traffic re-simulated | Reports that differ |
|---|---|---|---|---|---|
| 2 (14) | 5.0 ms | 1.4 ms | 3.6x | 30.8% | 0 |
| 4 (26) | 22.8 ms | 2.3 ms | 9.7x | 16.4% | 0 |
| 8 (51) | 111.8 ms | 5.7 ms | 19x | 10.6% | 0 |
| 16 (101) | 255.2 ms | 9.0 ms | 28x | 5.3% | 0 |
| 32 (201) | 399.1 ms | 9.5 ms | 42x | 3.6% | 0 |

The headline numbers for 50–75 devices, over several seeds with full probe coverage, come from
`python -m netguardx eval --devices 50 63 75 --commands 100 --seeds 1 2 3 4 5 --memory --out ...`.

## Evaluation harness

`python -m netguardx eval` generates a campus network of each requested size, generates one seeded
stream of commands, and replays that stream through five strategies:

| Arm | Rejects a command when |
|---|---|
| `none` | never |
| `lint` | it introduces a route whose next hop cannot be used |
| `reachability` | a flow that was delivered stops being delivered |
| `full` | the gatekeeper with full verification says NOT_RECOMMENDED |
| `incremental` | the gatekeeper with incremental verification says NOT_RECOMMENDED |

| Flag | Meaning |
|---|---|
| `--sites 4 8` / `--devices 50 63 75` | sizes; device counts round up to whole sites (8, 10, 12 sites = 51, 63, 76 devices) |
| `--users-per-site N` | N user machines behind each site's router (8 sites × 4 users = 75 devices) |
| `--seeds 1 2 3 4 5` | replay each size once per seed; means with 95% confidence intervals |
| `--memory` | memory the incremental verifier keeps between commands, and its peak |
| `--probe-limit N` | cap exposure probes; by default every endpoint pair is probed |
| `--out DIR` | writes `summary.json`, `steps.csv` and a readable `report.md` |

Per arm it reports commands executed, rejected, held and invalid; unsafe commands executed; safe
commands rejected; steps during which the network had a violated policy or a lost flow; check time
(median, 95th percentile, mean, throughput); and, for the gatekeeper arms, the time per step of
verification, commit time, the share of traffic re-simulated and the number of reports that differ
from full verification. Per size it adds the overhead summary, and across sizes a power-law fit of
check time against devices with projections to 150 and 300 devices, labelled as projections.

Whether a command is unsafe is decided by full verification against the state it is proposed in.
The `full` arm is therefore safe by construction; the comparison is about what the weaker checks
let through and what each check costs. The React UI runs evaluations of up to 12 sites (76 devices)
as background jobs with a progress bar, and imports `summary.json` from larger command-line runs.

## Limits of the current results

- Timings are from one machine. Use `--seeds` for confidence intervals; the multi-seed headline run
  has not been published yet.
- Evaluation runs probe every endpoint pair. `analyze` and the UI's single-change simulation still
  cap exposure probes at 2000 per check, so on large networks they cover only part of the pairs.
- Check time covers verification only; applying an executed change (`commit_ms`) is reported
  separately.
- The 95th-percentile time of the incremental verifier is several times its median on the larger
  networks, partly because the first command builds the cache. After a rollback the cache is rebuilt.
- Unsafe-command counts for the weak arms are undercounts: once a network is broken, later damage is
  treated as already present.
- The parser's 100% is a coverage figure on a developer-written corpus, not an accuracy figure.
- Verdicts look at policies and flows, not at how many firewalls stand in the way. A rule that
  removes one layer of several is SAFE while the others still block (see the VPN lines in
  `test-scripts/enterprise-session.txt`).
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
| Text -> checked changes: clauses, vocabulary, routes, links, ACLs, requirements, validation, scorer (the seam where an LLM plugs in) | `nlp/` |
| Typed commands through the gatekeeper (`draft`, `session`) | `pipeline.py` |
| Evaluation: topologies, command streams, arms, statistics, overhead and scaling, report, background jobs | `eval/` |
| Markdown report of one change | `report.py` |
| FastAPI service and the original single-file UI | `api.py`, `static/index.html` |

A React frontend lives in `frontend/` (see `frontend/README.md`). The original single-file UI at `/`
still works, and a built React UI is served at `/app` when `frontend/dist` exists.

API: `GET /api/health`, `GET /api/examples`, `POST /api/verify`, `POST /api/simulate`,
`POST /api/diff`, `POST /api/interpret`, `POST /api/eval/run`, `POST /api/eval/jobs`,
`GET /api/eval/jobs/{id}`, `POST /api/eval/jobs/{id}/cancel`.

## Example networks and scenarios

Two built-in networks, both in the UI's network list:

- `netguardx/examples/basic.json`, the **three-tier app network** (9 devices): the original demo.
- `netguardx/examples/enterprise.json`, an **enterprise network** (60 devices), hand-designed for
  larger demos: two internet providers, a perimeter firewall and DMZ (web, mail, DNS, VPN), two
  core switches, a data centre behind its own firewall with the databases behind a third, a storage
  network that is physically wired to the databases but never used for queries, management, head
  office, three branches over a WAN, guest Wi-Fi and a dev lab. 34 flows and 24 requirements, all
  met as shipped.

Scenarios for the three-tier network are in `netguardx/examples/changes/`; scenarios for another
network go in `netguardx/examples/changes/<network>/`. The UI lists only the open network's.

Three-tier network:

| File | Expected verdict |
|------|------------------|
| `route-via-r3.json` (bypasses the firewall) | NOT_RECOMMENDED, critical |
| `open-firewall.json` (broad ALLOW rule) | NOT_RECOMMENDED, critical |
| `remove-r1-r2.json` (leaves a dangling route) | NOT_RECOMMENDED |
| `route-loop.json` | NOT_RECOMMENDED |
| `backup-link.json` (path changes, still allowed) | REVIEW |
| `safe-metric.json` | SAFE |

Enterprise network (`changes/enterprise/`, each file states its expected verdict and
`tests/test_scenarios.py` checks it):

| File | Expected verdict |
|------|------------------|
| `pass-01` … `pass-04` (standby ISP metric, a new link, an extra deny, a more specific route) | SAFE |
| `review-01`, `review-02` (branch and head-office traffic take a new path) | REVIEW |
| `fail-01-database-firewall-bypass` (database route over the storage network) | NOT_RECOMMENDED |
| `fail-02-dmz-routing-loop`, `fail-03-database-loses-gateway`, `fail-04-cut-core1-to-data-centre` | NOT_RECOMMENDED |
| `fail-05-open-perimeter`, `fail-06-guest-isolation-removed`, `fail-07-branch-block-too-broad` | NOT_RECOMMENDED |
| `fail-08-vpn-database-access` (one rule on each of the three firewalls) | NOT_RECOMMENDED |
| `fail-09-maintenance-window` (9 changes, one bad; only that one is blamed) | NOT_RECOMMENDED |

`test-scripts/` holds the labelled demo changes for the three-tier network, the sentences for both
networks, and a typed session for each; see `test-scripts/README.md`.
