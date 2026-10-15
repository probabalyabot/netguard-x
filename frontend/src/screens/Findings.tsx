import clsx from "clsx";
import { ArrowDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Finding, Severity } from "../api/types";
import { HopTable } from "../components/HopTable";
import { ImpactGraph, KIND_LABEL } from "../components/ImpactGraph";
import { Chip, Empty, PageHeader, PathText, SeverityBadge, Tabs, VerdictBadge } from "../components/ui";
import { findingTypeLabel, severityTone, statusLabel, svc, toneText } from "../lib/format";
import { useApp } from "../state/AppState";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "info"];

function FactRow({ k, children }: { k: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-[130px_1fr] gap-3 py-1.5 border-b border-line/50 last:border-0"><dt className="text-muted">{k}</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd></div>;
}

export function Findings() {
  const { report, focus, setFocus } = useApp();
  const [sev, setSev] = useState<Severity | "all">("all");
  const [tab, setTab] = useState<"list" | "graph">("list");

  const list = useMemo(() => (report?.findings ?? []).filter((f) => sev === "all" || f.severity === sev), [report, sev]);
  if (!report) return (<><PageHeader title="Findings" /><div className="panel"><Empty title="No findings yet" action={<Link to="/analyze" className="btn btn-primary">Analyze a change</Link>}>Findings are produced by simulating a change.</Empty></div></>);

  const sel: Finding | undefined = report.findings.find((f) => f.id === focus.findingId) ?? list[0];
  const delta = sel && report.flow_deltas.find((d) => d.key === sel.flow_key);
  const rootChange = sel && sel.root_change != null ? report.changes[sel.root_change] : undefined;
  const revert = sel && sel.root_change != null ? report.rollback?.revert.find((r) => r.index === sel.root_change) : undefined;
  const highlight = sel ? new Set(sel.propagation.map((s) => s.key)) : null;
  const counts = Object.fromEntries(SEVERITIES.map((s) => [s, report.findings.filter((f) => f.severity === s).length])) as Record<Severity, number>;

  return (
    <>
      <PageHeader title="Findings" sub="What the simulator observed, how it traced each problem back to a change, and what it recommends. Evidence and explanation are shown separately."
        right={<VerdictBadge decision={report.verdict.decision} large />} />

      {report.findings.length === 0 ? (
        <div className="panel"><Empty title="No findings">{report.verdict.headline}.</Empty></div>
      ) : (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ value: "list", label: "Findings", count: report.findings.length }, { value: "graph", label: "Impact graph" }]} />
          {tab === "graph" ? (
            <div className="mt-4 panel overflow-hidden">
              <div className="panel-h !py-2.5"><h2 className="panel-title">Configuration impact graph</h2><span className="text-xs text-muted">every finding's chain merged · {sel ? `highlighting ${sel.id}` : ""}</span></div>
              <div className="h-[520px] bg-ink"><ImpactGraph graph={report.impact_graph} highlight={highlight} /></div>
              <div className="flex flex-wrap gap-1.5 border-t border-line p-3">{report.findings.map((f) => (
                <button key={f.id} className={clsx("btn !py-0.5 !text-xs", sel?.id === f.id && "!border-net !text-net")} onClick={() => setFocus({ findingId: f.id, flowKey: f.flow_key })}>{f.id}</button>))}</div>
            </div>
          ) : (
            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <section className="panel self-start overflow-hidden">
                <div className="flex flex-wrap gap-1.5 border-b border-line p-3">
                  <button className={clsx("chip", sev === "all" ? "border-net/50 text-net bg-net/10" : "border-line-strong text-muted")} aria-pressed={sev === "all"} onClick={() => setSev("all")}>All {report.findings.length}</button>
                  {SEVERITIES.filter((s) => counts[s] > 0).map((s) => (
                    <button key={s} className={clsx("chip", sev === s ? "border-net/50 text-net bg-net/10" : "border-line-strong text-muted")} aria-pressed={sev === s} onClick={() => setSev(s)}>{s} {counts[s]}</button>))}
                </div>
                <ul>{list.map((f) => (
                  <li key={f.id} className="border-b border-line/60 last:border-0">
                    <button className={clsx("flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-raised/60", sel?.id === f.id && "bg-raised shadow-[inset_2px_0_0_rgb(var(--net))]")}
                      aria-current={sel?.id === f.id} onClick={() => setFocus({ findingId: f.id, flowKey: f.flow_key })}>
                      <span className="flex items-center gap-2"><span className="mono text-muted">{f.id}</span><SeverityBadge severity={f.severity} /><span className="text-xs text-muted">{findingTypeLabel[f.type] ?? f.type}</span></span>
                      <span className="text-sm leading-snug">{f.title}</span>
                    </button>
                  </li>))}
                  {list.length === 0 && <li className="p-4 text-sm text-muted">No findings at this severity.</li>}
                </ul>
              </section>

              {sel && (
                <div className="space-y-4">
                  <section className="panel">
                    <div className="panel-h"><div className="flex items-center gap-2"><span className="mono text-muted">{sel.id}</span><SeverityBadge severity={sel.severity} /><Chip>{findingTypeLabel[sel.type] ?? sel.type}</Chip></div>
                      <Link to="/compare" onClick={() => setFocus({ findingId: sel.id, flowKey: sel.flow_key })} className="text-sm text-net hover:underline">Show on the map</Link></div>
                    <div className="p-4"><h2 className="text-lg font-semibold leading-snug">{sel.title}</h2></div>
                  </section>

                  <section className="panel">
                    <div className="panel-h"><h2 className="panel-title">Computed evidence</h2><span className="text-xs text-muted">observed in the simulation</span></div>
                    <dl className="px-4 py-2 text-sm">
                      <FactRow k="Traffic">{sel.type === "NEW_EXPOSURE" ? `${sel.source} → ${sel.destination}${sel.extra.services ? ` on ${sel.extra.services.join(", ")}` : ""}` : `${sel.source} → ${sel.destination}${delta ? ` ${svc(delta.protocol, delta.port)}` : ""}`}</FactRow>
                      <FactRow k="Required by policy">{sel.expected ? <>{sel.expected === "ALLOW" ? "Delivered" : sel.expected === "DENY" ? "Blocked" : "Mixed"}{sel.policies.length > 0 && <span className="mono text-muted"> ({sel.policies.join(", ")})</span>}</> : <span className="text-muted">No policy covers this traffic</span>}</FactRow>
                      <FactRow k="Before"><PathText path={sel.before_path} /> <span className={clsx("ml-1", sel.before_status === "DELIVERED" ? "text-safe" : "text-muted")}>{statusLabel(sel.before_status)}</span></FactRow>
                      <FactRow k="After"><PathText path={sel.after_path} /> <span className={clsx("ml-1", sel.after_status === "DELIVERED" ? toneText[severityTone[sel.severity]] : "text-bad")}>{statusLabel(sel.after_status)}</span></FactRow>
                      {sel.extra.violations?.map((v) => <FactRow key={v.policy_id} k={`Policy ${v.policy_id}`}><span className="text-bad">{v.violation?.replaceAll("_", " ")}</span><span className="block text-muted">{v.reason}</span></FactRow>)}
                      <FactRow k="Root cause">{rootChange ? <>Change {rootChange.index + 1}: {rootChange.description}</> : <span className="text-muted">The engine could not attribute this to a single change.</span>}</FactRow>
                      {sel.extra.criticality != null && <FactRow k="Criticality">{sel.extra.criticality} of 5</FactRow>}
                    </dl>
                    {delta && <div className="border-t border-line"><h3 className="px-4 pt-3 text-xs font-medium text-muted">Hop-by-hop after the change (changed rows marked)</h3><HopTable trace={delta.after} compareTo={delta.before} /></div>}
                  </section>

                  <section className="panel">
                    <div className="panel-h"><h2 className="panel-title">How the change leads to this</h2><span className="text-xs text-muted">propagation chain</span></div>
                    <ol className="p-4">
                      {sel.propagation.map((s, i) => (
                        <li key={s.key} className="relative pl-6 pb-3 last:pb-0">
                          {i < sel.propagation.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-line-strong" aria-hidden />}
                          <span className={clsx("absolute left-0 top-1 size-[15px] rounded-full border-2 bg-panel", s.kind === "impact" || s.kind === "policy" ? "border-bad" : s.kind === "enforcement" ? "border-warn" : "border-net")} aria-hidden />
                          <p className="text-xs text-muted">{KIND_LABEL[s.kind]}</p>
                          <p className="text-sm">{s.label}</p>
                          {s.detail && <p className="mono mt-0.5 whitespace-pre-wrap text-muted">{s.detail}</p>}
                        </li>))}
                    </ol>
                  </section>

                  <section className="panel">
                    <div className="panel-h"><h2 className="panel-title">Explanation</h2><span className="text-xs text-muted">templated from the evidence above, no language model</span></div>
                    <div className="space-y-3 p-4 text-sm">
                      <div><h3 className="text-xs font-medium text-muted">In plain terms</h3><p className="mt-0.5">{sel.human}</p></div>
                      <div><h3 className="text-xs font-medium text-muted">Technical</h3><p className="mt-0.5 text-muted [overflow-wrap:anywhere]">{sel.technical}</p></div>
                    </div>
                  </section>

                  <section className="panel">
                    <div className="panel-h"><h2 className="panel-title">Recommendation</h2></div>
                    <div className="space-y-2 p-4 text-sm">
                      {revert && report.rollback ? (<>
                        <p>Revert change {revert.index + 1}: {revert.description}</p>
                        <p className="text-muted">The simulator re-ran the analysis with that change removed and returned <b className="font-medium text-fg">{report.rollback.if_reverted.decision.replace("_", " ").toLowerCase()}</b> with {report.rollback.if_reverted.remaining_problems} remaining problem{report.rollback.if_reverted.remaining_problems === 1 ? "" : "s"}.</p>
                        <details><summary className="cursor-pointer text-xs text-muted hover:text-fg">Inverse change</summary><pre className="mono mt-1 overflow-x-auto rounded border border-line bg-ink p-2 text-muted">{JSON.stringify(revert.revert_with, null, 2)}</pre></details>
                        <p className="flex items-center gap-1.5 text-xs text-faint"><ArrowDown size={12} aria-hidden />{report.rollback.note}</p>
                      </>) : <p className="text-muted">The engine makes a revert recommendation only for critical and high findings that trace back to a change. None applies to this finding.</p>}
                    </div>
                  </section>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
