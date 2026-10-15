import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import type { Change, Network, Operation } from "../api/types";
import { describeRule } from "../lib/describe";
import { OPERATIONS, validateChanges } from "../lib/validate";

type Kind = "node" | "text" | "number" | "action" | "protocol";
interface Field { key: string; label: string; kind: Kind; optional?: boolean; placeholder?: string }
const f = (key: string, label: string, kind: Kind, optional = false, placeholder?: string): Field => ({ key, label, kind, optional, placeholder });

const RULE: Field[] = [
  f("rule.node", "Device", "node"), f("rule.source", "Source (id, IP, CIDR or any)", "text", true, "any"),
  f("rule.destination", "Destination", "text", true, "any"), f("rule.protocol", "Protocol", "protocol", true),
  f("rule.port", "Port", "number", true), f("rule.action", "Action", "action"),
];
const POLICY: Field[] = [
  f("policy.action", "Requirement", "action"), f("policy.source", "Source", "node"), f("policy.destination", "Destination", "node"),
  f("policy.protocol", "Protocol", "protocol", true), f("policy.port", "Port", "number", true),
  f("policy.waypoint", "Must pass through", "node", true), f("policy.id", "Policy id", "text", true, "auto"),
];
const SPEC: Record<Operation, Field[]> = {
  ADD_ROUTE: [f("router", "Device", "node"), f("destination", "Prefix", "text", false, "10.0.5.0/24"), f("next_hop", "Next hop", "node"), f("metric", "Metric", "number", true)],
  DELETE_ROUTE: [f("router", "Device", "node"), f("destination", "Prefix", "text", false, "10.0.5.0/24"), f("next_hop", "Next hop", "node", true)],
  MODIFY_ROUTE: [f("router", "Device", "node"), f("destination", "Prefix", "text", false, "10.0.5.0/24"), f("old_next_hop", "Current next hop", "node", true), f("new_next_hop", "New next hop", "node"), f("new_metric", "New metric", "number", true)],
  CHANGE_METRIC: [f("router", "Device", "node"), f("destination", "Prefix", "text", false, "0.0.0.0/0"), f("next_hop", "Next hop", "node", true), f("new_metric", "New metric", "number")],
  ADD_LINK: [f("node_a", "Device A", "node"), f("node_b", "Device B", "node"), f("cost", "Cost", "number", true)],
  DELETE_LINK: [f("node_a", "Device A", "node"), f("node_b", "Device B", "node")],
  ADD_ACL_RULE: [...RULE, f("position", "Position (0 = top)", "number", true)],
  DELETE_ACL_RULE: [],
  ADD_POLICY: POLICY,
  DELETE_POLICY: [],
};

type Draft = Record<string, string>;

function build(op: Operation, d: Draft, spec: Field[]): Change {
  const c: Record<string, unknown> = { operation: op };
  const nested: Record<string, Record<string, unknown>> = {};
  for (const fld of spec) {
    const raw = (d[fld.key] ?? "").trim();
    if (raw === "") continue;
    const v: unknown = fld.kind === "number" ? Number(raw) : raw;
    const [head, tail] = fld.key.split(".");
    if (tail) (nested[head] ??= {})[tail] = v; else c[head] = v;
  }
  Object.assign(c, nested);
  return c as unknown as Change;
}

export function ChangeBuilder({ network, onAdd }: { network: Network; onAdd: (c: Change) => void }) {
  const [op, setOp] = useState<Operation>("MODIFY_ROUTE");
  const [draft, setDraft] = useState<Draft>({ "rule.action": "ALLOW", "policy.action": "DENY" });
  const [errors, setErrors] = useState<string[]>([]);
  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }));
  const spec = SPEC[op];
  const nodeIds = useMemo(() => network.nodes.map((n) => n.id), [network]);
  const routes = network.routes ?? [], acls = network.acls ?? [], policies = network.policies ?? [];

  const pickRoute = (i: string) => {
    if (i === "") return;
    const r = routes[Number(i)];
    setDraft((d) => ({ ...d, router: r.router, destination: r.destination, [op === "MODIFY_ROUTE" ? "old_next_hop" : "next_hop"]: r.next_hop }));
  };

  const add = () => {
    let change: Change;
    if (op === "DELETE_ACL_RULE") {
      const i = draft.aclIndex;
      if (!i) { setErrors(["Choose the ACL rule to delete."]); return; }
      change = { operation: op, rule: acls[Number(i)] };
    } else if (op === "DELETE_POLICY") {
      if (!draft.policy_id) { setErrors(["Choose the policy to delete."]); return; }
      change = { operation: op, policy_id: draft.policy_id };
    } else change = build(op, draft, spec);
    const { errors } = validateChanges([change], network);
    if (errors.length) { setErrors(errors); return; }
    setErrors([]); onAdd(change);
  };

  const input = (fld: Field) => {
    const id = `cb-${fld.key}`;
    const v = draft[fld.key] ?? "";
    const common = { id, className: "field", value: v, onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => set(fld.key, e.target.value) };
    if (fld.kind === "node") return <select {...common}><option value="">{fld.optional ? "Any / not set" : "Choose a device"}</option>{nodeIds.map((n) => <option key={n}>{n}</option>)}</select>;
    if (fld.kind === "action") return <select {...common}><option>ALLOW</option><option>DENY</option></select>;
    if (fld.kind === "protocol") return <select {...common}><option value="">Default</option><option>TCP</option><option>UDP</option><option>ICMP</option><option>ANY</option></select>;
    return <input {...common} type={fld.kind === "number" ? "number" : "text"} min={fld.kind === "number" ? 0 : undefined} placeholder={fld.placeholder} spellCheck={false} />;
  };

  return (
    <div className="space-y-3">
      <div>
        <label className="label" htmlFor="cb-op">Operation</label>
        <select id="cb-op" className="field" value={op} onChange={(e) => { setOp(e.target.value as Operation); setErrors([]); }}>
          {OPERATIONS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
        </select>
      </div>
      {(op === "DELETE_ROUTE" || op === "MODIFY_ROUTE" || op === "CHANGE_METRIC") && (
        <div>
          <label className="label" htmlFor="cb-route">Pick an existing route (fills the fields below)</label>
          <select id="cb-route" className="field" defaultValue="" onChange={(e) => pickRoute(e.target.value)}>
            <option value="">Choose…</option>
            {routes.map((r, i) => <option key={i} value={i}>{r.router}: {r.destination} via {r.next_hop}</option>)}
          </select>
        </div>
      )}
      {op === "DELETE_ACL_RULE" && (
        <div>
          <label className="label" htmlFor="cb-acl">ACL rule</label>
          <select id="cb-acl" className="field" value={draft.aclIndex ?? ""} onChange={(e) => set("aclIndex", e.target.value)}>
            <option value="">{acls.length ? "Choose a rule" : "This network has no ACL rules"}</option>
            {acls.map((a, i) => <option key={i} value={i}>{a.node}: {describeRule(a)}</option>)}
          </select>
        </div>
      )}
      {op === "DELETE_POLICY" && (
        <div>
          <label className="label" htmlFor="cb-pol">Policy</label>
          <select id="cb-pol" className="field" value={draft.policy_id ?? ""} onChange={(e) => set("policy_id", e.target.value)}>
            <option value="">{policies.length ? "Choose a policy" : "This network has no policies"}</option>
            {policies.map((p) => <option key={p.id} value={p.id ?? ""}>{p.id}: {p.action} {p.source} → {p.destination}{p.port != null ? `/${p.port}` : ""}</option>)}
          </select>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {spec.map((fld) => (
          <div key={fld.key} className={fld.kind === "text" && fld.key.endsWith("source") ? "col-span-2" : undefined}>
            <label className="label" htmlFor={`cb-${fld.key}`}>{fld.label}{fld.optional && <span className="text-faint"> (optional)</span>}</label>
            {input(fld)}
          </div>
        ))}
      </div>
      {errors.length > 0 && <ul role="alert" className="space-y-0.5 text-sm text-bad">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
      <button type="button" className="btn" onClick={add}><Plus size={15} aria-hidden />Add to change set</button>
    </div>
  );
}
