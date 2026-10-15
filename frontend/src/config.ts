/** Central configuration. Everything environment-specific is read here. */
export const config = {
  /** Base path for API calls. In dev, Vite proxies it to FastAPI (see vite.config.ts). */
  apiBase: (import.meta.env.VITE_API_BASE as string | undefined) ?? "",
  /** Eval limits enforced by the backend (netguardx/api.py: EVAL_MAX_SITES etc.). */
  evalLimits: { maxSites: 8, maxCommands: 100, minCommands: 5, maxSizes: 4 },
  historyKey: "netguardx.history.v1",
  historyMax: 8,
};
