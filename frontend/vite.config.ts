import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the browser talks to Vite, Vite forwards /api to FastAPI.
// Override the target with VITE_API_PROXY, e.g. VITE_API_PROXY=http://127.0.0.1:9000
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    // Use VITE_BASE=/app/ when the build is served by FastAPI at /app.
    base: env.VITE_BASE || "/",
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/api": { target: env.VITE_API_PROXY || "http://127.0.0.1:8000", changeOrigin: true } },
    },
    test: { environment: "node", include: ["src/**/*.test.ts"] },
  };
});
