"""FastAPI service: JSON API plus the single-page UI."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import __version__
from .changes import ChangeError
from .eval.jobs import Busy, JobStore
from .impact import AnalysisOptions, _topology, analyze, layout_topology
from .models import Change, Network
from .nlp import interpret, llm
from .report import render_markdown
from .risk import RiskWeights
from .verify import verify_network

HERE = Path(__file__).parent
EXAMPLES = HERE / "examples"
EVAL_MAX_SITES = 12  # 76 devices; larger networks belong to the CLI
FRONTEND_DIST = HERE.parent / "frontend" / "dist"

app = FastAPI(title="NetGuard-X", version=__version__,
              description="Predictive, explainable verification of network configuration changes.")


@app.on_event("startup")
def _warm_up_llm():
    """Load the local model in the background, so the first draft that needs it is not slow."""
    threading.Thread(target=llm.warm_up, daemon=True).start()


class VerifyRequest(BaseModel):
    network: Network


class SimulateRequest(BaseModel):
    network: Network
    changes: list[Change] = Field(min_length=1)
    weights: Optional[RiskWeights] = None
    probes: bool = True
    probe_limit: int = Field(2000, ge=0, le=20000)


class EvalRequest(BaseModel):
    """Bounded so a run finishes in minutes. The CLI has no such limits."""
    sites: list[int] = Field(default_factory=lambda: [2, 4], min_length=1, max_length=4)
    commands: int = Field(30, ge=5, le=100)
    seed: int = 0
    seeds: Optional[list[int]] = Field(None, min_length=1, max_length=5)
    fault_rate: float = Field(0.3, ge=0, le=1)
    probes: bool = True

    def run(self, progress=None) -> dict:
        from .eval.run import run_eval
        return run_eval(self.sites, self.commands, self.seed, self.fault_rate, probes=self.probes,
                        seeds=self.seeds, progress=progress)

    def total(self) -> int:
        from .eval.run import ARMS
        return len(self.sites) * len(self.seeds or [self.seed]) * len(ARMS) * self.commands

    @field_validator("sites")
    @classmethod
    def _sites(cls, v: list[int]) -> list[int]:
        if any(not 1 <= s <= EVAL_MAX_SITES for s in v):
            raise ValueError(f"sites must be between 1 and {EVAL_MAX_SITES} in the API (the CLI allows more)")
        return v


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    network: Network


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        msg = str(e.get("msg", "invalid")).removeprefix("Value error, ")
        msgs.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(status_code=422, content={"detail": "; ".join(msgs)})


@app.exception_handler(ChangeError)
async def _change_error(_: Request, exc: ChangeError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/examples")
def examples():
    networks = []
    for f in sorted(EXAMPLES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        networks.append({"id": f.stem, "title": d.get("name", f.stem), "network": d})
    # examples/changes/*.json are for the basic network; examples/changes/<network>/*.json for <network>
    changes = []
    for f in sorted((EXAMPLES / "changes").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        changes.append({"id": f.stem, "network": "basic", **d})
    for folder in sorted(p for p in (EXAMPLES / "changes").iterdir() if p.is_dir()):
        for f in sorted(folder.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            changes.append({"id": f"{folder.name}/{f.stem}", "network": folder.name, **d})
    return {"networks": networks, "changes": changes}


@app.post("/api/verify")
def verify(req: VerifyRequest):
    out = verify_network(req.network).model_dump(mode="json")
    out["topology"] = layout_topology(_topology(req.network, req.network))
    return out


@app.post("/api/simulate")
def simulate_change(req: SimulateRequest):
    opts = AnalysisOptions(probes=req.probes, probe_limit=req.probe_limit,
                           weights=req.weights or RiskWeights())
    report = analyze(req.network, req.changes, opts)
    out = report.model_dump(mode="json")
    layout_topology(out["topology"])
    out["report_markdown"] = render_markdown(report)
    return out


@app.post("/api/diff")
def diff(req: SimulateRequest):
    """Just the before/after comparison: per-flow deltas, topology changes and counts."""
    opts = AnalysisOptions(probes=req.probes, probe_limit=req.probe_limit,
                           weights=req.weights or RiskWeights(), rollback=False)
    r = analyze(req.network, req.changes, opts)
    return {"flow_deltas": [d.model_dump(mode="json") for d in r.flow_deltas],
            "topology": layout_topology(r.topology), "summary": r.summary}


@app.post("/api/interpret")
def interpret_text(req: InterpretRequest):
    if llm.enabled():
        return llm.interpret(req.text, req.network)
    return interpret(req.text, req.network)


@app.post("/api/eval/run")
def eval_run(req: EvalRequest):
    """Run the evaluation harness (netguardx.eval) and return its result unchanged:
    config, one entry per network size with per-arm summaries, and per-step rows."""
    return req.run()


JOBS = JobStore()


@app.post("/api/eval/jobs", status_code=202)
def eval_job_start(req: EvalRequest):
    """Start an evaluation in the background. Poll GET /api/eval/jobs/{id} for progress and the result."""
    try:
        return JOBS.start(req.total(), req.run)
    except Busy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/eval/jobs/{job_id}")
def eval_job_get(job_id: str):
    """Status (running, done, failed, cancelled), commands replayed so far, and the result when done."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no evaluation job {job_id}")
    return job


@app.post("/api/eval/jobs/{job_id}/cancel")
def eval_job_cancel(job_id: str):
    job = JOBS.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no evaluation job {job_id}")
    return job


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


# Optional: serve the built React app (frontend/dist) at /app when it exists.
if FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/app", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
