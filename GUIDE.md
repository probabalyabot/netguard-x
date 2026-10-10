# NetGuard-X: User Guide

How to run it, what it does, how it works, and how to read what you see on screen.

---

## 1. What NetGuard-X is

Network engineers change configuration all the time: a new route, a firewall rule, a removed link. A change that looks harmless can quietly break an application or open a door that was supposed to stay shut. Usually you only find out after it is deployed.

**NetGuard-X checks a change before it is deployed.** You give it:

1. **A network**: devices, links, routes, and firewall rules (ACLs).
2. **What must be true**: *flows* (traffic that must keep working) and *policies* (rules such as "the app must reach the database through the firewall" or "the internet must never reach the database").
3. **A proposed change**: for example "point R1's route to the database at R3 instead of R2".

It then answers, with evidence:

- Which flows break, and which get a different path?
- Which policies would be violated?
- What becomes reachable that was not reachable before (new exposure)?
- *Why* does this happen? It shows the chain from your change to each problem.
- How risky is it overall, and which change should be rolled back?

It never touches a real device. It reasons about a model of your network, and it only recommends; it never deploys or reverts anything.

### What it does not cover (MVP scope)

| Covered | Not covered |
|---|---|
| Static routing (longest-prefix match, metrics) | Dynamic routing protocols (OSPF, BGP) |
| ACLs (ordered rules, first match, default action) | NAT |
| Links between devices, one-way traffic paths | Reading configs from real devices |
| IPv4 and IPv6 addresses | Live traffic or performance (bandwidth, latency) |

If a change involves something in the right-hand column, NetGuard-X will not see its effect. Treat a "safe" verdict as "safe within the modelled behaviour".

---

## 2. Running it

### Setup (once)

```
cd netguard-x
pip install -r requirements.txt
```

Requires Python 3.10 or newer (built and tested on 3.12).

### Start the web UI

```
python -m netguardx serve
```

Open **http://127.0.0.1:8000** in a browser. Use `--port 9000` to change the port, or `--host 0.0.0.0` to allow other machines to connect.

### Command line (no browser)

```
# Check the network as it is today
python -m netguardx verify netguardx/examples/basic.json

# Predict the impact of a change (prints a Markdown report)
python -m netguardx analyze netguardx/examples/basic.json netguardx/examples/changes/route-via-r3.json

# Same, but save the report or get raw JSON
python -m netguardx analyze <network.json> <change.json> --out report.md
python -m netguardx analyze <network.json> <change.json> --json

# Faster on big networks: skip the exposure probes (see section 4)
python -m netguardx analyze <network.json> <change.json> --no-probes

# Change the risk weights (see section 5)
python -m netguardx analyze <network.json> <change.json> --weights '{"security_violations": 40}'
```

**Exit codes** (useful for automation such as a CI pipeline):

| Code | Meaning |
|---|---|
| 0 | OK: the change is SAFE or REVIEW (`verify`: all policies hold) |
| 1 | The change is NOT_RECOMMENDED (`verify`: at least one policy is already violated) |
| 2 | Bad input (invalid JSON, reference to a device that does not exist, and so on) |

### Run the tests

```
python -m pytest -q tests
```

---

## 3. Using the web UI

The page has two halves. The **left panel** is where you set things up. The **right side** is where results appear.

### Left panel

**Network**
- **Model**: a dropdown of built-in example networks. The default is a three-tier app network (see section 7).
- **Choose File**: load your own network as a JSON file.
- **Edit network JSON**: expand it to view or edit the network directly, then press **Use this network**.
- The line under the picker (for example "9 devices, 9 links, 12 routes, 6 policies") confirms what was loaded.

**Proposed change**
- **Preset buttons**: one click loads a ready-made change (for example "Send database traffic via R3").
- **Change as JSON**: the actual change that will be analysed. Edit it by hand if you like.
- **Or describe it in words + Draft**: type something like *"Change the route on R1 for 10.0.5.0/24 to use R3"* and press **Draft**. It fills in the JSON for you and lists any part it did not understand. **Always read the JSON before analysing.** This is a simple rule-based reader, not an AI model, and it only understands basic route, link, and reachability sentences.
- **Risk weights**: how much each kind of problem adds to the risk score (section 5).
- **Analyze change**: runs the analysis.

### Before you analyse: the "Current state" screen

When you first load a network, the right side shows the network as it is today:

- A banner such as **"All 6 policies hold today"** (green) or **"2 of 6 policies are already violated today"** (red). If policies are already violated, that is a problem in the network itself, not something your change caused.
- **Declared flows today**: each flow and what currently happens to it, for example `APP > R1 > R2 > FW > DB` and *delivered*.
- **A network map**: devices as small icons, links as lines. Pick a flow in the dropdown to highlight its path.

Some flows are *supposed* to be blocked. "DB to INET, dropped by ACL at FW" is correct if a policy says the database must never reach the internet.

### After you press Analyze change

Results appear in the order below.

#### 1. The verdict banner

The big headline at the top has three possible outcomes:

| Banner | Meaning |
|---|---|
| **Not recommended** (red) | At least one critical or high-severity problem: a policy is broken, a required flow fails, or the firewall is bypassed. Do not deploy as is. |
| **Review before deploying** (amber) | Nothing is broken outright, but something changed that a person should look at (for example traffic now takes a different path, or something new became reachable). |
| **No problems found** (green) | No required flow is lost and no policy is broken. |

Under the headline is the list of changes that were analysed, then five figures:

| Figure | What it counts |
|---|---|
| **Flows affected** | Declared flows whose path or result differs after the change, out of all declared flows ("3 of 7") |
| **Flows broken** | Declared flows that worked before and no longer arrive |
| **Policy violations** | Policies that held before and are violated after |
| **Newly reachable pairs** | Source and destination pairs that could not talk before and now can |
| **Risk** | A 0 to 100 score and a level (section 5) |

#### 2. Findings

Each finding is one specific problem or notable difference. It has a severity, a title in plain English, and a short explanation. **Click a finding to expand it**:

- **The propagation chain**: a vertical timeline that reads top to bottom from cause to consequence. This is the "why". For example:
  1. *Modify route on R1: 10.0.5.0/24 R2 -> R3* (your change)
  2. *R1 selects a different route* (the forwarding decision that changed)
  3. *Forwarding path changes* (before and after paths)
  4. *FW is no longer on the path* (a protection point dropped out)
  5. *Policy P4 is violated* (the rule that is now broken)
  6. *Forbidden traffic reaches DB* (the real-world impact)
- **Technical detail**: the same story in engineer's language, with route and ACL specifics.
- **Show this flow on the map**: highlights this flow's path on the map.

**Finding types and what they mean:**

| Type | Severity | Meaning |
|---|---|---|
| **POLICY_VIOLATION** | Critical | Traffic that a DENY policy forbids is now delivered |
| **WAYPOINT_BYPASS** | High | Traffic still arrives but no longer passes through a device a policy requires (typically the firewall) |
| **ROUTING_LOOP** | Critical or high | Packets circle between devices and never arrive |
| **BLACKHOLE** | Critical or high | A device has no route for the destination, so packets are dropped |
| **INVALID_NEXT_HOP** | Critical or high | A route points to a neighbour that is no longer connected (for example after deleting a link) |
| **FLOW_BLOCKED** | Critical or high | An ACL now drops a flow that used to be allowed |
| **NEW_EXPOSURE** | High if the source is the internet, otherwise medium | A destination can now be reached from sources that could not reach it before |
| **PATH_CHANGED** | Info | Still delivered, but by a different route |
| **NEW_REACHABILITY** | Info | A flow that was blocked now arrives (and no policy said it was a problem) |
| **FLOW_RESTORED** | Info | A previously failing flow now works, fixing an existing violation |

For the failure types, "critical" is used when the affected flow has criticality 4 or 5 and "high" otherwise.

**Configuration warnings** (if present) are static lint results on the *changed* network, for example "R1: route 10.0.5.0/24 via R2, but there is no link R1-R2". They are only shown when the change introduces them.

#### 3. The Before and After map

Three tabs:

- **before**: the network as it is today, with the selected flow's path.
- **after**: the network with your change applied.
- **Changes**: both at once, which is usually the most useful view.

Use the **Flow** dropdown to pick which flow to trace. The legend explains the line styles:

| Style | Meaning |
|---|---|
| Solid dark line | Path used both before and after |
| Dashed red line | Path used before, no longer used |
| Solid green line | Path used only after the change |
| "Traffic stops here" marker | Where a packet is dropped, loops, or finds no route |

Devices that drop off the path are ringed in dashed red; devices newly on the path are ringed in green. A link you added is drawn as an added link, and a deleted link is drawn as removed.

Under the map, the path is shown hop by hop. The **−** row is before, the **+** row is after, each ending in its result ("dropped by ACL at FW", "delivered"). Devices that changed are highlighted.

#### 4. Recommended rollback

Shown when the verdict is Not recommended. It names the specific change(s) identified as the root cause and says what would happen if you left them out: *"Without it the verdict becomes safe, with 0 remaining problems."* NetGuard-X actually re-runs the analysis without those changes to confirm this, so it is a checked claim, not a guess. If you proposed several changes at once, only the guilty ones are named; the others can go ahead.

Each entry also carries the exact inverse change (available in the JSON download) that would undo it.

#### 5. Declared flows that change

A table of every declared flow whose behaviour differs, with **Before** and **After** columns and the policy that covers it. Under the table, "4 other declared flows behave exactly as before" tells you the rest of your traffic is untouched.

Read this table carefully: a row that reads *"dropped by ACL"* before and *"delivered"* after is not automatically good. If a policy says that traffic must be blocked, then the "improvement" is actually a violation.

#### 6. Policies

Every policy with its status after the change:

| Status | Meaning |
|---|---|
| **Holds** | Satisfied before and after |
| **Newly violated** (red) | Held before, broken by this change |
| **Now holds** | Was violated before, and this change fixes it |
| **Already violated before the change** (amber) | Broken already; not caused by this change |
| **Added, holds** / **Removed** | Your change added or deleted the policy |

For violated policies, a line of detail says exactly what was observed, for example *"forbidden traffic is delivered: INET -> R1 -> R3 -> DB"*.

#### 7. Downloads

- **Download report (Markdown)**: a readable report for reviews or tickets.
- **Download full result (JSON)**: everything, including inverse changes, per-hop traces, and the impact graph, for other tools.

---

## 4. How it works

The analysis runs in six steps.

1. **Build a "what if" network.** The change is applied to a *copy* of the network. Your original is never modified. If a change is invalid (for example editing a route that does not exist), you get a clear error instead of a wrong answer.

2. **Decide what to test.** It builds a list of traffic classes to simulate:
   - your declared **flows**,
   - the traffic covered by your **policies**, and
   - **exposure probes**: every pair of endpoints, for each service (protocol and port) that appears anywhere in the configuration. Probes are what find problems nobody wrote a policy for, such as "the database is suddenly reachable from the internet on a port nobody listed". The default cap is 2000; `--no-probes` turns them off.

3. **Simulate forwarding, before and after.** Each traffic class is traced hop by hop through both networks, the way a packet would travel: check the ACL at the device, find the best route (longest matching prefix, then lowest metric), move to the next hop, and repeat. The outcome is one of *delivered*, *dropped by ACL*, *loop*, *no route*, or *unusable next hop*. This is deterministic: the same input always gives the same result.

4. **Compare and find the cause.** For every traffic class that behaves differently, it finds the **first device where the before and after paths disagree** and matches that device (and the route, link, or ACL involved) to the specific change that touched it. This is the root cause.

5. **Explain.** It builds the propagation chain from cause to impact. The explanation text comes from fixed templates that are filled with facts the simulator actually observed. **It uses no AI model to explain or to decide**, so it cannot invent a cause that did not happen. All chains are also merged into one *impact graph* (in the JSON output) showing how one change fans out to several findings.

6. **Score and decide.** Findings are ranked by severity, a risk score is computed, and a verdict is chosen. If the verdict is negative, the change set is re-analysed without the guilty changes to verify the rollback recommendation.

### How the verdict is chosen

| Condition | Verdict |
|---|---|
| Any critical or high finding | **NOT_RECOMMENDED** |
| Else, any medium finding | **REVIEW** |
| Else, any info finding (a path change, for example) | **REVIEW** |
| Else | **SAFE** |

---

## 5. Understanding the risk score

The risk figure is a simple, transparent weighted sum, capped at 100:

```
score = min(100,  20 x broken flows
                + 30 x policy violations
                +  6 x newly reachable pairs
                + 10 x routing failures
                +  5 x criticality excess)
```

- **Routing failures** are loops, blackholes, and unusable next hops.
- **Criticality excess** adds extra weight when the affected flows or devices are important. It is the sum of (criticality - 1) over the affected items, where criticality runs from 1 to 5 on each flow and device in your network file.

| Score | Level |
|---|---|
| 0 | NONE |
| 1 to 24 | LOW |
| 25 to 49 | MEDIUM |
| 50 to 74 | HIGH |
| 75 to 100 | CRITICAL |

You can change the weights in the **Risk weights** section of the UI (or with `--weights`). **The defaults are starting points, not calibrated values.** Tune them to what matters in your environment.

**The verdict and the risk score are separate things.** The verdict comes from the findings; the score is a summary of size. A forwarding loop scoring 38 (MEDIUM) is still *Not recommended*, because a loop is an outage. A new backup link can score 0 (NONE) and still say *Review*, because a path changed. When they seem to disagree, trust the verdict and read the findings.

---

## 6. Input formats

### Network file

```json
{
  "name": "My network",
  "nodes":    [{"id": "R1", "type": "router", "ip_addresses": ["10.255.0.1"], "criticality": 3}],
  "links":    [{"source": "R1", "destination": "R2"}],
  "routes":   [{"router": "R1", "destination": "10.0.5.0/24", "next_hop": "R2", "metric": 1}],
  "acls":     [{"node": "FW", "source": "APP", "destination": "DB",
                "protocol": "TCP", "port": 5432, "action": "ALLOW"}],
  "flows":    [{"source": "APP", "destination": "DB", "protocol": "TCP", "port": 5432,
                "criticality": 5, "description": "App queries the database"}],
  "policies": [{"id": "P1", "action": "ALLOW", "source": "APP", "destination": "DB",
                "protocol": "TCP", "port": 5432, "waypoint": "FW"}]
}
```

- Node `type` is one of `router`, `firewall`, `host`, `server`, `internet`.
- Optional `x` and `y` (0 to 1) on nodes fix their place on the map. Without them, a layout is computed.
- A policy with `"action": "DENY"` means the traffic must **not** be delivered. With `"action": "ALLOW"` it must be delivered, and if `waypoint` is set it must pass through that device.
- References are validated: a link or route that names a device that does not exist is rejected with a readable message.

### Change file

A single change, a list, or `{"changes": [...]}`. Available operations:

| Operation | What it does |
|---|---|
| `ADD_ROUTE`, `DELETE_ROUTE`, `MODIFY_ROUTE` | Add, remove, or repoint a route on a router |
| `CHANGE_METRIC` | Change a route's metric |
| `ADD_LINK`, `DELETE_LINK` | Connect or disconnect two devices |
| `ADD_ACL_RULE`, `DELETE_ACL_RULE` | Insert (at a `position`) or remove a firewall rule |
| `ADD_POLICY`, `DELETE_POLICY` | Add or remove a requirement to check |

Example (`MODIFY_ROUTE`):

```json
[{"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24",
  "old_next_hop": "R2", "new_next_hop": "R3"}]
```

---

## 7. Worked example: reading a real result

The built-in **Three-tier app network** has a user, an app server, a database (DB), a backup server, an internet node, three routers (R1, R2, R3), and a firewall (FW). Normally the app reaches the database along `APP > R1 > R2 > FW > DB`, and the firewall stands in the way of everything else. Six policies describe this (P1 to P6), and all of them hold today.

Choose the preset **"Send database traffic via R3"** and press **Analyze change**. This repoints R1's route to the database subnet from R2 to R3. R3 has a direct link to DB, so it looks like a harmless shortcut. NetGuard-X shows:

- **Banner**: *Not recommended: INET can now reach DB on TCP/5432, which policy P4 forbids (and 3 more problems)*. Risk **Critical, 100 of 100**.
- **Findings**, four of them:
  - Two **critical** policy violations: the internet (P4) and the user machine (P3) can now reach the database.
  - One **high** waypoint bypass: APP to DB *still works* but no longer goes through the firewall (P1).
  - One **high** new exposure: DB is now reachable from APP, INET, and USER.
- **Why**: expand a finding and read the chain. R1 now picks R3, so the packet takes `R1 > R3 > DB` and skips `R2 > FW`. The firewall is no longer on the path, so its ACL never sees the traffic, and the forbidden flows get through.
- **Map**: on the *Changes* tab, `R2` and `FW` are marked as dropped from the path (dashed red), and `R3` and `DB` are the new path (green).
- **Flows table**: `APP > DB` is delivered before and after, so nothing looks broken to a simple "is it up?" check. This is the trap. It is the *security* consequence that matters. `USER > DB` and `INET > DB` flip from *dropped by ACL* to *delivered*.
- **Rollback**: revert change 1; without it the verdict is safe, with 0 remaining problems.

The point of the example: a plain reachability test would have said "the database is still reachable, all good". NetGuard-X notices that the traffic now avoids the firewall, and that other traffic is now let through.

### The other built-in examples

| Preset | What happens | Verdict |
|---|---|---|
| Cable the firewall straight to the backup server | Backup traffic takes a shorter path, still allowed | Review |
| Temporarily allow all traffic to the database | A broad ALLOW rule at the top of the firewall's ACL lets forbidden traffic through | Not recommended (Critical) |
| Decommission the R1-R2 link | Routes still point at a link that is gone; flows through it fail | Not recommended |
| Point R2 back at R1 | R1 and R2 send the traffic back and forth in a loop | Not recommended |
| Send database traffic via R3 | Bypasses the firewall (above) | Not recommended (Critical) |
| Tune the default route metric on R1 | Metric change with no effect on any flow | Safe |

---

## 8. Limits to keep in mind

- **A model is only as good as its input.** If a flow or policy is missing from your file, it is not checked directly (exposure probes catch many, but not all, of these gaps).
- **"Safe" means "safe within what is modelled".** Static routes and ACLs only; no NAT, no dynamic routing, no performance effects.
- **Draft from words is basic.** It handles simple route, link, and reachability sentences and reports what it could not read. Always check the JSON.
- **The risk weights are uncalibrated defaults.** Do not present the score as a measured probability.
- **Recommendation only.** NetGuard-X reads and reasons. It does not connect to devices.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Page will not load | Check that `python -m netguardx serve` is still running and that you used the right port |
| "Address already in use" | Another program uses port 8000; run with `--port 8001` |
| Red error text under the change box | The change JSON is invalid or refers to something that does not exist. The message says which device, route, or rule |
| Analysis is slow on a large network | Use `--no-probes` on the command line, or reduce the number of flows and services |
| A finding looks wrong | Expand it and read the technical detail and the before and after paths. Every claim is tied to a traced path, so the trace shows what the simulator saw |
| Fonts look plain | The UI asks Google Fonts for its typefaces. Offline, it falls back to system fonts; nothing else is affected |
