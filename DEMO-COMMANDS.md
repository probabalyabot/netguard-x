# NetGuard-X demo commands



1. **Ollama is running.** Open the Ollama app from the Start menu; the llama icon shows in the tray.
2. **Start the app:** VS Code on the `netguard-x` folder, **Ctrl+Shift+B**. Wait for the browser.
3. **Warm up:** draft one line from Part 2 before presenting. The first one takes a few seconds longer.
4. **Overview** screen: pick the network. **Change analysis** screen: the Drafter box is under the
   change set.
5. **Press Clear (top of the change set) before each new demo line.** Drafting replaces the last
   draft, but changes from earlier demos stay in the set and would be simulated together.
6. For a line you haven't rehearsed, press **Draft** first, check the "understood as" line, then
   **Simulate change**.

Verdicts: **Safe** · **Review before deploying** · **Not recommended**.

---

## Part 1: three-tier network, exact commands (instant)

Network: *Three-tier app network* (USER, APP, INET, R1, R2, R3, FW, BACKUP, DB).

| # | Type | Expect | The point |
|---|---|---|---|
| 1 | `set the metric of R1's default route to 50` | Safe | A harmless tweak passes with no findings |
| 2 | `change R1's route for 10.0.5.0/24 from R2 to R3` | **Not recommended**, critical: "INET can now reach DB on TCP/5432, which policy P4 forbids (and 3 more problems)" | **The headline.** Ping still works, but database traffic now skips the firewall |
| 3 | `cable the firewall straight to the backup server` | Review: "1 flow takes a different path; no policy is broken" | Behaviour changes, nothing breaks: a person decides |
| 4 | `change the route on R2 for DB from FW to R1` | Not recommended: "Forwarding loop for APP to DB" | Routing loop caught before it happens |
| 5 | `set the metric of R1's default route to 50, then change R1's route for 10.0.5.0/24 from R2 to R3` | Not recommended | Two changes at once: only the bad one is blamed, and the revert suggestion drops just that one |
| 6 | `allow everything from any to any on FW at the top` | Not recommended | Opening the firewall is a policy breach with no route change |
| 7 | `block postgres from APP to DB on FW at the top` | Not recommended: "APP to DB (TCP/5432) is now dropped at FW" | A critical flow is cut off |
| 8 | `remove the default route on FW` | Not recommended: "FW has no route for DB to BACKUP" | Backups silently discarded |
| 9 | `decommission the link between R1 and R2` | Not recommended: "R1 cannot forward APP to DB traffic" | A route left pointing at a removed link |

Cisco style (two lines, paste both):

```
R1(config)#
ip route 10.0.5.0 255.255.255.0 R3 50
```
→ Add route on R1: 10.0.5.0/24 via R3 · **Safe** (a backup route with a worse metric moves no traffic).

## Part 2: three-tier network, everyday English (a few seconds each)

Typed the way someone would say it; the "understood as" line shows the exact command it became.

| Type | Understood as | Expect |
|---|---|---|
| `R1 should send database traffic through R3 now` | Modify route on R1: 10.0.5.0/24 → R3 | **Not recommended** (same as #2) |
| `stop the user machine from sshing into the database` | Add ACL rule on FW: DENY USER → DB TCP 22 | Safe |
| `FW(config)# access-list 101 deny tcp host 10.0.0.10 host 10.0.5.10 eq 22` | Add ACL rule on FW: DENY USER → DB TCP 22 | Safe |
| `let anyone reach the app over https, put it at the top` | Add ACL rule on FW: ALLOW any → APP TCP 443 (first) | Review: "APP becomes reachable from DB" |
| `plug the firewall into the backup server` | Add link FW – BACKUP | Review |
| `get rid of the 2nd firewall rule` | Delete ACL rule 2 on FW | Not recommended: "DB to BACKUP is now dropped at FW" |
| `unplug R1 from R2` | Delete link R1 – R2 | Not recommended |
| `take out R1's default route` | Delete route on R1: 0.0.0.0/0 | Safe |
| `on FW, block ssh from USER to DB` | Add ACL rule on FW: DENY USER → DB TCP 22 | Safe |

## Part 3: it never guesses

Each is **not simulated**, with a message saying what's missing:

| Type | Message |
|---|---|
| `make the network faster` | not understood (no concrete change) |
| `delete rule 7 on FW` | FW has only 3 rules |
| `ip route 10.0.7.0 255.255.255.0 R3` | a Cisco line needs a device: start with `R1(config)#` … |

## Part 4: 60-device enterprise network

Pick *Enterprise network* on Overview first. Names differ here: DB1, DB2, DB-FW, DC-FW, FW-EDGE, CORE1 …

| Type | Expect |
|---|---|
| `set the metric of FW-EDGE's default route via EDGE2 to 200` | Safe |
| `change DC-R's route for 10.20.5.0/24 from DB-FW to SAN-R` | **Not recommended**: "APP1 to DB1 no longer passes through DB-FW (and 3 more problems)". The headline at scale |
| `send the primary database's traffic on DC-R through the storage router` | Same change and verdict, in everyday English |
| `set the metric of WAN-R's default route via CORE1 to 5` | Review: "7 flows take a different path" |
| `delete rule 2 on GUEST-R` | Not recommended: "GUEST1 can now reach AUTH on TCP/389, which policy P21 forbids" |
| `allow everything from any to any on FW-EDGE at the top` | Not recommended: "INET can now reach JUMP on TCP/22" |
| `cut the cable between core1 and the datacenter firewall` | Not recommended (CORE1 – DC-FW link removed) |
| `block ssh from the guest laptop to the primary database on the database firewall` | Safe (DENY GUEST1 → DB1 on DB-FW) |
| `block ssh from GUEST1 to DB1 on the firewall` | Not simulated: "this network has DB-FW, DC-FW and FW-EDGE" |

## Part 5 (optional): the gatekeeper session, from a terminal

In the `netguard-x` folder, with the venv active:

```
python -m netguardx session netguardx/examples/basic.json test-scripts/session.txt
```
Ends with 5 executed, 1 held, 7 rejected, 1 not understood. Shows the policy lock: the agent may
not add "USER must never reach DB".

```
python -m netguardx session netguardx/examples/enterprise.json test-scripts/enterprise-session.txt
```
Ends with 6 executed, 2 held, 10 rejected, 2 not understood. Point out the three VPN rules: the
first two pass because the next firewall still blocks; the third completes the path and is rejected.

## If something goes wrong

- **Everyday English stops working:** Ollama isn't running. Parts 1, 3 and 4 still work instantly
  with exact commands.
- **A line reads wrong:** press Clear and use the exact command from Part 1 or 4 instead.
- **Simulate does nothing:** something wasn't understood; "Draft and simulate" waits until every
  line is. Fix or remove the red line.
- **Backup plan:** the *Example scenarios* list at the top of Change analysis runs the same demos
  with one click each.
