import type { Decision, DeltaOutcome, PolicyStatus, Severity, Trace } from "../api/types";

export const svc = (proto?: string | null, port?: number | null) =>
  !proto || proto === "ANY" ? (port != null ? `*/${port}` : "any") : port != null ? `${proto}/${port}` : proto;

export type Tone = "safe" | "warn" | "bad" | "net" | "muted";

export const decisionTone: Record<Decision, Tone> = { SAFE: "safe", REVIEW: "warn", NOT_RECOMMENDED: "bad" };
export const decisionLabel: Record<Decision, string> = { SAFE: "Safe", REVIEW: "Review", NOT_RECOMMENDED: "Not recommended" };
export const severityTone: Record<Severity, Tone> = { critical: "bad", high: "bad", medium: "warn", info: "net" };
export const outcomeLabel: Record<DeltaOutcome, string> = {
  path_changed: "Path changed", newly_reachable: "Now reachable", newly_unreachable: "No longer reachable", status_changed: "Failure mode changed",
};
export const outcomeTone: Record<DeltaOutcome, Tone> = {
  path_changed: "net", newly_reachable: "warn", newly_unreachable: "bad", status_changed: "warn",
};
export const policyStatusLabel: Record<PolicyStatus, string> = {
  ok: "Holds", new_violation: "Newly violated", resolved: "Now satisfied", preexisting_violation: "Already violated",
  added: "Added, holds", removed: "Removed",
};
export const policyStatusTone: Record<PolicyStatus, Tone> = {
  ok: "safe", new_violation: "bad", resolved: "safe", preexisting_violation: "warn", added: "safe", removed: "muted",
};
export const riskTone = (level: string): Tone =>
  level === "NONE" ? "safe" : level === "LOW" ? "net" : level === "MEDIUM" ? "warn" : "bad";

export const statusText: Record<string, string> = {
  DELIVERED: "Delivered", DROPPED_ACL: "Dropped by ACL", LOOP: "Forwarding loop", BLACKHOLE: "No route (blackhole)",
  INVALID_NEXT_HOP: "Unusable next hop",
};
export const statusLabel = (s: string) => statusText[s] ?? s;
export const statusTone = (s: string): Tone => (s === "DELIVERED" ? "safe" : "bad");

export const findingTypeLabel: Record<string, string> = {
  POLICY_VIOLATION: "Policy violation", WAYPOINT_BYPASS: "Waypoint bypassed", ROUTING_LOOP: "Routing loop", BLACKHOLE: "Blackhole",
  INVALID_NEXT_HOP: "Invalid next hop", FLOW_BLOCKED: "Flow blocked", NEW_EXPOSURE: "New exposure", PATH_CHANGED: "Path changed",
  FLOW_RESTORED: "Flow restored", NEW_REACHABILITY: "New reachability",
};

export const toneClass: Record<Tone, string> = {
  safe: "text-safe border-safe/40 bg-safe/10", warn: "text-warn border-warn/40 bg-warn/10",
  bad: "text-bad border-bad/40 bg-bad/10", net: "text-net border-net/40 bg-net/10", muted: "text-muted border-line-strong bg-raised",
};
export const toneText: Record<Tone, string> = { safe: "text-safe", warn: "text-warn", bad: "text-bad", net: "text-net", muted: "text-muted" };
export const toneVar: Record<Tone, string> = {
  safe: "rgb(var(--safe))", warn: "rgb(var(--warn))", bad: "rgb(var(--bad))", net: "rgb(var(--net))", muted: "rgb(var(--muted))",
};

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "n/a" : `${(v * 100).toFixed(digits)}%`);
export const ms = (v: number | null | undefined) => (v == null ? "n/a" : v < 10 ? `${v.toFixed(2)} ms` : `${v.toFixed(1)} ms`);

/** Where a trace stops, for display. */
export function traceEnd(t: Trace): string {
  return t.status === "DELIVERED" ? `delivered at ${t.path[t.path.length - 1]}` : `${statusLabel(t.status).toLowerCase()} at ${t.stop_node ?? t.path[t.path.length - 1]}`;
}

export const edgeKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));
/** A count, possibly averaged over seeds: whole numbers as they are, otherwise one decimal. */
export const count = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
