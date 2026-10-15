import { config } from "../config";
import type {
  ChangeReport, Change, EvalRequest, EvalResult, ExamplesResponse, InterpretResponse, Network, RiskWeights, VerifyResponse,
} from "./types";

/** An error with a message that is safe to show as-is. `kind` tells the UI how to react. */
export class ApiError extends Error {
  constructor(message: string, public kind: "offline" | "validation" | "server", public status?: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(config.apiBase + path, { ...init, signal, headers: { "Content-Type": "application/json" } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Cannot reach the NetGuard-X API. Start it with: python -m netguardx serve.", "offline");
  }
  const text = await res.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
  if (!res.ok) {
    // A dev proxy with no backend behind it answers 5xx with an empty or HTML body.
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") throw new ApiError(detail, res.status === 422 ? "validation" : "server", res.status);
    if (res.status >= 500 && !body) throw new ApiError("Cannot reach the NetGuard-X API. Start it with: python -m netguardx serve.", "offline", res.status);
    throw new ApiError(`The API returned HTTP ${res.status}.`, "server", res.status);
  }
  return body as T;
}

const post = <T,>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) }, signal);

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string; version: string }>("/api/health", undefined, signal),
  examples: () => request<ExamplesResponse>("/api/examples"),
  verify: (network: Network) => post<VerifyResponse>("/api/verify", { network }),
  simulate: (network: Network, changes: Change[], opts: { weights?: RiskWeights; probes: boolean; probe_limit: number }) =>
    post<ChangeReport>("/api/simulate", { network, changes, ...opts }),
  interpret: (text: string, network: Network) => post<InterpretResponse>("/api/interpret", { text, network }),
  evalRun: (req: EvalRequest, signal?: AbortSignal) => post<EvalResult>("/api/eval/run", req, signal),
};
