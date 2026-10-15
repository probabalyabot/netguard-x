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

## 1. Unzip and enter the project

Unzip `netguard-x-with-frontend.zip`. The folder `netguard-x-master` contains `netguardx/`, `frontend/`, `samples/` and this file.

    cd path/to/netguard-x-master

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
6. **Research evaluation.** Click **Import summary.json** and choose `samples/eval-summary.json` to see charts immediately. Or set sizes 2 and 4, commands 30, seed 1, and click **Run evaluation** (about 10 seconds). A live run adds the per-command timing chart. Timings differ from machine to machine; incremental should come out several times faster than full at these sizes.

Other ways to enter a change: the **Form** switch, the example scenarios list, or a sentence such as `remove the link between R2 and FW` followed by **Draft**.

## 7. Stop everything

Press `Ctrl+C` in each terminal.

## Run the checks (optional)

    python -m pytest -q tests        # backend, 115 tests (run in terminal 1's environment)
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
| `No module named netguardx` | You are not in the `netguard-x-master` folder. `cd` there and retry. |
| `npm install` fails | Check `node --version` is 18 or newer. |
| "The change could not be analysed" | The message names the problem, for example a route that does not exist on that device. Fix the JSON and retry. |
| Evaluation says sizes must be 1 to 8 | The API caps interactive runs. For larger runs use the command line: `python -m netguardx eval --sites 4 8 16 --commands 100 --seed 1 --out eval-results/run1`, then import `eval-results/run1/summary.json`. |
