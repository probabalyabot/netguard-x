import clsx from "clsx";
import { Link } from "react-router-dom";
import type { ChangeReport, Finding, Trace } from "../api/types";
import { HopTable } from "../components/HopTable";
import { TopologyCanvas, type PathOverlay } from "../components/TopologyCanvas";
import { Chip, Empty, PageHeader, PathText, VerdictBadge } from "../components/ui";
import {
  findingTypeLabel, outcomeLabel, outcomeTone, policyStatusLabel, policyStatusTone, severityTone, statusLabel, statusTone, svc, toneText, type Tone,
} from "../lib/format";
import { useApp } from "../state/AppState";

interface Row {
  key: string; label: string; beforePath: string[]; afterPath: string[]; beforeStatus: string; afterStatus: string;
  expected: string | null; outcome: string; tone: Tone; before?: Trace; after?: Trace; finding?: Finding;
  added: string[]; removed: string[]; stopBefore?: string | null; stopAfter?: string | null;
}

/** One row per behavioural difference the backend reports: flow deltas, plus findings that have no delta (exposures found by probes). */
function buildRows(report: ChangeReport): Row[] {
  const byFlow = new Map(report.findings.filter((f) => f.flow_key).map((f) => [f.flow_key!, f]));
  const rows: Row[] = report.flow_deltas.map((d) => ({
    key: d.key, label: `${d.source} → ${d.destination} ${svc(d.protocol, d.port)}`, beforePath: d.before.path, afterPath: d.after.path,
    beforeStatus: d.before.status, afterStatus: d.after.status, expected: d.expected, outcome: outcomeLabel[d.outcome], tone: outcomeTone[d.outcome],
    before: d.before, after: d.after, finding: byFlow.get(d.key), added: d.added_devices, removed: d.removed_devices,
    stopBefore: d.before.stop_node, stopAfter: d.after.stop_node,
  }));
  const seen = new Set(rows.map((r) => r.key));
  for (const f of report.findings) {
    if (!f.flow_key || seen.has(f.flow_key)) continue;
    rows.push({
      key: f.flow_key, label: f.type === "NEW_EXPOSURE" ? `${f.source} → ${f.destination} (probe)` : `${f.source} → ${f.destination}`,
      beforePath: f.before_path, afterPath: f.after_path, beforeStatus: f.before_status, afterStatus: f.after_status, expected: f.expected,
      outcome: findingTypeLabel[f.type] ?? f.type, tone: severityTone[f.severity], finding: f,
      added: f.after_path.filter((n) => !f.before_path.includes(n)), removed: f.before_path.filter((n) => !f.after_path.includes(n)),
    });
  }
  return rows;
}

function Pane({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="panel overflow-hidden">
      <div className="panel-h !py-2.5"><h2 className="panel-title">{title}</h2><span className="text-xs text-muted">{sub}</span></div>
      <div className="h-[400px] bg-ink">{children}</div>
    </section>
  );
}

export function Compare() {
  const { report, focus, setFocus, reportTitle } = useApp();
  if (!report) {
    return (<>
      <PageHeader title="Before and after" />
      <div className="panel"><Empty title="No analysis to compare" action={<Link to="/analyze" className="btn btn-primary">Analyze a change</Link>}>Simulate a change first. This screen then shows the network and its traffic paths with and without it.</Empty></div>
    </>);
  }
  const rows = buildRows(report);
  const sel = rows.find((r) => r.key === focus.flowKey) ?? rows.find((r) => r.finding?.id === focus.findingId) ?? rows[0] ?? null;

  const markTone = (r: Row, status: string): Tone => (status === "DELIVERED" ? "net" : r.expected === "DENY" ? "safe" : r.expected ? "bad" : "warn");
  const beforeOv: PathOverlay[] = sel && sel.beforePath.length ? [{ id: "b", nodes: sel.beforePath, tone: sel.beforeStatus === "DELIVERED" ? "net" : "muted" }] : [];
  const afterTone: Tone = sel?.finding && sel.afterStatus === "DELIVERED" && sel.finding.severity !== "info" ? severityTone[sel.finding.severity] : sel?.afterStatus === "DELIVERED" ? "net" : "bad";
  const afterOv: PathOverlay[] = sel && sel.afterPath.length ? [{ id: "a", nodes: sel.afterPath, tone: afterTone }] : [];
  const stop = (r: Row | null, which: "before" | "after"): Record<string, Tone> => {
    if (!r) return {};
    const status = which === "before" ? r.beforeStatus : r.afterStatus;
    const path = which === "before" ? r.beforePath : r.afterPath;
    if (status === "DELIVERED" || path.length === 0) return {};
    const node = (which === "before" ? r.stopBefore : r.stopAfter) ?? path[path.length - 1];
    return { [node]: markTone(r, status) };
  };

  return (
    <>
      <PageHeader title="Before and after"
        sub={<>{reportTitle}. Select a flow to see its path with and without the change. Each side comes from a separate simulation of the same traffic.</>}
        right={<VerdictBadge decision={report.verdict.decision} large />} />
      <p className="mb-4 text-lg leading-snug">{report.verdict.headline}</p>

      <div className="grid gap-4 lg:grid-cols-2">
        <Pane title="Before" sub="current network"><TopologyCanvas topology={report.topology} view="before" overlays={beforeOv} marks={stop(sel, "before")} className="h-full" ariaLabel="Topology before the change" /></Pane>
        <Pane title="After" sub="with the proposed change"><TopologyCanvas topology={report.topology} view="after" overlays={afterOv} marks={stop(sel, "after")} className="h-full" ariaLabel="Topology after the change" /></Pane>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <section className="panel overflow-hidden">
          <div className="panel-h"><h2 className="panel-title">Flows that behave differently</h2><span className="text-xs text-muted">{rows.length} of {report.summary.declared_flows_checked} declared{report.meta.probes_enabled ? ` + ${report.summary.probes_newly_reachable} probe exposures` : ""}</span></div>
          {rows.length === 0 ? <Empty title="No flow behaves differently">Every declared flow and policy takes the same path and has the same outcome with this change.</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="th">Flow</th><th className="th">Required</th><th className="th">Before</th><th className="th">After</th><th className="th">Outcome</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} onClick={() => setFocus({ flowKey: r.key, findingId: r.finding?.id ?? null })} aria-selected={sel?.key === r.key}
                      className={clsx("cursor-pointer hover:bg-raised/60", sel?.key === r.key && "bg-raised")}>
                      <td className={clsx("td", sel?.key === r.key && "shadow-[inset_2px_0_0_rgb(var(--net))]")}>
                        <button className="text-left font-medium" onClick={(e) => { e.stopPropagation(); setFocus({ flowKey: r.key, findingId: r.finding?.id ?? null }); }}>{r.label}</button>
                      </td>
                      <td className="td text-muted">{r.expected === "ALLOW" ? "Delivered" : r.expected === "DENY" ? "Blocked" : r.expected ? "Mixed" : "no policy"}</td>
                      <td className={clsx("td", toneText[statusTone(r.beforeStatus)])}>{statusLabel(r.beforeStatus)}</td>
                      <td className={clsx("td", toneText[statusTone(r.afterStatus)])}>{statusLabel(r.afterStatus)}</td>
                      <td className="td"><Chip tone={r.tone}>{r.outcome}</Chip></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel self-start">
          <div className="panel-h"><h2 className="panel-title">{sel ? sel.label : "Selected flow"}</h2>{sel?.finding && <Link to="/findings" onClick={() => setFocus({ findingId: sel.finding!.id })} className="text-sm text-net hover:underline">{sel.finding.id} in findings</Link>}</div>
          {!sel ? <p className="p-4 text-sm text-muted">Nothing selected.</p> : (
            <div className="space-y-3 p-4 text-sm">
              <dl className="space-y-2">
                <div><dt className="text-xs text-muted">Path before</dt><dd><PathText path={sel.beforePath} mark={sel.beforeStatus !== "DELIVERED" ? sel.stopBefore ?? sel.beforePath[sel.beforePath.length - 1] : null} /> <span className={clsx("ml-1", toneText[statusTone(sel.beforeStatus)])}>{statusLabel(sel.beforeStatus)}</span></dd></div>
                <div><dt className="text-xs text-muted">Path after</dt><dd><PathText path={sel.afterPath} mark={sel.afterStatus !== "DELIVERED" ? sel.stopAfter ?? sel.afterPath[sel.afterPath.length - 1] : null} /> <span className={clsx("ml-1", toneText[statusTone(sel.afterStatus)])}>{statusLabel(sel.afterStatus)}</span></dd></div>
                {sel.removed.length > 0 && <div><dt className="text-xs text-muted">No longer on the path</dt><dd className="mono text-bad">{sel.removed.join(", ")}</dd></div>}
                {sel.added.length > 0 && <div><dt className="text-xs text-muted">Newly on the path</dt><dd className="mono text-net">{sel.added.join(", ")}</dd></div>}
              </dl>
              {sel.before && sel.after ? (
                <div className="space-y-2">
                  <div><h3 className="mb-1 text-xs font-medium text-muted">Forwarding decisions before</h3><div className="rounded border border-line"><HopTable trace={sel.before} /></div></div>
                  <div><h3 className="mb-1 text-xs font-medium text-muted">Forwarding decisions after <span className="text-faint">(rows that differ are marked)</span></h3><div className="rounded border border-line"><HopTable trace={sel.after} compareTo={sel.before} /></div></div>
                </div>
              ) : <p className="text-xs text-faint">Hop-level traces are returned for declared flows. This result comes from an exposure probe, so only the paths are available.</p>}
            </div>
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <section className="panel overflow-hidden self-start">
          <div className="panel-h"><h2 className="panel-title">Policies</h2><span className="text-xs text-muted">{report.policies.length}</span></div>
          {report.policies.length === 0 ? <p className="p-4 text-sm text-muted">This network declares no policies.</p> : (
            <table className="w-full text-sm"><thead><tr><th className="th">Policy</th><th className="th">Requirement</th><th className="th">Before</th><th className="th">After</th><th className="th">Status</th></tr></thead>
              <tbody>{report.policies.map((p) => (
                <tr key={p.id}>
                  <td className="td mono">{p.id}</td><td className="td">{p.description}{p.after && !p.after.satisfied && <span className="block text-xs text-muted">{p.after.reason}</span>}</td>
                  <td className="td">{p.before ? (p.before.satisfied ? <span className="text-safe">holds</span> : <span className="text-bad">violated</span>) : <span className="text-faint">–</span>}</td>
                  <td className="td">{p.after ? (p.after.satisfied ? <span className="text-safe">holds</span> : <span className="text-bad">violated</span>) : <span className="text-faint">–</span>}</td>
                  <td className="td"><Chip tone={policyStatusTone[p.status]}>{policyStatusLabel[p.status]}</Chip></td>
                </tr>))}</tbody></table>
          )}
        </section>

        <section className="panel overflow-hidden self-start">
          <div className="panel-h"><h2 className="panel-title">Changes simulated</h2><span className="text-xs text-muted">and the inverse that would undo each</span></div>
          <ol className="divide-y divide-line/60">
            {report.changes.map((c) => (
              <li key={c.index} className="px-4 py-2.5 text-sm">
                <p><span className="mr-2 text-faint tabular-nums">{c.index + 1}</span>{c.description}</p>
                <p className="mt-0.5 text-xs text-muted">Touches {c.effect.kind}{c.effect.nodes?.length ? ` on ${c.effect.nodes.join(", ")}` : ""}{c.effect.prefix ? ` for ${c.effect.prefix}` : ""}{c.effect.policy_id ? ` (${c.effect.policy_id})` : ""}</p>
                <details className="mt-1"><summary className="cursor-pointer text-xs text-muted hover:text-fg">Inverse change</summary><pre className="mono mt-1 overflow-x-auto rounded border border-line bg-ink p-2 text-muted">{JSON.stringify(c.inverse, null, 2)}</pre></details>
              </li>))}
          </ol>
        </section>
      </div>
    </>
  );
}
