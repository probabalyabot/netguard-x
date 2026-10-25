import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type {
  Change, ChangeReport, ExampleChange, ExamplesResponse, Network, RiskWeights, VerifyResponse,
} from "../api/types";
import { config } from "../config";
import { errMsg } from "../lib/format";
import { validateNetwork } from "../lib/validate";

export const DEFAULT_WEIGHTS: RiskWeights = { broken_flows: 20, security_violations: 30, new_exposures: 6, routing_failures: 10, criticality: 5 };

export interface HistoryEntry { id: string; at: string; network: string; title: string; verdict: string; report: ChangeReport }
export type Health = { state: "checking" } | { state: "online"; version: string } | { state: "offline"; message: string };

/** Which finding / flow the user is looking at; shared so Findings and Compare stay in step. */
export interface Focus { findingId: string | null; flowKey: string | null }

interface Ctx {
  health: Health; recheckHealth: () => void;
  examples: ExamplesResponse | null; examplesError: string | null;
  network: Network | null; networkLabel: string; baseline: VerifyResponse | null; baselineError: string | null; baselineLoading: boolean;
  loadNetwork: (n: unknown, label: string) => Promise<boolean>;
  changes: Change[]; setChanges: (c: Change[]) => void; scenario: ExampleChange | null; setScenario: (s: ExampleChange | null) => void;
  weights: RiskWeights; setWeights: (w: RiskWeights) => void; probes: boolean; setProbes: (b: boolean) => void;
  report: ChangeReport | null; reportError: string | null; analyzing: boolean; stale: boolean; reportTitle: string;
  analyze: (title?: string, changesOverride?: Change[]) => Promise<boolean>; openHistory: (id: string) => void; history: HistoryEntry[]; clearHistory: () => void;
  focus: Focus; setFocus: (f: Partial<Focus>) => void;
}
const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => { const c = useContext(AppCtx); if (!c) throw new Error("useApp outside provider"); return c; };

function loadHistory(): HistoryEntry[] {
  try { const raw = localStorage.getItem(config.historyKey); return raw ? (JSON.parse(raw) as HistoryEntry[]) : []; } catch { return []; }
}
function saveHistory(h: HistoryEntry[]) {
  // Reports are large; if the quota is hit, keep fewer rather than failing.
  for (let keep = h.length; keep >= 0; keep--) {
    try { localStorage.setItem(config.historyKey, JSON.stringify(h.slice(0, keep))); return; } catch { /* try fewer */ }
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health>({ state: "checking" });
  const [examples, setExamples] = useState<ExamplesResponse | null>(null);
  const [examplesError, setExamplesError] = useState<string | null>(null);
  const [network, setNetwork] = useState<Network | null>(null);
  const [networkLabel, setNetworkLabel] = useState("");
  const [baseline, setBaseline] = useState<VerifyResponse | null>(null);
  const [baselineError, setBaselineError] = useState<string | null>(null);
  const [baselineLoading, setBaselineLoading] = useState(false);
  const [changes, setChangesRaw] = useState<Change[]>([]);
  const [scenario, setScenario] = useState<ExampleChange | null>(null);
  const [weights, setWeights] = useState<RiskWeights>(DEFAULT_WEIGHTS);
  const [probes, setProbes] = useState(true);
  const [report, setReport] = useState<ChangeReport | null>(null);
  const [reportInput, setReportInput] = useState("");
  const [reportTitle, setReportTitle] = useState("");
  const [reportError, setReportError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory);
  const [focus, setFocusRaw] = useState<Focus>({ findingId: null, flowKey: null });
  const loadSeq = useRef(0);

  const recheckHealth = useCallback(() => {
    setHealth({ state: "checking" });
    api.health().then((h) => setHealth({ state: "online", version: h.version }))
      .catch((e) => setHealth({ state: "offline", message: errMsg(e) }));
  }, []);

  const loadNetwork = useCallback(async (n: unknown, label: string) => {
    const problem = validateNetwork(n);
    if (problem) { setBaselineError(problem); return false; }
    const net = n as Network;
    const seq = ++loadSeq.current;
    setNetwork(net); setNetworkLabel(label); setBaseline(null); setBaselineError(null); setBaselineLoading(true);
    setReport(null); setReportError(null); setFocusRaw({ findingId: null, flowKey: null });
    try {
      const b = await api.verify(net);
      if (seq === loadSeq.current) setBaseline(b);
      return true;
    } catch (e) {
      if (seq === loadSeq.current) setBaselineError(errMsg(e));
      return false;
    } finally { if (seq === loadSeq.current) setBaselineLoading(false); }
  }, []);

  // Boot: health check, then load examples and open the first network and scenario.
  const booted = useRef(false);
  useEffect(() => {
    recheckHealth();
    if (booted.current) return;
    booted.current = true;
    api.examples().then(async (ex) => {
      setExamples(ex);
      const first = ex.networks[0];
      if (first) {
        await loadNetwork(first.network, first.title);
        const sc = ex.changes.find((c) => c.network === first.id) ?? ex.changes[0];
        if (sc) { setScenario(sc); setChangesRaw(sc.changes); }
      }
    }).catch((e) => setExamplesError(errMsg(e)));
  }, [loadNetwork, recheckHealth]);

  const setChanges = useCallback((c: Change[]) => setChangesRaw(c), []);
  const inputKey = useMemo(() => JSON.stringify([networkLabel, changes, weights, probes]), [networkLabel, changes, weights, probes]);

  /** Simulate the change set. `changesOverride` is for callers that have just set the changes
   *  and cannot wait for the state update to re-render (the Drafter's "Draft and simulate"). */
  const analyze = useCallback(async (title?: string, changesOverride?: Change[]) => {
    const cs = changesOverride ?? changes;
    if (!network || cs.length === 0) return false;
    setAnalyzing(true); setReportError(null);
    try {
      const r = await api.simulate(network, cs, { weights, probes, probe_limit: 2000 });
      const t = title ?? scenario?.title ?? "Custom change";
      setReport(r); setReportInput(changesOverride ? JSON.stringify([networkLabel, cs, weights, probes]) : inputKey); setReportTitle(t);
      setFocusRaw({ findingId: r.findings[0]?.id ?? null, flowKey: null });
      setHistory((h) => {
        const next = [{ id: `${Date.now()}`, at: new Date().toISOString(), network: networkLabel, title: t, verdict: r.verdict.decision, report: r }, ...h].slice(0, config.historyMax);
        saveHistory(next); return next;
      });
      return true;
    } catch (e) {
      setReportError(e instanceof ApiError ? e.message : errMsg(e));
      return false;
    } finally { setAnalyzing(false); }
  }, [network, changes, weights, probes, scenario, inputKey, networkLabel]);

  const openHistory = useCallback((id: string) => {
    const h = history.find((x) => x.id === id);
    if (!h) return;
    setReport(h.report); setReportTitle(h.title); setReportInput("history"); setReportError(null);
    setFocusRaw({ findingId: h.report.findings[0]?.id ?? null, flowKey: null });
  }, [history]);

  const clearHistory = useCallback(() => { setHistory([]); saveHistory([]); }, []);
  const setFocus = useCallback((f: Partial<Focus>) => setFocusRaw((p) => ({ ...p, ...f })), []);
  const stale = report !== null && reportInput !== "history" && reportInput !== inputKey;

  const value: Ctx = {
    health, recheckHealth, examples, examplesError, network, networkLabel, baseline, baselineError, baselineLoading, loadNetwork,
    changes, setChanges, scenario, setScenario, weights, setWeights, probes, setProbes,
    report, reportError, analyzing, stale, reportTitle, analyze, openHistory, history, clearHistory, focus, setFocus,
  };
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}
