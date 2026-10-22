/** Central configuration. Everything environment-specific is read here. */
export const config = {
  /** Base path for API calls. In dev, Vite proxies it to FastAPI (see vite.config.ts). */
  apiBase: (import.meta.env.VITE_API_BASE as string | undefined) ?? "",
  /** Eval limits enforced by the backend (netguardx/api.py: EVAL_MAX_SITES etc.). */
  evalLimits: { maxSites: 12, maxCommands: 100, minCommands: 5, maxSizes: 4, maxSeeds: 5 },
  /** How often the Evaluation screen asks the API how far a background run has got. */
  evalPollMs: 700,
  historyKey: "netguardx.history.v1",
  historyMax: 8,
};
