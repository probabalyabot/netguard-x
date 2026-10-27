import { FileJson, FlaskConical, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { TopologyCanvas, TYPE_LABEL } from "../components/TopologyCanvas";
import { ResultSummary } from "../components/ResultSummary";
import { Chip, Empty, Notice, PageHeader, Spinner, Stat, VerdictBadge } from "../components/ui";
import { errMsg, toneText } from "../lib/format";
import { scenariosFor } from "../lib/scenarios";
import { useApp } from "../state/AppState";
import type { NodeType } from "../api/types";

function NetworkPicker() {
  const { examples, networkLabel, loadNetwork, baselineError, setScenario, setChanges } = useApp();
  const [err, setErr] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const upload = async (f: File) => {
    setErr(null);
    try { await loadNetwork(JSON.parse(await f.text()), f.name); } catch (e) { setErr(`Could not read ${f.name}: ${errMsg(e)}`); }
  };
  const current = examples?.networks.find((n) => n.title === networkLabel)?.id ?? "";
  return (
    <div className="space-y-2">
      <label className="label" htmlFor="net">Network</label>
      <div className="flex flex-wrap gap-2">
        <select id="net" className="field !w-auto min-w-[220px] flex-1" value={current} disabled={!examples}
          onChange={(e) => {
            const n = examples?.networks.find((x) => x.id === e.target.value);
            if (!n) return;
            // open the new network's first scenario; the old change set would not apply to it
            const sc = scenariosFor(examples, n.id)[0] ?? null;
            setScenario(sc); setChanges(sc?.changes ?? []);
            loadNetwork(n.network, n.title);
          }}>
          {!current && <option value="">{networkLabel || "Loading…"}</option>}
          {examples?.networks.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
        </select>
        <input ref={file} type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        <button className="btn" onClick={() => file.current?.click()}><Upload size={15} aria-hidden />Load JSON file</button>
      </div>
      {(err || baselineError) && <p role="alert" className="text-sm text-bad [overflow-wrap:anywhere]">{err ?? baselineError}</p>}
    </div>
  );
}

const TYPES: NodeType[] = ["router", "firewall", "server", "host", "internet"];

export function Overview() {
  const { network, baseline, baselineLoading, report, history, openHistory, clearHistory, health, stale, reportTitle } = useApp();
  const nav = useNavigate();
  const counts = network && {
    types: TYPES.map((t) => [t, network.nodes.filter((n) => n.type === t).length] as const).filter(([, c]) => c > 0),
    links: network.links?.length ?? 0, routes: network.routes?.length ?? 0, acls: network.acls?.length ?? 0,
    flows: network.flows?.length ?? 0, policies: network.policies?.length ?? 0,
  };

  return (
    <>
      <PageHeader title="Overview"
        sub="Check a proposed network change before it is made. NetGuard-X replays your traffic and policies through a simulated copy of the network and reports what would break, and why."
        right={<Link to="/analyze" className="btn btn-primary"><FlaskConical size={15} aria-hidden />Analyze a change</Link>} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <section className="panel">
          <div className="panel-h"><h2 className="panel-title">Current network</h2>{network && <Link to="/explorer" className="text-sm text-net hover:underline">Open in explorer</Link>}</div>
          <div className="space-y-4 p-4">
            <NetworkPicker />
            {!network && health.state === "offline" && <Empty title="No network loaded">The API is offline. Start it, then retry from the top bar.</Empty>}
            {network && counts && (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {counts.types.map(([t, c]) => <Chip key={t}>{c} {TYPE_LABEL[t].toLowerCase()}{c === 1 ? "" : "s"}</Chip>)}
                  <Chip>{counts.links} links</Chip><Chip>{counts.routes} static routes</Chip><Chip>{counts.acls} ACL rules</Chip>
                  <Chip>{counts.flows} flows</Chip><Chip>{counts.policies} policies</Chip>
                </div>
                <div className="h-[380px] overflow-hidden rounded-md border border-line bg-ink">
                  {baseline ? <TopologyCanvas topology={baseline.topology} hideLegend className="h-full" ariaLabel="Network topology preview" />
                    : <div className="grid h-full place-items-center">{baselineLoading ? <Spinner label="Checking the network…" /> : <span className="text-sm text-muted">Topology unavailable.</span>}</div>}
                </div>
              </>
            )}
          </div>
        </section>

        <section className="panel self-start">
          <div className="panel-h"><h2 className="panel-title">Verification status</h2><span className="text-xs text-muted">network as it is today</span></div>
          <div className="space-y-4 p-4">
            {baselineLoading && <Spinner label="Verifying…" />}
            {!baseline && !baselineLoading && <p className="text-sm text-muted">Not verified yet. Load a network to check its declared flows and policies.</p>}
            {baseline && (
              <>
                <dl className="grid grid-cols-3 gap-4">
                  <Stat label="Policies held" value={`${baseline.summary.policies_satisfied} / ${baseline.summary.policies}`} tone={baseline.summary.policies_violated ? "bad" : "safe"} />
                  <Stat label="Traffic delivered" value={`${baseline.summary.delivered} / ${baseline.summary.flows_checked}`} sub="declared flows and policy traffic" />
                  <Stat label="Config issues" value={baseline.summary.static_issues} tone={baseline.summary.static_issues ? "warn" : undefined} sub="dangling routes and similar" />
                </dl>
                {baseline.policy_results.some((p) => !p.satisfied) && (
                  <Notice tone="bad" title="Policies already violated">
                    <ul className="list-disc pl-4">{baseline.policy_results.filter((p) => !p.satisfied).map((p) => <li key={p.policy_id}><b className="font-medium text-fg">{p.policy_id}</b>: {p.reason}</li>)}</ul>
                  </Notice>
                )}
                {baseline.static_issues.length > 0 && <Notice tone="warn" title="Configuration issues"><ul className="list-disc pl-4">{baseline.static_issues.map((i, k) => <li key={k}>{i.message}</li>)}</ul></Notice>}
                <p className="text-xs text-faint">Traffic that a DENY policy blocks counts as not delivered, which is the intended result.</p>
              </>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-h"><h2 className="panel-title">Latest result</h2>{report && <span className="text-xs text-muted">{reportTitle}{stale ? " · out of date" : ""}</span>}</div>
          <div className="p-4">
            {report ? <ResultSummary report={report} /> : <Empty title="Nothing analysed in this session" action={<Link to="/analyze" className="btn btn-primary">Analyze a change</Link>}>Results appear here after you simulate a change. Nothing is pre-filled.</Empty>}
          </div>
        </section>

        <section className="panel self-start">
          <div className="panel-h"><h2 className="panel-title">Recent analyses</h2>{history.length > 0 && <button className="btn btn-ghost !py-0.5 !text-xs" onClick={clearHistory}>Clear</button>}</div>
          {history.length === 0
            ? <Empty title="No saved analyses">Analyses you run are kept in this browser only, so you can reopen them here.</Empty>
            : <ul className="divide-y divide-line/60">{history.map((h) => (
                <li key={h.id}>
                  <button className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-raised/60" onClick={() => { openHistory(h.id); nav("/compare"); }}>
                    <VerdictBadge decision={h.report.verdict.decision} />
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm">{h.title}</span><span className="block truncate text-xs text-muted">{h.network} · {new Date(h.at).toLocaleString()}</span></span>
                    <FileJson size={15} className={toneText.muted} aria-hidden />
                  </button>
                </li>))}</ul>}
        </section>
      </div>
    </>
  );
}
