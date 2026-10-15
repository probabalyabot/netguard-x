import { describe, expect, it } from "vitest";
import type { ArmSummary, EvalRun } from "../api/types";
import { armSeries, parseEvalResult, sizeRows } from "./evalData";

const arm = (p50: number, p95: number, resim: number | null, extra: Partial<ArmSummary> = {}): ArmSummary => ({
  commands: 10, executed: 8, rejected: 2, held: 0, invalid: 0, unsafe_executed: 0, safe_rejected: 0, unhealthy_steps: 0, mismatches: 0,
  resim_share: resim, check_ms_mean: p50, check_ms_p50: p50, check_ms_p95: p95, ...extra,
});
const run: EvalRun = { sites: 4, nodes: 26, links: 1, routes: 1, flows: 1, policies: 1, arms: { full: arm(20, 30, 1), incremental: arm(4, 10, 0.2) } };

describe("sizeRows", () => {
  it("derives speed-up as full p50 over incremental p50", () => {
    const [r] = sizeRows([run]);
    expect(r.speedup).toBe(5);
    expect(r.resim).toBe(0.2);
    expect(r.label).toBe("4 sites · 26 nodes");
  });
  it("leaves speed-up undefined when an arm is missing", () => {
    expect(sizeRows([{ ...run, arms: { full: arm(20, 30, 1) } }])[0].speedup).toBeUndefined();
  });
});

describe("armSeries", () => {
  it("only includes arms that were run", () => {
    expect(armSeries([run], "check_ms_p50")[0]).toEqual({ label: "4 sites · 26 nodes", full: 20, incremental: 4 });
  });
});

describe("parseEvalResult", () => {
  it("rejects unrelated JSON", () => {
    expect(() => parseEvalResult({ nodes: [] })).toThrow(/not an evaluation result/);
    expect(() => parseEvalResult({ config: {}, runs: [{}] })).toThrow(/missing/);
  });
  it("accepts a summary.json shape", () => {
    expect(parseEvalResult({ config: { sites: [4] }, runs: [run] }).runs).toHaveLength(1);
  });
});
