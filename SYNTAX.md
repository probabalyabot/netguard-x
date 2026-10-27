# Typing changes: what the parser understands

NetGuard-X turns typed sentences and Cisco-style config lines into checked changes. This page lists
what it understands, with examples copied from real parser output.

The parser follows rules; it is not a language model. If a sentence doesn't match one of the
patterns below, it says **not understood** and gives a reason. It never guesses.

You can type in three places:

- **The web app:** the Drafter box on the **Change analysis** screen. Press **Draft** (or Ctrl+Enter)
  to see how each line was understood, or **Draft and simulate** to analyse it straight away.
- **The command line, to draft:**
  `python -m netguardx draft netguardx/examples/basic.json "block ssh from USER to DB on FW"`
- **The command line, as the gatekeeper:** `python -m netguardx session <network.json> <commands.txt>`
  checks one command per line.

Examples marked **(basic)** use the three-tier network, and **(enterprise)** the 60-device one.
Device names only work on the network that has those devices.

In the "Understood as" columns, the text is the parser's own read-back. Details in brackets, such
as a metric, a cost or a rule position, are part of the drafted change, but the read-back line
doesn't show them.

---

## The five rules to remember

1. **Name devices exactly as the network names them.** On the enterprise network there is no `DB` or
   `FW`; there are `DB1`, `DB2`, `DB-FW`, `DC-FW` and `FW-EDGE`.
2. **Firewall rules need `on <device>`:** the device the rule goes on. `via` is for routes.
3. **Routes need a router (`on R1`) and a destination.** Adding or changing one also needs a next
   hop (`via R3`).
4. **Rule numbers and positions count from 1.** "rule 1" is the first rule.
5. **One change per sentence.** Put several on separate lines, or join them with `;`, `.` or
   `, then`.

Upper or lower case doesn't matter, for keywords or device names.

---

## Naming devices

| You can write | Example | Means |
|---|---|---|
| Its id | `DB1`, `dc-fw` | DB1, DC-FW |
| Its label | `Primary database`, `the guest laptop` | DB1, GUEST1 |
| Its address | `10.2.2.11` | BR2-PC1 (enterprise) |
| A role word, when the network has exactly one of that kind | `the firewall`, `the internet` | FW (basic); INET |

- An address with a prefix length or netmask (`10.0.5.0/24`, `10.0.5.0 255.255.255.0`) is a
  **range of addresses**, not a device.
- A word that looks like a device name but isn't one gets a hint: "unknown device FWW (did you mean
  FW?)". In the app, click the hint to fix it.
- "The firewall" on the enterprise network is refused, because it has three; the error lists them.

**Basic network devices:** USER, APP, INET (the internet), R1, R2, R3, FW, BACKUP, DB.

**Enterprise network devices:**

| Area | Devices |
|---|---|
| Internet edge | INET, EDGE1, EDGE2, FW-EDGE (perimeter firewall) |
| DMZ | DMZ-R, WEB1, WEB2, MAIL, DNS, VPN |
| Core | CORE1, CORE2 |
| Data centre | DC-FW (data-centre firewall), DC-R, APP1, APP2, APP3, AUTH, FILES, PRINT, LOG, BACKUP |
| Databases | DB-FW (database firewall), DB1, DB2, SAN-R (storage router) |
| Management | MGMT-R, JUMP, MON, NOC |
| Head office | HQ-R1, HQ-R2, HQ-PC1 to HQ-PC8 |
| Branches | WAN-R, BR1-R to BR3-R, each with PC1, PC2 and POS (e.g. BR2-PC1, BR3-POS) |
| Guest Wi-Fi | GUEST-R, GUEST1, GUEST2 |
| Dev lab | DEV-R, DEV1, DEV2, CI |

---

## Firewall (ACL) rules

### Adding a rule

```
<allow | block> [service] [from <source>] [to <destination>] on <device> [position]
```

- **allow** can also be written *permit*. **block** can also be *deny* or *forbid*.
- **Source and destination:** a device, an address, a range (`10.0.0.0/24`) or `any`. If you leave
  one out, it means any.
- **Service:**
  - a name: ssh, telnet, smtp, dns, http, https, ntp, snmp, ldap, smb, rsync, mysql, rdp, postgres,
    redis, ping or icmp
  - or written out: `tcp/8080`, `udp 53`, `port 3389` (port alone means TCP)
  - Leave it out to cover all traffic.
- **Position:** `at the top`, `first`, `at position 2` or `as rule 2`. Leave it out to add the rule
  at the end. Rules are checked top to bottom, and the first one that matches decides.

| You type | Understood as |
|---|---|
| `block ssh from USER to DB on FW` **(basic)** | Add ACL rule on FW: DENY USER → DB TCP port 22 |
| `allow https from any to APP on FW at the top` **(basic)** | Add ACL rule on FW: ALLOW any → APP TCP port 443 (first) |
| `deny tcp/8080 from 10.0.0.0/24 to DB on FW` **(basic)** | Add ACL rule on FW: DENY 10.0.0.0/24 → DB TCP port 8080 |
| `permit APP to BACKUP on FW at position 2` **(basic)** | Add ACL rule on FW: ALLOW APP → BACKUP, all traffic (2nd) |
| `block ping from the internet to APP on FW` **(basic)** | Add ACL rule on FW: DENY INET → APP ICMP |
| `deny udp 53 from USER to any on FW` **(basic)** | Add ACL rule on FW: DENY USER → any UDP port 53 |
| `block port 3389 to DB on FW` **(basic)** | Add ACL rule on FW: DENY any → DB TCP port 3389 |
| `block ssh from 10.2.2.11 to DB1 on DB-FW` **(enterprise)** | Add ACL rule on DB-FW: DENY BR2-PC1 → DB1 TCP port 22 |
| `block ssh from GUEST1 to JUMP on DC-FW` **(enterprise)** | Add ACL rule on DC-FW: DENY GUEST1 → JUMP TCP port 22 |

### Deleting a rule

You can name the rule by its number:

```
delete rule <n> on <device>
```

or by what it does:

```
remove the rule on <device> that <allows|blocks> <source> to <destination>
```

| You type | Understood as |
|---|---|
| `delete rule 2 on FW` **(basic)** | Delete ACL rule 2 on FW |
| `delete the third rule on FW` **(basic)** | Delete ACL rule 3 on FW |
| `remove the rule on FW that allows APP to DB` **(basic)** | Delete ACL rule 1 on FW |

If more than one rule matches the description, the parser lists their numbers and asks you to choose
one.

---

## Routes

```
<add | change | send | point | remove | set the metric of> ... on <router> ... [via <next hop>]
```

**The destination** can be written as:
- a range: `10.0.5.0/24`, `10.0.5.0 255.255.255.0`, or a single address
- `the default route`
- a device: `DB traffic`, `for DB`. This means the router's most specific existing route that
  covers that device. The parser won't quietly edit a default route this way; it asks for the range
  instead.

**The next hop** goes after `via`, `through` or `using`, or after `to` in "change … to R3". It can
be a device or its address.

| You type | Understood as |
|---|---|
| `add a route on R1 to 10.0.7.0/24 via R3 with metric 20` **(basic)** | Add route on R1: 10.0.7.0/24 via R3 (metric 20) |
| `add a route on R3 to DB via R2` **(basic)** | Add route on R3: 10.0.5.10/32 via R2 |
| `change the route on R1 for 10.0.5.0/24 to R3` **(basic)** | Modify route on R1: 10.0.5.0/24 next hop → R3 |
| `send DB traffic on R1 via R3` **(basic)** | Modify route on R1: 10.0.5.0/24 next hop → R3 |
| `change R1's route for DB from R2 to R3` **(basic)** | Modify route on R1: 10.0.5.0/24 R2 → R3 |
| `point R2 at R1 for 10.0.5.0/24` **(basic)** | Modify route on R2: 10.0.5.0/24 next hop → R1 |
| `reroute 10.0.6.0 255.255.255.0 on R1 through R3` **(basic)** | Modify route on R1: 10.0.6.0/24 next hop → R3 |
| `remove the default route on R1` **(basic)** | Delete route on R1: 0.0.0.0/0 |
| `delete the route on R1 for 10.0.6.0/24` **(basic)** | Delete route on R1: 10.0.6.0/24 |
| `set the metric of R1's default route to 50` **(basic)** | Change metric on R1: 0.0.0.0/0 to 50 |
| `send DB1 traffic on DC-R via SAN-R` **(enterprise)** | Modify route on DC-R: 10.20.5.0/24 next hop → SAN-R |

### Cisco-style lines

Name the router once in a header line, then put the `ip route` lines under it. These headers all
work: `R1(config)#`, `R1#`, `on R1:` and `configure R1`. Session lines such as `conf t`, `end`,
`exit`, `write mem` and `!` comments are skipped.

```
R1(config)#
ip route 10.0.7.0 255.255.255.0 R3 20
no ip route 10.0.6.0 255.255.255.0 R2
```

| You type | Understood as |
|---|---|
| `ip route 10.0.7.0 255.255.255.0 R3 20` (under `R1(config)#`) | Add route on R1: 10.0.7.0/24 via R3 (metric 20) |
| `R1(config)# no ip route 10.0.6.0 255.255.255.0 R2` | Delete route on R1: 10.0.6.0/24 via R2 |
| `on R1: ip route 10.0.8.0 255.255.255.0 10.255.0.3` | Add route on R1: 10.0.8.0/24 via R3 |
| `ip route 10.20.7.0 255.255.255.0 SAN-R` (under `DC-R(config)#`) **(enterprise)** | Add route on DC-R: 10.20.7.0/24 via SAN-R |

- The number after the next hop is the metric.
- `ip route` for a range that already has a route adds a **second** route, as a real router would.
  To replace a next hop, write "change … to …" instead.
- Cisco `access-list` lines are not supported; write firewall rules as sentences.

---

## Links (cables)

| You type | Understood as |
|---|---|
| `connect R2 and R3 with cost 5` **(basic)** | Add link R2 – R3 (cost 5) |
| `cable FW to BACKUP` **(basic)** | Add link FW – BACKUP |
| `add a link between R3 and FW` **(basic)** | Add link R3 – FW |
| `remove the link between R1 and R2` **(basic)** | Delete link R1 – R2 |
| `disconnect R1 from R2` **(basic)** | Delete link R1 – R2 |
| `remove the link between CORE1 and DC-FW` **(enterprise)** | Delete link CORE1 – DC-FW |

---

## Requirements (policies)

A requirement says what must, or must never, be able to reach what. It isn't a change; the analysis
checks every change against it.

```
<source> must [never | not] <reach | access | talk to> <destination> [through <device>] [on port <n>]
```

| You type | Understood as |
|---|---|
| `APP must reach DB through FW on port 5432` **(basic)** | Requirement: ALLOW APP → DB TCP/5432 via FW |
| `USER must never reach DB` **(basic)** | Requirement: DENY USER → DB TCP |
| `the internet must not access DB on port 5432` **(basic)** | Requirement: DENY INET → DB TCP/5432 |
| `BACKUP should be able to talk to DB` **(basic)** | Requirement: ALLOW BACKUP → DB TCP |
| `DEV1 must never reach DB1` **(enterprise)** | Requirement: DENY DEV1 → DB1 TCP |
| `delete policy P3` | Delete policy P3 |

In a `session`, the commands act as the AI agent, so adding or deleting requirements is refused by
the policy lock. Use `--operator` to act as a person.

---

## Several changes at once

Put each change on its own line, or separate them with `;`, a full stop, or `, then`. A plain "and"
never splits ("connect R2 and R3" is one link). Changes are checked in order, so a later one can use
what an earlier one created.

| You type | Understood as |
|---|---|
| `connect R2 and R3, then send DB traffic on R1 via R3` | Add link R2 – R3; Modify route on R1: 10.0.5.0/24 next hop → R3 |
| `block ssh from USER to DB on FW; delete rule 3 on FW` | Add ACL rule on FW: …; Delete ACL rule 3 on FW |
| `cable FW to BACKUP. Remove the link between R2 and FW` | Add link FW – BACKUP; Delete link R2 – FW |

---

## When it says "not understood"

| Message | What it means | Fix |
|---|---|---|
| `unknown device FWW (did you mean FW?)` | A name that isn't on this network | Use the suggested name |
| `unknown device firewall: this network has DB-FW, DC-FW and FW-EDGE` | The role word fits more than one device | Name one of them |
| `an ACL rule needs a device ('on FW')` | A firewall rule with no `on <device>` (often `via` was used) | Add `on <device>` |
| `could not tell which device 'to the moon' means` | What follows `from` or `to` isn't a device, address or `any` | Name a device or address |
| `could not find the next hop ('via R3')` | A route change with no next hop | Add `via <device>` |
| `R1 has no specific route for USER (only the default route covers it)` | "USER traffic" would mean editing the default route | Give the range, or say "the default route" |
| `a Cisco line needs a device` | `ip route` with no header above it | Put `R1(config)#` above it, or `on R1:` in front |
| `FW has only 3 rules` / `rules count from 1` | The rule number doesn't exist | Use a number from 1 to the rule count |
| `no policy P9 (policies: P1, …)` | No requirement with that id | Pick one from the list |
| `cannot apply to this network: R3 has no route 10.0.5.0/24` | Understood, but the network has nothing to change | Check the router and range |

---

## Known gaps

- **An error can blame the wrong word.** If a sentence fails for any reason, the first word that
  looks like a device name gets blamed. For example, "block ssh FROM 10.2.2.11 to DB on FW" on the
  enterprise network reports "unknown device FROM", even though capital FROM is fine and the real
  problems are DB and FW.
- **No "the" after "on".** "on database firewall" works, but "on the database firewall" does not.
  "The" before a source or destination is fine.
- **Typo suggestions pick one name.** "DB" on the enterprise network suggests only DB2, not DB1 and
  DB2.
- **The hint under the Drafter box always uses the basic network's names**, even on the enterprise
  network.
- **Not supported:** Cisco `access-list` lines, NAT, dynamic routing (OSPF, BGP), and rules on
  return traffic.
