"use strict";
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

let META = null;
const modelInfo = (id) => META?.claude_models.find((m) => m.id === id);

/* ============================== tabs ============================== */
$$("nav button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
function showTab(name) {
  $$("nav button").forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("active", on); on ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"); });
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "results") loadRuns();
  if (name === "settings") loadSettings();
  window.scrollTo({ top: 0 });
}

/* ============================== presets ============================== */
const PRESET_GROUPS = [
  ["Main experiments", [
    ["study_b_key", "Study B · key cell", "No reward, with memory. Does a convention emerge without any incentive?",
      { reward: "none", memory: true, content: "own_and_partner" }],
    ["study_b_base", "Study B · prior baseline", "No reward, no memory. What the shared prior alone produces.",
      { reward: "none", memory: false }],
    ["study_a", "Study A · rewarded", "Points for matching, memory H = 5, random pairs.",
      { reward: "local_match", memory: true, feedback: "numeric_score" }],
    ["focal", "Focal-point control", "Points for matching, no memory. Coordination from the prior alone.",
      { reward: "local_match", memory: false }],
  ]],
  ["Controls and topology", [
    ["b1", "B+1 · own choices only", "No reward; memory shows only the agent's own past choices.",
      { reward: "none", memory: true, content: "own_only" }],
    ["b2", "B+2 · own choices + points", "Reward; memory shows own choices and points, not the partner's label.",
      { reward: "local_match", memory: true, content: "own_only", feedback: "numeric_score" }],
    ["star", "Study A · star", "Rewarded, one hub meets one leaf per round.",
      { reward: "local_match", memory: true, feedback: "numeric_score", pairing: "star" }],
    ["community", "Study A · communities", "Rewarded, two blocks, 90 % of pairs within a block.",
      { reward: "local_match", memory: true, feedback: "numeric_score", pairing: "community" }],
  ]],
  ["Calibration and null models", [
    ["study0", "Study 0 · prior calibration", "20 isolated agents × 20 choices, no partner. Measures label bias.",
      { pairing: "isolated", n_agents: 20, n_rounds: 20, reward: "none", memory: false }],
    ["null_major", "Null · majority_H", "No model. Each agent copies the most frequent partner label.",
      { reward: "none", memory: true, kind: "rule", rule: "majority_H" }],
    ["null_voter", "Null · voter(q)", "No model. Copy the last partner with probability q = 0.5.",
      { reward: "none", memory: true, kind: "rule", rule: "voter" }],
  ]],
  ["Quick checks", [
    ["smoke", "Smoke test (real API)", "12 agents × 3 rounds with the default Claude model. About $0.01.",
      { reward: "none", memory: true, n_agents: 12, n_rounds: 3 }],
    ["demo", "Offline demo", "Mock model that copies partners. Free; shows what convergence looks like.",
      { reward: "none", memory: true, kind: "mock", mock_mode: "majority", n_rounds: 100 }],
  ]],
];
const PRESETS = Object.fromEntries(PRESET_GROUPS.flatMap(([, items]) => items.map(([k, t, d, p]) => [k, { title: t, desc: d, p }])));
let activePreset = null, presetSnapshot = null;

function buildPresets() {
  $("#presets").innerHTML = PRESET_GROUPS.map(([g, items]) => `<div class="preset-group"><h4>${esc(g)}</h4><div class="preset-row">${
    items.map(([k, t, d]) => `<button type="button" class="preset" data-preset="${k}" aria-pressed="false"><b>${esc(t)}</b><small>${esc(d)}</small></button>`).join("")}</div></div>`).join("");
  $$(".preset").forEach((b) => b.onclick = () => applyPreset(b.dataset.preset));
}

function setRadio(name, value) { const el = $(`#cfg input[name="${name}"][value="${value}"]`); if (el) el.checked = true; }
function applyPreset(key) {
  const p = PRESETS[key].p;
  const f = $("#cfg").elements;
  setRadio("pairing", p.pairing ?? "random_dyad");
  f.n_agents.value = p.n_agents ?? 24;
  f.n_rounds.value = p.n_rounds ?? 300;
  f.memory_on.checked = p.memory ?? true;
  setRadio("memory_content", p.content ?? "own_and_partner");
  f.memory_horizon_H.value = 5;
  setRadio("reward_mode", p.reward ?? "none");
  f.feedback_mode.value = p.feedback ?? "choices_only";
  f.show_cumulative_points.checked = true;
  setRadio("agent_kind", p.kind ?? "claude");
  if (p.rule) f.rule_policy.value = p.rule;
  f.mock_mode.value = p.mock_mode ?? "uniform";
  f.mock_invalid_rate.value = 0;
  f.robustness_cell.checked = false;
  f.minority_on.checked = false;
  activePreset = key;
  syncForm();
  presetSnapshot = JSON.stringify(readConfig());
  onChange();
}

/* ============================== form -> config ============================== */
const kind = () => $("#cfg input[name=agent_kind]:checked").value;
const radio = (n) => $(`#cfg input[name="${n}"]:checked`)?.value;

function experimentId() {
  if (radio("pairing") === "isolated") return "prior_calibration";
  if (kind() === "rule") return "null_model";
  return radio("reward_mode") === "local_match" ? "rewarded_naming" : "no_reward_convergence";
}

function readConfig() {
  const f = $("#cfg").elements;
  const num = (n) => f[n].value === "" ? null : Number(f[n].value);
  const pairing = radio("pairing");
  const memoryOn = f.memory_on.checked;
  const reward = radio("reward_mode");
  const cfg = {
    experiment_id: experimentId(), seed: num("seed"), label_set_id: f.label_set_id.value,
    n_agents: num("n_agents"), n_rounds: num("n_rounds"), pairing,
    topology_params: { n_blocks: num("n_blocks"), p_within: num("p_within"), hub_id: f.hub_id.value },
    memory_mode: memoryOn ? "own_interactions_only" : "none", memory_content: radio("memory_content"),
    memory_order: f.memory_order.value, reward_mode: reward, feedback_mode: f.feedback_mode.value,
    show_own_agent_id: f.show_own_agent_id.checked, robustness_cell: f.robustness_cell.checked,
    max_concurrency: num("max_concurrency"), notes: f.notes.value,
  };
  if (memoryOn) cfg.memory_horizon_H = num("memory_horizon_H");
  if (reward === "local_match") cfg.payoff = { match: num("payoff_match"), mismatch: num("payoff_mismatch") };
  if (cfg.feedback_mode === "numeric_score") cfg.show_cumulative_points = f.show_cumulative_points.checked;
  const k = kind();
  if (k === "rule") {
    cfg.policy_default = f.rule_policy.value;
    if (cfg.policy_default === "voter") cfg.policy_params = { q: num("q") };
  } else {
    cfg.policy_default = "llm";
    if (k === "mock") cfg.model = { provider: "mock", model_id: "mock", mock_mode: f.mock_mode.value, mock_invalid_rate: num("mock_invalid_rate") };
    else {
      const prov = f.provider.value;
      cfg.model = { provider: prov, model_id: prov === "anthropic" ? f.model_id.value : f.other_model_id.value,
        temperature: f.temperature.disabled ? null : num("temperature"), max_tokens_cap: num("max_tokens_cap") };
    }
  }
  if (f.p0.value.trim()) cfg.p0 = f.p0.value.split(/[,\s]+/).filter(Boolean).map(Number);
  if (f.minority_on.checked) cfg.committed_minority = { frac: num("minority_frac"), start_rule: f.minority_start_rule.value, start_round: num("minority_start_round") };
  return cfg;
}

/* Keep dependent controls consistent, so impossible combinations cannot be selected. */
function syncForm() {
  const f = $("#cfg").elements;
  const pairing = radio("pairing");
  const isolated = pairing === "isolated";
  const show = (sel, on) => $$(sel).forEach((e) => e.hidden = !on);
  if (isolated) { f.memory_on.checked = false; setRadio("reward_mode", "none"); }
  f.memory_on.disabled = isolated;
  $$('#cfg input[name="reward_mode"]').forEach((r) => r.disabled = isolated);
  const memoryOn = f.memory_on.checked, reward = radio("reward_mode");
  const fb = f.feedback_mode;
  fb.querySelector('[value="numeric_score"]').disabled = reward !== "local_match" || !memoryOn;
  fb.querySelector('[value="match_indicator"]').disabled = !f.robustness_cell.checked || !memoryOn || radio("memory_content") === "own_only";
  if (fb.selectedOptions[0]?.disabled || !memoryOn) fb.value = "choices_only";
  fb.disabled = !memoryOn;
  show(".show-community", pairing === "community");
  show(".show-star", pairing === "star");
  $("#topo-fields").hidden = !["community", "star"].includes(pairing);
  show(".show-memory", memoryOn);
  show(".show-reward", reward === "local_match");
  show(".show-points", fb.value === "numeric_score");
  const k = kind();
  show(".show-claude", k === "claude");
  show(".show-mock", k === "mock");
  show(".show-rule", k === "rule");
  show(".show-voter", k === "rule" && f.rule_policy.value === "voter");
  show(".show-minority", f.minority_on.checked);
  const other = f.provider.value !== "anthropic";
  show(".show-otherprov", other);
  f.model_id.disabled = other;
  const mi = modelInfo(f.model_id.value);
  const tempOk = other || !mi || mi.temperature;
  f.temperature.disabled = !tempOk;
  if (!tempOk) f.temperature.value = "";
  $("#temp-note").textContent = tempOk ? "Leave empty for the provider default (1.0)." : "This model does not accept a temperature; the provider default is used and logged.";
  $("#model-note").textContent = other ? "Using the provider set in Advanced options." : (mi ? `${mi.note} $${mi.price[0]} / $${mi.price[1]} per 1M input / output tokens.` : "");
  const ls = META?.label_sets?.[f.label_set_id.value];
  $("#label-chips").innerHTML = ls ? ls.labels.map((l) => `<span class="chip">${esc(l)}</span>`).join("") : "";
  $("#exp-id").textContent = experimentId();
  $$(".preset").forEach((b) => { const on = b.dataset.preset === activePreset; b.classList.toggle("active", on); b.setAttribute("aria-pressed", on); });
  const modified = activePreset && presetSnapshot && JSON.stringify(readConfig()) !== presetSnapshot;
  $("#preset-state").textContent = activePreset ? (modified ? `Based on "${PRESETS[activePreset].title}", with your changes.` : `Using "${PRESETS[activePreset].title}".`) : "";
  $("#design-summary").textContent = describe(readConfig());
}

function describe(c) {
  const parts = [];
  const pair = { random_dyad: "random pairs", community: `${c.topology_params.n_blocks} communities`, star: `a star around hub ${c.topology_params.hub_id}`, isolated: "no partners (isolated)" }[c.pairing];
  parts.push(`${c.n_agents} agents, ${c.n_rounds} rounds, ${pair}.`);
  if (c.memory_mode === "none") parts.push("No memory: every choice is made fresh.");
  else parts.push(`Each agent sees its last ${c.memory_horizon_H} interactions (${c.memory_content === "own_only" ? "its own choices only" : "its own and its partner's choice"}).`);
  if (c.pairing !== "isolated") parts.push(c.reward_mode === "none" ? "No reward." : `Matching earns ${c.payoff.match} points, a mismatch ${c.payoff.mismatch}.`);
  if (c.policy_default !== "llm") parts.push(`Choices by the rule-based policy ${c.policy_default}${c.policy_default === "voter" ? `(q = ${c.policy_params.q})` : ""}.`);
  else if (c.model.provider === "mock") parts.push("Choices by the offline mock model.");
  else parts.push(`Choices by ${modelInfo(c.model.model_id)?.name ?? c.model.model_id}.`);
  if (c.committed_minority) parts.push(`${Math.round(c.committed_minority.frac * c.n_agents)} committed-minority agents.`);
  return parts.join(" ");
}

/* ============================== validation ============================== */
const FIELD_KEYS = ["memory_horizon_H", "n_agents", "n_rounds", "seed", "label_set_id", "feedback_mode", "match_indicator",
  "temperature", "max_tokens_cap", "p0", "payoff", "committed_minority", "show_cumulative_points", "hub_id", "p_within",
  "n_blocks", "policy_params", "voter", "pairing", "memory_mode", "reward_mode", "model", "max_concurrency", "policy"];
const ALIAS = { match_indicator: "feedback_mode", hub_id: "hub_id", voter: "policy_params", policy: "policy_default" };
function fieldFor(msg) {
  for (const k of FIELD_KEYS) if (msg.includes(k)) {
    const key = ALIAS[k] ?? k;
    const el = $(`#cfg [data-field="${key}"]`);
    if (el && !el.closest("[hidden]")) return el;
  }
  return null;
}

const FRIENDLY = [["memory_horizon_H", "Memory length (H)"], ["n_agents", "Number of agents"], ["n_rounds", "Rounds"],
  ["feedback_mode", "Memory record content"], ["label_set_id", "Label set"], ["max_tokens_cap", "Max output tokens"],
  ["show_cumulative_points", "Running point total"], ["committed_minority", "Committed minority"], ["policy_params.q", "q"],
  ["topology_params.", ""], ["memory_mode", "Memory"], ["reward_mode", "Reward"], ["pairing", "Pairing"]];
const friendly = (m) => FRIENDLY.reduce((s, [a, b]) => s.split(a).join(b), m);

let lastValidation = null, previewKey = "this_config.first_round", vTimer = null, vSeq = 0;
function onChange() { syncForm(); clearTimeout(vTimer); vTimer = setTimeout(validate, 250); }

async function validate() {
  const seq = ++vSeq;
  let v;
  try { v = await api("/api/validate", { method: "POST", body: JSON.stringify(readConfig()) }); }
  catch (e) { $("#validation").innerHTML = notice("bad", esc(e.message)); return; }
  if (seq !== vSeq) return;
  lastValidation = v;
  $$("#cfg .field-error").forEach((e) => e.remove());
  $$("#cfg .invalid").forEach((e) => e.classList.remove("invalid"));
  if (!v.ok) {
    const items = v.errors.map((msg, i) => {
      const fld = fieldFor(msg);
      if (fld) {
        fld.classList.add("invalid");
        const p = document.createElement("p"); p.className = "field-error"; p.id = `err-${i}`; p.textContent = friendly(msg);
        fld.appendChild(p);
      }
      return `<li>${fld ? `<a data-goto="${i}">${esc(friendly(msg))}</a>` : esc(friendly(msg))}</li>`;
    });
    $("#validation").innerHTML = notice("bad", `<b>Fix before running:</b><ul>${items.join("")}</ul>`);
    $$("#validation a[data-goto]").forEach((a) => a.onclick = () => { const el = $(`#err-${a.dataset.goto}`)?.closest(".field"); el?.scrollIntoView({ behavior: "smooth", block: "center" }); el?.querySelector("input,select")?.focus(); });
    $("#estimate").innerHTML = ""; $("#model-warn").innerHTML = ""; $("#preview").textContent = ""; $("#confirm-wrap").hidden = true;
    $("#btn-run").disabled = $("#btn-dry").disabled = true;
    return;
  }
  $("#btn-run").disabled = $("#btn-dry").disabled = false;
  const est = v.estimate;
  $("#validation").innerHTML = notice("ok", `Settings are valid. <span class="help">config_hash ${v.config_hash.slice(0, 12)}…</span>`);
  const cost = est.est_cost_usd === null ? "unknown" : `$${est.est_cost_usd.toFixed(est.est_cost_usd < 1 ? 4 : 2)}`;
  $("#estimate").innerHTML = [["Model calls", est.calls.toLocaleString()], ["Input tokens (est.)", est.est_input_tokens.toLocaleString()],
    ["Cost (est.)", est.paid ? cost + (est.output_estimate_uncertain ? "+" : "") : "Free"]].map(([k, x]) => `<div class="stat"><div class="k">${k}</div><div class="v">${x}</div></div>`).join("");
  $("#model-warn").innerHTML = (est.model_notes || []).map((n) => notice("warn", esc(n))).join("") +
    (est.output_estimate_uncertain ? notice("warn", "Hidden reasoning tokens are billed as output; the cost estimate is a rough lower bound.") : "");
  $("#confirm-wrap").hidden = !est.paid;
  if (!est.paid) $("#confirm-cost").checked = false;
  renderPreview();
}
function renderPreview() {
  if (!lastValidation?.prompts) return;
  const [a, b] = previewKey.split(".");
  const p = lastValidation.prompts[a]?.[b];
  $("#preview").textContent = p ?? "This condition has no other reward arm (prior calibration uses isolated agents).";
}
$$("#preview-seg button").forEach((b) => b.onclick = () => {
  $$("#preview-seg button").forEach((x) => x.classList.toggle("active", x === b));
  previewKey = b.dataset.p; renderPreview();
});

/* ============================== run ============================== */
$("#btn-dry").onclick = async () => {
  const btn = $("#btn-dry"); btn.disabled = true;
  $("#run-msg").innerHTML = `<span class="help">Running the full pipeline with the mock model (up to 20 rounds, no network)…</span>`;
  try {
    const r = await api("/api/dry-run", { method: "POST", body: JSON.stringify(readConfig()) });
    const last = r.population[r.population.length - 1] || {};
    $("#run-msg").innerHTML = notice(r.leakage.passed ? "ok" : "bad",
      `Offline test ${esc(r.status)}: ${r.rounds} rounds, ${r.leakage.prompts_checked} prompts checked, leakage check ${r.leakage.passed ? "passed" : "FAILED"}. Nothing was saved.`);
  } catch (e) { $("#run-msg").innerHTML = notice("bad", esc(e.message)); }
  btn.disabled = false;
};
$("#btn-run").onclick = async () => {
  const est = lastValidation?.estimate;
  if (est?.paid && !$("#confirm-cost").checked) {
    $("#run-msg").innerHTML = notice("warn", "This run makes paid API calls. Tick the cost confirmation first.");
    $("#confirm-wrap").scrollIntoView({ behavior: "smooth", block: "center" }); $("#confirm-cost").focus();
    return;
  }
  const btn = $("#btn-run"); btn.disabled = true;
  try {
    const r = await api("/api/runs", { method: "POST", body: JSON.stringify({ config: readConfig(), confirm_cost: $("#confirm-cost").checked }) });
    $("#confirm-cost").checked = false;
    $("#run-msg").innerHTML = notice("ok", `Started run <code>${esc(r.run_id)}</code>.`);
    watchJob(r.job_id, r.run_id);
    showTab("monitor");
  } catch (e) { $("#run-msg").innerHTML = notice("bad", esc(e.message)); }
  btn.disabled = false;
};

/* ============================== monitor ============================== */
let currentJob = null, currentRun = null, monRows = [], monN = 1;
function watchJob(jobId, runId) {
  currentJob = jobId; currentRun = runId; monRows = [];
  $("#mon-title").textContent = `Running ${runId}`; $("#mon-sub").textContent = "Live population state after each round.";
  $("#btn-cancel").disabled = false; $("#btn-open-result").hidden = true; $("#mon-log").textContent = ""; $("#live-dot").hidden = false;
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  const log = (s) => { const el = $("#mon-log"); el.textContent += s + "\n"; el.scrollTop = el.scrollHeight; };
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "run_started") { monN = ev.n_rounds; monRows = []; currentRun = ev.run_id; $("#mon-title").textContent = `Running ${ev.run_id}`; log(`run ${ev.run_id} started at round ${ev.start_round}`); }
    else if (ev.type === "round") {
      monRows.push(ev);
      const pct = 100 * (ev.round + 1) / monN;
      $("#mon-bar").style.width = `${pct}%`; $("#mon-progress").setAttribute("aria-valuenow", Math.round(pct));
      $("#mon-cards").innerHTML = stats([["Round", `${ev.round + 1} / ${monN}`], ["Most common label", ev.state_modal_label || "–"],
        ["Its share", fmt(ev.state_modal_share, 2)], ["Entropy (normalized)", fmt(ev.state_entropy_norm, 2)],
        ["Switch rate", fmt(ev.switch_rate, 2)], ["Invalid answers", fmt(ev.invalid_rate, 3)]]);
      lineChart($("#mon-chart"), [
        { name: "Entropy (normalized)", pts: monRows.map((r) => [r.round, r.state_entropy_norm]) },
        { name: "Share of most common label", pts: monRows.map((r) => [r.round, r.state_modal_share]) }], { xLabel: "round", yMax: 1 });
      if (ev.round % 10 === 0) log(`round ${ev.round}: ${ev.state_modal_label} ${fmt(ev.state_modal_share, 2)}, entropy ${fmt(ev.state_entropy_norm, 2)}`);
    } else if (ev.type === "done") {
      log(`run ${ev.run_id} → ${ev.status}${ev.error ? " — " + ev.error : ""}`);
      if (ev.summary) log(`consensus: ${ev.summary.consensus}; final label ${ev.summary.final_modal_label} (${fmt(ev.summary.final_modal_share, 2)}); invalid ${fmt(ev.summary.invalid_rate)}`);
    } else if (ev.type === "error") log("ERROR " + ev.message);
    else if (ev.type === "job_done") {
      log(`job ${ev.status}`); $("#btn-cancel").disabled = true; $("#live-dot").hidden = true;
      $("#mon-title").textContent = `Run ${currentRun}: ${ev.status}`; $("#btn-open-result").hidden = false; es.close();
    }
  };
  es.onerror = () => { log("(event stream closed)"); es.close(); $("#btn-cancel").disabled = true; $("#live-dot").hidden = true; };
}
$("#btn-cancel").onclick = async () => { if (currentJob) await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" }); };
$("#btn-open-result").onclick = () => { showTab("results"); setTimeout(() => openRun(currentRun), 150); };
const stats = (items) => items.map(([k, v]) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");

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
    const d = pts.map((p, j) => `${j ? "L" : "M"}${sx(+p[0]).toFixed(1)},${sy(+p[1]).toFixed(1)}`).join("");
    g += `<path d="${d}" fill="none" stroke="${colors[i % colors.length]}" stroke-width="2" ${i % 2 ? 'stroke-dasharray="6 4"' : ""}/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))} by ${esc(xLabel)}">${g}</svg>
    <div class="legend">${series.map((s, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

/* ============================== results ============================== */
let runs = [], selected = new Set(), cmpMetric = "state_entropy_norm", cmpAxis = "round";
const detailCache = {};
$("#btn-refresh").onclick = loadRuns;
function condition(r) {
  if (r.experiment_id === "prior_calibration") return "Study 0 calibration";
  const mem = r.memory_mode === "none" ? "no memory" : `memory H=${r.H}${r.memory_content === "own_only" ? " (own only)" : ""}`;
  return `${r.reward_mode === "none" ? "no reward" : "reward"}, ${mem}, ${r.pairing.replace("_dyad", "")}`;
}
const yesNo = (b) => b === undefined || b === null ? "–" : `<span class="badge ${b ? "yes" : "no"}">${b ? "yes" : "no"}</span>`;
async function loadRuns() {
  runs = await api("/api/runs");
  const head = `<thead><tr><th scope="col"><span class="sr">Compare</span></th><th scope="col">Run</th><th scope="col">Status</th><th scope="col">Condition</th><th scope="col">Agents</th><th scope="col">Seed</th><th scope="col">Label set</th><th scope="col">Rounds</th><th scope="col">Chosen by</th><th scope="col">Consensus</th><th scope="col">Winning label</th><th scope="col">Share</th><th scope="col">Invalid</th><th scope="col">Leakage check</th></tr></thead>`;
  const body = runs.map((r) => {
    const s = r.summary || {};
    return `<tr class="${selected.has(r.run_id) ? "sel" : ""}">
      <td><input type="checkbox" aria-label="Compare ${r.run_id}" data-run="${r.run_id}" ${selected.has(r.run_id) ? "checked" : ""}></td>
      <td><button class="link" data-open="${r.run_id}">${r.run_id}</button></td>
      <td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
      <td>${esc(condition(r))}</td><td>${r.n_agents}</td><td>${r.seed}</td><td>${esc(r.label_set_id)}</td>
      <td>${r.rounds_done ?? 0} / ${r.n_rounds}</td>
      <td>${esc(r.policy === "llm" ? (r.provider === "mock" ? "mock" : (modelInfo(r.model)?.name ?? r.model)) : r.policy)}</td>
      <td>${yesNo(s.consensus)}</td><td>${s.final_modal_label ? `<span class="label-tag">${esc(s.final_modal_label)}</span>` : "–"}</td>
      <td>${fmt(s.final_modal_share, 2)}</td><td>${fmt(s.invalid_rate, 3)}</td><td>${r.leakage_passed === undefined || r.leakage_passed === null ? "–" : (r.leakage_passed ? '<span class="badge yes">passed</span>' : '<span class="badge no">failed</span>')}</td></tr>`;
  }).join("");
  $("#runs-table").innerHTML = head + `<tbody>${body || `<tr><td colspan="14" class="help">No runs yet. Start one from Setup.</td></tr>`}</tbody>`;
  $$("#runs-table input[data-run]").forEach((c) => c.onchange = () => { c.checked ? selected.add(c.dataset.run) : selected.delete(c.dataset.run); c.closest("tr").classList.toggle("sel", c.checked); renderCompare(); });
  $$("#runs-table button[data-open]").forEach((a) => a.onclick = () => openRun(a.dataset.open));
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
  lineChart($("#cmp-chart"), details.map((d, i) => ({ name: `${ids[i]} (seed ${d.config.seed}, ${d.config.label_set_id})`,
    pts: d.population.map((r) => [+r[cmpAxis], r[cmpMetric]]) })), { xLabel: cmpAxis === "round" ? "round" : "interactions per agent", yMax: 1 });
  const byLs = {};
  details.forEach((d) => { const s = d.summary || {}; (byLs[d.config.label_set_id] ??= []).push({ seed: d.config.seed, label: s.consensus ? s.final_modal_label : (s.fragmentation ? "fragmented" : "no consensus") }); });
  $("#winners").innerHTML = `<h3>Winning label by seed (path dependence, H4)</h3>` + Object.entries(byLs).map(([ls, arr]) => {
    const counts = {}; arr.forEach((a) => counts[a.label] = (counts[a.label] || 0) + 1);
    return `<p class="help"><b>${esc(ls)}</b>: ${arr.map((a) => `seed ${a.seed} → ${esc(a.label)}`).join(", ")}</p>
      <div class="bars">${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([l, c]) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * c / arr.length}%"></div></div><span>${c} / ${arr.length}</span></div>`).join("")}</div>`;
  }).join("");
}
function segBind(sel, fn) { $$(`${sel} button`).forEach((b) => b.onclick = () => { $$(`${sel} button`).forEach((x) => x.classList.toggle("active", x === b)); fn(b); }); }
segBind("#metric-seg", (b) => { cmpMetric = b.dataset.m; renderCompare(); });
segBind("#axis-seg", (b) => { cmpAxis = b.dataset.a; renderCompare(); });

async function openRun(runId) {
  const d = await api(`/api/runs/${runId}`);
  detailCache[runId] = d;
  const s = d.summary || {}, m = d.manifest || {}, c = d.config || {};
  const canResume = m.status && !["completed", "failed_leakage", "running"].includes(m.status);
  const el = $("#detail"); el.hidden = false;
  el.innerHTML = `<div class="row between wrap"><div><h2>Run ${esc(runId)}</h2><p class="hint">${esc(condition({ ...c, H: c.memory_horizon_H }))} · seed ${c.seed} · label set ${esc(c.label_set_id)} · <span class="badge ${esc(m.status)}">${esc(m.status)}</span></p></div>
      ${canResume ? `<button type="button" class="btn secondary" id="btn-resume">Resume this run</button>` : ""}</div>
    <div class="seg" id="detail-seg" role="tablist">
      <button type="button" data-t="overview" class="active">Overview</button>
      <button type="button" data-t="interactions">Interactions by round</button>
      <button type="button" data-t="calls">Model calls</button>
      <button type="button" data-t="downloads">Downloads</button>
    </div>
    <div id="dt-overview"></div><div id="dt-interactions" hidden></div><div id="dt-calls" hidden></div><div id="dt-downloads" hidden></div>`;
  segBind("#detail-seg", (b) => { ["overview", "interactions", "calls", "downloads"].forEach((t) => $(`#dt-${t}`).hidden = t !== b.dataset.t); if (b.dataset.t === "calls") loadCalls(runId); });
  const prior = s.prior;
  $("#dt-overview").innerHTML = `<div class="stats">${stats([["Consensus", s.consensus === undefined ? "–" : (s.consensus ? "yes" : "no")],
      ["Reached at round", s.T_consensus_round ?? "–"], ["Winning label", s.final_modal_label ?? "–"], ["Its share (last 20 %)", fmt(s.final_modal_share, 2)],
      ["Fragmented", s.fragmentation === undefined ? "–" : (s.fragmentation ? "yes" : "no")], ["Labels used (last 20 %)", s.n_unique_last20pct ?? "–"],
      ["Invalid answers", fmt(s.invalid_rate)], ["Void pairings", fmt(s.void_rate)],
      ["Leakage check", d.leakage ? (d.leakage.passed ? `passed (${d.leakage.prompts_checked} prompts)` : "FAILED") : "–"],
      ["Model version", (m.model_versions || []).join(", ") || "–"]])}</div>
    ${s.flag_invalid ? notice("warn", `Invalid-answer rate above ${c.invalid_rate_flag}${s.exclude_invalid ? " and above the exclusion threshold: exclude this run" : ""}.`) : ""}
    ${(m.model_notes || []).map((n) => notice("warn", esc(n))).join("")}
    ${m.error ? notice("bad", esc(m.error)) : ""}
    <div class="chart" id="detail-chart"></div>
    ${prior ? `<h3>Study 0 · label prior</h3><p class="help">${prior.n_valid} valid of ${prior.n_total} choices · χ² p = ${fmt(prior.chi2_p, 4)} · max/min = ${fmt(prior.max_min_ratio, 2)}</p>
      ${prior.flagged ? notice("warn", `Label bias flagged: ${esc(prior.flag_reasons.join("; "))}`) : notice("ok", "No label-bias flag.")}
      <div class="bars">${prior.labels.map((l, i) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * prior.p0[i] / Math.max(...prior.p0, 1e-9)}%"></div></div><span>${fmt(prior.p0[i], 3)}</span></div>`).join("")}</div>
      <p class="help">Paste into Setup → Advanced → Label prior p0 for later runs on this label set:</p><pre class="prompt">${prior.p0_smoothed.map((x) => x.toFixed(4)).join(", ")}</pre>` : ""}
    ${s.final_label_shares ? `<h3>Label shares over the last 20 % of rounds</h3><div class="bars">${Object.entries(s.final_label_shares).sort((a, b) => b[1] - a[1]).map(([l, v]) => `<div class="bar"><span>${esc(l)}</span><div class="track2"><div class="fill" style="width:${100 * v}%"></div></div><span>${fmt(v, 2)}</span></div>`).join("")}</div>` : ""}`;
  lineChart($("#detail-chart"), [
    { name: "Entropy (normalized)", pts: d.population.map((r) => [+r.round, r.state_entropy_norm]) },
    { name: "Share of most common label", pts: d.population.map((r) => [+r.round, r.state_modal_share]) },
    { name: "Switch rate", pts: d.population.map((r) => [+r.round, r.switch_rate]) }], { xLabel: "round", yMax: 1 });

  const maxRound = Math.max(0, d.population.length - 1);
  $("#dt-interactions").innerHTML = `<p class="hint">Who was paired with whom in each round, and what each chose. This is analyst data; agents never see it.</p>
    <div class="round-nav"><button type="button" class="btn secondary small" id="rn-prev" aria-label="Previous round">Previous</button>
      <label for="rn-num" class="sr">Round</label><input id="rn-num" type="number" min="0" max="${maxRound}" value="0">
      <button type="button" class="btn secondary small" id="rn-next" aria-label="Next round">Next</button>
      <input type="range" id="rn-range" min="0" max="${maxRound}" value="0" aria-label="Round slider"><span class="help">of ${maxRound}</span></div>
    <div id="rn-table"></div>
    <p class="help">Download the complete record in the Downloads tab.</p>`;
  const go = (r) => {
    r = Math.max(0, Math.min(maxRound, r)); $("#rn-num").value = r; $("#rn-range").value = r;
    $("#rn-prev").disabled = r === 0; $("#rn-next").disabled = r === maxRound;
    loadRound(runId, r, d.population[r]);
  };
  $("#rn-prev").onclick = () => go(+$("#rn-num").value - 1);
  $("#rn-next").onclick = () => go(+$("#rn-num").value + 1);
  $("#rn-num").onchange = () => go(+$("#rn-num").value);
  $("#rn-range").oninput = () => go(+$("#rn-range").value);
  go(0);

  $("#dt-downloads").innerHTML = `<div class="dl-grid">
    <a class="dl" href="/api/runs/${runId}/transcript.txt" download><b>Readable transcript (.txt)</b><small>Round by round: who met whom, their choices, same/different, points.</small></a>
    <a class="dl" href="/api/runs/${runId}/transcript.txt?prompts=true" download><b>Transcript with full prompts (.txt)</b><small>Adds the exact prompt each agent received and its raw answer.</small></a>
    <a class="dl" href="/api/runs/${runId}/transcript.csv" download><b>Interaction table (.csv)</b><small>One row per pair per round: round, agent A/B, choices, match, points, raw outputs.</small></a>
    <a class="dl" href="/api/runs/${runId}/choice-model.csv" download><b>Choice-model data (.csv)</b><small>Long format for the conditional logit (H3): own_prev, own_count_H, partner_count_H, position.</small></a>
    <a class="dl" href="/api/runs/${runId}/export" download><b>All raw data (.zip)</b><small>config, manifest, calls.jsonl, interactions.csv, population.csv, summary, leakage report.</small></a></div>`;
  const rb = $("#btn-resume");
  if (rb) rb.onclick = async () => { const r = await api(`/api/runs/${runId}/resume`, { method: "POST" }); watchJob(r.job_id, runId); showTab("monitor"); };
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}
async function loadRound(runId, r, pop) {
  const rows = await api(`/api/runs/${runId}/dyads?round_from=${r}&round_to=${r}`);
  const isolated = rows.length && !rows[0].agent_b;
  const body = rows.map((x) => {
    const outcome = x.void === "True" ? '<span class="badge no">void</span>' : (isolated ? "" : (x.match === "True" ? '<span class="badge yes">same</span>' : '<span class="badge">different</span>'));
    const cls = x.match === "True" ? "label-tag same" : "label-tag";
    return `<tr><td>${x.dyad_id}</td><td>${esc(x.agent_a)}${x.minority_a === "True" ? " (minority)" : ""}</td><td><span class="${cls}">${esc(x.choice_a)}</span></td>
      ${isolated ? "" : `<td>${esc(x.agent_b)}${x.minority_b === "True" ? " (minority)" : ""}</td><td><span class="${cls}">${esc(x.choice_b)}</span></td><td>${outcome}</td>
      <td>${x.points_a === "" || x.points_a === null ? "–" : `${esc(x.points_a)} / ${esc(x.points_b)}`}</td>`}</tr>`;
  }).join("");
  const head = isolated ? "<tr><th>#</th><th>Agent</th><th>Choice</th></tr>" : "<tr><th>Pair</th><th>Agent A</th><th>Choice A</th><th>Agent B</th><th>Choice B</th><th>Outcome</th><th>Points A / B</th></tr>";
  $("#rn-table").innerHTML = `<div class="table-wrap"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>` +
    (pop ? `<p class="help">After round ${r}: most common label <span class="label-tag">${esc(pop.state_modal_label)}</span> held by ${fmt(pop.state_modal_share, 2)} of agents; normalized entropy ${fmt(pop.state_entropy_norm, 2)}.</p>` : "");
}
async function loadCalls(runId) {
  const calls = await api(`/api/runs/${runId}/calls?limit=20`);
  $("#dt-calls").innerHTML = `<p class="hint">The first 20 model calls: exact prompt and raw answer. Download the full log in Downloads.</p>` + (calls.map((c) =>
    `<p class="help">round ${c.round} · ${esc(c.agent_id)} · attempt ${c.attempt} · ${esc(c.model_version)} · ${c.tokens_in} in / ${c.tokens_out} out tokens · ${c.latency_ms} ms · temperature ${c.effective_temperature ?? "provider default"}</p>
     <pre class="prompt">${esc(c.prompt_text)}\n\n──── raw answer ────\n${esc(c.raw_output)}   → ${c.valid ? `parsed as ${esc(c.parsed_label)}` : "INVALID"}</pre>`).join("") ||
    `<p class="help">This run made no model calls (rule-based policy).</p>`);
}

/* ============================== settings ============================== */
async function loadSettings() {
  META = await api("/api/meta");
  $("#keys").innerHTML = Object.entries(META.providers).map(([p, v]) =>
    `<div><span class="badge ${v.has_key ? "yes" : ""}">${v.has_key ? "configured" : "not set"}</span><b>${esc(p)}</b><span class="help">${esc(v.env)}</span></div>`).join("") +
    `<p class="help">File: ${esc(META.env_path)}</p>`;
  $("#models-table").innerHTML = `<thead><tr><th>Default</th><th>Model</th><th>Input $/1M</th><th>Output $/1M</th><th>Temperature</th><th>Hidden reasoning</th><th>Notes</th><th></th></tr></thead><tbody>${
    META.claude_models.map((m) => `<tr><td><input type="radio" name="default_model" value="${m.id}" aria-label="Make ${esc(m.name)} the default" ${m.id === META.default_model ? "checked" : ""}></td>
      <td><b>${esc(m.name)}</b><br><code>${esc(m.id)}</code></td><td>${m.price[0].toFixed(2)}</td><td>${m.price[1].toFixed(2)}</td>
      <td>${m.temperature ? "settable" : "fixed (default)"}</td><td>${{ off_by_default: "off", disable: "switched off by engine", always: "always on (flagged)" }[m.thinking]}</td>
      <td style="white-space:normal;min-width:240px">${esc(m.note)}</td><td><button type="button" class="btn secondary small" data-test="${m.id}">Test</button></td></tr>`).join("")}</tbody>`;
  $$('#models-table input[name="default_model"]').forEach((r) => r.onchange = async () => {
    await api("/api/settings/default-model", { method: "POST", body: JSON.stringify({ model_id: r.value }) });
    META.default_model = r.value; $("#cfg").elements.model_id.value = r.value; onChange();
    $("#model-msg").innerHTML = notice("ok", `Default model is now ${esc(modelInfo(r.value).name)}. New runs in Setup use it.`);
  });
  $$("#models-table button[data-test]").forEach((b) => b.onclick = async () => {
    b.disabled = true; $("#model-msg").innerHTML = `<p class="help">Sending one short request to ${esc(b.dataset.test)}…</p>`;
    try {
      const r = await api("/api/models/test", { method: "POST", body: JSON.stringify({ model_id: b.dataset.test }) });
      $("#model-msg").innerHTML = r.ok ? notice("ok", `${esc(r.model_version)} replied "${esc(r.reply)}" in ${r.latency_ms} ms (${r.tokens_in} in / ${r.tokens_out} out tokens).`) : notice("bad", esc(r.error));
    } catch (e) { $("#model-msg").innerHTML = notice("bad", esc(e.message)); }
    b.disabled = false;
  });
}
$("#btn-key").onclick = async () => {
  try {
    await api("/api/settings/key", { method: "POST", body: JSON.stringify({ provider: $("#key-provider").value, key: $("#key-value").value }) });
    $("#key-value").value = ""; $("#key-msg").innerHTML = notice("ok", "Key saved."); loadSettings();
  } catch (e) { $("#key-msg").innerHTML = notice("bad", esc(e.message)); }
};

/* ============================== init ============================== */
(async function init() {
  META = await api("/api/meta");
  const f = $("#cfg").elements;
  f.label_set_id.innerHTML = Object.keys(META.label_sets).map((k) => `<option value="${k}">${k}</option>`).join("");
  f.model_id.innerHTML = META.claude_models.map((m) => `<option value="${m.id}">${esc(m.name)} — $${m.price[0]} / $${m.price[1]} per 1M tokens</option>`).join("");
  f.model_id.value = META.default_model;
  buildPresets();
  $("#cfg").addEventListener("input", () => onChange());
  $("#cfg").addEventListener("change", () => onChange());
  applyPreset("study_b_key");
  const jobs = await api("/api/jobs");
  const live = jobs.find((j) => j.status === "running");
  if (live) watchJob(live.job_id, live.current_run || live.run_ids[0]);
})();
