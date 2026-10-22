import { Play, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EvalResult, GatedArm } from "../api/types";
import { ArmChart, LatencyChart, PhaseChart, ResimChart, ScalingChart, SpeedupChart, StepChart } from "../components/EvalCharts";
import { Chip, Empty, Notice, PageHeader, Segmented, Spinner } from "../components/ui";
import { config } from "../config";
import { ARM_LABEL, ARM_ORDER, ARM_RULE, METRICS, parseEvalResult, phaseRows, runLabel } from "../lib/evalData";
import { count, errMsg, ms, pct } from "../lib/format";

interface Loaded { result: EvalResult; source: string; at: string; seconds?: number }
let cache: Loaded | null = null; // survives navigation within the session; never persisted

const SIZE_CHOICES = [1, 2, 4, 8];

function Panel({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return <section className="panel"><div className="panel-h"><h2 className="panel-title">{title}</h2>{sub && <span className="text-xs text-muted">{sub}</span>}</div><div className="p-4">{children}</div></section>;
}

export function Evaluation() {
  const lim = config.evalLimits;
  const [sizes, setSizes] = useState<number[]>([2, 4]);
  const [commands, setCommands] = useState(30);
  const [seed, setSeed] = useState(0);
  const [fault, setFault] = useState(0.3);
  const [probes, setProbes] = useState(true);
  const [loaded, setLoaded] = useState<Loaded | null>(cache);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState(METRICS[0].key);
  const [stepSites, setStepSites] = useState<number | null>(null);
  const [phaseArm, setPhaseArm] = useState<GatedArm>("incremental");
  const abort = useRef<AbortController | null>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!running) return;
    const t0 = Date.now(); const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(id);
  }, [running]);

  const toggle = (s: number) => setSizes((cur) => cur.includes(s) ? cur.filter((x) => x !== s) : cur.length >= lim.maxSizes ? cur : [...cur, s].sort((a, b) => a - b));
  const commit = (l: Loaded) => { cache = l; setLoaded(l); setStepSites(null); };

  const run = async () => {
    setError(null); setRunning(true); setElapsed(0);
    abort.current = new AbortController();
    const t0 = Date.now();
    try {
      const result = await api.evalRun({ sites: sizes, commands, seed, fault_rate: fault, probes }, abort.current.signal);
      commit({ result, source: "Run just now on the API server", at: new Date().toISOString(), seconds: (Date.now() - t0) / 1000 });
    } catch (e) { if ((e as Error).name !== "AbortError") setError(errMsg(e)); }
    finally { setRunning(false); }
  };

  const importFile = async (f: File) => {
    setError(null);
    try { commit({ result: parseEvalResult(JSON.parse(await f.text())), source: `Imported from ${f.name}`, at: new Date().toISOString() }); }
    catch (e) { setError(`Could not read ${f.name}: ${errMsg(e)}`); }
  };

  const r = loaded?.result;
  const cfg = r?.config;
  const seeds = cfg?.seeds ?? (cfg ? [cfg.seed] : []);
  const gated = r?.runs.some((x) => x.arms.full && x.arms.incremental);
  const m = METRICS.find((x) => x.key === metric)!;
  const stepSize = stepSites ?? r?.runs[r.runs.length - 1]?.sites ?? 0;

  return (
    <>
      <PageHeader title="Research evaluation" sub="Replays one seeded stream of synthetic commands through five checking strategies and measures what each lets through and what each costs. Every number on this page comes from a run of the repository's own harness." />

      <section className="panel mb-5">
        <div className="panel-h"><h2 className="panel-title">Run the harness</h2><span className="text-xs text-muted">on generated campus networks</span></div>
        <div className="grid gap-4 p-4 md:grid-cols-[auto_1fr_auto] md:items-end">
          <div>
            <span className="label">Network sizes (sites), up to {lim.maxSizes}</span>
            <div className="flex gap-1.5" role="group" aria-label="Network sizes">
              {SIZE_CHOICES.map((s) => <button key={s} aria-pressed={sizes.includes(s)} onClick={() => toggle(s)} className={`btn !px-3 ${sizes.includes(s) ? "!border-net !bg-net/15 !text-net" : ""}`}>{s}</button>)}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div><label className="label" htmlFor="ev-n">Commands per network</label><input id="ev-n" className="field" type="number" min={lim.minCommands} max={lim.maxCommands} value={commands} onChange={(e) => setCommands(Math.min(lim.maxCommands, Math.max(lim.minCommands, Number(e.target.value) || lim.minCommands)))} /></div>
            <div><label className="label" htmlFor="ev-s">Seed</label><input id="ev-s" className="field" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} /></div>
            <div><label className="label" htmlFor="ev-f">Fault rate (0 to 1)</label><input id="ev-f" className="field" type="number" min={0} max={1} step={0.05} value={fault} onChange={(e) => setFault(Math.min(1, Math.max(0, Number(e.target.value) || 0)))} /></div>
            <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={probes} onChange={(e) => setProbes(e.target.checked)} className="accent-[rgb(var(--net))]" />Exposure probes</label>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn btn-primary" onClick={run} disabled={running || sizes.length === 0}><Play size={15} aria-hidden />{running ? "Running…" : "Run evaluation"}</button>
            <input ref={file} type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
            <button className="btn" onClick={() => file.current?.click()} disabled={running}><Upload size={15} aria-hidden />Import summary.json</button>
          </div>
        </div>
        <div className="border-t border-line px-4 py-2.5 text-xs text-muted">
          {running ? <span className="flex items-center gap-3"><Spinner label={`Running on the server… ${elapsed}s`} /><button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => abort.current?.abort()}>Cancel</button></span>
            : <>The API caps a run at {lim.maxSizes} sizes, up to {lim.maxSites} sites per network and {lim.maxCommands} commands so it stays interactive. The CLI has no cap: <code>python -m netguardx eval --sites 4 8 16 --commands 100 --seed 1 --out eval-results/run1</code>, then import <code>summary.json</code> here.</>}
        </div>
      </section>

      {error && <div className="mb-5"><Notice tone="bad" title="The evaluation did not run">{error}</Notice></div>}

      {!r || !cfg ? (
        <div className="panel"><Empty title="No evaluation loaded">Nothing is pre-filled and no earlier results are stored. Run the harness above, or import a <code>summary.json</code> from the command line.</Empty></div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Chip tone="net">{loaded!.source}</Chip>
            <Chip>{cfg.commands} commands per network</Chip><Chip>{seeds.length > 1 ? `seeds ${seeds.join(", ")}` : `seed ${cfg.seed}`}</Chip><Chip>fault rate {cfg.fault_rate}</Chip><Chip>probes {cfg.probes ? "on" : "off"}</Chip>
            {loaded!.seconds != null && <Chip>took {loaded!.seconds.toFixed(1)} s</Chip>}
          </div>
          {seeds.length > 1
            ? <Notice tone="net" title={`Means over ${seeds.length} seeds`}>Each network size was replayed once per seed. Figures are means, and error bars show 95% confidence intervals. Timings are from whichever machine ran the harness and cover verification only. Unsafe-command counts for the weaker strategies are undercounts, because once a network is broken later damage is treated as already present. The <b className="font-medium text-fg">full</b> arm is safe by construction: unsafe is defined by full verification.</Notice>
            : <Notice tone="net" title="Read these as one measurement, not a benchmark">Timings are from a single seed on whichever machine runs the API, with no repeated runs or confidence intervals; run several seeds from the command line (<code>--seeds 1 2 3 4 5</code>) for error bars. Check time covers verification only. Unsafe-command counts for the weaker strategies are undercounts, because once a network is broken later damage is treated as already present. The <b className="font-medium text-fg">full</b> arm is safe by construction: unsafe is defined by full verification.</Notice>}

          {gated ? (
            <div className="grid gap-5 xl:grid-cols-2">
              <Panel title="Check time per command" sub="median, milliseconds; hover for p95"><LatencyChart runs={r.runs} /></Panel>
              <div className="grid gap-5">
                <Panel title="Speed-up of incremental over full" sub="derived: full median ÷ incremental median"><SpeedupChart runs={r.runs} /></Panel>
              </div>
              <Panel title="Traffic re-simulated by the incremental verifier" sub="share of traffic classes, mean per command; full verification re-simulates 100%"><ResimChart runs={r.runs} /></Panel>
              <Panel title="Incremental reports that differ from full" sub="count per network; the harness compares every report">
                <table className="w-full text-sm"><thead><tr><th className="th">Network</th><th className="th text-right">Commands</th><th className="th text-right">Differing reports</th></tr></thead>
                  <tbody>{r.runs.map((x) => <tr key={x.sites}><td className="td">{runLabel(x)}</td><td className="td text-right tabular-nums">{x.arms.incremental?.commands ?? "n/a"}</td><td className="td text-right tabular-nums">{x.arms.incremental?.mismatches ?? "n/a"}</td></tr>)}</tbody></table>
                <p className="mt-2 text-xs text-faint">A report differs when anything other than timing metadata is unequal to the report full verification produces for the same command.</p>
              </Panel>
            </div>
          ) : <Notice tone="warn" title="Latency charts need both gatekeeper arms">This result does not include both the full and incremental arms, so speed-up and re-simulation are not shown.</Notice>}

          {phaseRows(r.runs, phaseArm).length > 0 && (
            <Panel title="Where the time goes" sub="mean milliseconds per command, by step of the verifier">
              <div className="mb-3"><Segmented label="Verifier" value={phaseArm} onChange={setPhaseArm} options={[{ value: "incremental", label: ARM_LABEL.incremental }, { value: "full", label: ARM_LABEL.full }]} /></div>
              <PhaseChart runs={r.runs} arm={phaseArm} />
              <p className="mt-2 text-xs text-faint">This is the overhead the gatekeeper adds before a command may run. Applying an executed command to the model (commit) is measured separately: {r.runs.map((x) => `${runLabel(x)}: ${ms(x.arms[phaseArm]?.commit_ms_mean)}`).join("; ")}.</p>
            </Panel>
          )}

          {r.scaling && Object.keys(r.scaling).length > 0 && (
            <Panel title="Scaling and projection" sub="median check time against devices, log scales; dashed lines continue the fit">
              <ScalingChart scaling={r.scaling} />
              <table className="mt-3 w-full text-sm"><thead><tr>{["Verifier", "Growth exponent", "Fit R²", ...(Object.values(r.scaling)[0]?.projected ?? []).map((p) => `Projected at ${p.devices} devices`)].map((h, i) => <th key={h} className={`th ${i > 0 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
                <tbody>{(["full", "incremental"] as const).filter((a) => r.scaling![a]).map((a) => { const s = r.scaling![a]!; return (
                  <tr key={a}><td className="td">{ARM_LABEL[a]}</td><td className="td text-right tabular-nums">{s.fit.exponent.toFixed(2)}</td><td className="td text-right tabular-nums">{s.fit.r2 == null ? "n/a" : s.fit.r2.toFixed(3)}</td>
                    {s.projected.map((p) => <td key={p.devices} className="td text-right tabular-nums">{ms(p.ms_p50)}</td>)}</tr>); })}</tbody></table>
              <p className="mt-2 text-xs text-faint">Time grows roughly as devices to the power of the exponent. Projected values extrapolate the fit beyond the measured sizes; they are not measurements.</p>
            </Panel>
          )}

          {r.runs.some((x) => x.memory) && (
            <Panel title="Memory of the incremental cache" sub="kept between commands; peak while building it">
              <table className="w-full text-sm"><thead><tr><th className="th">Network</th><th className="th text-right">Cache held</th><th className="th text-right">Peak while building</th></tr></thead>
                <tbody>{r.runs.filter((x) => x.memory).map((x) => <tr key={x.sites}><td className="td">{runLabel(x)}</td><td className="td text-right tabular-nums">{x.memory!.cache_mb} MB</td><td className="td text-right tabular-nums">{x.memory!.peak_mb} MB</td></tr>)}</tbody></table>
            </Panel>
          )}

          <Panel title="Strategies compared" sub="by network size">
            <div className="mb-3"><Segmented label="Metric" value={metric} onChange={setMetric} options={METRICS.map((x) => ({ value: x.key, label: x.label }))} /></div>
            <ArmChart runs={r.runs} metric={metric} unit={m.unit} />
          </Panel>

          {r.steps && r.steps.length > 0 ? (
            <Panel title="Check time for every command" sub="full and incremental, in the order the commands were proposed">
              <div className="mb-3 flex items-center gap-2 text-sm"><label htmlFor="ev-sz" className="text-muted">Network</label>
                <select id="ev-sz" className="field !w-auto" value={stepSize} onChange={(e) => setStepSites(Number(e.target.value))}>{r.runs.map((x) => <option key={x.sites} value={x.sites}>{runLabel(x)}</option>)}</select></div>
              <StepChart steps={r.steps} sites={stepSize} seed={cfg.seed} />
              <p className="mt-2 text-xs text-faint">The first incremental command pays for building its cache. Commands that do not apply to the network are not verified and are left out.</p>
            </Panel>
          ) : <p className="text-xs text-faint">Per-command timings are not part of summary.json. Run the harness here to see them.</p>}

          <Panel title="All measurements" sub="the table behind every chart">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr>{["Network", "Strategy", "Executed", "Rejected", "Held", "Invalid", "Unsafe executed", "Safe rejected", "Unhealthy steps", "Differing reports", "Re-simulated", "p50", "p95", "Mean"].map((h, i) => <th key={h} className={`th ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
                <tbody>
                  {r.runs.flatMap((run) => ARM_ORDER.filter((a) => run.arms[a]).map((a, i) => {
                    const s = run.arms[a]!; const gk = s.resim_share != null;
                    return (
                      <tr key={`${run.sites}-${a}`} className={i === 0 ? "[&>td]:border-t [&>td]:border-line-strong" : undefined}>
                        <td className="td whitespace-nowrap">{i === 0 ? runLabel(run) : ""}</td><td className="td whitespace-nowrap">{ARM_LABEL[a]}</td>
                        {[s.executed, s.rejected, s.held, s.invalid, s.unsafe_executed, s.safe_rejected, s.unhealthy_steps].map((v, k) => <td key={k} className="td text-right tabular-nums">{count(v)}</td>)}
                        <td className="td text-right tabular-nums">{gk ? s.mismatches : "n/a"}</td><td className="td text-right tabular-nums">{gk ? pct(s.resim_share) : "n/a"}</td>
                        <td className="td text-right tabular-nums">{ms(s.check_ms_p50)}</td><td className="td text-right tabular-nums">{ms(s.check_ms_p95)}</td><td className="td text-right tabular-nums">{ms(s.check_ms_mean)}</td>
                      </tr>);
                  }))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-faint">n/a: the strategy has no such measurement (the baselines do not re-simulate traffic). A check time of 0 means the strategy performs no check.</p>
          </Panel>

          <Panel title="What each strategy rejects">
            <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-[170px_1fr]">{ARM_ORDER.map((a) => <div key={a} className="contents"><dt className="font-medium">{ARM_LABEL[a]}</dt><dd className="text-muted">{ARM_RULE[a]}</dd></div>)}</dl>
          </Panel>
        </div>
      )}
    </>
  );
}
