# Running NetGuard-X with the new frontend

Exact steps, from a fresh copy of the repository to a working demo. Two programs run side by side:
the **API** (Python, port 8000) and the **UI** (Node, port 5173).

Tested with Python 3.13 and Node 22. You need **Python 3.10 or newer** and **Node 18 or newer**.

## 0. Check what you have

Open a terminal (PowerShell on Windows, Terminal on macOS/Linux) and run:

    python --version        # macOS/Linux: use python3 if "python" is not found
    node --version
    npm --version

If either is missing: install Python from python.org (tick "Add python.exe to PATH" on Windows) and Node.js (LTS) from nodejs.org, then open a new terminal.

## 1. Get the project

Clone the repository and enter it. The folder contains `netguardx/`, `frontend/`, `samples/`,
`test-scripts/` and this file.

    git clone https://github.com/probabalyabot/netguard-x.git
    cd netguard-x

Every command below is run from this folder unless it says otherwise.

## 2. Start the API (terminal 1)

macOS / Linux:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python -m netguardx serve

Windows PowerShell:

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python -m netguardx serve

(If PowerShell refuses to run the activate script, run `Set-ExecutionPolicy -Scope Process Bypass` first, then activate again.)

Success looks like `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open.

Quick check: open http://127.0.0.1:8000/api/health in a browser. It should show `{"status":"ok","version":"0.1.0"}`.

## 3. Start the UI (terminal 2)

Open a **second** terminal, go to the project folder, then:

    cd frontend
    npm install
    npm run dev

The first `npm install` takes a minute or two. Success looks like `Local: http://localhost:5173/`. Leave this terminal open too.

## 4. Open the app

Go to **http://localhost:5173** in your browser.

**Shortcut in VS Code:** once steps 1–3 have worked once (`.venv` set up and `npm install` done),
open this folder in VS Code and press **Ctrl+Shift+B** (Cmd+Shift+B on a Mac). It starts the API
and the UI in two terminal panels and opens the app when both are ready (`.vscode/tasks.json`).
Stop them with Terminal > Terminate Task.

The top-right of the page should say **API v0.1.0** with a green dot. If it says "API offline", go back to step 2.

## 5. Load the sample input

The sample files are in the `samples/` folder:

| File | What it is | How you use it |
|---|---|---|
| `samples/network.json` | The three-tier example network (9 devices, 6 policies) | **Overview → Load JSON file** |
| `samples/change-unsafe-route-via-r3.json` | A change that bypasses the firewall | paste into **Change analysis → JSON** |
| `samples/change-safe-metric.json` | A harmless metric change | paste into **Change analysis → JSON** |
| `samples/eval-summary.json` | Real output of `python -m netguardx eval` (seed 1, 30 commands, 2 and 4 sites) | **Research evaluation → Import summary.json** |

`network.json` is the same network the app opens by default, so loading it is optional. It shows how to bring in your own network: any JSON with a `nodes` list (plus `links`, `routes`, `acls`, `flows`, `policies`) works.

## 6. Walk through the demo

1. **Overview.** Click **Load JSON file** and choose `samples/network.json`. You should see 6 / 6 policies held and 4 / 7 traffic delivered. (Traffic blocked by a DENY policy counts as not delivered, which is correct.)
2. **Change analysis.** Click the **JSON** switch in the Change set panel. Select all the text in the editor, delete it, and paste the contents of `samples/change-unsafe-route-via-r3.json`. Click **Simulate change**.
   Expected result: **Not recommended**, 4 findings (2 critical, 2 high), 3 flows affected, 3 security violations.
3. **Before and after.** Both topologies appear side by side. Click a row in "Flows that behave differently" (for example `INET → DB TCP/5432`). The left map shows the path that ends at the firewall, and the right map shows the new path through R3 that skips it.
4. **Findings.** Click `FND-01`. Read "Computed evidence", then the propagation chain, then the templated explanation. Open the **Impact graph** tab.
5. **Try the safe case.** Back on Change analysis, replace the JSON with `samples/change-safe-metric.json` and simulate again. Expected: **Safe**, no flows affected, no findings.
6. **Type a change.** On Change analysis, type `block ssh from USER to DB on FWW` in the Drafter box (note the typo) and press **Draft** or Ctrl+Enter. The row explains the problem; click **Use FW instead of FWW**. Then type `send DB traffic on R1 via R3` and click **Draft and simulate**: it is the firewall bypass again, written as a sentence. A pasted block such as `R1(config)#` followed by `ip route 10.0.7.0 255.255.255.0 R3` works too. Sentences for every demo change are in `test-scripts/README.md`.
7. **Research evaluation.** Click **Import summary.json** and choose `samples/eval-summary.json` to see charts immediately. Or pick sizes (shown in devices: 14, 26, 51, 63, 76), commands, a first seed and how many seeds, and click **Run evaluation**. It runs in the background with a progress bar and a Cancel button; you can leave the screen and come back. 14 and 26 devices with 30 commands and one seed take about 10 seconds; the 50–75 device sizes take minutes. Two or more seeds add error bars; every run adds where the time goes, a scaling chart with projections, and per-command timings. Timings differ from machine to machine.

8. **A bigger network.** On Overview, pick **Enterprise network (60 devices)** in the Network list. Change analysis now lists its 15 scenarios and opens the first: the database-firewall bypass. Simulate it, then try `fail-09`, a 9-change maintenance window where only the one bad change is blamed. Sentences for all of them are in `test-scripts/README.md`.

Other ways to enter a change: the **Form** switch, the **JSON** switch, or the example scenarios list.

## 8. Stop everything

Press `Ctrl+C` in each terminal.

## Run the checks (optional)

    python -m pytest -q tests        # backend, 474 tests (run in terminal 1's environment)
    cd frontend && npm test          # frontend unit tests
    npm run build                    # type-check and production build

## Serve the UI from the API instead (one terminal)

    cd frontend
    npm install
    VITE_BASE=/app/ npm run build    # Windows PowerShell: $env:VITE_BASE="/app/"; npm run build
    cd ..
    python -m netguardx serve

Then open http://127.0.0.1:8000/app/. The original single-file UI is still at http://127.0.0.1:8000/.

## If something goes wrong

| Symptom | Fix |
|---|---|
| "API offline" banner | The API is not running. Start it (step 2) and click the red badge to retry. |
| `Address already in use` on port 8000 | Another program uses it. Run `python -m netguardx serve --port 8001`, then start the UI with `VITE_API_PROXY=http://127.0.0.1:8001 npm run dev` (PowerShell: `$env:VITE_API_PROXY="http://127.0.0.1:8001"; npm run dev`). |
| `python` or `pip` not found | Use `python3` / `pip3` (macOS/Linux), or reinstall Python with PATH enabled (Windows). |
| `No module named netguardx` | You are not in the project folder (the one containing `netguardx/`). `cd` there and retry. |
| `npm install` fails | Check `node --version` is 18 or newer. |
| "The change could not be analysed" | The message names the problem, for example a route that does not exist on that device. Fix the JSON and retry. |
| Evaluation says sizes must be 1 to 12 | The API caps a run at 12 sites (76 devices), 100 commands and 5 seeds. For larger runs use the command line, for example `python -m netguardx eval --devices 50 63 75 101 --commands 100 --seeds 1 2 3 --out eval-results/run1`, then import `eval-results/run1/summary.json`. |
| "an evaluation is already running" | One evaluation runs at a time so timings are not skewed. Wait for it, or cancel it from the Evaluation screen. |
| A sentence is "not understood" | The row gives the reason. The parser is rule-based: see the examples under the box and in `test-scripts/README.md`, or use the Form or JSON editor. |
