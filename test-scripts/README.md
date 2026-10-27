# Demo test scripts

Change files for the built-in **Three-tier app network** (the default in the UI, also
`netguardx/examples/basic.json`). Each file says what it does and what verdict to expect, and each
can also be typed as a sentence.

| Label | Meaning |
|---|---|
| `pass-` | **Safe**: nothing behaves differently |
| `review-` | **Review before deploying**: behaviour changes, nothing breaks |
| `fail-` | **Not recommended**: a flow breaks or a policy is violated |

## Files

| File | What it does | Verdict | What the demo shows |
|---|---|---|---|
| `pass-01-tune-default-metric.json` | Changes an unused route metric | Safe | No findings |
| `pass-02-standby-route-via-r3.json` | Adds a backup route with a worse metric | Safe | A route can be added without moving traffic |
| `pass-03-redundant-core-link.json` | Adds a router-to-router link | Safe | New cabling alone changes nothing |
| `pass-04-explicit-firewall-deny.json` | Makes an existing firewall deny explicit | Safe | Hardening with no side effects |
| `review-01-backup-shortcut.json` | Links the firewall straight to the backup server | Review | Path changes, still allowed |
| `fail-01-firewall-bypass.json` | Routes database traffic around the firewall | Not recommended, critical | Ping still works but security breaks |
| `fail-02-routing-loop.json` | Points R2 back at R1 | Not recommended | Routing loop |
| `fail-03-blackhole.json` | Deletes the firewall's return route | Not recommended | Backups silently discarded |
| `fail-04-dangling-route.json` | Removes the R1-R2 link, routes still point at it | Not recommended | Unusable next hop |
| `fail-05-open-firewall.json` | Allows everything through the firewall | Not recommended, critical | Policy breach with no route change |
| `fail-06-block-app-database.json` | Blocks the app from the database | Not recommended | A critical flow is cut off |
| `fail-07-batch-one-bad-change.json` | A safe change and a bad one together | Not recommended | Only the bad change is blamed; dropping it makes the batch safe |

## The same changes as sentences

Each sentence drafts exactly the file's changes (checked by `tests/nlp_corpus.json`).

| File | Type this |
|---|---|
| `pass-01` | set the metric of R1's default route to 50 |
| `pass-02` | add a route on R1 for 10.0.5.0/24 via R3 with metric 50 &nbsp;·&nbsp; or `R1(config)# ip route 10.0.5.0 255.255.255.0 R3 50` |
| `pass-03` | cable R2 to R3 |
| `pass-04` | deny postgres from USER to DB on FW |
| `review-01` | cable the firewall straight to the backup server |
| `fail-01` | change R1's route for 10.0.5.0/24 from R2 to R3 |
| `fail-02` | change the route on R2 for DB from FW to R1 |
| `fail-03` | remove the default route on FW |
| `fail-04` | decommission the link between R1 and R2 |
| `fail-05` | allow everything from any to any on FW at the top |
| `fail-06` | block postgres from APP to DB on FW at the top |
| `fail-07` | set the metric of R1's default route to 50, then change R1's route for 10.0.5.0/24 from R2 to R3 |

## Using them

**In the UI:** Change analysis → type a sentence in the Drafter box → **Draft and simulate**. Or
switch the Change set panel to **JSON**, replace the text with a file's contents and press
**Simulate change** (the `title`, `expected` and `description` fields are ignored).

**From the command line** (in the `netguard-x` folder):

    python -m netguardx analyze netguardx/examples/basic.json test-scripts/fail-01-firewall-bypass.json
    python -m netguardx draft netguardx/examples/basic.json "remove the default route on FW" --analyze

Both exit with code 1 for a `fail-` change and 0 for the others.

**As one typed session:** `session.txt` replays the scripts as commands, one per line, plus a Cisco
block, a requirement the agent may not add, and a typo:

    python -m netguardx session netguardx/examples/basic.json test-scripts/session.txt

It ends with 5 executed, 1 held, 7 rejected and 1 not understood. Each line is checked against the
network as the earlier lines left it, so in a session the order matters.

A suggested demo order: `pass-01`, `fail-01` (the headline), `review-01`, `fail-02`, `fail-07`,
then the session.

## The 60-device enterprise network

`netguardx/examples/enterprise.json` is a larger, hand-designed network: two internet providers
(EDGE1, EDGE2), a perimeter firewall (FW-EDGE) with a DMZ (WEB1, WEB2, MAIL, DNS, VPN), two core
switches (CORE1, CORE2), a data centre behind DC-FW (APP1–3, AUTH, FILES, PRINT, LOG, BACKUP), the
databases DB1 and DB2 behind DB-FW, a storage network (SAN-R) that is wired to the databases but
never used for queries, management (JUMP, MON, NOC), head office (HQ-R1, HQ-R2, HQ-PC1–8), three
branches behind WAN-R (BR1-R … BR3-R, each with two PCs and a till), guest Wi-Fi (GUEST-R) and a
dev lab (DEV-R, DEV1, DEV2, CI).

Its 15 scenarios are in `netguardx/examples/changes/enterprise/`. In the UI, pick the network on
Overview and they replace the three-tier ones on Change analysis. Each can be typed instead
(checked by `tests/nlp_corpus_enterprise.json`):

| Scenario | Verdict | Type this |
|---|---|---|
| `pass-01` standby ISP metric | Safe | set the metric of FW-EDGE's default route via EDGE2 to 200 |
| `pass-02` link the head-office routers | Safe | cable HQ-R1 to HQ-R2 |
| `pass-03` dev lab denied at DB-FW too | Safe | deny everything from 10.30.0.0/24 to 10.20.5.0/24 on DB-FW at the top |
| `pass-04` specific backup route | Safe | add a route on DC-FW for 10.20.6.0/24 via DC-R |
| `review-01` branches via CORE1 | Review | set the metric of WAN-R's default route via CORE1 to 5 |
| `review-02` floors 3–4 via floors 1–2 | Review | cable HQ-R1 to HQ-R2, then change the default route on HQ-R2 from CORE2 to HQ-R1 |
| `fail-01` database-firewall bypass | Not recommended, critical | change DC-R's route for 10.20.5.0/24 from DB-FW to SAN-R |
| `fail-02` DMZ routing loop | Not recommended | change FW-EDGE's route for 10.10.0.0/24 from DMZ-R to CORE1 |
| `fail-03` database loses its route | Not recommended | remove the default route on DB1 |
| `fail-04` cut a core link | Not recommended | decommission the link between CORE1 and DC-FW |
| `fail-05` open perimeter | Not recommended | allow everything from any to any on FW-EDGE at the top |
| `fail-06` guest isolation removed | Not recommended | delete rule 2 on GUEST-R |
| `fail-07` branch block too broad | Not recommended | block https from 10.2.0.0/16 to any on DC-FW at the top |
| `fail-08` VPN to the database | Not recommended | allow postgres from VPN to DB1 on FW-EDGE at the top; allow postgres from VPN to DB1 on DC-FW at the top; allow postgres from VPN to DB1 on DB-FW at the top |
| `fail-09` maintenance window | Not recommended | the nine lines in `tests/nlp_corpus_enterprise.json`, one change per line |

From the command line:

    python -m netguardx analyze netguardx/examples/enterprise.json netguardx/examples/changes/enterprise/fail-01-database-firewall-bypass.json
    python -m netguardx draft netguardx/examples/enterprise.json "delete rule 2 on GUEST-R" --analyze

**Typed session:** `enterprise-session.txt` runs the scenarios as commands, one per line:

    python -m netguardx session netguardx/examples/enterprise.json test-scripts/enterprise-session.txt

It ends with 6 executed, 2 held, 10 rejected and 2 not understood. Two things to point out:

- The three VPN rules go in one at a time. The first two are executed, because the next firewall
  along still blocks the traffic; the third would complete the path to the database and is
  rejected. Verdicts judge policies, not how many layers of defence are left.
- Because those two rules are now in place, the Cisco host route a few lines later (DB1 over the
  storage network, skipping DB-FW) is rejected for letting VPN users reach the database, on top of
  the usual bypass findings.

A suggested order: `pass-01`, `fail-01` (the headline), `review-01`, `fail-08`, `fail-09`, then the
session.
