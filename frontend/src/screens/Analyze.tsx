import { ChevronDown, Play, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Change, InterpretResponse } from "../api/types";
import { ChangeBuilder } from "../components/ChangeBuilder";
import { ResultSummary } from "../components/ResultSummary";
import { Empty, Notice, PageHeader, Segmented, Spinner } from "../components/ui";
import { describeChange } from "../lib/describe";
import { errMsg } from "../lib/format";
import { validateChanges } from "../lib/validate";
import { DEFAULT_WEIGHTS, useApp } from "../state/AppState";

function JsonEditor() {
  const { changes, setChanges, network, setScenario } = useApp();
  const pretty = (c: Change[]) => JSON.stringify(c, null, 2);
  const [text, setText] = useState(pretty(changes));
  const [errors, setErrors] = useState<string[]>([]);
  const lastEmitted = useRef(JSON.stringify(changes));

  useEffect(() => {
    if (JSON.stringify(changes) !== lastEmitted.current) { setText(pretty(changes)); setErrors([]); lastEmitted.current = JSON.stringify(changes); }
  }, [changes]);

  const onChange = (v: string) => {
    setText(v);
    let parsed: unknown;
    try { parsed = JSON.parse(v); } catch (e) { setErrors([`Not valid JSON: ${errMsg(e)}`]); return; }
    const r = validateChanges(parsed, network);
    setErrors(r.errors);
    if (!r.errors.length) { lastEmitted.current = JSON.stringify(r.changes); setChanges(r.changes); setScenario(null); }
  };
  return (
    <div>
      <label className="label" htmlFor="json">Changes as JSON. A list of change objects, or {"{ \"changes\": [...] }"}</label>
      <textarea id="json" className="field mono min-h-[240px] resize-y leading-5" spellCheck={false} value={text} onChange={(e) => onChange(e.target.value)} aria-invalid={errors.length > 0} />
      {errors.length > 0
        ? <ul role="alert" className="mt-1.5 space-y-0.5 text-sm text-bad">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
        : <p className="mt-1.5 text-xs text-faint">Valid. The API still checks that each change applies to this network.</p>}
    </div>
  );
}

function Drafter() {
  const { network, changes, setChanges, setScenario } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<InterpretResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    if (!network || !text.trim()) return;
    setBusy(true); setErr(null); setRes(null);
    try {
      const r = await api.interpret(text, network);
      setRes(r);
      const drafted: Change[] = [...r.changes, ...r.policies.map((p) => ({ operation: "ADD_POLICY" as const, policy: p }))];
      if (drafted.length) { setChanges([...changes, ...drafted]); setScenario(null); }
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <div>
      <label className="label" htmlFor="nl">Draft from a sentence</label>
      <div className="flex gap-2">
        <input id="nl" className="field" value={text} placeholder="Change the route on R1 for 10.0.5.0/24 to R3"
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
        <button className="btn" onClick={run} disabled={busy || !text.trim()}><Sparkles size={15} aria-hidden />Draft</button>
      </div>
      <p className="mt-1.5 text-xs text-faint">A rule-based parser, not a language model. It understands simple route, link and reachability phrasings, and drafted changes are added to the set below for you to review.</p>
      {err && <p role="alert" className="mt-1.5 text-sm text-bad">{err}</p>}
      {res && (
        <div className="mt-2 space-y-1 text-sm">
          {(res.changes.length > 0 || res.policies.length > 0) && <p className="text-safe">Added {res.changes.length} change{res.changes.length === 1 ? "" : "s"}{res.policies.length > 0 && ` and ${res.policies.length} polic${res.policies.length === 1 ? "y" : "ies"} (as ADD_POLICY)`}. Review before analysing.</p>}
          {res.unparsed.map((u) => <p key={u.text} className="text-warn">Not understood: “{u.text}”{u.reason ? ` (${u.reason})` : ""}</p>)}
        </div>
      )}
    </div>
  );
}

function Options() {
  const { weights, setWeights, probes, setProbes } = useApp();
  const [open, setOpen] = useState(false);
  const fields: [keyof typeof weights, string][] = [["broken_flows", "Broken flow"], ["security_violations", "Security violation"], ["new_exposures", "New exposure"], ["routing_failures", "Routing failure"], ["criticality", "Criticality"]];
  return (
    <div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={probes} onChange={(e) => setProbes(e.target.checked)} className="accent-[rgb(var(--net))]" />Probe every endpoint pair for new exposure <span className="text-faint">(capped at 2000 probes)</span></label>
      <button type="button" className="btn btn-ghost mt-1 !px-0" aria-expanded={open} onClick={() => setOpen(!open)}><ChevronDown size={15} className={open ? "rotate-180" : ""} aria-hidden />Risk weights</button>
      {open && (
        <div className="mt-1 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {fields.map(([k, l]) => (
            <div key={k}><label className="label" htmlFor={`w-${k}`}>{l}</label>
              <input id={`w-${k}`} type="number" min={0} className="field" value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: Math.max(0, Number(e.target.value) || 0) })} /></div>
          ))}
          <div className="col-span-full flex items-center justify-between text-xs text-faint"><span>Heuristic starting points, not calibrated values.</span>
            <button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => setWeights(DEFAULT_WEIGHTS)}>Reset</button></div>
        </div>
      )}
    </div>
  );
}

export function Analyze() {
  const { network, examples, scenario, setScenario, changes, setChanges, report, reportError, analyzing, analyze, stale, networkLabel } = useApp();
  const [mode, setMode] = useState<"builder" | "json">("builder");
  const scenarios = (examples?.changes ?? []);

  if (!network) return <Empty title="No network loaded">Load a network on the Overview screen first.</Empty>;

  return (
    <>
      <PageHeader title="Change analysis" sub={<>Propose a change, simulate it against <b className="font-medium text-fg">{networkLabel}</b>, and see what it breaks before anything is executed.</>} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <div className="space-y-5">
          <section className="panel">
            <div className="panel-h"><h2 className="panel-title">Example scenarios</h2><span className="text-xs text-muted">from the repository</span></div>
            <ul className="divide-y divide-line/60">
              {scenarios.map((s) => (
                <li key={s.id}>
                  <button className="flex w-full flex-col items-start gap-0.5 px-4 py-2.5 text-left transition-colors hover:bg-raised/60 aria-pressed:bg-raised aria-pressed:shadow-[inset_2px_0_0_rgb(var(--net))]"
                    aria-pressed={scenario?.id === s.id} onClick={() => { setScenario(s); setChanges(s.changes); }}>
                    <span className="text-sm font-medium">{s.title ?? s.id}</span>
                    {s.description && <span className="text-xs text-muted">{s.description}</span>}
                  </button>
                </li>
              ))}
              {scenarios.length === 0 && <li className="px-4 py-3 text-sm text-muted">No example scenarios were returned by the API.</li>}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-h">
              <h2 className="panel-title">Change set <span className="font-normal text-muted">({changes.length})</span></h2>
              {changes.length > 0 && <button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => { setChanges([]); setScenario(null); }}><Trash2 size={13} aria-hidden />Clear</button>}
            </div>
            <div className="space-y-4 p-4">
              {changes.length === 0
                ? <p className="text-sm text-muted">Empty. Pick a scenario, draft one from a sentence, or build one below.</p>
                : <ol className="space-y-1">{changes.map((c, i) => (
                    <li key={i} className="flex items-start justify-between gap-2 rounded border border-line bg-raised/40 px-2.5 py-1.5 text-sm">
                      <span><span className="mr-2 text-faint tabular-nums">{i + 1}</span>{describeChange(c)}</span>
                      <button aria-label={`Remove change ${i + 1}`} className="text-muted hover:text-bad" onClick={() => { setChanges(changes.filter((_, j) => j !== i)); setScenario(null); }}><Trash2 size={14} /></button>
                    </li>))}</ol>}
              <Drafter />
              <div className="border-t border-line pt-3">
                <Segmented label="Editor" value={mode} onChange={setMode} options={[{ value: "builder", label: "Form" }, { value: "json", label: "JSON" }]} />
                <div className="mt-3">{mode === "builder" ? <ChangeBuilder network={network} onAdd={(c) => { setChanges([...changes, c]); setScenario(null); }} /> : <JsonEditor />}</div>
              </div>
              <div className="border-t border-line pt-3"><Options /></div>
              <div className="flex items-center gap-3">
                <button className="btn btn-primary" disabled={analyzing || changes.length === 0} onClick={() => analyze()}>
                  <Play size={15} aria-hidden />{analyzing ? "Simulating…" : "Simulate change"}
                </button>
                {analyzing && <Spinner />}
              </div>
              {reportError && <Notice tone="bad" title="The change could not be analysed">{reportError}</Notice>}
            </div>
          </section>
        </div>

        <section className="panel self-start xl:sticky xl:top-0">
          <div className="panel-h"><h2 className="panel-title">Result</h2>{stale && <span className="text-xs text-warn">Inputs changed since this result</span>}</div>
          <div className="p-4">
            {analyzing && !report && <Spinner label="Simulating every traffic class in both networks…" />}
            {!report && !analyzing && <Empty title="No result yet">The simulator applies the change to a copy of the network, replays every declared flow and policy in both, and reports the differences. Nothing is executed on a device.</Empty>}
            {report && <div className={stale ? "opacity-60" : undefined}><ResultSummary report={report} /></div>}
          </div>
        </section>
      </div>
    </>
  );
}
