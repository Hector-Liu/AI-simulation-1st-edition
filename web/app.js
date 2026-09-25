"use strict";
/* Naming Game Simulator — web UI (v2). Plain JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const isNum = (x) => x !== null && x !== undefined && x !== "" && !Number.isNaN(+x);
const fmt = (x, d = 3) => isNum(x) ? (+x).toFixed(d) : "–";
const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const COLORS = () => ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"].map(cssVar);
const ICON = {
  ok: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  warn: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4.5M12 17.2v.3"/></svg>`,
  bad: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.2v.3"/></svg>`,
};
const notice = (kind, html) => `<div class="notice ${kind}">${ICON[kind]}<div>${html}</div></div>`;
const stats = (items) => items.map(([k, v]) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const text = await r.text();
  let body; try { body = JSON.parse(text); } catch { body = text; }
  if (!r.ok) {
    const d = typeof body === "object" ? body.detail ?? body : body;
    const msg = Array.isArray(d) ? d.filter((x) => typeof x === "string").join("; ") : (typeof d === "string" ? d : JSON.stringify(d));
    throw Object.assign(new Error(msg), { status: r.status, body });
  }
  return body;
}

/* ============================== shared model helpers ============================== */
let META = null;
const claudeInfo = (id) => META?.claude_models.find((m) => m.id === id);
const isReasoningOpenAI = (id) => /^(o\d|gpt-5)/.test(id || "");
function modelOptions({ includeMock = false } = {}) {
  const c = META.claude_models.map((m) => `<option value="anthropic:${m.id}">${esc(m.name)} — $${m.price[0]} / $${m.price[1]} per 1M</option>`).join("");
  const o = (META.openai_models || []).map((id) => {
    const p = META.pricing_overrides?.[id];
    return `<option value="openai:${esc(id)}">${esc(id)}${p ? ` — $${p[0]} / $${p[1]} per 1M` : " — price not set"}</option>`;
  }).join("");
  return `<optgroup label="Claude">${c}</optgroup>` + (o ? `<optgroup label="OpenAI">${o}</optgroup>` : "") +
    (includeMock ? `<optgroup label="Offline"><option value="mock:mock">Offline mock (free, test only)</option></optgroup>` : "");
}
function defaultModelValue() {
  const d = META.default_model;
  if (META.claude_models.some((m) => m.id === d)) return `anthropic:${d}`;
  if ((META.openai_models || []).includes(d)) return `openai:${d}`;
  return `anthropic:${META.claude_models[0].id}`;
}
const splitModel = (v) => { const i = v.indexOf(":"); return { provider: v.slice(0, i), model_id: v.slice(i + 1) }; };
function tempInfo(provider, id) {
  if (provider === "mock") return { settable: false, note: "Not used by the mock model." };
  if (provider === "anthropic") {
    const m = claudeInfo(id);
    if (m && !m.temperature) return { settable: false, note: "This model does not accept a temperature; its default is used and logged." };
    return { settable: true, note: "1.0 = the model's own sampling distribution (recommended)." };
  }
  if (isReasoningOpenAI(id)) return { settable: false, note: "Reasoning models ignore temperature (flagged)." };
  return { settable: true, note: "1.0 = the model's own sampling distribution (recommended)." };
}
function modelNote(provider, id) {
  if (provider === "mock") return "Free offline test model. Its runs are marked as test data.";
  if (provider === "anthropic") { const m = claudeInfo(id); return m ? m.note : ""; }
  const p = META.pricing_overrides?.[id];
  return (isReasoningOpenAI(id) ? "Reasoning model: hidden reasoning, temperature ignored. " : "") + (p ? "" : "Set its price on the API & Models page to get a cost estimate.");
}
const roomName = (id) => META?.rooms?.[id] ? `${id} · ${META.rooms[id].title}` : (id || "ad-hoc");
const labelSetText = (id) => { const s = META?.label_sets?.[id]; return s ? `${id}${s.name && s.name !== id ? ` · ${s.name}` : ""}` : id; };

/* ============================== tabs ============================== */
$$("nav button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", (e) => { const a = e.target.closest("[data-goto]"); if (a) { e.preventDefault(); showTab(a.dataset.goto); } });
function showTab(name) {
  $$("nav button").forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("active", on); on ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"); });
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "plan") loadPlan();
  if (name === "results") loadRuns();
  if (name === "labels") loadLabelSets();
  if (name === "settings") loadSettings();
  window.scrollTo({ top: 0 });
}

/* ============================== charts ============================== */
function lineChart(el, series, { xLabel = "", yMax = null } = {}) {
  const W = 900, H = 300, L = 44, R = 14, T = 12, B = 34, colors = COLORS();
  const clean = (pts) => pts.filter((p) => isNum(p[1]) && isNum(p[0]));
  const all = series.flatMap((s) => clean(s.pts));
  if (!all.length) { el.innerHTML = `<p class="help">No data yet.</p>`; return; }
  const xs = all.map((p) => +p[0]), ys = all.map((p) => +p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1), y1 = yMax ?? Math.max(...ys, 1e-9);
  const sx = (x) => L + (x - x0) / (x1 - x0) * (W - L - R), sy = (y) => T + (1 - y / y1) * (H - T - B);
  let g = "";
  for (let i = 0; i <= 4; i++) { const y = y1 * i / 4; g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${sy(y)}" y2="${sy(y)}" opacity="${i ? .5 : 1}"/><text x="${L - 6}" y="${sy(y) + 4}" text-anchor="end">${fmt(y, 2)}</text>`; }
  const raw = (x1 - x0) / 5, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  for (let x = Math.ceil(x0 / step) * step; x <= x1 + 1e-9; x += step) g += `<text x="${sx(x)}" y="${H - B + 16}" text-anchor="middle">${+x.toFixed(6)}</text>`;
  g += `<text x="${(W + L) / 2}" y="${H - 2}" text-anchor="middle">${esc(xLabel)}</text>`;
  series.forEach((s, i) => {
    const pts = clean(s.pts); if (!pts.length) return;
    const c = s.color ?? colors[i % colors.length];
    const d = pts.map((p, j) => `${j ? "L" : "M"}${sx(+p[0]).toFixed(1)},${sy(+p[1]).toFixed(1)}`).join("");
    g += `<path d="${d}" fill="none" stroke="${c}" stroke-width="${s.width ?? 2}" ${s.dash ? 'stroke-dasharray="6 4"' : ""} opacity="${s.opacity ?? 1}"/>`;
  });
  const legend = series.filter((s) => !s.hideLegend);
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))} by ${esc(xLabel)}">${g}</svg>
    <div class="legend">${legend.map((s) => `<span><i style="background:${s.color ?? colors[series.indexOf(s) % colors.length]}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

/* ============================== STUDY PLAN ============================== */
let PLAN = null, selectedRooms = new Set(), openRoomId = null, planPhase = "pilot";
const MAIN_ROWS = [["No reward", ["B0", "B1", "B2"]], ["Reward for matching", ["A0", "A1", "A2"]]];
const MAIN_COLS = ["No memory", "Own choices only", "Own + partner choices"];

async function loadPlan() {
  PLAN = await api("/api/plan");
  const models = new Set();
  Object.values(PLAN.rooms).forEach((r) => r.runs.forEach((x) => models.add(`${x.provider}:${x.model}`)));
  const fm = $("#f-model"), cur = fm.value;
  fm.innerHTML = `<option value="">All models</option>` + [...models].sort().map((m) => `<option value="${esc(m)}">${esc(m.replace(/^anthropic:/, "").replace(/^mock:mock$/, "mock"))}</option>`).join("");
  fm.value = [...models].includes(cur) ? cur : "";
  renderPlan();
  if (openRoomId) renderRoomPanel(openRoomId);
}
$("#f-model").onchange = () => { renderPlan(); if (openRoomId) renderRoomPanel(openRoomId); };
$("#f-phase").onchange = () => { renderPlan(); if (openRoomId) renderRoomPanel(openRoomId); };
$("#plan-refresh").onclick = loadPlan;

function filteredRuns(roomId) {
  const fm = $("#f-model").value, fp = $("#f-phase").value;
  return (PLAN?.rooms[roomId]?.runs || []).filter((r) => (!fm || `${r.provider}:${r.model}` === fm) && (!fp || r.phase === fp));
}
function roomStats(runs) {
  const done = runs.filter((r) => r.status === "completed");
  const e = done.map((r) => r.entropy_final).filter(isNum).map(Number);
  const mean = e.length ? e.reduce((a, b) => a + b, 0) / e.length : null;
  const sd = e.length > 1 ? Math.sqrt(e.reduce((a, b) => a + (b - mean) ** 2, 0) / (e.length - 1)) : null;
  const byLs = {};
  done.forEach((r) => byLs[r.label_set_id] = (byLs[r.label_set_id] || 0) + 1);
  return { n: done.length, running: runs.filter((r) => r.status === "running").length, mean, sd, byLs };
}
function roomCard(id) {
  const r = META.rooms[id], s = roomStats(filteredRuns(id));
  const ls = Object.entries(s.byLs).map(([k, v]) => `${esc(k)}×${v}`).join(" · ");
  return `<div class="room-card ${selectedRooms.has(id) ? "selected" : ""} ${openRoomId === id ? "open" : ""}" data-room="${id}">
    <div class="rc-top"><span class="code">${id}</span><span class="rc-title">${esc(r.short)}</span></div>
    <div class="rc-sub">${esc(r.title)}</div>
    <div class="rc-stats"><span><b>${s.n}</b> runs${s.running ? ` · <b>${s.running}</b> running` : ""}</span>
      ${s.mean !== null ? `<span>final entropy <b>${fmt(s.mean, 2)}</b>${s.sd !== null ? ` ± ${fmt(s.sd, 2)}` : ""} <span class="mini-bar" aria-hidden="true"><i style="width:${100 * s.mean}%"></i></span></span>` : ""}</div>
    <div class="rc-stats">${ls ? `<span>${ls}</span>` : `<span>No completed runs yet</span>`}</div>
    <div class="rc-actions">
      <label class="check"><input type="checkbox" data-select="${id}" ${selectedRooms.has(id) ? "checked" : ""} aria-label="Select room ${id} for launch"> Select</label>
      <button type="button" class="btn secondary small" data-open-room="${id}">Results</button>
    </div></div>`;
}
function renderPlan() {
  let g = `<div class="axis-head"></div>` + MAIN_COLS.map((c) => `<div class="axis-head">${esc(c)}</div>`).join("");
  MAIN_ROWS.forEach(([label, ids]) => { g += `<div class="row-head">${esc(label)}</div>` + ids.map(roomCard).join(""); });
  $("#room-grid").innerHTML = g;
  $("#control-grid").innerHTML = ["B2R", "A2R", "NS2"].map(roomCard).join("");
  $("#other-runs-note").textContent = PLAN.other_runs ? `${PLAN.other_runs} other run(s) do not belong to a room (ad-hoc, calibration, null models or v1). See All runs.` : "";
  $$("[data-select]").forEach((c) => c.onchange = () => { c.checked ? selectedRooms.add(c.dataset.select) : selectedRooms.delete(c.dataset.select); renderPlan(); updateLauncher(); });
  $$("[data-open-room]").forEach((b) => b.onclick = () => openRoom(b.dataset.openRoom));
  $$(".room-card").forEach((card) => card.addEventListener("click", (e) => {
    if (e.target.closest("input, label, button")) return;
    openRoom(card.dataset.room);
  }));
}
function openRoom(id) {
  openRoomId = id; roomLsFilter = ""; renderPlan(); renderRoomPanel(id);
  $("#room-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}
let roomLsFilter = "";
async function renderRoomPanel(id) {
  const r = META.rooms[id], runs = filteredRuns(id).filter((x) => !roomLsFilter || x.label_set_id === roomLsFilter);
  const lsAll = [...new Set(filteredRuns(id).map((x) => x.label_set_id))].sort();
  const el = $("#room-panel"); el.hidden = false;
  el.innerHTML = `<div class="row between wrap"><div><h2><span class="code">${id}</span> ${esc(r.title)}</h2><p class="hint">${esc(r.tests)}</p></div>
      <button type="button" class="btn secondary small" id="room-close">Close</button></div>
    <div class="seg" id="room-ls">${["", ...lsAll].map((l) => `<button type="button" data-ls="${esc(l)}" class="${l === roomLsFilter ? "active" : ""}">${l ? esc(l) : "All label sets"}</button>`).join("")}</div>
    <div class="chart" id="room-chart"></div>
    <div id="room-winners"></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Run</th><th>Status</th><th>Label set</th><th>Seed</th><th>Agents × rounds</th><th>Model</th><th>T</th><th>Phase</th><th>Final entropy</th><th>Winner</th><th>Share</th><th>Consensus</th><th>Invalid</th></tr></thead>
      <tbody>${runs.map((x) => `<tr><td><button class="link" data-run="${x.run_id}">${x.run_id}</button></td>
        <td><span class="badge ${esc(x.status)}">${esc(x.status)}</span></td><td>${esc(x.label_set_id)}</td><td>${x.seed}</td>
        <td>${x.n_agents} × ${x.rounds_done ?? 0}/${x.n_rounds}</td><td>${esc(x.provider === "anthropic" ? (claudeInfo(x.model)?.name ?? x.model) : x.model)}</td>
        <td>${x.temperature ?? "default"}</td><td><span class="badge ${esc(x.phase)}">${esc(x.phase)}</span></td>
        <td>${fmt(x.entropy_final, 2)}</td><td>${x.winner ? `<span class="label-tag">${esc(x.winner)}</span>` : "–"}</td><td>${fmt(x.winner_share, 2)}</td>
        <td>${x.consensus === undefined || x.consensus === null ? "–" : `<span class="badge ${x.consensus ? "yes" : "no"}">${x.consensus ? "yes" : "no"}</span>`}</td>
        <td>${fmt(x.invalid_rate, 3)}</td></tr>`).join("") || `<tr><td colspan="13" class="help">No runs in this room yet (with the current filters). Select the room and launch it from the panel on the right.</td></tr>`}</tbody></table></div>`;
  $("#room-close").onclick = () => { openRoomId = null; el.hidden = true; renderPlan(); };
  $$("#room-ls button").forEach((b) => b.onclick = () => { roomLsFilter = b.dataset.ls; renderRoomPanel(id); });
  $$("#room-panel [data-run]").forEach((b) => b.onclick = () => openRunDialog(b.dataset.run));
  const curves = (await api(`/api/plan/room/${id}/curves`)).filter((c) => runs.some((x) => x.run_id === c.run_id));
  const lsColors = {}; const colors = COLORS(); lsAll.forEach((l, i) => lsColors[l] = colors[i % colors.length]);
  const seen = new Set();
  lineChart($("#room-chart"), curves.map((c) => {
    const first = !seen.has(c.label_set_id); seen.add(c.label_set_id);
    return { name: `label set ${c.label_set_id}`, color: lsColors[c.label_set_id], width: 1.6, opacity: .8, hideLegend: !first,
      pts: c.round.map((x, i) => [x, c.entropy[i]]) };
  }), { xLabel: "round (normalized entropy of the population; lower = more agreement)", yMax: 1 });
  const byLs = {};
  runs.filter((x) => x.status === "completed").forEach((x) => (byLs[x.label_set_id] ??= []).push(x));
  $("#room-winners").innerHTML = Object.keys(byLs).length ? `<h3>Winning label by run</h3>` + Object.entries(byLs).map(([ls, arr]) =>
    `<p class="help"><b>${esc(ls)}</b>: ${arr.map((a) => `seed ${a.seed} → ${a.winner ? esc(a.winner) : "–"}${a.consensus ? "" : " (no consensus)"}`).join(", ")}</p>`).join("") : "";
}

/* ---------- launcher ---------- */
function renderLabelChecks() {
  const prev = new Set($$("#ls-checks input:checked").map((c) => c.value));
  const ids = Object.keys(META.label_sets);
  if (!prev.size && ids.includes("P1")) prev.add("P1");
  $("#ls-checks").innerHTML = ids.map((id) => {
    const s = META.label_sets[id];
    return `<label class="check"><input type="checkbox" value="${esc(id)}" ${prev.has(id) ? "checked" : ""}> <span>${esc(labelSetText(id))}<br><small>${esc(s.labels.join(" "))}</small></span></label>`;
  }).join("");
  $$("#ls-checks input").forEach((c) => c.onchange = () => updateLauncher());
}
$$("#p-phase button").forEach((b) => b.onclick = () => {
  $$("#p-phase button").forEach((x) => { const on = x === b; x.classList.toggle("active", on); x.setAttribute("aria-checked", on); });
  planPhase = b.dataset.v; updateLauncher();
});
["#p-nseeds", "#p-seed0", "#p-n", "#p-rounds", "#p-H", "#p-T", "#p-model", "#p-pin", "#p-answer"].forEach((s) => $(s).addEventListener("input", () => updateLauncher()));
$$('input[name="prior_mode"]').forEach((r) => r.onchange = () => updateLauncher());

function planSpec() {
  const { provider, model_id } = splitModel($("#p-model").value);
  const ti = tempInfo(provider, model_id);
  const model = { provider, model_id, temperature: ti.settable && isNum($("#p-T").value) ? Number($("#p-T").value) : null, max_tokens_cap: 16 };
  if (provider !== "mock" && $("#p-pin").checked) model.pin_version = "auto";
  model.answer_mode = $("#p-answer").value;
  if (provider === "mock") model.mock_mode = "uniform";
  return {
    rooms: [...selectedRooms], label_sets: $$("#ls-checks input:checked").map((c) => c.value),
    n_seeds: Number($("#p-nseeds").value || 1), seed_start: Number($("#p-seed0").value || 0),
    n_agents: Number($("#p-n").value), n_rounds: Number($("#p-rounds").value || 1), H: Number($("#p-H").value || 5),
    model, phase: planPhase, prior_mode: $('input[name="prior_mode"]:checked').value,
  };
}
const updateLauncher = debounce(async () => {
  const spec = planSpec();
  $("#sel-rooms").innerHTML = spec.rooms.map((r) => `<span class="chip x">${esc(r)} <button type="button" aria-label="Remove ${r}" data-unsel="${r}">×</button></span>`).join("");
  $$("[data-unsel]").forEach((b) => b.onclick = () => { selectedRooms.delete(b.dataset.unsel); renderPlan(); updateLauncher(); });
  $("#sel-hint").hidden = spec.rooms.length > 0;
  const ti = tempInfo(spec.model.provider, spec.model.model_id);
  $("#p-T").disabled = !ti.settable; $("#p-T-note").textContent = ti.note;
  $("#p-model-note").textContent = modelNote(spec.model.provider, spec.model.model_id);
  $("#p-pin").disabled = spec.model.provider === "mock";
  const replay = spec.rooms.filter((r) => META.rooms[r].partner_source === "prior_replay");
  $("#prior-box").hidden = !replay.length;
  if (replay.length && spec.prior_mode === "derive") {
    const lines = [];
    for (const r of replay) for (const ls of spec.label_sets) {
      const src = META.rooms[r].prior_room;
      const q = new URLSearchParams({ label_set_id: ls, room: src, provider: spec.model.provider, model_id: spec.model.model_id, phase: spec.model.provider === "mock" ? "test" : spec.phase, answer_mode: spec.model.answer_mode });
      if (spec.model.temperature !== null) q.set("temperature", spec.model.temperature);
      try {
        const pr = await api(`/api/priors?${q}`);
        lines.push(pr.available ? `${r} on ${esc(ls)}: prior from ${pr.n_runs} ${src} run(s), ${pr.n_choices.toLocaleString()} choices.`
          : `${r} on ${esc(ls)}: <b>no finished ${src} run</b> with this model and temperature yet. Run ${src} first, or use a uniform prior.`);
      } catch (e) { lines.push(esc(e.message)); }
    }
    $("#prior-status").innerHTML = lines.join("<br>");
  } else $("#prior-status").textContent = "";
  const btn = $("#p-launch");
  if (!spec.rooms.length || !spec.label_sets.length) {
    $("#p-est").innerHTML = ""; $("#p-msg").innerHTML = spec.rooms.length ? notice("warn", "Choose at least one label set.") : "";
    btn.disabled = true; btn.textContent = "Launch"; $("#p-confirm-wrap").hidden = true; return;
  }
  try {
    const est = await api("/api/plan/estimate", { method: "POST", body: JSON.stringify({ spec }) });
    const cost = est.est_cost_usd === null ? "unknown" : `$${est.est_cost_usd.toFixed(est.est_cost_usd < 1 ? 4 : 2)}`;
    $("#p-est").innerHTML = stats([["Runs", est.n_runs], ["Model calls", est.calls.toLocaleString()], ["Cost (est.)", est.paid ? cost : "Free"]]);
    $("#p-msg").innerHTML = (est.model_notes || []).map((n) => notice("warn", esc(n))).join("") +
      (spec.model.provider === "mock" ? notice("warn", "Mock runs are saved as phase \"test\" and never count as study data.") : "");
    $("#p-confirm-wrap").hidden = !est.paid;
    btn.disabled = false; btn.textContent = `Launch ${est.n_runs} run${est.n_runs > 1 ? "s" : ""}`;
  } catch (e) {
    $("#p-est").innerHTML = ""; $("#p-msg").innerHTML = notice("bad", esc(e.message)); btn.disabled = true; btn.textContent = "Launch";
    $("#p-confirm-wrap").hidden = true;
  }
}, 250);
$("#p-launch").onclick = async () => {
  const btn = $("#p-launch"); btn.disabled = true;
  try {
    const r = await api("/api/plan/launch", { method: "POST", body: JSON.stringify({ spec: planSpec(), confirm_cost: $("#p-confirm").checked }) });
    $("#p-confirm").checked = false;
    $("#p-msg").innerHTML = notice("ok", `Launched ${r.run_ids.length} run(s), in a shuffled order across rooms.`);
    watchJob(r.job_id, r.run_ids[0]);
    showTab("monitor");
  } catch (e) {
    $("#p-msg").innerHTML = notice(e.status === 409 ? "warn" : "bad", e.status === 409 ? "These runs make paid API calls. Tick the cost confirmation first." : esc(e.message));
    if (e.status === 409) { $("#p-confirm-wrap").hidden = false; $("#p-confirm").focus(); }
  }
  btn.disabled = false;
};

/* ============================== CUSTOM RUN (setup) ============================== */
const EXTRA_PRESETS = [
  ["Calibration and null models", [
    ["study0", "Study 0 · prior calibration", "20 isolated agents × 20 choices, no partner. Label gate.", { pairing: "isolated", n_agents: 20, n_rounds: 20, reward: "none", memory: false }],
    ["null_major", "Null · majority_H", "No model. Each agent copies the most frequent partner label.", { reward: "none", memory: true, kind: "rule", rule: "majority_H" }],
    ["null_voter", "Null · voter(q)", "No model. Copy the last partner with probability q = 0.5.", { reward: "none", memory: true, kind: "rule", rule: "voter" }],
  ]],
  ["Quick checks", [
    ["smoke", "Smoke test (real API)", "Room B2 with 12 agents × 3 rounds and the default model. About $0.01.", { room: "B2", n_agents: 12, n_rounds: 3 }],
    ["demo", "Offline demo", "Mock model that copies partners. Free; shows what convergence looks like.", { room: "B2", kind: "mock", mock_mode: "majority", n_rounds: 100 }],
  ]],
];
function presetGroups() {
  const R = META.rooms;
  const room = (id) => [id, `${id} · ${R[id].short}`, R[id].title, { room: id }];
  return [["Main design", ["B0", "B1", "B2", "A0", "A1", "A2"].map(room)], ["Control rooms", ["B2R", "A2R", "NS2"].map(room)], ...EXTRA_PRESETS];
}
let PRESETS = {}, activePreset = null, presetSnapshot = null;
function buildPresets() {
  const groups = presetGroups();
  PRESETS = Object.fromEntries(groups.flatMap(([, items]) => items.map(([k, t, d, p]) => [k, { title: t, desc: d, p }])));
  $("#presets").innerHTML = groups.map(([g, items]) => `<div class="preset-group"><h4>${esc(g)}</h4><div class="preset-row">${
    items.map(([k, t, d]) => `<button type="button" class="preset" data-preset="${k}" aria-pressed="false"><b>${esc(t)}</b><small>${esc(d)}</small></button>`).join("")}</div></div>`).join("");
  $$(".preset").forEach((b) => b.onclick = () => applyPreset(b.dataset.preset));
}
const setRadio = (name, value) => { const el = $(`#cfg input[name="${name}"][value="${value}"]`); if (el) el.checked = true; };
const radio = (n) => $(`#cfg input[name="${n}"]:checked`)?.value;
function applyPreset(key) {
  const p = PRESETS[key].p, f = $("#cfg").elements;
  const rm = p.room ? META.rooms[p.room] : null;
  setRadio("pairing", p.pairing ?? "random_dyad");
  f.n_agents.value = p.n_agents ?? 24; f.n_rounds.value = p.n_rounds ?? 300;
  f.memory_on.checked = rm ? rm.memory !== "none" : (p.memory ?? true);
  setRadio("memory_content", rm && rm.memory !== "none" ? rm.memory : "own_and_partner");
  f.memory_horizon_H.value = 5;
  setRadio("reward_mode", rm ? rm.reward : (p.reward ?? "none"));
  f.feedback_mode.value = "choices_only"; f.show_cumulative_points.checked = true;
  setRadio("agent_kind", p.kind ?? "llm");
  if (p.rule) f.rule_policy.value = p.rule;
  f.mock_mode.value = p.mock_mode ?? "uniform"; f.mock_invalid_rate.value = 0;
  f.robustness_cell.checked = false; f.minority_on.checked = false; f.show_own_agent_id.checked = false;
  f.partner_source.value = rm?.partner_source ?? "actual"; f.framing.value = rm?.framing ?? "social";
  f.p0.value = ""; customP0Source = "";
  if (rm?.partner_source === "prior_replay") $("#advanced").open = true;
  activePreset = key; syncForm(); presetSnapshot = JSON.stringify(readConfig()); onChange();
}
function experimentId() {
  if (radio("pairing") === "isolated") return "prior_calibration";
  if (radio("agent_kind") === "rule") return "null_model";
  return radio("reward_mode") === "local_match" ? "rewarded_naming" : "no_reward_convergence";
}
function matchRoom(c) {
  if (c.pairing !== "random_dyad" || c.feedback_mode !== "choices_only" || c.show_own_agent_id || c.policy_default !== "llm" || c.committed_minority) return null;
  const mem = c.memory_mode === "none" ? "none" : c.memory_content;
  for (const [id, r] of Object.entries(META.rooms)) {
    if (r.reward === c.reward_mode && r.memory === mem && (r.partner_source ?? "actual") === c.partner_source && (r.framing ?? "social") === c.framing) return id;
  }
  return null;
}
function readConfig() {
  const f = $("#cfg").elements;
  const num = (n) => f[n].value === "" ? null : Number(f[n].value);
  const memoryOn = f.memory_on.checked, reward = radio("reward_mode"), kind = radio("agent_kind");
  const ls = META.label_sets[f.label_set_id.value];
  const cfg = {
    experiment_id: experimentId(), seed: num("seed"), label_set_id: f.label_set_id.value, label_pool_size: ls ? ls.labels.length : 10,
    n_agents: num("n_agents"), n_rounds: num("n_rounds"), pairing: radio("pairing"),
    topology_params: { n_blocks: num("n_blocks"), p_within: num("p_within"), hub_id: f.hub_id.value },
    memory_mode: memoryOn ? "own_interactions_only" : "none", memory_content: radio("memory_content"),
    memory_order: f.memory_order.value, reward_mode: reward, feedback_mode: f.feedback_mode.value,
    show_own_agent_id: f.show_own_agent_id.checked, robustness_cell: f.robustness_cell.checked,
    max_concurrency: num("max_concurrency"), notes: f.notes.value,
    phase: kind === "mock" ? "test" : f.phase.value, partner_source: f.partner_source.value, framing: f.framing.value,
  };
  if (memoryOn) cfg.memory_horizon_H = num("memory_horizon_H");
  if (reward === "local_match") cfg.payoff = { match: num("payoff_match"), mismatch: num("payoff_mismatch") };
  if (cfg.feedback_mode === "numeric_score") cfg.show_cumulative_points = f.show_cumulative_points.checked;
  if (kind === "rule") {
    cfg.policy_default = f.rule_policy.value;
    if (cfg.policy_default === "voter") cfg.policy_params = { q: num("q") };
  } else {
    cfg.policy_default = "llm";
    if (kind === "mock") cfg.model = { provider: "mock", model_id: "mock", mock_mode: f.mock_mode.value, mock_invalid_rate: num("mock_invalid_rate"), answer_mode: f.answer_mode.value };
    else {
      const { provider, model_id } = splitModel(f.model_sel.value);
      cfg.model = { provider, model_id, temperature: f.temperature.disabled ? null : num("temperature"), max_tokens_cap: num("max_tokens_cap") };
      if (f.pin.checked) cfg.model.pin_version = "auto";
      cfg.model.answer_mode = f.answer_mode.value;
    }
  }
  if (f.p0.value.trim()) { cfg.p0 = f.p0.value.split(/[,\s]+/).filter(Boolean).map(Number); cfg.p0_source = customP0Source || "explicit (custom run)"; }
  if (f.minority_on.checked) {
    cfg.committed_minority = { frac: num("minority_frac"), start_rule: f.minority_start_rule.value, start_round: num("minority_start_round"), label_rule: f.minority_label_rule.value };
    if (num("minority_end_round") !== null) cfg.committed_minority.end_round = num("minority_end_round");
  }
  cfg.cell_id = matchRoom(cfg);
  return cfg;
}
function syncForm() {
  const f = $("#cfg").elements, pairing = radio("pairing"), isolated = pairing === "isolated";
  const show = (sel, on) => $$(sel).forEach((e) => e.hidden = !on);
  if (isolated) { f.memory_on.checked = false; setRadio("reward_mode", "none"); }
  f.memory_on.disabled = isolated;
  $$('#cfg input[name="reward_mode"]').forEach((r) => r.disabled = isolated);
  const memoryOn = f.memory_on.checked, reward = radio("reward_mode"), fb = f.feedback_mode;
  fb.querySelector('[value="numeric_score"]').disabled = reward !== "local_match" || !memoryOn || f.partner_source.value === "prior_replay";
  fb.querySelector('[value="match_indicator"]').disabled = !f.robustness_cell.checked || !memoryOn || radio("memory_content") === "own_only";
  if (fb.selectedOptions[0]?.disabled || !memoryOn) fb.value = "choices_only";
  fb.disabled = !memoryOn;
  show(".show-community", pairing === "community"); show(".show-star", pairing === "star");
  $("#topo-fields").hidden = !["community", "star"].includes(pairing);
  show(".show-memory", memoryOn); show(".show-reward", reward === "local_match"); show(".show-points", fb.value === "numeric_score");
  const kind = radio("agent_kind");
  show(".show-llm", kind === "llm"); show(".show-mock", kind === "mock"); show(".show-rule", kind === "rule");
  show(".show-voter", kind === "rule" && f.rule_policy.value === "voter"); show(".show-minority", f.minority_on.checked);
  show(".show-replay", f.partner_source.value === "prior_replay");
  if (kind === "mock") f.phase.value = "test";
  f.phase.disabled = kind === "mock";
  const { provider, model_id } = splitModel(f.model_sel.value || defaultModelValue());
  const ti = tempInfo(provider, model_id);
  f.temperature.disabled = !ti.settable; $("#temp-note").textContent = ti.note;
  $("#model-note").textContent = modelNote(provider, model_id);
  const ls = META.label_sets[f.label_set_id.value];
  $("#label-chips").innerHTML = ls ? ls.labels.map((l) => `<span class="chip">${esc(l)}</span>`).join("") : "";
  const cfg = readConfig();
  $("#exp-id").textContent = cfg.experiment_id;
  $("#cell-id").textContent = cfg.cell_id ? roomName(cfg.cell_id) : "none (ad-hoc run)";
  $$(".preset").forEach((b) => { const on = b.dataset.preset === activePreset; b.classList.toggle("active", on); b.setAttribute("aria-pressed", on); });
  const modified = activePreset && presetSnapshot && JSON.stringify(cfg) !== presetSnapshot;
  $("#preset-state").textContent = activePreset ? (modified ? `Based on "${PRESETS[activePreset].title}", with your changes.` : `Using "${PRESETS[activePreset].title}".`) : "";
  $("#design-summary").textContent = describe(cfg);
}
function describe(c) {
  const parts = [], pair = { random_dyad: "random pairs", community: `${c.topology_params.n_blocks} communities`, star: `a star around hub ${c.topology_params.hub_id}`, isolated: "no partners (isolated)" }[c.pairing];
  parts.push(`${c.n_agents} agents, ${c.n_rounds} rounds, ${pair}, label set ${c.label_set_id}.`);
  if (c.memory_mode === "none") parts.push("No memory: every choice is made fresh.");
  else parts.push(`Each agent sees its last ${c.memory_horizon_H} interactions (${c.memory_content === "own_only" ? "its own choices only" : "its own and its partner's choice"}).`);
  if (c.partner_source === "prior_replay") parts.push("The partner label shown is replayed from the prior, not the partner's real choice.");
  if (c.framing === "nonsocial") parts.push("The partner's choice is presented as a \"reference label\".");
  if (c.pairing !== "isolated") parts.push(c.reward_mode === "none" ? "No reward." : `Matching earns ${c.payoff.match} points, a mismatch ${c.payoff.mismatch}.`);
  if (c.policy_default !== "llm") parts.push(`Choices by the rule-based policy ${c.policy_default}.`);
  else if (c.model.provider === "mock") parts.push("Choices by the offline mock model.");
  else parts.push(`Choices by ${claudeInfo(c.model.model_id)?.name ?? c.model.model_id}${c.model.temperature ? ` at temperature ${c.model.temperature}` : ""}.`);
  return parts.join(" ");
}
const FIELD_KEYS = ["memory_horizon_H", "n_agents", "n_rounds", "seed", "label_set_id", "feedback_mode", "match_indicator", "temperature", "max_tokens_cap",
  "p0", "payoff", "committed_minority", "show_cumulative_points", "hub_id", "p_within", "n_blocks", "policy_params", "voter", "pairing", "partner_source",
  "framing", "memory_mode", "reward_mode", "phase", "model", "max_concurrency", "policy"];
const ALIAS = { match_indicator: "feedback_mode", voter: "policy_params", policy: "policy_default" };
function fieldFor(msg) {
  for (const k of FIELD_KEYS) if (msg.includes(k)) { const el = $(`#cfg [data-field="${ALIAS[k] ?? k}"]`); if (el && !el.closest("[hidden]")) return el; }
  return null;
}
const FRIENDLY = [["memory_horizon_H", "Memory length (H)"], ["n_agents", "Number of agents"], ["n_rounds", "Rounds"], ["feedback_mode", "Memory record content"],
  ["label_set_id", "Label set"], ["max_tokens_cap", "Max output tokens"], ["show_cumulative_points", "Running point total"], ["committed_minority", "Committed minority"],
  ["partner_source=prior_replay", "Replayed partners"], ["topology_params.", ""]];
const friendly = (m) => FRIENDLY.reduce((s, [a, b]) => s.split(a).join(b), m);
let lastValidation = null, previewKey = "this_config.first_round", vSeq = 0;
const onChange = debounce(() => { syncForm(); validate(); }, 200);
async function validate() {
  const seq = ++vSeq;
  let v;
  try { v = await api("/api/validate", { method: "POST", body: JSON.stringify(readConfig()) }); } catch (e) { $("#validation").innerHTML = notice("bad", esc(e.message)); return; }
  if (seq !== vSeq) return;
  lastValidation = v;
  $$("#cfg .field-error").forEach((e) => e.remove()); $$("#cfg .invalid").forEach((e) => e.classList.remove("invalid"));
  if (!v.ok) {
    const items = v.errors.map((msg, i) => {
      const fld = fieldFor(msg);
      if (fld) { fld.classList.add("invalid"); const p = document.createElement("p"); p.className = "field-error"; p.id = `err-${i}`; p.textContent = friendly(msg); fld.appendChild(p); }
      return `<li>${fld ? `<a href="#" data-err="${i}">${esc(friendly(msg))}</a>` : esc(friendly(msg))}</li>`;
    });
    $("#validation").innerHTML = notice("bad", `<b>Fix before running:</b><ul>${items.join("")}</ul>`);
    $$("#validation a[data-err]").forEach((a) => a.onclick = (e) => { e.preventDefault(); const el = $(`#err-${a.dataset.err}`)?.closest(".field"); el?.closest("details")?.setAttribute("open", ""); el?.scrollIntoView({ behavior: "smooth", block: "center" }); el?.querySelector("input,select")?.focus(); });
    $("#estimate").innerHTML = ""; $("#model-warn").innerHTML = ""; $("#preview").textContent = ""; $("#confirm-wrap").hidden = true;
    $("#btn-run").disabled = $("#btn-dry").disabled = true; return;
  }
  $("#btn-run").disabled = $("#btn-dry").disabled = false;
  const est = v.estimate;
  $("#validation").innerHTML = notice("ok", `Settings are valid. <span class="help">config_hash ${v.config_hash.slice(0, 12)}…</span>`);
  const cost = est.est_cost_usd === null ? "unknown" : `$${est.est_cost_usd.toFixed(est.est_cost_usd < 1 ? 4 : 2)}`;
  $("#estimate").innerHTML = stats([["Model calls", est.calls.toLocaleString()], ["Input tokens (est.)", est.est_input_tokens.toLocaleString()], ["Cost (est.)", est.paid ? cost + (est.output_estimate_uncertain ? "+" : "") : "Free"]]);
  $("#model-warn").innerHTML = (est.model_notes || []).map((n) => notice("warn", esc(n))).join("");
  $("#confirm-wrap").hidden = !est.paid; if (!est.paid) $("#confirm-cost").checked = false;
  renderPreview();
}
function renderPreview() {
  if (!lastValidation?.prompts) return;
  const [a, b] = previewKey.split(".");
  $("#preview").textContent = lastValidation.prompts[a]?.[b] ?? "This condition has no other reward arm.";
}
$$("#preview-seg button").forEach((b) => b.onclick = () => { $$("#preview-seg button").forEach((x) => x.classList.toggle("active", x === b)); previewKey = b.dataset.p; renderPreview(); });
$("#btn-dry").onclick = async () => {
  const btn = $("#btn-dry"); btn.disabled = true;
  $("#run-msg").innerHTML = `<p class="help">Running the full pipeline with the mock model (up to 20 rounds, no network)…</p>`;
  try {
    const r = await api("/api/dry-run", { method: "POST", body: JSON.stringify(readConfig()) });
    $("#run-msg").innerHTML = notice(r.leakage.passed ? "ok" : "bad", `Offline test ${esc(r.status)}: ${r.rounds} rounds, ${r.leakage.prompts_checked} prompts checked, leakage check ${r.leakage.passed ? "passed" : "FAILED"}. Nothing was saved.`);
  } catch (e) { $("#run-msg").innerHTML = notice("bad", esc(e.message)); }
  btn.disabled = false;
};
$("#btn-run").onclick = async () => {
  if (lastValidation?.estimate?.paid && !$("#confirm-cost").checked) { $("#run-msg").innerHTML = notice("warn", "This run makes paid API calls. Tick the cost confirmation first."); $("#confirm-cost").focus(); return; }
  const btn = $("#btn-run"); btn.disabled = true;
  try {
    const r = await api("/api/runs", { method: "POST", body: JSON.stringify({ config: readConfig(), confirm_cost: $("#confirm-cost").checked }) });
    $("#confirm-cost").checked = false; $("#run-msg").innerHTML = notice("ok", `Started run <code>${esc(r.run_id)}</code>.`);
    watchJob(r.job_id, r.run_id); showTab("monitor");
  } catch (e) { $("#run-msg").innerHTML = notice("bad", esc(e.message)); }
  btn.disabled = false;
};

let customP0Source = "";
$("#cfg").elements.p0.addEventListener("input", () => { customP0Source = ""; $("#fill-prior-msg").textContent = ""; });
$("#fill-prior").onclick = async () => {
  const c = readConfig(), room = c.reward_mode === "local_match" ? "A0" : "B0";
  if (!c.model) { $("#fill-prior-msg").textContent = "Choose a model first."; return; }
  const q = new URLSearchParams({ label_set_id: c.label_set_id, room, provider: c.model.provider, model_id: c.model.model_id, phase: c.phase, answer_mode: c.model.answer_mode || "constrained" });
  if (c.model.temperature !== null && c.model.temperature !== undefined) q.set("temperature", c.model.temperature);
  const pr = await api(`/api/priors?${q}`);
  if (!pr.available) { $("#fill-prior-msg").textContent = `No finished ${room} run on ${c.label_set_id} with this model and temperature yet.`; return; }
  $("#cfg").elements.p0.value = pr.p0_smoothed.map((x) => x.toFixed(6)).join(", ");
  customP0Source = pr.source;
  $("#fill-prior-msg").textContent = `From ${pr.n_runs} ${room} run(s), ${pr.n_choices.toLocaleString()} choices.`;
  onChange();
};

/* ============================== MONITOR ============================== */
let currentJob = null, currentRun = null, monRows = [], monN = 1;
function watchJob(jobId, runId) {
  currentJob = jobId; currentRun = runId; monRows = [];
  $("#mon-title").textContent = `Running ${runId}`; $("#mon-sub").textContent = "Population state after each round.";
  $("#mon-batch").textContent = ""; $("#btn-cancel").disabled = false; $("#btn-open-result").hidden = true; $("#mon-log").textContent = ""; $("#live-dot").hidden = false;
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  const log = (s) => { const el = $("#mon-log"); el.textContent += s + "\n"; el.scrollTop = el.scrollHeight; };
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "run_started") {
      monN = ev.n_rounds; monRows = []; currentRun = ev.run_id;
      $("#mon-title").textContent = `Running ${ev.run_id}`;
      $("#mon-batch").textContent = `Run ${ev.index + 1} of ${ev.n_runs}${ev.cell_id ? ` · room ${ev.cell_id}` : ""} · label set ${ev.label_set_id} · seed ${ev.seed}`;
      log(`run ${ev.run_id} (${ev.cell_id ?? "ad-hoc"}, ${ev.label_set_id}, seed ${ev.seed}) started at round ${ev.start_round}`);
    } else if (ev.type === "round") {
      monRows.push(ev);
      const pct = 100 * (ev.round + 1) / monN;
      $("#mon-bar").style.width = `${pct}%`; $("#mon-progress").setAttribute("aria-valuenow", Math.round(pct));
      $("#mon-cards").innerHTML = stats([["Round", `${ev.round + 1} / ${monN}`], ["Most common label", ev.state_modal_label || "–"], ["Its share", fmt(ev.state_modal_share, 2)],
        ["Entropy (normalized)", fmt(ev.state_entropy_norm, 2)], ["Switch rate", fmt(ev.switch_rate, 2)], ["Invalid answers", fmt(ev.invalid_rate, 3)]]);
      lineChart($("#mon-chart"), [{ name: "Entropy (normalized)", pts: monRows.map((r) => [r.round, r.state_entropy_norm]) },
        { name: "Share of most common label", dash: true, pts: monRows.map((r) => [r.round, r.state_modal_share]) }], { xLabel: "round", yMax: 1 });
      if (ev.round % 10 === 0) log(`round ${ev.round}: ${ev.state_modal_label} ${fmt(ev.state_modal_share, 2)}, entropy ${fmt(ev.state_entropy_norm, 2)}`);
    } else if (ev.type === "done") {
      log(`run ${ev.run_id} → ${ev.status}${ev.error ? " — " + ev.error : ""}`);
      if (ev.summary) log(`final entropy ${fmt(ev.summary.entropy_final, 2)}; consensus ${ev.summary.consensus}; winner ${ev.summary.final_modal_label} (${fmt(ev.summary.final_modal_share, 2)})`);
    } else if (ev.type === "schedule") log(`schedule: ${ev.order.map((o) => `${o.cell_id ?? "-"}/${o.label_set_id}/s${o.seed}`).join(", ")}`);
    else if (ev.type === "error") log("ERROR " + ev.message);
    else if (ev.type === "job_done") {
      log(`job ${ev.status}`); $("#btn-cancel").disabled = true; $("#live-dot").hidden = true;
      $("#mon-title").textContent = `Finished (${ev.status})`; $("#btn-open-result").hidden = false; es.close();
    }
  };
  es.onerror = () => { log("(event stream closed)"); es.close(); $("#btn-cancel").disabled = true; $("#live-dot").hidden = true; };
}
$("#btn-cancel").onclick = async () => { if (currentJob) await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" }); };
$("#btn-open-result").onclick = () => openRunDialog(currentRun);

/* ============================== ALL RUNS ============================== */
let runs = [], selected = new Set(), cmpMetric = "state_entropy_norm", cmpAxis = "round";
const detailCache = {};
$("#btn-refresh").onclick = loadRuns;
function condition(r) {
  if (r.experiment_id === "prior_calibration") return "Study 0 calibration";
  const mem = r.memory_mode === "none" ? "no memory" : `memory H=${r.H}${r.memory_content === "own_only" ? " (own only)" : ""}`;
  return `${r.reward_mode === "none" ? "no reward" : "reward"}, ${mem}, ${String(r.pairing).replace("_dyad", "")}`;
}
async function loadRuns() {
  runs = await api("/api/runs");
  const head = `<thead><tr><th><span class="sr">Compare</span></th><th>Run</th><th>Status</th><th>Room</th><th>Phase</th><th>Condition</th><th>Label set</th><th>Seed</th><th>Rounds</th><th>Chosen by</th><th>Final entropy</th><th>Winner</th><th>Consensus</th><th>Invalid</th><th>Leakage</th></tr></thead>`;
  const body = runs.map((r) => {
    const s = r.summary || {};
    return `<tr class="${selected.has(r.run_id) ? "sel" : ""}"><td><input type="checkbox" aria-label="Compare ${r.run_id}" data-cmp="${r.run_id}" ${selected.has(r.run_id) ? "checked" : ""}></td>
      <td><button class="link" data-run="${r.run_id}">${r.run_id}</button></td><td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
      <td>${r.cell_id ? `<span class="code">${esc(r.cell_id)}</span>` : "–"}</td><td><span class="badge ${esc(r.phase)}">${esc(r.phase)}</span></td>
      <td>${esc(condition(r))}</td><td>${esc(r.label_set_id)}</td><td>${r.seed}</td><td>${r.rounds_done ?? 0} / ${r.n_rounds}</td>
      <td>${esc(r.policy === "llm" ? (r.provider === "mock" ? "mock" : (claudeInfo(r.model)?.name ?? r.model)) : r.policy)}</td>
      <td>${fmt(s.entropy_final, 2)}</td><td>${s.final_modal_label ? `<span class="label-tag">${esc(s.final_modal_label)}</span>` : "–"}</td>
      <td>${s.consensus === undefined ? "–" : `<span class="badge ${s.consensus ? "yes" : "no"}">${s.consensus ? "yes" : "no"}</span>`}</td>
      <td>${fmt(s.invalid_rate, 3)}</td><td>${r.leakage_passed === undefined || r.leakage_passed === null ? "–" : (r.leakage_passed ? '<span class="badge yes">passed</span>' : '<span class="badge no">failed</span>')}</td></tr>`;
  }).join("");
  $("#runs-table").innerHTML = head + `<tbody>${body || `<tr><td colspan="15" class="help">No runs yet.</td></tr>`}</tbody>`;
  $$("#runs-table input[data-cmp]").forEach((c) => c.onchange = () => { c.checked ? selected.add(c.dataset.cmp) : selected.delete(c.dataset.cmp); c.closest("tr").classList.toggle("sel", c.checked); renderCompare(); });
  $$("#runs-table button[data-run]").forEach((a) => a.onclick = () => openRunDialog(a.dataset.run));
  renderCompare();
}
async function runDetail(id) {
  const r = runs.find((x) => x.run_id === id);
  if (!detailCache[id] || r?.status === "running") detailCache[id] = await api(`/api/runs/${id}`);
  return detailCache[id];
}
async function renderCompare() {
  const ids = [...selected];
  $("#compare").hidden = !ids.length;
  if (!ids.length) return;
  const details = await Promise.all(ids.map(runDetail));
  lineChart($("#cmp-chart"), details.map((d, i) => ({ name: `${ids[i]} (${d.config.cell_id ?? "ad-hoc"}, seed ${d.config.seed}, ${d.config.label_set_id})`,
    pts: d.population.map((r) => [+r[cmpAxis], r[cmpMetric]]) })), { xLabel: cmpAxis === "round" ? "round" : "interactions per agent", yMax: 1 });
  const byLs = {};
  details.forEach((d) => { const s = d.summary || {}; (byLs[d.config.label_set_id] ??= []).push({ seed: d.config.seed, label: s.consensus ? s.final_modal_label : (s.fragmentation ? "fragmented" : "no consensus") }); });
  $("#winners").innerHTML = `<h3>Winning label by seed</h3>` + Object.entries(byLs).map(([ls, arr]) => {
    const counts = {}; arr.forEach((a) => counts[a.label] = (counts[a.label] || 0) + 1);
    return `<p class="help"><b>${esc(ls)}</b>: ${arr.map((a) => `seed ${a.seed} → ${esc(a.label)}`).join(", ")}</p>
      <div class="bars">${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([l, c]) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * c / arr.length}%"></div></div><span>${c} / ${arr.length}</span></div>`).join("")}</div>`;
  }).join("");
}
function segBind(sel, fn) { $$(`${sel} button`).forEach((b) => b.onclick = () => { $$(`${sel} button`).forEach((x) => x.classList.toggle("active", x === b)); fn(b); }); }
segBind("#metric-seg", (b) => { cmpMetric = b.dataset.m; renderCompare(); });
segBind("#axis-seg", (b) => { cmpAxis = b.dataset.a; renderCompare(); });

/* ============================== RUN DIALOG ============================== */
const dlg = $("#run-dialog");
$("#rd-close").onclick = () => dlg.close();
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
async function openRunDialog(runId) {
  if (!runId) return;
  const d = await api(`/api/runs/${runId}`);
  detailCache[runId] = d;
  const s = d.summary || {}, m = d.manifest || {}, c = d.config || {};
  const canResume = m.status && !["completed", "failed_leakage", "running"].includes(m.status);
  $("#rd-title").textContent = `Run ${runId}`;
  $("#rd-body").innerHTML = `<p class="hint">${c.cell_id ? `Room <span class="code">${esc(c.cell_id)}</span> ${esc(META.rooms[c.cell_id]?.title ?? "")} · ` : "Ad-hoc run · "}label set ${esc(c.label_set_id)} · seed ${c.seed} · ${c.n_agents} agents · <span class="badge ${esc(m.status)}">${esc(m.status)}</span> <span class="badge ${esc(c.phase ?? "pilot")}">${esc(c.phase ?? "pilot")}</span></p>
    <div class="row between wrap"><div class="seg" id="detail-seg" role="tablist">
      <button type="button" data-t="overview" class="active">Overview</button><button type="button" data-t="interactions">Interactions by round</button>
      <button type="button" data-t="calls">Model calls</button><button type="button" data-t="downloads">Downloads</button></div>
      ${canResume ? `<button type="button" class="btn secondary small" id="btn-resume">Resume this run</button>` : ""}</div>
    <div id="dt-overview"></div><div id="dt-interactions" hidden></div><div id="dt-calls" hidden></div><div id="dt-downloads" hidden></div>`;
  segBind("#detail-seg", (b) => { ["overview", "interactions", "calls", "downloads"].forEach((t) => $(`#dt-${t}`).hidden = t !== b.dataset.t); if (b.dataset.t === "calls") loadCalls(runId); });
  const prior = s.prior, cbt = s.consensus_by_threshold || {};
  $("#dt-overview").innerHTML = `<div class="stats">${stats([["Final entropy", fmt(s.entropy_final, 2)], ["Consensus (0.9)", s.consensus === undefined ? "–" : (s.consensus ? `yes, round ${s.T_consensus_round}` : "no")],
      ["Winning label", s.final_modal_label ?? "–"], ["Its share (last 20 %)", fmt(s.final_modal_share, 2)], ["Fragmented", s.fragmentation === undefined ? "–" : (s.fragmentation ? (s.fragmentation_stable ? "yes, stable" : "yes, not stable") : "no")],
      ["Labels used (last 20 %)", s.n_unique_last20pct ?? "–"], ["Invalid answers", fmt(s.invalid_rate)], ["Void pairings", fmt(s.void_rate)],
      ["Leakage check", d.leakage ? (d.leakage.passed ? `passed (${d.leakage.prompts_checked})` : "FAILED") : "–"], ["Model version", (m.model_versions || []).join(", ") || "–"],
      ["Temperature", c.model?.temperature ?? (c.model ? "default" : "–")], ["Answer format", c.model ? (c.model.answer_mode === "constrained" ? "pick from list" : "free text") : "–"],
      ["Prior source", c.p0_source || (c.p0 ? "explicit" : "uniform / none")]])}</div>
    ${Object.keys(cbt).length ? `<p class="help">Consensus at other thresholds: ${Object.entries(cbt).map(([t, v]) => `${t}: ${v.reached ? `round ${v.T_round}` : "not reached"}`).join(" · ")}</p>` : ""}
    ${s.flag_invalid ? notice("warn", `Invalid-answer rate above ${c.invalid_rate_flag}${s.exclude_invalid ? " and above the exclusion threshold: exclude this run" : ""}.`) : ""}
    ${(m.model_notes || []).map((n) => notice("warn", esc(n))).join("")}${m.error ? notice("bad", esc(m.error)) : ""}
    <div class="chart" id="detail-chart"></div>
    ${prior ? `<h3>Study 0 · label prior</h3><p class="help">${prior.n_valid} valid of ${prior.n_total} choices · χ² p = ${fmt(prior.chi2_p, 4)} · max/min = ${fmt(prior.max_min_ratio, 2)}</p>
      ${prior.flagged ? notice("warn", `Label bias flagged: ${esc(prior.flag_reasons.join("; "))}`) : notice("ok", "No label-bias flag.")}
      <div class="bars">${prior.labels.map((l, i) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * prior.p0[i] / Math.max(...prior.p0, 1e-9)}%"></div></div><span>${fmt(prior.p0[i], 3)}</span></div>`).join("")}</div>` : ""}
    ${s.final_label_shares ? `<h3>Label shares over the last 20 % of rounds</h3><div class="bars">${Object.entries(s.final_label_shares).sort((a, b) => b[1] - a[1]).map(([l, v]) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * v}%"></div></div><span>${fmt(v, 2)}</span></div>`).join("")}</div>` : ""}`;
  lineChart($("#detail-chart"), [{ name: "Entropy (normalized)", pts: d.population.map((r) => [+r.round, r.state_entropy_norm]) },
    { name: "Share of most common label", dash: true, pts: d.population.map((r) => [+r.round, r.state_modal_share]) },
    { name: "Switch rate", pts: d.population.map((r) => [+r.round, r.switch_rate]) }], { xLabel: "round", yMax: 1 });
  const maxRound = Math.max(0, d.population.length - 1);
  $("#dt-interactions").innerHTML = `<p class="hint">Who was paired with whom in each round, and what each chose. Analyst data; agents never see it.</p>
    <div class="round-nav"><button type="button" class="btn secondary small" id="rn-prev">Previous</button><label for="rn-num" class="sr">Round</label>
      <input id="rn-num" type="number" min="0" max="${maxRound}" value="0"><button type="button" class="btn secondary small" id="rn-next">Next</button>
      <input type="range" id="rn-range" min="0" max="${maxRound}" value="0" aria-label="Round slider"><span class="help">of ${maxRound}</span></div><div id="rn-table"></div>`;
  const go = (r) => { r = Math.max(0, Math.min(maxRound, r)); $("#rn-num").value = r; $("#rn-range").value = r; $("#rn-prev").disabled = r === 0; $("#rn-next").disabled = r === maxRound; loadRound(runId, r, d.population[r], c); };
  $("#rn-prev").onclick = () => go(+$("#rn-num").value - 1); $("#rn-next").onclick = () => go(+$("#rn-num").value + 1);
  $("#rn-num").onchange = () => go(+$("#rn-num").value); $("#rn-range").oninput = () => go(+$("#rn-range").value);
  go(0);
  $("#dt-downloads").innerHTML = `<div class="dl-grid">
    <a class="dl" href="/api/runs/${runId}/transcript.txt" download><b>Readable transcript (.txt)</b><small>Round by round: who met whom, their choices, same/different, points.</small></a>
    <a class="dl" href="/api/runs/${runId}/transcript.txt?prompts=true" download><b>Transcript with full prompts (.txt)</b><small>Adds the exact prompt each agent received and its raw answer.</small></a>
    <a class="dl" href="/api/runs/${runId}/transcript.csv" download><b>Interaction table (.csv)</b><small>One row per pair per round.</small></a>
    <a class="dl" href="/api/runs/${runId}/choice-model.csv" download><b>Choice-model data (.csv)</b><small>Long format for the choice model (H3).</small></a>
    <a class="dl" href="/api/runs/${runId}/export" download><b>All raw data (.zip)</b><small>config, manifest, calls, interactions, population, summary, leakage report.</small></a></div>`;
  const rb = $("#btn-resume");
  if (rb) rb.onclick = async () => { const r = await api(`/api/runs/${runId}/resume`, { method: "POST" }); dlg.close(); watchJob(r.job_id, runId); showTab("monitor"); };
  if (!dlg.open) dlg.showModal();
  $("#rd-close").focus();
}
async function loadRound(runId, r, pop, cfg) {
  const rows = await api(`/api/runs/${runId}/dyads?round_from=${r}&round_to=${r}`);
  const isolated = rows.length && !rows[0].agent_b;
  const replay = cfg.partner_source === "prior_replay";
  const res = (m, v) => v === "True" ? '<span class="badge no">void</span>' : (m === "True" ? '<span class="badge yes">same</span>' : '<span class="badge">different</span>');
  const tag = (l, same) => `<span class="label-tag ${same ? "same" : ""}">${esc(l)}</span>`;
  let head, body;
  if (isolated) {
    head = "<tr><th>#</th><th>Agent</th><th>Choice</th></tr>";
    body = rows.map((x) => `<tr><td>${x.dyad_id}</td><td>${esc(x.agent_a)}</td><td>${tag(x.choice_a)}</td></tr>`).join("");
  } else if (replay) {
    head = "<tr><th>Pair</th><th>Agent A</th><th>Chose</th><th>Was shown</th><th>A's outcome</th><th>Agent B</th><th>Chose</th><th>Was shown</th><th>B's outcome</th></tr>";
    body = rows.map((x) => `<tr><td>${x.dyad_id}</td><td>${esc(x.agent_a)}</td><td>${tag(x.choice_a, x.match_a === "True")}</td><td>${tag(x.shown_to_a, x.match_a === "True")}</td><td>${res(x.match_a, x.void)}</td>
      <td>${esc(x.agent_b)}</td><td>${tag(x.choice_b, x.match_b === "True")}</td><td>${tag(x.shown_to_b, x.match_b === "True")}</td><td>${res(x.match_b, x.void)}</td></tr>`).join("");
  } else {
    head = "<tr><th>Pair</th><th>Agent A</th><th>Choice A</th><th>Agent B</th><th>Choice B</th><th>Outcome</th><th>Points A / B</th></tr>";
    body = rows.map((x) => `<tr><td>${x.dyad_id}</td><td>${esc(x.agent_a)}${x.minority_a === "True" ? " (minority)" : ""}</td><td>${tag(x.choice_a, x.match === "True")}</td>
      <td>${esc(x.agent_b)}${x.minority_b === "True" ? " (minority)" : ""}</td><td>${tag(x.choice_b, x.match === "True")}</td><td>${res(x.match, x.void)}</td>
      <td>${x.points_a === "" || x.points_a === null ? "–" : `${esc(x.points_a)} / ${esc(x.points_b)}`}</td></tr>`).join("");
  }
  $("#rn-table").innerHTML = (replay ? notice("warn", "Replayed-partner run: each agent was shown a label drawn from the prior, not its partner's choice. The outcome compares an agent's choice with what it was shown.") : "") +
    `<div class="table-wrap"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>` +
    (pop ? `<p class="help">After round ${r}: most common label <span class="label-tag">${esc(pop.state_modal_label)}</span> held by ${fmt(pop.state_modal_share, 2)} of agents; normalized entropy ${fmt(pop.state_entropy_norm, 2)}.</p>` : "");
}
async function loadCalls(runId) {
  const calls = await api(`/api/runs/${runId}/calls?limit=20`);
  $("#dt-calls").innerHTML = `<p class="hint">The first 20 model calls: exact prompt and raw answer.</p>` + (calls.map((c) =>
    `<p class="help">round ${c.round} · ${esc(c.agent_id)} · attempt ${c.attempt} · ${esc(c.model_version)} · ${c.tokens_in} in / ${c.tokens_out} out tokens · ${c.latency_ms} ms · temperature ${c.effective_temperature ?? "provider default"}</p>
     <pre class="prompt">${esc(c.prompt_text)}\n\n──── raw answer ────\n${esc(c.raw_output)}   → ${c.valid ? `parsed as ${esc(c.parsed_label)}` : "INVALID"}</pre>`).join("") ||
    `<p class="help">This run made no model calls (rule-based policy).</p>`);
}

/* ============================== LABEL SETS ============================== */
let LS = [], editingId = null;
async function loadLabelSets() {
  LS = await api("/api/label-sets");
  $("#ls-list").innerHTML = LS.map((s) => `<div class="ls-item">
    <div class="ls-head"><div><b>${esc(s.id)}</b> ${s.name && s.name !== s.id ? `· ${esc(s.name)}` : ""} <span class="badge ${esc(s.kind)}">${esc(s.kind)}</span></div>
      <div class="row gap-s">
        <button type="button" class="btn secondary small" data-clone="${esc(s.id)}">Clone</button>
        ${s.kind === "custom" && !s.locked ? `<button type="button" class="btn secondary small" data-edit="${esc(s.id)}">Edit</button><button type="button" class="btn danger small" data-del="${esc(s.id)}">Delete</button>` : ""}
      </div></div>
    <div class="ls-chips">${s.labels.map((l) => `<span class="chip">${esc(l)}</span>`).join("")}</div>
    <div class="ls-meta"><span>${s.labels.length} labels</span><span>${s.runs} run(s)</span><span>${s.locked ? "locked" : "editable"}</span>
      ${s.warnings.length ? `<span class="warn">${s.warnings.length} warning(s)</span>` : ""}${s.note ? `<span>${esc(s.note)}</span>` : ""}</div></div>`).join("");
  $$("[data-clone]").forEach((b) => b.onclick = () => { const s = LS.find((x) => x.id === b.dataset.clone); editingId = null; fillEditor(`${s.name || s.id} (copy)`, s.labels, ""); });
  $$("[data-edit]").forEach((b) => b.onclick = () => { const s = LS.find((x) => x.id === b.dataset.edit); editingId = s.id; fillEditor(s.name, s.labels, s.note); });
  $$("[data-del]").forEach((b) => b.onclick = async () => {
    if (!confirm(`Delete label set ${b.dataset.del}? This cannot be undone.`)) return;
    try { await api(`/api/label-sets/${b.dataset.del}`, { method: "DELETE" }); await refreshMeta(); loadLabelSets(); } catch (e) { alert(e.message); }
  });
}
function fillEditor(name, labels, note) {
  $("#ls-ed-title").textContent = editingId ? `Edit ${editingId}` : "New label set";
  $("#ls-name").value = name; $("#ls-labels").value = labels.join("\n"); $("#ls-note").value = note || "";
  checkLabels(); $("#ls-editor").scrollIntoView({ behavior: "smooth" }); $("#ls-name").focus();
}
const parseLabels = () => $("#ls-labels").value.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
const checkLabels = debounce(async () => {
  const labels = parseLabels();
  if (!labels.length) { $("#ls-check").innerHTML = ""; $("#ls-save").disabled = true; return; }
  const r = await api("/api/label-sets/check", { method: "POST", body: JSON.stringify({ name: "x", labels }) });
  $("#ls-check").innerHTML = (r.errors.length ? notice("bad", `<b>Must fix:</b><ul>${r.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`) : notice("ok", `${labels.length} labels, no errors.`)) +
    (r.warnings.length ? notice("warn", `<b>Please review:</b><ul>${r.warnings.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`) : "");
  $("#ls-save").disabled = !!r.errors.length;
}, 250);
$("#ls-labels").addEventListener("input", checkLabels);
$("#ls-gen").onclick = async () => { const r = await api(`/api/label-sets/generate?size=${$("#ls-size").value || 10}`, { method: "POST" }); $("#ls-labels").value = r.labels.join("\n"); checkLabels(); };
$("#ls-new").onclick = () => { editingId = null; fillEditor("", [], ""); };
$("#ls-save").onclick = async () => {
  const body = JSON.stringify({ name: $("#ls-name").value || "Custom set", labels: parseLabels(), note: $("#ls-note").value });
  try {
    const r = editingId ? await api(`/api/label-sets/${editingId}`, { method: "PUT", body }) : await api("/api/label-sets", { method: "POST", body });
    editingId = null; $("#ls-ed-title").textContent = "New label set";
    await refreshMeta(); await loadLabelSets();
    $("#ls-check").innerHTML = notice("ok", `Saved as ${esc(r.id)}. It is now available in the Study Plan and Custom run.`);
  } catch (e) { $("#ls-check").innerHTML = notice("bad", esc(e.message)); }
};

/* ============================== SETTINGS ============================== */
async function loadSettings() {
  await refreshMeta();
  $("#keys").innerHTML = Object.entries(META.providers).map(([p, v]) => `<div><span class="badge ${v.has_key ? "yes" : ""}">${v.has_key ? "configured" : "not set"}</span><b>${esc(p)}</b><span class="help">${esc(v.env)}</span></div>`).join("") + `<p class="help">File: ${esc(META.env_path)}</p>`;
  const dflt = defaultModelValue();
  $("#models-table").innerHTML = `<thead><tr><th>Default</th><th>Model</th><th>Input $/1M</th><th>Output $/1M</th><th>Temperature</th><th>Hidden reasoning</th><th>Notes</th><th></th></tr></thead><tbody>${
    META.claude_models.map((m) => `<tr><td><input type="radio" name="default_model" value="anthropic:${m.id}" aria-label="Make ${esc(m.name)} the default" ${dflt === `anthropic:${m.id}` ? "checked" : ""}></td>
      <td><b>${esc(m.name)}</b><br><code>${esc(m.id)}</code></td><td>${m.price[0].toFixed(2)}</td><td>${m.price[1].toFixed(2)}</td><td>${m.temperature ? "settable" : "fixed"}</td>
      <td>${{ off_by_default: "off", disable: "switched off by engine", always: "always on (flagged)" }[m.thinking]}</td><td style="white-space:normal;min-width:240px">${esc(m.note)}</td>
      <td><button type="button" class="btn secondary small" data-test="anthropic:${m.id}">Test</button></td></tr>`).join("")}</tbody>`;
  const oa = META.openai_models || [];
  $("#oa-table").innerHTML = oa.length ? `<thead><tr><th>Default</th><th>Model</th><th>Input $/1M</th><th>Output $/1M</th><th>Notes</th><th></th></tr></thead><tbody>${oa.map((id) => {
    const p = META.pricing_overrides?.[id];
    return `<tr><td><input type="radio" name="default_model" value="openai:${esc(id)}" ${dflt === `openai:${id}` ? "checked" : ""} aria-label="Make ${esc(id)} the default"></td><td><code>${esc(id)}</code></td>
      <td>${p ? p[0] : "–"}</td><td>${p ? p[1] : "–"}</td><td>${isReasoningOpenAI(id) ? "reasoning model (flagged)" : ""}</td>
      <td><div class="row gap-s"><button type="button" class="btn secondary small" data-test="openai:${esc(id)}">Test</button><button type="button" class="btn danger small" data-oa-del="${esc(id)}">Remove</button></div></td></tr>`;
  }).join("")}</tbody>` : `<tbody><tr><td class="help">No OpenAI model added yet.</td></tr></tbody>`;
  $$('input[name="default_model"]').forEach((r) => r.onchange = async () => {
    const { provider, model_id } = splitModel(r.value);
    await api("/api/settings/default-model", { method: "POST", body: JSON.stringify({ model_id, provider }) });
    await refreshMeta(); $("#model-msg").innerHTML = notice("ok", `Default model is now ${esc(model_id)}.`);
  });
  $$("[data-test]").forEach((b) => b.onclick = async () => {
    const { provider, model_id } = splitModel(b.dataset.test);
    b.disabled = true; $("#model-msg").innerHTML = `<p class="help">Sending one short request to ${esc(model_id)}…</p>`;
    try {
      const r = await api("/api/models/test", { method: "POST", body: JSON.stringify({ model_id, provider }) });
      $("#model-msg").innerHTML = r.ok ? notice("ok", `${esc(r.model_version)} replied "${esc(r.reply)}" in ${r.latency_ms} ms (${r.tokens_in} in / ${r.tokens_out} out tokens).`) : notice("bad", esc(r.error));
    } catch (e) { $("#model-msg").innerHTML = notice("bad", esc(e.message)); }
    b.disabled = false; $("#model-msg").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  $$("[data-oa-del]").forEach((b) => b.onclick = async () => { await api(`/api/settings/openai-model/${encodeURIComponent(b.dataset.oaDel)}`, { method: "DELETE" }); loadSettings(); });
}
$("#oa-add").onclick = async () => {
  const id = $("#oa-id").value.trim();
  if (!id) return;
  const pin = $("#oa-in").value, pout = $("#oa-out").value;
  try {
    await api("/api/settings/openai-model", { method: "POST", body: JSON.stringify({ model_id: id, price_in: pin === "" ? null : Number(pin), price_out: pout === "" ? null : Number(pout) }) });
    $("#oa-id").value = $("#oa-in").value = $("#oa-out").value = ""; loadSettings();
  } catch (e) { $("#model-msg").innerHTML = notice("bad", esc(e.message)); }
};
$("#btn-key").onclick = async () => {
  try { await api("/api/settings/key", { method: "POST", body: JSON.stringify({ provider: $("#key-provider").value, key: $("#key-value").value }) }); $("#key-value").value = ""; $("#key-msg").innerHTML = notice("ok", "Key saved."); loadSettings(); }
  catch (e) { $("#key-msg").innerHTML = notice("bad", esc(e.message)); }
};

/* ============================== init ============================== */
async function refreshMeta() {
  META = await api("/api/meta");
  const f = $("#cfg").elements;
  const curLs = f.label_set_id.value;
  f.label_set_id.innerHTML = Object.keys(META.label_sets).map((k) => `<option value="${esc(k)}">${esc(labelSetText(k))}</option>`).join("");
  if (curLs && META.label_sets[curLs]) f.label_set_id.value = curLs;
  const curM = f.model_sel.value;
  f.model_sel.innerHTML = modelOptions();
  f.model_sel.value = curM && [...f.model_sel.options].some((o) => o.value === curM) ? curM : defaultModelValue();
  const curP = $("#p-model").value;
  $("#p-model").innerHTML = modelOptions({ includeMock: true });
  $("#p-model").value = curP && [...$("#p-model").options].some((o) => o.value === curP) ? curP : defaultModelValue();
  renderLabelChecks();
}
(async function init() {
  await refreshMeta();
  $("#p-T").value = META.default_temperature;
  $("#cfg").elements.temperature.value = META.default_temperature;
  buildPresets();
  $("#cfg").addEventListener("input", () => onChange());
  $("#cfg").addEventListener("change", () => onChange());
  applyPreset("B2");
  await loadPlan();
  updateLauncher();
  const jobs = await api("/api/jobs");
  const live = jobs.find((j) => j.status === "running");
  if (live) watchJob(live.job_id, live.current_run || live.run_ids[0]);
})();
