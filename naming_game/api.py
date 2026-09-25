"""FastAPI app: JSON API under /api and the static web UI at /.

Binds to 127.0.0.1 only (see start.sh). API keys stay in the local .env.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import local_settings, runner
from .config import ExperimentConfig
from .labels import (check_label_set, delete_custom_label_set, generate_label_set, get_labels,
                     load_label_sets, save_custom_label_set)
from .llm import (CLAUDE_MODELS, ENV_PATH, PROVIDER_ENV, FatalModelError, RetryableError, api_key, load_env,
                  make_model)
from .metrics import choice_model_rows
from .priors import derive_prior
from .rooms import ROOM_ORDER, ROOMS
from .store import RunStore, find_run, list_runs, sanitize
from .transcript import dyad_rows, transcript_csv, transcript_text

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


def _label_set_usage() -> dict:
    used = {}
    for r in list_runs():
        used[r.get("label_set_id")] = used.get(r.get("label_set_id"), 0) + 1
    return used


@app.get("/api/meta")
def meta():
    load_env()
    st = local_settings.load()
    return _json({
        "label_sets": load_label_sets(include_legacy=False),
        "rooms": {k: ROOMS[k] for k in ROOM_ORDER},
        "providers": {p: {"env": env, "has_key": api_key(p) is not None} for p, env in PROVIDER_ENV.items()},
        "claude_models": CLAUDE_MODELS,
        "default_model": st.get("default_model", local_settings.DEFAULT_MODEL),
        "default_temperature": local_settings.DEFAULT_TEMPERATURE,
        "openai_models": st.get("openai_models", []),
        "pricing_overrides": st.get("pricing", {}),
        "env_path": str(ENV_PATH),
    })


class DefaultModelBody(BaseModel):
    model_id: str
    provider: str = "anthropic"


@app.post("/api/settings/default-model")
def set_default_model(body: DefaultModelBody):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-\._:]{1,80}", body.model_id):
        raise HTTPException(400, "not a valid model id")
    local_settings.update(default_model=body.model_id)
    return {"ok": True, "default_model": body.model_id}


class OpenAIModelBody(BaseModel):
    model_id: str
    price_in: float | None = None
    price_out: float | None = None


@app.post("/api/settings/openai-model")
def add_openai_model(body: OpenAIModelBody):
    """Remember an OpenAI model id (and optionally its price) for the model menus."""
    mid = body.model_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-\._:]{1,80}", mid):
        raise HTTPException(400, "not a valid model id")
    st = local_settings.load()
    models = [m for m in st.get("openai_models", []) if m != mid] + [mid]
    pricing = st.get("pricing", {})
    if body.price_in is not None and body.price_out is not None:
        pricing[mid] = [body.price_in, body.price_out]
    local_settings.update(openai_models=models, pricing=pricing)
    return {"ok": True}


@app.delete("/api/settings/openai-model/{model_id}")
def remove_openai_model(model_id: str):
    st = local_settings.load()
    local_settings.update(openai_models=[m for m in st.get("openai_models", []) if m != model_id])
    return {"ok": True}


class PriceBody(BaseModel):
    model_id: str
    price_in: float
    price_out: float


@app.post("/api/settings/pricing")
def set_price(body: PriceBody):
    st = local_settings.load()
    pricing = st.get("pricing", {})
    pricing[body.model_id] = [body.price_in, body.price_out]
    local_settings.update(pricing=pricing)
    return {"ok": True}


@app.post("/api/models/test")
def test_model(body: DefaultModelBody):
    """One tiny real call (a few tokens) to check the key and the model id."""
    from .config import ModelSpec
    try:
        m = make_model(ModelSpec(provider=body.provider, model_id=body.model_id, max_tokens_cap=8))
        res = m.complete("Reply with only the word: ready", 0)
    except (FatalModelError, RetryableError) as ex:
        return _json({"ok": False, "error": str(ex)})
    except Exception as ex:  # noqa: BLE001
        return _json({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
    return _json({"ok": True, "reply": res.text, "model_version": res.model_version,
                  "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "latency_ms": res.latency_ms,
                  "effective_temperature": res.effective_temperature})


# ------------------------------------------------------------- label sets --
@app.get("/api/label-sets")
def label_sets():
    used = _label_set_usage()
    out = []
    for sid, e in load_label_sets(include_legacy=True).items():
        chk = check_label_set(e["labels"])
        out.append({"id": sid, "name": e.get("name", sid), "kind": e["kind"], "labels": e["labels"],
                    "hash": e["hash"], "runs": used.get(sid, 0), "note": e.get("note", ""),
                    "created_at": e.get("created_at") or e.get("frozen_at"),
                    "locked": e["kind"] != "custom" or used.get(sid, 0) > 0,
                    "errors": chk["errors"], "warnings": chk["warnings"]})
    order = {"preset": 0, "custom": 1, "legacy": 2}
    out.sort(key=lambda x: (order.get(x["kind"], 3), x["id"]))
    return _json(out)


class LabelSetBody(BaseModel):
    name: str
    labels: list[str]
    note: str = ""


@app.post("/api/label-sets/check")
def label_set_check(body: LabelSetBody):
    return _json(check_label_set([x.strip() for x in body.labels if x.strip()]))


@app.post("/api/label-sets/generate")
def label_set_generate(size: int = 10, seed: int | None = None):
    import random
    if not (2 <= size <= 20):
        raise HTTPException(400, "size must be 2-20")
    taken = {x.lower() for e in load_label_sets().values() for x in e["labels"]}
    seed = seed if seed is not None else random.SystemRandom().randrange(10 ** 6)
    return {"labels": generate_label_set(seed, size, "CVCV", exclude=taken), "seed": seed}


@app.post("/api/label-sets")
def label_set_create(body: LabelSetBody):
    try:
        sid = save_custom_label_set(body.name, body.labels, note=body.note)
    except ValueError as ex:
        raise HTTPException(422, detail=[str(ex)]) from ex
    return {"ok": True, "id": sid}


@app.put("/api/label-sets/{set_id}")
def label_set_update(set_id: str, body: LabelSetBody):
    sets = load_label_sets()
    if set_id not in sets or sets[set_id]["kind"] != "custom":
        raise HTTPException(400, "only custom label sets can be edited; clone a preset instead")
    if _label_set_usage().get(set_id):
        raise HTTPException(409, "this label set has runs, so it is locked; clone it to make changes")
    try:
        save_custom_label_set(body.name, body.labels, set_id=set_id, note=body.note)
    except ValueError as ex:
        raise HTTPException(422, detail=[str(ex)]) from ex
    return {"ok": True, "id": set_id}


@app.delete("/api/label-sets/{set_id}")
def label_set_delete(set_id: str):
    sets = load_label_sets()
    if set_id not in sets or sets[set_id]["kind"] != "custom":
        raise HTTPException(400, "only custom label sets can be deleted")
    if _label_set_usage().get(set_id):
        raise HTTPException(409, "this label set has runs, so it cannot be deleted")
    delete_custom_label_set(set_id)
    return {"ok": True}


# ------------------------------------------------------------- study plan --
@app.get("/api/plan")
def plan():
    """Every run grouped by room, with the run-level numbers the Study Plan shows."""
    runs = list_runs()
    rooms = {k: {**ROOMS[k], "id": k, "runs": []} for k in ROOM_ORDER}
    other = []
    for r in runs:
        s = r.get("summary") or {}
        row = {k: r.get(k) for k in ("run_id", "status", "label_set_id", "seed", "n_agents", "n_rounds", "rounds_done",
                                     "provider", "model", "temperature", "phase", "started_at", "leakage_passed",
                                     "cell_id", "model_versions")}
        row.update(entropy_final=s.get("entropy_final"), consensus=s.get("consensus"),
                   winner=s.get("final_modal_label"), winner_share=s.get("final_modal_share"),
                   invalid_rate=s.get("invalid_rate"), T_consensus_round=s.get("T_consensus_round"))
        (rooms[r["cell_id"]]["runs"] if r.get("cell_id") in rooms else other).append(row)
    return _json({"rooms": rooms, "order": ROOM_ORDER, "other_runs": len(other)})


@app.get("/api/plan/room/{room_id}/curves")
def room_curves(room_id: str):
    out = []
    for r in list_runs():
        if r.get("cell_id") != room_id:
            continue
        pop = RunStore(r["dir"]).read_csv("population.csv")
        out.append({"run_id": r["run_id"], "label_set_id": r["label_set_id"], "seed": r["seed"],
                    "model": r.get("model"), "phase": r.get("phase"),
                    "round": [int(p["round"]) for p in pop], "entropy": [p["state_entropy_norm"] for p in pop],
                    "modal_share": [p["state_modal_share"] for p in pop]})
    return _json(out)


class PlanBody(BaseModel):
    spec: dict
    confirm_cost: bool = False


def _plan(spec: dict):
    try:
        return runner.plan_configs(spec)
    except runner.PlanError as ex:
        raise HTTPException(422, detail=[str(ex)]) from ex
    except ValidationError as ex:
        raise HTTPException(422, detail=_errors(ex)) from ex


@app.post("/api/plan/estimate")
def plan_estimate(body: PlanBody):
    cfgs, notes = _plan(body.spec)
    est = runner.estimate_matrix(cfgs)
    notes_list = [n for n in notes if "room" in n]
    return _json({**est, "priors": notes_list, "model_notes": runner.estimate(cfgs[0])["model_notes"] if cfgs else [],
                  "runs": [{"cell_id": c.cell_id, "label_set_id": c.label_set_id, "seed": c.seed} for c in cfgs]})


@app.post("/api/plan/launch")
def plan_launch(body: PlanBody):
    cfgs, notes = _plan(body.spec)
    est = runner.estimate_matrix(cfgs)
    if est["paid"] and not body.confirm_cost:
        raise HTTPException(409, detail=["These runs make paid model calls. Confirm the cost estimate first.", est])
    job = runner.jobs.start(cfgs, kind="plan")
    job.emit({"type": "schedule", "order": [{"run_id": c.run_id, "cell_id": c.cell_id, "label_set_id": c.label_set_id,
                                             "seed": c.seed} for c in cfgs], "notes": notes})
    return {"job_id": job.id, "run_ids": [c.run_id for c in cfgs], "estimate": est}


@app.get("/api/priors")
def prior(label_set_id: str, room: str, provider: str, model_id: str, temperature: float | None = None,
          phase: str = "pilot"):
    return _json(derive_prior(label_set_id, room, provider, model_id, temperature, phase))


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


@app.get("/api/runs/{run_id}/dyads")
def run_dyads(run_id: str, round_from: int | None = None, round_to: int | None = None):
    return _json(dyad_rows(_store(run_id), round_from, round_to))


@app.get("/api/runs/{run_id}/transcript.csv")
def run_transcript_csv(run_id: str):
    return Response(transcript_csv(_store(run_id)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}_transcript.csv"'})


@app.get("/api/runs/{run_id}/transcript.txt")
def run_transcript_txt(run_id: str, prompts: bool = False):
    name = f"{run_id}_transcript{'_with_prompts' if prompts else ''}.txt"
    return Response(transcript_text(_store(run_id), include_prompts=prompts), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


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

