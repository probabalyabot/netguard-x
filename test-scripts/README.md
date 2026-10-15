# Demo test scripts

Change files for the built-in **Three-tier app network** (the default in the UI, also
`netguardx/examples/basic.json`). Each file says what it does and what verdict to expect.

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

## Using them

**In the UI:** Change analysis → switch the Change set panel to **JSON** → replace the text with a
file's contents → **Simulate change**. The `title`, `expected` and `description` fields are ignored;
only `changes` is used.

**From the command line** (in the `netguard-x` folder):

    python -m netguardx analyze netguardx/examples/basic.json test-scripts/fail-01-firewall-bypass.json

It exits with code 1 for a `fail-` file and 0 for the others.

A suggested demo order: `pass-01`, `fail-01` (the headline), `review-01`, `fail-02`, `fail-07`.
