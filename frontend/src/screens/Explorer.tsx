import clsx from "clsx";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Network, Trace } from "../api/types";
import { HopTable } from "../components/HopTable";
import { TopologyCanvas, TYPE_LABEL, type PathOverlay } from "../components/TopologyCanvas";
import { Chip, Empty, PageHeader, Segmented, Spinner } from "../components/ui";
import { describePolicy, describeRule } from "../lib/describe";
import { outcomeLabel, outcomeTone, statusLabel, statusTone, svc, toneText, type Tone } from "../lib/format";
import { useApp } from "../state/AppState";

function DevicePanel({ id, network, onClose }: { id: string; network: Network; onClose: () => void }) {
  const node = network.nodes.find((n) => n.id === id);
  if (!node) return null;
  const links = (network.links ?? []).filter((l) => l.source === id || l.destination === id);
  const routes = (network.routes ?? []).filter((r) => r.router === id);
  const acls = (network.acls ?? []).filter((a) => a.node === id);
  const flows = (network.flows ?? []).filter((f) => f.source === id || f.destination === id);
  const policies = (network.policies ?? []).filter((p) => p.source === id || p.destination === id || p.waypoint === id);
  const Row = ({ k, v }: { k: string; v: React.ReactNode }) => <div className="flex justify-between gap-3 py-1"><dt className="text-muted">{k}</dt><dd className="text-right">{v}</dd></div>;
  const Sec = ({ t, n, children }: { t: string; n: number; children: React.ReactNode }) => n === 0 ? null : (
    <section className="border-t border-line px-4 py-3"><h3 className="mb-1.5 text-xs font-medium text-muted">{t} <span className="text-faint">{n}</span></h3>{children}</section>);
  return (
    <div className="text-sm">
      <div className="flex items-start justify-between gap-2 px-4 py-3">
        <div><h2 className="text-base font-semibold">{node.label || node.id}</h2><p className="text-xs text-muted">{TYPE_LABEL[node.type ?? "host"]}{node.label && node.label !== node.id ? ` · ${node.id}` : ""}</p></div>
        <button className="btn btn-ghost !py-0.5 !text-xs" onClick={onClose}>Close</button>
      </div>
      <dl className="px-4 pb-3">
        <Row k="IP addresses" v={<span className="mono">{node.ip_addresses?.join(", ") || "none"}</span>} />
        <Row k="Criticality" v={`${node.criticality ?? 1} of 5`} />
        <Row k="When no ACL rule matches" v={node.default_action ?? (node.type === "firewall" ? "DENY (firewall default)" : "ALLOW (default)")} />
      </dl>
      <Sec t="Links" n={links.length}><ul className="space-y-0.5">{links.map((l, i) => <li key={i} className="flex justify-between"><span className="mono">{l.source === id ? l.destination : l.source}</span><span className="text-muted">cost {l.cost ?? 1}</span></li>)}</ul></Sec>
      <Sec t="Static routes" n={routes.length}><ul className="space-y-0.5">{routes.map((r, i) => <li key={i} className="mono">{r.destination} → {r.next_hop} <span className="text-faint">metric {r.metric ?? 10}</span></li>)}</ul></Sec>
      <Sec t="ACL rules (first match wins)" n={acls.length}><ol className="space-y-0.5">{acls.map((a, i) => <li key={i}><span className="mr-2 text-faint">{i}</span>{describeRule(a)}</li>)}</ol></Sec>
      <Sec t="Declared flows" n={flows.length}><ul className="space-y-0.5">{flows.map((f, i) => <li key={i}>{f.source} → {f.destination} <span className="text-muted">{svc(f.protocol, f.port)}</span></li>)}</ul></Sec>
      <Sec t="Policies" n={policies.length}><ul className="space-y-0.5">{policies.map((p, i) => <li key={i}><span className="mono text-muted">{p.id}</span> {describePolicy(p)}</li>)}</ul></Sec>
    </div>
  );
}

interface FlowRow { key: string; label: string; trace: Trace; badge: { text: string; tone: Tone } }

export function Explorer() {
  const { network, baseline, baselineLoading, report } = useApp();
  const [view, setView] = useState<"current" | "after">("current");
  const [selected, setSelected] = useState<string | null>(null);
  const [flowKey, setFlowKey] = useState<string | null>(null);
  const showAfter = view === "after" && !!report;

  const rows: FlowRow[] = useMemo(() => {
    if (showAfter && report) return report.flow_deltas.map((d) => ({
      key: d.key, label: `${d.source} → ${d.destination} ${svc(d.protocol, d.port)}`, trace: d.after, badge: { text: outcomeLabel[d.outcome], tone: outcomeTone[d.outcome] } }));
    return (baseline?.traces ?? []).map((t) => ({
      key: t.key, label: `${t.source} → ${t.destination} ${svc(t.protocol, t.port)}`, trace: t, badge: { text: statusLabel(t.status), tone: statusTone(t.status) } }));
  }, [showAfter, report, baseline]);

  const active = rows.find((r) => r.key === flowKey) ?? null;
  const overlays: PathOverlay[] = active ? [{ id: active.key, nodes: active.trace.path, tone: active.trace.status === "DELIVERED" ? "net" : "bad" }] : [];
  const marks: Record<string, Tone> = active && active.trace.status !== "DELIVERED" && active.trace.stop_node ? { [active.trace.stop_node]: "bad" } : {};
  const topology = showAfter && report ? report.topology : baseline?.topology;

  if (!network) return <Empty title="No network loaded">Load a network on the Overview screen.</Empty>;

  return (
    <>
      <PageHeader title="Network explorer" sub="Pan, zoom and select devices. Pick a flow to draw the path the simulator computed for it."
        right={<Segmented label="State shown" value={showAfter ? "after" : "current"} onChange={(v) => { setView(v); setFlowKey(null); }}
          options={[{ value: "current", label: "Current network" }, { value: "after", label: report ? "After proposed change" : "After change (run an analysis)" }]} />} />
      {view === "after" && !report && <p className="mb-3 text-sm text-warn">No analysis yet, so there is no after state to show. <Link to="/analyze" className="underline">Simulate a change</Link>.</p>}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className="panel overflow-hidden">
          <div className="h-[calc(100vh-250px)] min-h-[420px] bg-ink">
            {topology ? <TopologyCanvas topology={topology} view={showAfter ? "after" : "plain"} overlays={overlays} marks={marks} selected={selected} onSelect={setSelected} minimap={topology.nodes.length > 30}
                className="h-full" ariaLabel={`Topology of ${network.name ?? "the network"}`} />
              : <div className="grid h-full place-items-center">{baselineLoading ? <Spinner label="Loading topology…" /> : <span className="text-sm text-muted">No topology available.</span>}</div>}
          </div>
        </section>

        <aside className="panel flex max-h-[calc(100vh-250px)] min-h-[420px] flex-col overflow-hidden">
          {selected && <div className="max-h-[55%] shrink-0 overflow-y-auto border-b border-line"><DevicePanel id={selected} network={network} onClose={() => setSelected(null)} /></div>}
          <div className="panel-h shrink-0 !py-2.5"><h2 className="panel-title">{showAfter ? "Affected flows after the change" : "Declared flows and policy traffic"}</h2><span className="text-xs text-muted">{rows.length}</span></div>
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {rows.length === 0 && <li className="p-4 text-sm text-muted">{showAfter ? "No declared flow behaves differently after this change." : "No flows to show."}</li>}
            {rows.map((r) => (
              <li key={r.key} className="border-b border-line/60">
                <button aria-pressed={flowKey === r.key} onClick={() => setFlowKey(flowKey === r.key ? null : r.key)}
                  className={clsx("flex w-full flex-col gap-1 px-4 py-2 text-left hover:bg-raised/60", flowKey === r.key && "bg-raised shadow-[inset_2px_0_0_rgb(var(--net))]")}>
                  <span className="flex items-center justify-between gap-2 text-sm"><span>{r.label}</span><Chip tone={r.badge.tone}>{r.badge.text}</Chip></span>
                  <span className="mono text-muted">{r.trace.path.join(" › ") || "(no path)"}</span>
                </button>
                {flowKey === r.key && <div className="border-t border-line bg-ink/40"><HopTable trace={r.trace} /></div>}
              </li>
            ))}
          </ul>
          {showAfter && <p className="shrink-0 border-t border-line px-4 py-2 text-xs text-faint">Device details show the current configuration. The API returns the changed topology, not a changed configuration.</p>}
        </aside>
      </div>
      <p className="mt-3 text-xs text-faint"><span className={toneText.net}>●</span> Paths are single-direction forwarding traces. Return traffic is not simulated.</p>
    </>
  );
}
