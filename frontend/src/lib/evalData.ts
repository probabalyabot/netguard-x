import type { ArmName, ArmSummary, EvalResult, EvalRun, GatedArm } from "../api/types";

export const ARM_ORDER: ArmName[] = ["none", "lint", "reachability", "full", "incremental"];
export const ARM_LABEL: Record<ArmName, string> = { none: "No check", lint: "Lint", reachability: "Reachability", full: "Full verification", incremental: "Incremental" };
/** What each arm rejects, as documented in the repository README and eval/run.py. */
export const ARM_RULE: Record<ArmName, string> = {
  none: "Never rejects a command.",
  lint: "Rejects a command that introduces a route whose next hop cannot be used.",
  reachability: "Rejects a command if a flow that was delivered stops being delivered.",
  full: "Gatekeeper with full verification; rejects when the verdict is NOT_RECOMMENDED.",
  incremental: "Gatekeeper with incremental verification; rejects when the verdict is NOT_RECOMMENDED.",
};
/** Entity colours (dark surface). Order and hexes validated with the dataviz palette script. */
export const ARM_COLOR: Record<ArmName, string> = {
  none: "#d55181", lint: "#c98500", reachability: "#199e70", full: "#d95926", incremental: "#3987e5",
};

/** Devices in a generated campus network of ``sites`` sites (mirrors netguardx/eval/topologies.py devices_in). */
export const devicesIn = (sites: number, usersPerSite = 1) => sites * (5 + usersPerSite) + Math.max(1, Math.floor(sites / 4)) + 1;

export const runLabel = (r: EvalRun) => `${r.sites} site${r.sites === 1 ? "" : "s"} · ${r.nodes} nodes`;

export interface SizeRow { label: string; sites: number; nodes: number; fullP50?: number; fullP95?: number; incP50?: number; incP95?: number; fullCi?: number; incCi?: number; speedup?: number; resim?: number; mismatches?: number }

/** Derived values are computed here, never stored: speed-up = full p50 / incremental p50. */
export function sizeRows(runs: EvalRun[]): SizeRow[] {
  return runs.map((r) => {
    const f = r.arms.full, i = r.arms.incremental;
    return {
      label: runLabel(r), sites: r.sites, nodes: r.nodes,
      fullP50: f?.check_ms_p50, fullP95: f?.check_ms_p95, incP50: i?.check_ms_p50, incP95: i?.check_ms_p95,
      fullCi: f?.check_ms_p50_ci95 ?? undefined, incCi: i?.check_ms_p50_ci95 ?? undefined,
      speedup: f && i && i.check_ms_p50 > 0 ? f.check_ms_p50 / i.check_ms_p50 : undefined,
      resim: i?.resim_share ?? undefined, mismatches: i?.mismatches,
    };
  });
}

/** Steps of each verifier in pipeline order, as recorded in meta.phases_ms by the engine. */
export const PHASES: Record<GatedArm, { key: string; label: string }[]> = {
  incremental: [
    { key: "sync", label: "Update cache" }, { key: "apply", label: "Build what-if network" },
    { key: "state", label: "Rebuild touched tables" }, { key: "select", label: "Select affected traffic" },
    { key: "simulate", label: "Simulate" }, { key: "assess", label: "Compare and decide" },
  ],
  full: [
    { key: "apply", label: "Build what-if network" }, { key: "state", label: "Build forwarding tables" },
    { key: "classes", label: "Choose traffic" }, { key: "simulate", label: "Simulate" },
    { key: "assess", label: "Compare and decide" },
  ],
};
export const PHASE_COLOR = ["#3987e5", "#199e70", "#c98500", "#8f6ad4", "#d95926", "#7d8b99"];

/** Mean milliseconds per step for one verifier, one row per network size that recorded them. */
export function phaseRows(runs: EvalRun[], arm: GatedArm): Record<string, string | number>[] {
  return runs.flatMap((r) => {
    const p = r.arms[arm]?.phases_ms_mean;
    if (!p) return [];
    const row: Record<string, string | number> = { label: runLabel(r) };
    for (const { key } of PHASES[arm]) row[key] = p[key] ?? 0;
    return [row];
  });
}

/** Points for the scaling chart: measured medians, and the fitted curve across measured and projected sizes. */
export function scalingSeries(scaling: EvalResult["scaling"]): Record<string, number>[] {
  if (!scaling) return [];
  const byDevices = new Map<number, Record<string, number>>();
  const at = (d: number) => { const row = byDevices.get(d) ?? { devices: d }; byDevices.set(d, row); return row; };
  for (const arm of ["full", "incremental"] as GatedArm[]) {
    const s = scaling[arm];
    if (!s) continue;
    for (const m of s.measured) at(m.devices)[`${arm}Measured`] = m.ms_p50;
    const xs = [...s.measured.map((m) => m.devices), ...s.projected.map((p) => p.devices)];
    for (const d of xs) at(d)[`${arm}Fit`] = s.fit.a * d ** s.fit.exponent;
  }
  return [...byDevices.values()].sort((a, b) => a.devices - b.devices);
}

export const METRICS: { key: keyof ArmSummary; label: string; unit: string }[] = [
  { key: "unsafe_executed", label: "Unsafe commands executed", unit: "commands" },
  { key: "safe_rejected", label: "Safe commands rejected", unit: "commands" },
  { key: "unhealthy_steps", label: "Steps with a violated policy or lost flow", unit: "steps" },
  { key: "check_ms_p50", label: "Median check time", unit: "ms" },
];

export function armSeries(runs: EvalRun[], metric: keyof ArmSummary): Record<string, string | number>[] {
  return runs.map((r) => {
    const row: Record<string, string | number> = { label: runLabel(r) };
    for (const a of ARM_ORDER) { const v = r.arms[a]?.[metric]; if (typeof v === "number") row[a] = v; }
    return row;
  });
}

/** Accepts the result of POST /api/eval/run or a summary.json written by `netguardx eval --out`. */
export function parseEvalResult(value: unknown): EvalResult {
  const v = value as Partial<EvalResult> | null;
  if (!v || typeof v !== "object" || !v.config || !Array.isArray(v.runs) || v.runs.length === 0)
    throw new Error("This is not an evaluation result. Expected an object with \"config\" and a non-empty \"runs\" list, as written by `python -m netguardx eval --out`.");
  for (const r of v.runs) if (!r || typeof r.sites !== "number" || !r.arms || typeof r.arms !== "object") throw new Error("A run in this file is missing \"sites\" or \"arms\".");
  return v as EvalResult;
}
