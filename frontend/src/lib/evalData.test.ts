import { describe, expect, it } from "vitest";
import type { ArmSummary, EvalRun } from "../api/types";
import { readFileSync } from "node:fs";
import { armSeries, parseEvalResult, phaseRows, scalingSeries, sizeRows } from "./evalData";

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

describe("confidence intervals", () => {
  it("are carried into size rows when present and absent otherwise", () => {
    const withCi = { ...run, arms: { full: arm(20, 30, 1, { check_ms_p50_ci95: 2 }), incremental: arm(4, 10, 0.2, { check_ms_p50_ci95: 0.5 }) } };
    expect(sizeRows([withCi])[0]).toMatchObject({ fullCi: 2, incCi: 0.5 });
    expect(sizeRows([run])[0].fullCi).toBeUndefined();
  });
});

describe("phaseRows", () => {
  it("lists every step of the verifier, zero-filling missing ones, and skips runs without timing", () => {
    const timed = { ...run, arms: { ...run.arms, incremental: arm(4, 10, 0.2, { phases_ms_mean: { simulate: 3, assess: 1 } }) } };
    const rows = phaseRows([timed, run], "incremental");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({ label: "4 sites · 26 nodes", sync: 0, apply: 0, state: 0, select: 0, simulate: 3, assess: 1 });
  });
});

describe("scalingSeries", () => {
  it("puts measured points and the fitted curve on one device axis, including projections", () => {
    const fit = { a: 2, exponent: 1, r2: 1, points: 2 };
    const rows = scalingSeries({ incremental: { measured: [{ devices: 10, ms_p50: 20 }, { devices: 20, ms_p50: 40 }], fit, projected: [{ devices: 150, ms_p50: 300 }] } });
    expect(rows.map((r) => r.devices)).toEqual([10, 20, 150]);
    expect(rows[0]).toEqual({ devices: 10, incrementalMeasured: 20, incrementalFit: 20 });
    expect(rows[2]).toEqual({ devices: 150, incrementalFit: 300 });
    expect(scalingSeries(null)).toEqual([]);
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
  it("still accepts the older sample written before seeds and timing existed", () => {
    const old = parseEvalResult(JSON.parse(readFileSync(new URL("../../../samples/eval-summary.json", import.meta.url), "utf-8")));
    expect(old.runs.length).toBeGreaterThan(0);
    expect(old.scaling).toBeUndefined();
    expect(phaseRows(old.runs, "incremental")).toEqual([]);
  });
});
