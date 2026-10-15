import { Link } from "react-router-dom";
import type { ChangeReport } from "../api/types";
import { decisionTone, riskTone, toneText } from "../lib/format";
import { Chip, Notice, Stat, VerdictBadge } from "./ui";

const RISK_LABELS: Record<string, string> = {
  broken_flows: "Broken flows", security_violations: "Security violations", new_exposures: "New exposures",
  routing_failures: "Routing failures", criticality: "Criticality excess",
};

export function RiskBreakdown({ report }: { report: ChangeReport }) {
  const { risk } = report;
  const inputKey = (k: string) => (k === "criticality" ? "criticality_excess" : k);
  const rows = Object.entries(risk.breakdown);
  const max = Math.max(1, ...rows.map(([, v]) => v));
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className={`text-2xl font-semibold tabular-nums ${toneText[riskTone(risk.level)]}`}>{risk.score}</span>
        <span className="text-sm text-muted">of 100 · {risk.level.toLowerCase()}</span>
      </div>
      <table className="mt-2 w-full text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="py-1 pr-3 text-muted whitespace-nowrap">{RISK_LABELS[k] ?? k}</td>
              <td className="w-full py-1"><div className="h-1.5 rounded-sm bg-raised"><div className="h-full rounded-sm bg-net/70" style={{ width: `${(v / max) * 100}%` }} /></div></td>
              <td className="mono py-1 pl-3 text-right whitespace-nowrap text-muted">{risk.inputs[inputKey(k)]} × {(risk.weights as unknown as Record<string, number>)[k]} = <span className="text-fg">{v}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-faint">Weighted sum, capped at 100. The weights are heuristic starting points, not calibrated values.</p>
    </div>
  );
}

/** The verdict and what it rests on. Shared by Overview and Change analysis. */
export function ResultSummary({ report, links = true }: { report: ChangeReport; links?: boolean }) {
  const s = report.summary;
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2"><VerdictBadge decision={report.verdict.decision} large /><Chip>{report.changes.length} change{report.changes.length === 1 ? "" : "s"}</Chip></div>
        <p className="text-lg leading-snug">{report.verdict.headline}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="Flows affected" value={`${s.affected_flows} / ${s.declared_flows_checked}`} />
        <Stat label="Broken flows" value={s.broken_flows} tone={s.broken_flows ? "bad" : undefined} />
        <Stat label="Policy violations" value={s.security_violations} tone={s.security_violations ? "bad" : undefined} />
        <Stat label="New exposures" value={s.new_exposures} tone={s.new_exposures ? "warn" : undefined} sub={report.meta.probes_enabled ? `${s.probes_checked} probes` : "probes off"} />
      </dl>
      <RiskBreakdown report={report} />
      {report.rollback && (
        <div className="rounded-md border border-line bg-raised/50 p-3 text-sm">
          <p className="font-medium">Recommended revert</p>
          <ul className="mt-1 space-y-0.5 text-muted">{report.rollback.revert.map((r) => <li key={r.index}>{r.description}</li>)}</ul>
          <p className="mt-1.5 text-muted">With that reverted the simulator returns <span className={toneText[decisionTone[report.rollback.if_reverted.decision]]}>{report.rollback.if_reverted.decision.replace("_", " ").toLowerCase()}</span> with {report.rollback.if_reverted.remaining_problems} remaining problem{report.rollback.if_reverted.remaining_problems === 1 ? "" : "s"}.</p>
          <p className="mt-1 text-xs text-faint">{report.rollback.note}</p>
        </div>
      )}
      {report.config_warnings.length > 0 && <Notice tone="warn" title="Configuration warnings introduced by this change">{<ul className="list-disc pl-4">{report.config_warnings.map((w) => <li key={w}>{w}</li>)}</ul>}</Notice>}
      <p className="text-xs text-faint">Computed in {report.meta.duration_ms} ms over {report.meta.classes} traffic classes ({report.meta.declared} declared, {report.meta.classes - report.meta.declared} probes).</p>
      {links && (
        <div className="flex flex-wrap gap-2">
          <Link to="/compare" className="btn btn-primary">Open before and after</Link>
          <Link to="/findings" className="btn">Read the findings</Link>
        </div>
      )}
    </div>
  );
}
