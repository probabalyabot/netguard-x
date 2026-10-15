import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { Decision, Severity } from "../api/types";
import { decisionLabel, decisionTone, severityTone, toneClass, toneText, type Tone } from "../lib/format";

export const Chip = ({ tone = "muted", children, className }: { tone?: Tone; children: ReactNode; className?: string }) => (
  <span className={clsx("chip", toneClass[tone], className)}>{children}</span>
);

const decisionIcon = { SAFE: CheckCircle2, REVIEW: AlertTriangle, NOT_RECOMMENDED: XCircle } as const;
export function VerdictBadge({ decision, large }: { decision: Decision; large?: boolean }) {
  const Icon = decisionIcon[decision];
  return (
    <span className={clsx("chip", toneClass[decisionTone[decision]], large && "!text-sm !px-2.5 !py-1")}>
      <Icon size={large ? 16 : 13} aria-hidden /> {decisionLabel[decision]}
    </span>
  );
}
export const SeverityBadge = ({ severity }: { severity: Severity }) => <Chip tone={severityTone[severity]}>{severity}</Chip>;

export function Spinner({ label }: { label?: string }) {
  return <span className="inline-flex items-center gap-2 text-muted text-sm" role="status"><Loader2 size={15} className="animate-spin" aria-hidden />{label}</span>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 px-5 py-8 max-w-prose">
      <p className="text-fg font-medium">{title}</p>
      {children && <div className="text-muted text-sm">{children}</div>}
      {action}
    </div>
  );
}

export function Notice({ tone = "warn", title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  const Icon = tone === "bad" ? XCircle : tone === "net" ? Info : AlertTriangle;
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={clsx("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", toneClass[tone])}>
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="text-fg min-w-0">{title && <p className="font-medium">{title}</p>}{children && <div className="text-muted [overflow-wrap:anywhere]">{children}</div>}</div>
    </div>
  );
}

export function PageHeader({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="text-muted text-sm mt-0.5 max-w-[70ch]">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded border border-line-strong bg-raised p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}
          className={clsx("px-2.5 py-1 text-sm rounded-[3px] transition-colors", o.value === value ? "bg-panel text-fg shadow-[inset_0_0_0_1px_rgb(var(--line-strong))]" : "text-muted hover:text-fg")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: string; count?: number }[] }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={t.value === value} onClick={() => onChange(t.value)}
          className={clsx("px-3 py-2 text-sm -mb-px border-b-2 transition-colors", t.value === value ? "border-net text-fg" : "border-transparent text-muted hover:text-fg")}>
          {t.label}{t.count != null && <span className="ml-1.5 text-faint">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Stat with a plain label; used sparingly where a number is the content. */
export const Stat = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone }) => (
  <div className="min-w-0">
    <dt className="text-xs text-muted">{label}</dt>
    <dd className={clsx("text-xl font-semibold tabular-nums leading-tight", tone && toneText[tone])}>{value}{sub && <span className="block text-xs font-normal text-muted mt-0.5">{sub}</span>}</dd>
  </div>
);

/** A forwarding path as inline mono text, with an optional node to flag. */
export function PathText({ path, mark, tone = "bad" }: { path: string[]; mark?: string | null; tone?: Tone }) {
  if (!path.length) return <span className="text-faint">(no path)</span>;
  return (
    <span className="mono inline-flex flex-wrap items-center gap-x-1">
      {path.map((n, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-faint" aria-hidden>›</span>}
          <span className={clsx(mark === n && i === path.length - 1 ? `${toneText[tone]} font-medium` : "text-fg")}>{n}</span>
        </span>
      ))}
    </span>
  );
}
