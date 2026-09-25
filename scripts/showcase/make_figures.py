"""Build the README figures (SVG) from local run logs.

    venv/bin/python scripts/showcase/make_figures.py

Reads logs/experiments/*/*/ (gitignored, local only) and writes docs/assets/*.svg.
Plain SVG, no plotting dependency.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs" / "experiments"
OUT = ROOT / "docs" / "assets"
FONT = "font-family='-apple-system,Segoe UI,Helvetica,Arial,sans-serif'"
PALETTE = ["#2451c9", "#e0662b", "#1f8a4c", "#8e44ad", "#c0392b", "#7f8c8d"]


def run_dir(run_id):
    return next(LOGS.glob(f"*/{run_id}"))


def load_config(d):
    return json.loads((d / "config.json").read_text())


def axes(x0, y0, w, h, n_rounds, y_label, x_step=10):
    """Frame with y grid 0..1 and x ticks; returns SVG parts."""
    s = []
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        y = y0 + h - v * h
        s.append(f"<line x1='{x0}' y1='{y:.1f}' x2='{x0 + w}' y2='{y:.1f}' stroke='#e5e8ee'/>")
        s.append(f"<text x='{x0 - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='#667' {FONT}>{v:g}</text>")
    for r in range(0, n_rounds + 1, x_step):
        x = x0 + r / n_rounds * w
        s.append(f"<text x='{x:.1f}' y='{y0 + h + 16}' text-anchor='middle' font-size='11' fill='#667' {FONT}>{r}</text>")
    s.append(f"<text x='{x0 + w / 2}' y='{y0 + h + 34}' text-anchor='middle' font-size='12' fill='#445' {FONT}>round</text>")
    s.append(f"<text transform='translate({x0 - 38},{y0 + h / 2}) rotate(-90)' text-anchor='middle' font-size='12' fill='#445' {FONT}>{y_label}</text>")
    return s


def polyline(points, color, width=2.2, dash=None, opacity=1.0):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='{width}' stroke-opacity='{opacity}' stroke-linejoin='round'{d}/>"


def svg(w, h, body):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' width='{w}' height='{h}'>"
            f"<rect width='{w}' height='{h}' fill='#ffffff'/>" + "".join(body) + "</svg>\n")


def fig_single_run(run_id, out_name):
    """Number of agents holding each label, per round, for one run."""
    d = run_dir(run_id)
    rows = list(csv.DictReader(open(d / "interactions.csv")))
    cfg = load_config(d)
    n, R = cfg["n_agents"], max(int(r["round"]) for r in rows) + 1
    counts = {}
    for r in rows:
        counts.setdefault(r["choice"], [0] * R)[int(r["round"])] += 1
    ranked = sorted(counts, key=lambda k: (-sum(counts[k]), k))
    shown = ranked[:3]
    other = [sum(counts[k][t] for k in ranked[3:]) for t in range(R)]
    W, H, x0, y0, w, h = 760, 330, 60, 48, 560, 220
    body = [f"<text x='{x0}' y='24' font-size='15' font-weight='600' fill='#1a1f36' {FONT}>"
            f"One run: {n} agents, {len(counts)} names used, one convention</text>"]
    body += axes(x0, y0, w, h, R - 1, "share of agents")
    series = [(k, counts[k]) for k in shown] + [("all other names", other)]
    for i, (name, vals) in enumerate(series):
        color = PALETTE[i] if i < 3 else "#9aa3b2"
        pts = [(x0 + t / (R - 1) * w, y0 + h - vals[t] / n * h) for t in range(R)]
        body.append(polyline(pts, color, dash="5,4" if i == 3 else None))
        ly = y0 + 10 + i * 22
        body.append(f"<line x1='{x0 + w + 18}' y1='{ly}' x2='{x0 + w + 38}' y2='{ly}' stroke='{color}' stroke-width='3'/>")
        body.append(f"<text x='{x0 + w + 44}' y='{ly + 4}' font-size='12' fill='#223' {FONT}>{name}</text>")
    body.append(f"<text x='{x0}' y='{H - 8}' font-size='11' fill='#667' {FONT}>Room A2 · {cfg['model']['model_id']} · "
                f"T = {cfg['model']['temperature']:g} · memory of last {cfg['memory_horizon_H']} interactions · run {run_id}</text>")
    (OUT / out_name).write_text(svg(W, H, body))


def modal_share_series(d):
    rows = list(csv.DictReader(open(d / "population.csv")))
    return [float(r["state_modal_share"]) for r in rows]


def fig_rooms(out_name, min_rounds=20):
    """Share of the most common name over rounds: A2 runs vs all other pilot runs."""
    a2, others = [], []
    for d in sorted(LOGS.glob("*/*")):
        if not (d / "config.json").exists() or not (d / "population.csv").exists():
            continue
        cfg = load_config(d)
        m = cfg.get("model") or {}
        if cfg.get("phase") != "pilot" or m.get("provider") == "mock" or m.get("answer_mode") != "constrained":
            continue
        room = cfg.get("cell_id")
        if room is None or room == "NS2":
            continue
        ser = modal_share_series(d)
        if len(ser) < min_rounds:
            continue
        (a2 if room == "A2" else others).append((room, ser, m.get("model_id")))
    R = 100
    W, H = 900, 330
    body = [f"<text x='60' y='24' font-size='15' font-weight='600' fill='#1a1f36' {FONT}>"
            f"Pilot: the most common name takes over only in room A2</text>"]
    panels = [("A2: reward + memory of partners", a2, "#2451c9"),
              ("All other rooms", others, "#9aa3b2")]
    for p, (title, runs, color) in enumerate(panels):
        x0, y0, w, h = 60 + p * 430, 58, 360, 210
        body.append(f"<text x='{x0}' y='48' font-size='12' font-weight='600' fill='#334' {FONT}>{title} · {len(runs)} runs</text>")
        body += axes(x0, y0, w, h, R, "share of most common name" if p == 0 else "", x_step=25)
        for room, ser, _ in runs:
            ser = ser[: R + 1]
            pts = [(x0 + t / R * w, y0 + h - v * h) for t, v in enumerate(ser)]
            body.append(polyline(pts, color, width=2.0, opacity=0.85))
        rooms = sorted({r for r, _, _ in runs})
        body.append(f"<text x='{x0}' y='{y0 + h + 50}' font-size='11' fill='#667' {FONT}>rooms: {', '.join(rooms)}</text>")
    (OUT / out_name).write_text(svg(W, H, body))
    return a2, others


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_single_run("7977e04bf159", "fig-one-run.svg")
    a2, others = fig_rooms("fig-rooms.svg")
    print(f"A2 runs: {len(a2)}; other runs: {len(others)}")
    for room, ser, model in a2 + others:
        print(f"  {room:4s} {model:18s} rounds={len(ser):3d} final share={ser[-1]:.2f}")
