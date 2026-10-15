# NetGuard-X frontend

React + TypeScript + Vite single-page app for the NetGuard-X verification engine. It talks to the existing
FastAPI service; the old single-file UI at `/` is untouched.

Stack: React 18, React Router (hash routes), Tailwind CSS, Lucide icons, React Flow (`@xyflow/react`) for the
topology and impact graph, Recharts for the evaluation charts. Fonts (IBM Plex) are bundled, nothing loads from a CDN.

## Run it (development)

Two terminals, from the repository root:

    pip install -r requirements.txt
    python -m netguardx serve                 # API on http://127.0.0.1:8000

    cd frontend
    npm install
    npm run dev                               # UI on http://localhost:5173

Vite proxies `/api/*` to `http://127.0.0.1:8000`. To point at another backend:
`VITE_API_PROXY=http://host:port npm run dev`. To bypass the proxy and call an API directly, set `VITE_API_BASE`
(the API has no CORS configuration, so prefer the proxy).

## Serve it from FastAPI (production-style)

    cd frontend
    npm install
    VITE_BASE=/app/ npm run build
    cd .. && python -m netguardx serve        # UI at http://127.0.0.1:8000/app/

`netguardx/api.py` mounts `frontend/dist` at `/app` only when that folder exists.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | dev server with API proxy |
| `npm run build` | type-check, then production build to `dist/` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | unit tests (change validation, evaluation maths) |

## Screens and the API they use

| Screen | Endpoints | Notes |
|---|---|---|
| Overview | `GET /api/examples`, `POST /api/verify` | counts come from the network JSON; status from `verify` |
| Network explorer | `/api/verify`, last `/api/simulate` result | flow paths are the simulator's traces; "after" view needs an analysis |
| Change analysis | `/api/simulate`, `/api/interpret` | form and JSON editors; drafting is the backend's rule-based parser |
| Before and after | last `/api/simulate` result | per-flow hop traces, policies, changes and their inverses |
| Findings | last `/api/simulate` result | evidence (computed) is separated from the templated explanation |
| Research evaluation | `POST /api/eval/run` (added), or an imported `summary.json` | see below |

## Backend changes

Additive only; the existing endpoints, models and 114 tests are unchanged.

- `POST /api/eval/run`: runs `netguardx.eval.run_eval` and returns its result. Bounded to 1-4 sizes, each 1-8 sites,
  5-100 commands. The CLI keeps its full range, and `summary.json` from the CLI can be imported on the Evaluation screen.
- Optional static mount of `frontend/dist` at `/app`.
- Two tests for the eval endpoint in `tests/test_api.py`.

## What is deliberately not here

- The gatekeeper (execute, hold, approve, roll back) has no API, so it has no screen. Everything shown is simulation.
- Return traffic, NAT and dynamic routing are not simulated by the engine, so they are not shown.
- No benchmark numbers are bundled. The Evaluation screen shows only what a run or an imported file contains.
- "Recent analyses" are stored in this browser's localStorage (last 8), not on the server.
