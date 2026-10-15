import clsx from "clsx";
import type { Trace } from "../api/types";
import { statusLabel, statusTone, toneText } from "../lib/format";

/** Hop-by-hop evidence from the simulator: which ACL rule and which route decided each step. */
export function HopTable({ trace, compareTo }: { trace: Trace; compareTo?: Trace }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr><th className="th">Device</th><th className="th">ACL decision</th><th className="th">Route used</th></tr></thead>
        <tbody>
          {trace.hops.map((h, i) => {
            const o = compareTo?.hops[i];
            const changed = !!compareTo && (!o || o.route?.next_hop !== h.route?.next_hop || o.route?.prefix !== h.route?.prefix || o.acl?.rule !== h.acl?.rule || o.acl?.action !== h.acl?.action);
            return (
              <tr key={i} className={clsx(changed && "bg-warn/5")}>
                <td className={clsx("td mono", changed && "shadow-[inset_2px_0_0_rgb(var(--warn))]")}>{h.node}</td>
                <td className="td">{h.acl ? <span><span className={h.acl.action === "DENY" ? "text-bad" : "text-safe"}>{h.acl.action}</span> <span className="text-muted">{h.acl.rule}</span></span> : <span className="text-faint">no ACL</span>}</td>
                <td className="td mono">{h.route ? <>{h.route.prefix} → {h.route.next_hop} <span className="text-faint">metric {h.route.metric}, {h.route.origin}</span></> : <span className="text-faint">none</span>}</td>
              </tr>
            );
          })}
          {trace.hops.length === 0 && <tr><td className="td text-muted" colSpan={3}>No hops were taken.</td></tr>}
        </tbody>
      </table>
      <p className="px-3 py-2 text-sm"><span className={toneText[statusTone(trace.status)]}>{statusLabel(trace.status)}</span>{trace.detail && <span className="text-muted"> — {trace.detail}</span>}</p>
    </div>
  );
}
