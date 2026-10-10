"""FastAPI service: JSON API plus the single-page UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .changes import ChangeError
from .impact import AnalysisOptions, _topology, analyze, layout_topology
from .models import Change, Network
from .nlp import interpret
from .report import render_markdown
from .risk import RiskWeights
from .verify import verify_network

HERE = Path(__file__).parent
EXAMPLES = HERE / "examples"

app = FastAPI(title="NetGuard-X", version=__version__,
              description="Predictive, explainable verification of network configuration changes.")


class VerifyRequest(BaseModel):
    network: Network


class SimulateRequest(BaseModel):
    network: Network
    changes: list[Change] = Field(min_length=1)
    weights: Optional[RiskWeights] = None
    probes: bool = True
    probe_limit: int = Field(2000, ge=0, le=20000)


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
        d = json.loads(f.read_text())
        networks.append({"id": f.stem, "title": d.get("name", f.stem), "network": d})
    changes = []
    for f in sorted((EXAMPLES / "changes").glob("*.json")):
        d = json.loads(f.read_text())
        changes.append({"id": f.stem, "network": "basic", **d})
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
    return interpret(req.text, req.network)


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")
