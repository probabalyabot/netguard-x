import type { Change, Network, Operation } from "../api/types";

export const OPERATIONS: { op: Operation; label: string; hint: string }[] = [
  { op: "ADD_ROUTE", label: "Add route", hint: "router, destination, next_hop" },
  { op: "DELETE_ROUTE", label: "Delete route", hint: "router, destination" },
  { op: "MODIFY_ROUTE", label: "Modify route", hint: "router, destination, new_next_hop" },
  { op: "CHANGE_METRIC", label: "Change metric", hint: "router, destination, new_metric" },
  { op: "ADD_LINK", label: "Add link", hint: "node_a, node_b" },
  { op: "DELETE_LINK", label: "Delete link", hint: "node_a, node_b" },
  { op: "ADD_ACL_RULE", label: "Add ACL rule", hint: "rule" },
  { op: "DELETE_ACL_RULE", label: "Delete ACL rule", hint: "rule, or node + rule_index" },
  { op: "ADD_POLICY", label: "Add policy", hint: "policy" },
  { op: "DELETE_POLICY", label: "Delete policy", hint: "policy_id" },
];
const OPS = new Set<string>(OPERATIONS.map((o) => o.op));

const REQUIRED: Record<Operation, (keyof Change)[]> = {
  ADD_ROUTE: ["router", "destination", "next_hop"], DELETE_ROUTE: ["router", "destination"],
  MODIFY_ROUTE: ["router", "destination", "new_next_hop"], CHANGE_METRIC: ["router", "destination", "new_metric"],
  ADD_LINK: ["node_a", "node_b"], DELETE_LINK: ["node_a", "node_b"], ADD_ACL_RULE: ["rule"],
  DELETE_ACL_RULE: [], ADD_POLICY: ["policy"], DELETE_POLICY: ["policy_id"],
};

/**
 * Fast, local checks so obvious mistakes show up while typing. The backend (pydantic + the change
 * engine) stays authoritative: anything this misses comes back as a 422 with a readable message.
 */
export function validateChanges(value: unknown, network?: Network | null): { changes: Change[]; errors: string[] } {
  const errors: string[] = [];
  let list: unknown = value;
  if (list && !Array.isArray(list) && typeof list === "object") {
    const o = list as { changes?: unknown };
    list = Array.isArray(o.changes) ? o.changes : [list];
  }
  if (!Array.isArray(list)) return { changes: [], errors: ["Expected a list of changes, e.g. [{ \"operation\": \"ADD_LINK\", ... }]."] };
  const ids = new Set((network?.nodes ?? []).map((n) => n.id));
  const nodeFields: (keyof Change)[] = ["router", "next_hop", "old_next_hop", "new_next_hop", "node_a", "node_b", "node"];
  list.forEach((raw, i) => {
    const at = `Change ${i + 1}`;
    if (!raw || typeof raw !== "object") { errors.push(`${at}: must be an object.`); return; }
    const c = raw as Change;
    if (!OPS.has(c.operation)) { errors.push(`${at}: unknown operation ${JSON.stringify(c.operation)}.`); return; }
    const missing = REQUIRED[c.operation].filter((f) => c[f] === undefined || c[f] === null || c[f] === "");
    if (missing.length) errors.push(`${at} (${c.operation}): missing ${missing.join(", ")}.`);
    if (c.operation === "DELETE_ACL_RULE" && !c.rule && !(c.node && c.rule_index != null))
      errors.push(`${at} (DELETE_ACL_RULE): needs "rule", or both "node" and "rule_index".`);
    if (ids.size) for (const f of nodeFields) {
      const v = c[f];
      if (typeof v === "string" && v && !ids.has(v)) errors.push(`${at}: ${f} "${v}" is not a device in this network.`);
    }
  });
  return { changes: list as Change[], errors };
}

export function validateNetwork(value: unknown): string | null {
  if (!value || typeof value !== "object") return "A network is a JSON object with a \"nodes\" list.";
  const n = value as Network;
  if (!Array.isArray(n.nodes) || n.nodes.length === 0) return "The network needs a non-empty \"nodes\" list.";
  if (n.nodes.some((x) => !x || typeof x.id !== "string")) return "Every node needs a string \"id\".";
  return null;
}
