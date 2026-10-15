import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ArmName, ArmSummary, EvalRun, EvalStep } from "../api/types";
import { ARM_COLOR, ARM_LABEL, ARM_ORDER, armSeries, sizeRows } from "../lib/evalData";

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
const fmt = (v: number, unit: string) => (unit === "ms" ? (v < 10 ? v.toFixed(2) : v.toFixed(1)) : unit === "%" ? (v * 100).toFixed(1) : unit === "x" ? v.toFixed(1) : String(v)) + (unit === "%" ? "%" : unit === "x" ? "×" : unit === "ms" ? "\u00a0ms" : "");

function Frame({ children, height = 280, label }: { children: React.ReactElement; height?: number; label: string }) {
  return <div role="img" aria-label={label} style={{ height }}><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>;
}
const yAxis = (unit: string, extra: object = {}) => <YAxis tick={TICK} axisLine={false} tickLine={false} width={48} tickFormatter={(v: number) => (unit === "%" ? `${Math.round(v * 100)}%` : unit === "x" ? `${v}×` : String(v))} {...extra} />;
const xAxis = <XAxis dataKey="label" tick={TICK} axisLine={AXIS} tickLine={false} interval={0} />;

/** Median (p50) check time, full vs incremental. The tooltip adds p95. */
export function LatencyChart({ runs }: { runs: EvalRun[] }) {
  const data = sizeRows(runs);
  return (<>
    <Key items={[{ name: ARM_LABEL.full, color: ARM_COLOR.full }, { name: ARM_LABEL.incremental, color: ARM_COLOR.incremental }]} />
    <Frame label="Median check time in milliseconds, full versus incremental verification, by network size">
      <BarChart data={data} margin={{ top: 18, right: 8, left: 0, bottom: 0 }} barGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />{xAxis}{yAxis("ms", { unit: "" })}
        <Tooltip cursor={{ fill: "rgb(var(--raised) / 0.5)" }} content={({ active, payload, label }) => {
          const d = (payload?.[0] as P | undefined)?.payload as unknown as ReturnType<typeof sizeRows>[number] | undefined;
          return <Tip active={active} label={label} rows={[
            { name: `${ARM_LABEL.full} median (p95 ${d?.fullP95 != null ? fmt(d.fullP95, "ms") : "n/a"})`, value: d?.fullP50 != null ? fmt(d.fullP50, "ms") : "n/a", color: ARM_COLOR.full },
            { name: `${ARM_LABEL.incremental} median (p95 ${d?.incP95 != null ? fmt(d.incP95, "ms") : "n/a"})`, value: d?.incP50 != null ? fmt(d.incP50, "ms") : "n/a", color: ARM_COLOR.incremental }]} />;
        }} />
        <Bar dataKey="fullP50" name={ARM_LABEL.full} fill={ARM_COLOR.full} radius={[4, 4, 0, 0]} maxBarSize={28}><LabelList dataKey="fullP50" position="top" fill="rgb(221 229 238)" fontSize={11} formatter={(v: number) => fmt(v, "ms")} /></Bar>
        <Bar dataKey="incP50" name={ARM_LABEL.incremental} fill={ARM_COLOR.incremental} radius={[4, 4, 0, 0]} maxBarSize={28}><LabelList dataKey="incP50" position="top" fill="rgb(221 229 238)" fontSize={11} formatter={(v: number) => fmt(v, "ms")} /></Bar>
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
export function StepChart({ steps, sites }: { steps: EvalStep[]; sites: number }) {
  const rows = new Map<number, Record<string, number>>();
  for (const s of steps) {
    if (s.sites !== sites || (s.arm !== "full" && s.arm !== "incremental") || !s.check_ms) continue;
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
