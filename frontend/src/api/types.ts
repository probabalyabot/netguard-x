/** Types mirror netguardx/models.py, impact.py, verify.py, risk.py and eval/run.py. */

export type NodeType = "router" | "firewall" | "host" | "server" | "internet";
export type Action = "ALLOW" | "DENY";

export interface NetNode {
  id: string; type: NodeType; ip_addresses?: string[]; default_action?: Action | null;
  criticality?: number; label?: string | null; x?: number | null; y?: number | null;
}
export interface Link { source: string; destination: string; cost?: number }
export interface Route { router: string; destination: string; next_hop: string; metric?: number }
export interface AclRule { node: string; source?: string; destination?: string; protocol?: string; port?: number | null; action: Action }
export interface Flow { id?: string | null; source: string; destination: string; protocol?: string; port?: number | null; criticality?: number; description?: string | null }
export interface Policy { id?: string | null; source: string; destination: string; protocol?: string; port?: number | null; action: Action; waypoint?: string | null; description?: string | null }
export interface Network {
  name?: string; nodes: NetNode[]; links?: Link[]; routes?: Route[]; acls?: AclRule[]; flows?: Flow[]; policies?: Policy[];
}

export type Operation =
  | "ADD_ROUTE" | "DELETE_ROUTE" | "MODIFY_ROUTE" | "CHANGE_METRIC" | "ADD_LINK"
  | "DELETE_LINK" | "ADD_ACL_RULE" | "DELETE_ACL_RULE" | "ADD_POLICY" | "DELETE_POLICY";

export interface Change {
  operation: Operation;
  router?: string; destination?: string; next_hop?: string; metric?: number;
  old_next_hop?: string; new_next_hop?: string; new_metric?: number;
  node_a?: string; node_b?: string; cost?: number;
  node?: string; rule?: AclRule; rule_index?: number; position?: number;
  policy?: Policy; policy_id?: string; note?: string;
}

export interface ExampleChange { id: string; network: string; title?: string; description?: string; changes: Change[] }
export interface ExampleNetwork { id: string; title: string; network: Network }
export interface ExamplesResponse { networks: ExampleNetwork[]; changes: ExampleChange[] }

// ----- topology (shared by verify / simulate / diff)
export interface TopoNode { id: string; type: NodeType; label: string; ip: string | null; x: number; y: number; criticality: number }
export interface TopoLink { source: string; destination: string; status: "unchanged" | "added" | "removed" }
export interface Topology { nodes: TopoNode[]; links: TopoLink[] }

// ----- traces
export interface HopRoute { prefix: string; next_hop: string; metric: number; origin: string }
export interface AclDecision { node: string; action: string; rule_index: number | null; rule: string }
export interface Hop { node: string; acl: AclDecision | null; route: HopRoute | null }
export type TraceStatus = "DELIVERED" | "DROPPED_ACL" | "LOOP" | "BLACKHOLE" | "INVALID_NEXT_HOP" | string;
export interface Trace {
  key: string; source: string; destination: string; protocol: string; port: number | null;
  status: TraceStatus; path: string[]; hops: Hop[]; stop_node: string | null; detail: string;
}

// ----- /api/verify
export interface PolicyResult { policy_id: string; action: Action; satisfied: boolean; violation: string | null; reason: string }
export interface StaticIssue { kind: string; node: string; prefix?: string | null; next_hop?: string | null; message: string }
export interface VerifyResponse {
  network: string; traces: Trace[]; policy_results: PolicyResult[]; static_issues: StaticIssue[];
  summary: {
    flows_checked: number; delivered: number; not_delivered: number; policies: number;
    policies_satisfied: number; policies_violated: number; static_issues: number;
  };
  topology: Topology;
}

// ----- /api/simulate
export type Severity = "critical" | "high" | "medium" | "info";
export type Decision = "SAFE" | "REVIEW" | "NOT_RECOMMENDED";
export interface Step { kind: "change" | "routing" | "path" | "enforcement" | "policy" | "impact"; label: string; detail: string; key: string }
export interface Finding {
  id: string; type: string; severity: Severity; title: string; source: string; destination: string;
  flow_key: string | null; policies: string[]; expected: string | null; observed: string | null;
  before_path: string[]; after_path: string[]; before_status: string; after_status: string;
  root_change: number | null; propagation: Step[]; technical: string; human: string;
  extra: { violations?: PolicyResult[]; criticality?: number; before_detail?: string; after_detail?: string;
    sources?: string[]; services?: string[]; from_internet?: boolean };
}
export type DeltaOutcome = "path_changed" | "newly_reachable" | "newly_unreachable" | "status_changed";
export interface FlowDelta {
  key: string; source: string; destination: string; protocol: string; port: number | null;
  flow_ids: string[]; policy_ids: string[]; expected: string | null;
  before: Trace; after: Trace; outcome: DeltaOutcome; added_devices: string[]; removed_devices: string[]; finding: string | null;
}
export interface Risk {
  score: number; level: "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  breakdown: Record<string, number>; inputs: Record<string, number>; weights: RiskWeights;
}
export interface RiskWeights { broken_flows: number; security_violations: number; new_exposures: number; routing_failures: number; criticality: number }
export type PolicyStatus = "ok" | "new_violation" | "resolved" | "preexisting_violation" | "added" | "removed";
export interface PolicyView {
  id: string; description: string; status: PolicyStatus; before: PolicyResult | null; after: PolicyResult | null;
}
export interface ChangeSummaryRow {
  index: number; operation: string; description: string; inverse: Change;
  effect: { index: number; kind: string; nodes?: string[]; prefix?: string; policy_id?: string; label?: string };
}
export interface ImpactGraph { nodes: { id: string; kind: Step["kind"]; label: string }[]; edges: { source: string; target: string }[] }
export interface ChangeReport {
  network: string; changes: ChangeSummaryRow[];
  verdict: { decision: Decision; headline: string };
  summary: {
    declared_flows_checked: number; affected_flows: number; unchanged_flows: number; broken_flows: number;
    routing_failures: number; security_violations: number; new_exposures: number; path_changes: number;
    probes_checked: number; probes_newly_reachable: number; probes_newly_unreachable: number;
    resolved_policies: string[]; preexisting_violations: string[];
  };
  risk: Risk; findings: Finding[]; flow_deltas: FlowDelta[]; policies: PolicyView[]; config_warnings: string[];
  rollback: null | {
    revert: { index: number; description: string; revert_with: Change }[];
    if_reverted: { decision: Decision; remaining_problems: number }; note: string;
  };
  impact_graph: ImpactGraph; topology: Topology;
  meta: { classes: number; declared: number; probes_enabled: boolean; duration_ms: number; resimulated?: number };
  report_markdown: string;
}

// ----- /api/interpret
export interface InterpretResponse {
  parser: string; kind: string; changes: Change[]; policies: Policy[];
  unparsed: { text: string; reason: string | null; suggestion?: string }[]; needs_review: boolean; note: string;
  /** Each accepted sentence and its draft, in the order written (newer APIs only). */
  matched?: { text: string; kind: "change" | "policy"; index: number; understood_as: string }[];
}

// ----- /api/eval/run (and summary.json written by `python -m netguardx eval --out`)
export type ArmName = "none" | "lint" | "reachability" | "full" | "incremental";
export interface ArmSummary {
  commands: number; executed: number; rejected: number; held: number; invalid: number;
  unsafe_executed: number; safe_rejected: number; unhealthy_steps: number; mismatches: number;
  resim_share: number | null; check_ms_mean: number; check_ms_p50: number; check_ms_p95: number;
  // Added with several seeds and per-step timing; absent in older summary.json files.
  check_ms_p50_ci95?: number | null; check_ms_p95_ci95?: number | null; check_ms_mean_ci95?: number | null;
  commands_per_s?: number | null; phases_ms_mean?: Record<string, number> | null; commit_ms_mean?: number | null;
}
export interface EvalRun {
  sites: number; nodes: number; links: number; routes: number; flows: number; policies: number;
  arms: Partial<Record<ArmName, ArmSummary>>;
  per_seed?: { seed: number; arms: Partial<Record<ArmName, ArmSummary>> }[];
  memory?: { cache_mb: number; peak_mb: number };
}
export interface EvalStep {
  sites: number; seed?: number; arm: ArmName; step: number; intent: string; operation: string; oracle: string;
  outcome: string; check_ms: number; resim_share: number | null; healthy: boolean;
}
export type GatedArm = "full" | "incremental";
export interface ScalingArm {
  measured: { devices: number; ms_p50: number }[];
  fit: { a: number; exponent: number; r2: number | null; points: number };
  projected: { devices: number; ms_p50: number }[];
}
export interface EvalResult {
  config: { sites: number[]; commands: number; seed: number; seeds?: number[]; fault_rate: number; probes: boolean; arms: ArmName[]; memory?: boolean };
  runs: EvalRun[]; steps?: EvalStep[]; scaling?: Partial<Record<GatedArm, ScalingArm>> | null;
}
export interface EvalRequest { sites: number[]; commands: number; seed: number; seeds?: number[]; fault_rate: number; probes: boolean }
/** A background evaluation (POST /api/eval/jobs, GET /api/eval/jobs/{id}). */
export interface EvalJob {
  id: string; status: "running" | "done" | "failed" | "cancelled"; done: number; total: number; elapsed_s: number;
  error?: string; result?: EvalResult;
}
