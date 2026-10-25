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
