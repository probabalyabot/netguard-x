import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ErrorBar, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ArmName, ArmSummary, EvalResult, EvalRun, EvalStep, GatedArm } from "../api/types";
import { ARM_COLOR, ARM_LABEL, ARM_ORDER, PHASES, PHASE_COLOR, armSeries, phaseRows, scalingSeries, sizeRows } from "../lib/evalData";
import { count } from "../lib/format";

const AXIS = { stroke: "rgb(var(--line-strong))" };
const TICK = { fill: "rgb(135 149 168)", fontSize: 12 };
const GRID = "rgb(var(--line) / 0.7)";

export function Key({ items }: { items: { name: string; color: string }[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map((i) => <li key={i.name} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ background: i.color }} aria-hidden />{i.name}</li>)}
    </ul>
  );
}

interface TipRow { name: string; value: string; color: string }
function Tip({ active, label, rows, note }: { active?: boolean; label?: ReactNode; rows: TipRow[]; note?: string }) {
  if (!active || rows.length === 0) return null;
  return (
    <div className="rounded-md border border-line-strong bg-panel px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 text-muted">{label}</p>
      {rows.map((r) => (
        <p key={r.name} className="flex items-center gap-2"><span className="inline-block h-0.5 w-3" style={{ background: r.color }} aria-hidden /><span className="font-medium tabular-nums text-fg">{r.value}</span><span className="text-muted">{r.name}</span></p>
      ))}
      {note && <p className="mt-1 text-faint">{note}</p>}
    </div>
  );
}

type P = { name?: string; dataKey?: string; value?: number; color?: string; payload?: Record<string, number | string> };
const fmt = (v: number, unit: string) => (unit === "ms" ? (v < 10 ? v.toFixed(2) : v.toFixed(1)) : unit === "%" ? (v * 100).toFixed(1) : unit === "x" ? v.toFixed(1) : count(v)) + (unit === "%" ? "%" : unit === "x" ? "×" : unit === "ms" ? "\u00a0ms" : "");

function Frame({ children, height = 280, label }: { children: React.ReactElement; height?: number; label: string }) {
  return <div role="img" aria-label={label} style={{ height }}><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>;
}
const yAxis = (unit: string, extra: object = {}) => <YAxis tick={TICK} axisLine={false} tickLine={false} width={48} tickFormatter={(v: number) => (unit === "%" ? `${Math.round(v * 100)}%` : unit === "x" ? `${v}×` : String(v))} {...extra} />;
const xAxis = <XAxis dataKey="label" tick={TICK} axisLine={AXIS} tickLine={false} interval={0} />;

/** Median (p50) check time, full vs incremental. The tooltip adds p95. */
export function LatencyChart({ runs }: { runs: EvalRun[] }) {
  const data = sizeRows(runs);
  const withCi = data.some((d) => d.fullCi != null || d.incCi != null);
  return (<>
    <Key items={[{ name: ARM_LABEL.full, color: ARM_COLOR.full }, { name: ARM_LABEL.incremental, color: ARM_COLOR.incremental }]} />
    <Frame label="Median check time in milliseconds, full versus incremental verification, by network size">
      <BarChart data={data} margin={{ top: 18, right: 8, left: 0, bottom: 0 }} barGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />{xAxis}{yAxis("ms", { unit: "", domain: [0, "auto"], allowDataOverflow: true })}
        <Tooltip cursor={{ fill: "rgb(var(--raised) / 0.5)" }} content={({ active, payload, label }) => {
          const d = (payload?.[0] as P | undefined)?.payload as unknown as ReturnType<typeof sizeRows>[number] | undefined;
          const ci = (v?: number) => (v != null ? ` ± ${fmt(v, "ms")}` : "");
          return <Tip active={active} label={label} note={withCi ? "± is the half-width of a 95% confidence interval over seeds" : undefined} rows={[
            { name: `${ARM_LABEL.full} median (p95 ${d?.fullP95 != null ? fmt(d.fullP95, "ms") : "n/a"})`, value: d?.fullP50 != null ? fmt(d.fullP50, "ms") + ci(d.fullCi) : "n/a", color: ARM_COLOR.full },
            { name: `${ARM_LABEL.incremental} median (p95 ${d?.incP95 != null ? fmt(d.incP95, "ms") : "n/a"})`, value: d?.incP50 != null ? fmt(d.incP50, "ms") + ci(d.incCi) : "n/a", color: ARM_COLOR.incremental }]} />;
        }} />
        <Bar dataKey="fullP50" name={ARM_LABEL.full} fill={ARM_COLOR.full} radius={[4, 4, 0, 0]} maxBarSize={28}>
          {withCi && <ErrorBar dataKey="fullCi" width={6} strokeWidth={1.5} stroke="rgb(221 229 238)" />}
          {!withCi && <LabelList dataKey="fullP50" position="top" fill="rgb(221 229 238)" fontSize={11} formatter={(v: number) => fmt(v, "ms")} />}
        </Bar>
        <Bar dataKey="incP50" name={ARM_LABEL.incremental} fill={ARM_COLOR.incremental} radius={[4, 4, 0, 0]} maxBarSize={28}>
          {withCi && <ErrorBar dataKey="incCi" width={6} strokeWidth={1.5} stroke="rgb(221 229 238)" />}
          {!withCi && <LabelList dataKey="incP50" position="top" fill="rgb(221 229 238)" fontSize={11} formatter={(v: number) => fmt(v, "ms")} />}
        </Bar>
      </BarChart>
    </Frame>
  </>);
}

function Single({ runs, field, unit, name, color, label }: { runs: EvalRun[]; field: "speedup" | "resim"; unit: "x" | "%"; name: string; color: string; label: string }) {
  const data = sizeRows(runs);
  return (
    <Frame label={label} height={240}>
      <BarChart data={data} margin={{ top: 18, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} />{xAxis}{yAxis(unit)}
        <Tooltip cursor={{ fill: "rgb(var(--raised) / 0.5)" }} content={({ active, payload, label: l }) => <Tip active={active} label={l} rows={payload?.[0]?.value != null ? [{ name, value: fmt(payload[0].value as number, unit), color }] : []} />} />
        <Bar dataKey={field} fill={color} radius={[4, 4, 0, 0]} maxBarSize={36}><LabelList dataKey={field} position="top" fill="rgb(221 229 238)" fontSize={11} formatter={(v: number) => fmt(v, unit)} /></Bar>
      </BarChart>
    </Frame>
  );
}
export const SpeedupChart = ({ runs }: { runs: EvalRun[] }) => <Single runs={runs} field="speedup" unit="x" name="Speed-up (full p50 ÷ incremental p50)" color={ARM_COLOR.incremental} label="Speed-up of incremental over full verification by network size" />;
export const ResimChart = ({ runs }: { runs: EvalRun[] }) => <Single runs={runs} field="resim" unit="%" name="Traffic classes re-simulated (mean per command)" color={ARM_COLOR.incremental} label="Share of traffic classes re-simulated by the incremental verifier by network size" />;

/** One metric across every arm that was run, grouped by network size. */
export function ArmChart({ runs, metric, unit }: { runs: EvalRun[]; metric: keyof ArmSummary; unit: string }) {
  const data = armSeries(runs, metric);
  const arms = ARM_ORDER.filter((a) => runs.some((r) => r.arms[a]));
  return (<>
    <Key items={arms.map((a) => ({ name: ARM_LABEL[a], color: ARM_COLOR[a] }))} />
    <Frame label={`${String(metric)} by arm and network size`}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />{xAxis}{yAxis(unit === "ms" ? "ms" : "n", { allowDecimals: false })}
        <Tooltip cursor={{ fill: "rgb(var(--raised) / 0.5)" }} content={({ active, payload, label }) => (
          <Tip active={active} label={label} rows={(payload as P[] | undefined ?? []).map((p) => ({ name: ARM_LABEL[p.dataKey as ArmName], value: fmt(Number(p.value), unit === "ms" ? "ms" : ""), color: ARM_COLOR[p.dataKey as ArmName] }))} />)} />
        {arms.map((a) => <Bar key={a} dataKey={a} name={ARM_LABEL[a]} fill={ARM_COLOR[a]} radius={[4, 4, 0, 0]} maxBarSize={18} />)}
      </BarChart>
    </Frame>
  </>);
}

/** Check time of every command, in order, for the two gatekeeper arms (needs the per-step rows). */
export function StepChart({ steps, sites, seed }: { steps: EvalStep[]; sites: number; seed?: number }) {
  const rows = new Map<number, Record<string, number>>();
  for (const s of steps) {
    if (s.sites !== sites || (s.arm !== "full" && s.arm !== "incremental") || !s.check_ms) continue;
    if (seed != null && s.seed != null && s.seed !== seed) continue; // one seed's commands at a time
    const r = rows.get(s.step) ?? { step: s.step }; r[s.arm] = s.check_ms; rows.set(s.step, r);
  }
  const data = [...rows.values()].sort((a, b) => a.step - b.step);
  return (<>
    <Key items={[{ name: ARM_LABEL.full, color: ARM_COLOR.full }, { name: ARM_LABEL.incremental, color: ARM_COLOR.incremental }]} />
    <Frame label="Check time per command, full versus incremental verification">
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="step" tick={TICK} axisLine={AXIS} tickLine={false} />{yAxis("ms")}
        <Tooltip cursor={{ stroke: "rgb(var(--line-strong))" }} content={({ active, payload, label }) => (
          <Tip active={active} label={`Command ${label}`} rows={(payload as P[] | undefined ?? []).map((p) => ({ name: ARM_LABEL[p.dataKey as ArmName], value: fmt(Number(p.value), "ms"), color: ARM_COLOR[p.dataKey as ArmName] }))} />)} />
        <Line type="monotone" dataKey="full" stroke={ARM_COLOR.full} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "rgb(var(--panel))", strokeWidth: 2 }} connectNulls />
        <Line type="monotone" dataKey="incremental" stroke={ARM_COLOR.incremental} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "rgb(var(--panel))", strokeWidth: 2 }} connectNulls />
      </LineChart>
    </Frame>
  </>);
}

/** Where one verifier's time goes: mean milliseconds per step, stacked, by network size. */
export function PhaseChart({ runs, arm }: { runs: EvalRun[]; arm: GatedArm }) {
  const data = phaseRows(runs, arm);
  const phases = PHASES[arm];
  return (<>
    <Key items={phases.map((p, i) => ({ name: p.label, color: PHASE_COLOR[i] }))} />
    <Frame label={`Mean time per command by step, ${ARM_LABEL[arm].toLowerCase()}, by network size`}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} />{xAxis}{yAxis("ms")}
        <Tooltip cursor={{ fill: "rgb(var(--raised) / 0.5)" }} content={({ active, payload, label }) => {
          const rows = (payload as P[] | undefined ?? []).slice().reverse().map((p) => {
            const i = phases.findIndex((x) => x.key === p.dataKey);
            return { name: phases[i]?.label ?? String(p.dataKey), value: fmt(Number(p.value), "ms"), color: PHASE_COLOR[i] };
          });
          const total = (payload as P[] | undefined ?? []).reduce((s, p) => s + Number(p.value ?? 0), 0);
          return <Tip active={active} label={label} rows={rows} note={`Total ${fmt(total, "ms")} per command (mean)`} />;
        }} />
        {phases.map((p, i) => <Bar key={p.key} dataKey={p.key} stackId="steps" fill={PHASE_COLOR[i]} maxBarSize={40} />)}
      </BarChart>
    </Frame>
  </>);
}

/** Median check time against devices on log-log axes: measured points, and the fitted curve
 *  continued (dashed) to the projected sizes. */
export function ScalingChart({ scaling }: { scaling: EvalResult["scaling"] }) {
  const data = scalingSeries(scaling);
  const arms = (["full", "incremental"] as GatedArm[]).filter((a) => scaling?.[a]);
  const lastMeasured = Math.max(...arms.flatMap((a) => scaling![a]!.measured.map((m) => m.devices)));
  return (<>
    <Key items={arms.flatMap((a) => [{ name: `${ARM_LABEL[a]}, measured`, color: ARM_COLOR[a] }, { name: `${ARM_LABEL[a]}, fit and projection (dashed)`, color: ARM_COLOR[a] }])} />
    <Frame label="Median check time against number of devices, measured and projected, log scales" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis dataKey="devices" type="number" scale="log" domain={["dataMin", "dataMax"]} ticks={data.map((d) => d.devices)} tick={TICK} axisLine={AXIS} tickLine={false} />
        {yAxis("ms", { scale: "log", domain: ["auto", "auto"], allowDataOverflow: true })}
        <Tooltip cursor={{ stroke: "rgb(var(--line-strong))" }} content={({ active, payload, label }) => (
          <Tip active={active} label={`${label} devices${Number(label) > lastMeasured ? " (projected)" : ""}`}
            rows={(payload as P[] | undefined ?? []).map((p) => {
              const a = String(p.dataKey).replace(/Measured|Fit/, "") as GatedArm;
              const kind = String(p.dataKey).endsWith("Fit") ? (Number(label) > lastMeasured ? "projected" : "fit") : "measured";
              return { name: `${ARM_LABEL[a]}, ${kind}`, value: fmt(Number(p.value), "ms"), color: ARM_COLOR[a] };
            })} />)} />
        {arms.map((a) => <Line key={`${a}Fit`} dataKey={`${a}Fit`} stroke={ARM_COLOR[a]} strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />)}
        {arms.map((a) => <Line key={`${a}Measured`} dataKey={`${a}Measured`} stroke={ARM_COLOR[a]} strokeWidth={2} dot={{ r: 4, fill: ARM_COLOR[a], strokeWidth: 0 }} connectNulls isAnimationActive={false} />)}
      </LineChart>
    </Frame>
  </>);
}
