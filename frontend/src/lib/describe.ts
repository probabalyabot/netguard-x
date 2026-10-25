import type { AclRule, Change, Policy } from "../api/types";
import { svc } from "./format";

export const describeRule = (r: AclRule) => `${r.action} ${r.source ?? "any"} → ${r.destination ?? "any"} ${svc(r.protocol ?? "ANY", r.port)}`;
export const describePolicy = (p: Policy) => `${p.action} ${p.source} → ${p.destination} ${svc(p.protocol ?? "TCP", p.port)}${p.waypoint ? ` via ${p.waypoint}` : ""}`;

/** Mirrors Change.describe() in netguardx/models.py, for changes that have not been analysed yet. */
export function describeChange(c: Change): string {
  switch (c.operation) {
    case "ADD_ROUTE": return `Add route on ${c.router}: ${c.destination} via ${c.next_hop}`;
    case "DELETE_ROUTE": return `Delete route on ${c.router}: ${c.destination}${c.next_hop ? ` via ${c.next_hop}` : ""}`;
    case "MODIFY_ROUTE": return `Modify route on ${c.router}: ${c.destination} ${c.old_next_hop ? `${c.old_next_hop} → ` : "next hop → "}${c.new_next_hop}`;
    case "CHANGE_METRIC": return `Change metric on ${c.router}: ${c.destination} to ${c.new_metric}`;
    case "ADD_LINK": return `Add link ${c.node_a} – ${c.node_b}`;
    case "DELETE_LINK": return `Delete link ${c.node_a} – ${c.node_b}`;
    case "ADD_ACL_RULE": return c.rule ? `Add ACL rule on ${c.rule.node}: ${describeRule(c.rule)}` : "Add ACL rule";
    case "DELETE_ACL_RULE": return c.rule ? `Delete ACL rule on ${c.rule.node}: ${describeRule(c.rule)}` : `Delete ACL rule ${(c.rule_index ?? 0) + 1} on ${c.node}`; // people count rules from 1
    case "ADD_POLICY": return c.policy ? `Add policy: ${describePolicy(c.policy)}` : "Add policy";
    case "DELETE_POLICY": return `Delete policy ${c.policy_id}`;
    default: return String((c as Change).operation);
  }
}
