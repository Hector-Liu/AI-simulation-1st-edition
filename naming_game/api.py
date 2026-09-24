"""FastAPI app: JSON API under /api and the static web UI at /.

Binds to 127.0.0.1 only (see start.sh). API keys stay in the local .env.
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import runner
from .config import ExperimentConfig
from .labels import get_labels, load_label_sets
from .llm import ANTHROPIC_PROFILES, ENV_PATH, PRICING, PROVIDER_ENV, api_key, load_env
from .metrics import choice_model_rows
from .store import RunStore, find_run, list_runs, sanitize

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

app = FastAPI(title="Naming Game Simulator", version="1.0")


def _json(o, status=200):
    return JSONResponse(sanitize(o), status_code=status)


def _errors(ex: ValidationError) -> list[str]:
    out = []
    for e in ex.errors():
        msg = e.get("msg", "")
        msg = msg.removeprefix("Value error, ")
        loc = ".".join(str(x) for x in e.get("loc", ()))
        out.extend(f"{loc}: {m}" if loc else m for m in msg.split("; "))
    return out


def _parse(cfg: dict) -> ExperimentConfig:
    try:
        return ExperimentConfig(**cfg)
    except ValidationError as ex:
        raise HTTPException(422, detail=_errors(ex)) from ex


# ------------------------------------------------------------- meta -------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    load_env()
    return _json({
        "label_sets": load_label_sets(),
        "providers": {p: {"env": env, "has_key": api_key(p) is not None} for p, env in PROVIDER_ENV.items()},
        "anthropic_models": list(ANTHROPIC_PROFILES),
        "pricing": PRICING,
        "env_path": str(ENV_PATH),
    })


class KeyBody(BaseModel):
    provider: str
    key: str


@app.post("/api/settings/key")
def save_key(body: KeyBody):
    env = PROVIDER_ENV.get(body.provider)
    key = body.key.strip()
    if not env:
        raise HTTPException(400, "unknown provider")
    if len(key) < 12 or not re.fullmatch(r"[A-Za-z0-9_\-\.]+", key):
        raise HTTPException(400, "this does not look like an API key")
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{env}=")] + [f"{env}={key}"]
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)
    os.environ[env] = key
    return {"ok": True, "has_key": True}


# ------------------------------------------------------------- config -----
@app.post("/api/validate")
def validate(cfg: dict):
    try:
        c = ExperimentConfig(**cfg)
    except ValidationError as ex:
        return _json({"ok": False, "errors": _errors(ex)})
    return _json({"ok": True, "errors": [], "config_hash": c.config_hash, "estimate": runner.estimate(c),
                  "prompts": runner.example_prompts(c), "resolved": c.model_dump(mode="json")})


@app.post("/api/dry-run")
def dry_run(cfg: dict):
    try:
        return _json(runner.dry_run(cfg))
    except ValidationError as ex:
        raise HTTPException(422, detail=_errors(ex)) from ex


class RunBody(BaseModel):
    config: dict
    confirm_cost: bool = False


@app.post("/api/runs")
def start_run(body: RunBody):
    c = _parse(body.config)
    est = runner.estimate(c)
    if est["paid"] and not body.confirm_cost:
        raise HTTPException(409, detail=["This run makes paid model calls. Confirm the cost estimate first.", est])
    job = runner.jobs.start([c])
    return {"job_id": job.id, "run_id": c.run_id, "estimate": est}


class MatrixBody(BaseModel):
    spec: dict
    confirm_cost: bool = False


@app.post("/api/matrix/estimate")
def matrix_estimate(body: MatrixBody):
    try:
        cfgs = runner.expand_matrix(body.spec)
    except ValidationError as ex:
        raise HTTPException(422, detail=_errors(ex)) from ex
    return _json({**runner.estimate_matrix(cfgs), "runs": [
        {"run_id": c.run_id, "seed": c.seed, "label_set_id": c.label_set_id, "config_hash": c.config_hash}
        for c in cfgs]})


@app.post("/api/matrix/run")
def matrix_run(body: MatrixBody):
    try:
        cfgs = runner.expand_matrix(body.spec)
    except ValidationError as ex:
        raise HTTPException(422, detail=_errors(ex)) from ex
    est = runner.estimate_matrix(cfgs)
    if est["paid"] and not body.confirm_cost:
        raise HTTPException(409, detail=["This matrix makes paid model calls. Confirm the cost estimate first.", est])
    job = runner.jobs.start(cfgs, kind="matrix")
    return {"job_id": job.id, "run_ids": [c.run_id for c in cfgs], "estimate": est}


# ------------------------------------------------------------- jobs -------
@app.get("/api/jobs")
def list_jobs():
    return [{"job_id": j.id, "kind": j.kind, "status": j.status, "run_ids": j.run_ids,
             "current_run": j.current_run} for j in runner.jobs.jobs.values()]


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = runner.jobs.jobs.get(job_id)
    if not job:
        raise HTTPException(404)
    job.cancel.set()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, since: int = 0):
    job = runner.jobs.jobs.get(job_id)
    if not job:
        raise HTTPException(404)

    async def gen():
        i = since
        while True:
            while i < len(job.events):
                ev = job.events[i]
                i += 1
                yield f"data: {runner.dumps(ev)}\n\n"
                if ev.get("type") == "job_done":
                    return
            await asyncio.sleep(0.25)
            yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------- results ----
def _store(run_id: str) -> RunStore:
    d = find_run(run_id)
    if d is None:
        raise HTTPException(404, "run not found")
    return RunStore(d)


@app.get("/api/runs")
def runs():
    return _json(list_runs())


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    s = _store(run_id)
    return _json({"config": s.read_json("config.json"), "manifest": s.read_json("manifest.json"),
                  "summary": s.read_json("summary.json"), "leakage": s.read_json("leakage_report.json"),
                  "population": s.read_csv("population.csv"), "events": s.read_jsonl("events.jsonl")})


@app.get("/api/runs/{run_id}/calls")
def run_calls(run_id: str, limit: int = 50):
    return _json(_store(run_id).read_jsonl("calls.jsonl", limit=limit))


@app.get("/api/runs/{run_id}/interactions")
def run_interactions(run_id: str, limit: int = 200):
    return _json(_store(run_id).read_csv("interactions.csv")[:limit])


@app.post("/api/runs/{run_id}/resume")
def resume(run_id: str):
    s = _store(run_id)
    m = s.read_json("manifest.json") or {}
    if m.get("status") == "completed":
        raise HTTPException(400, "run already completed")
    # Resuming finishes a run whose cost was already confirmed at launch.
    job = runner.jobs.start([], kind="resume", resume_dirs=[s.dir])
    job.run_ids = [run_id]
    return {"job_id": job.id, "run_id": run_id}


@app.get("/api/runs/{run_id}/export")
def export(run_id: str):
    s = _store(run_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(s.dir.iterdir()):
            if p.is_file():
                z.write(p, arcname=f"{run_id}/{p.name}")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})


@app.get("/api/runs/{run_id}/choice-model.csv")
def choice_model(run_id: str):
    s = _store(run_id)
    cfg = s.read_json("config.json")
    labels = get_labels(cfg["label_set_id"])
    p0 = cfg.get("p0") or [1 / len(labels)] * len(labels)
    rows = choice_model_rows(s.read_csv("interactions.csv"), labels, p0,
                             partner_visible=cfg.get("memory_content") == "own_and_partner")
    out = io.StringIO()
    if rows:
        w = csv.DictWriter(out, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}_choice_model.csv"'})


# ------------------------------------------------------------- static -----
@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")

