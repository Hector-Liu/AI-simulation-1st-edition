"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 3) => (x === null || x === undefined || x === "" || Number.isNaN(+x)) ? "–" : (+x).toFixed(d);
const COLORS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"].map(
  (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim());

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const text = await r.text();
  let body; try { body = JSON.parse(text); } catch { body = text; }
  if (!r.ok) throw Object.assign(new Error(typeof body === "object" ? JSON.stringify(body.detail ?? body) : body), { status: r.status, body });
  return body;
}

/* ---------------- tabs ---------------- */
$$("nav button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
function showTab(name) {
  $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "results") loadRuns();
  if (name === "settings") loadKeys();
}

/* ---------------- presets ---------------- */
const PRESETS = {
  "Study B · 关键格 (无奖励+记忆)": { experiment_id: "no_reward_convergence", reward_mode: "none", feedback_mode: "choices_only", memory_mode: "own_interactions_only", memory_content: "own_and_partner", memory_horizon_H: 5, pairing: "random_dyad" },
  "Study B · 先验基线 (无奖励无记忆)": { experiment_id: "no_reward_convergence", reward_mode: "none", feedback_mode: "choices_only", memory_mode: "none", pairing: "random_dyad" },
  "Focal-point 对照 (奖励无记忆)": { experiment_id: "rewarded_naming", reward_mode: "local_match", feedback_mode: "choices_only", memory_mode: "none", pairing: "random_dyad" },
  "Study A · random H=5": { experiment_id: "rewarded_naming", reward_mode: "local_match", feedback_mode: "numeric_score", memory_mode: "own_interactions_only", memory_content: "own_and_partner", memory_horizon_H: 5, pairing: "random_dyad" },
  "B+1 own_only (无奖励)": { experiment_id: "no_reward_convergence", reward_mode: "none", feedback_mode: "choices_only", memory_mode: "own_interactions_only", memory_content: "own_only", memory_horizon_H: 5 },
  "Study 0 · 先验校准": { experiment_id: "prior_calibration", pairing: "isolated", n_agents: 20, n_rounds: 20, memory_mode: "none", reward_mode: "none", feedback_mode: "choices_only" },
  "Null · majority_H": { experiment_id: "null_model", policy_default: "majority_H", reward_mode: "none", feedback_mode: "choices_only", memory_mode: "own_interactions_only", memory_horizon_H: 5 },
  "冒烟测试 (12人×3轮, Haiku)": { experiment_id: "no_reward_convergence", n_agents: 12, n_rounds: 3, reward_mode: "none", feedback_mode: "choices_only", memory_mode: "own_interactions_only", memory_horizon_H: 5, provider: "anthropic", model_id: "claude-haiku-4-5", policy_default: "llm" },
};
function buildPresets() {
  const box = $("#presets");
  for (const [name, p] of Object.entries(PRESETS)) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = name;
    b.onclick = () => { applyPreset(p); };
    box.appendChild(b);
  }
}
function applyPreset(p) {
  const f = $("#cfg");
  const defaults = { policy_default: "llm", pairing: "random_dyad", n_agents: 24, n_rounds: 300, memory_content: "own_and_partner", memory_horizon_H: 5 };
  for (const [k, v] of Object.entries({ ...defaults, ...p })) {
    const el = f.elements[k];
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  }
  onChange();
}

/* ---------------- form -> config ---------------- */
function readConfig() {
  const f = $("#cfg").elements;
  const num = (n) => f[n].value === "" ? null : Number(f[n].value);
  const cfg = {
    experiment_id: f.experiment_id.value, seed: num("seed"), label_set_id: f.label_set_id.value,
    n_agents: num("n_agents"), n_rounds: num("n_rounds"), pairing: f.pairing.value,
    topology_params: { n_blocks: num("n_blocks"), p_within: num("p_within"), hub_id: f.hub_id.value },
    memory_mode: f.memory_mode.value, memory_content: f.memory_content.value, memory_order: f.memory_order.value,
    reward_mode: f.reward_mode.value, feedback_mode: f.feedback_mode.value,
    show_own_agent_id: f.show_own_agent_id.checked, robustness_cell: f.robustness_cell.checked,
    policy_default: f.policy_default.value, max_concurrency: num("max_concurrency"), notes: f.notes.value,
  };
  if (cfg.memory_mode !== "none") cfg.memory_horizon_H = num("memory_horizon_H");
  if (cfg.reward_mode === "local_match") cfg.payoff = { match: num("payoff_match"), mismatch: num("payoff_mismatch") };
  if (cfg.feedback_mode === "numeric_score") cfg.show_cumulative_points = f.show_cumulative_points.checked;
  if (cfg.policy_default === "voter") cfg.policy_params = { q: num("q") };
  if (cfg.policy_default === "llm") {
    cfg.model = { provider: f.provider.value, model_id: f.provider.value === "mock" ? "mock" : f.model_id.value,
      temperature: num("temperature"), max_tokens_cap: num("max_tokens_cap") };
    if (f.provider.value === "mock") Object.assign(cfg.model, { mock_mode: f.mock_mode.value, mock_invalid_rate: num("mock_invalid_rate") });
  }
  if (f.p0.value.trim()) cfg.p0 = f.p0.value.split(/[,\s]+/).filter(Boolean).map(Number);
  if (f.minority_on.checked) cfg.committed_minority = { frac: num("minority_frac"), start_rule: f.minority_start_rule.value, start_round: num("minority_start_round") };
  return cfg;
}

function toggleFields() {
  const f = $("#cfg").elements;
  const show = (sel, on) => $$(sel).forEach((e) => e.hidden = !on);
  show(".topo.community", f.pairing.value === "community");
  show(".topo.star", f.pairing.value === "star");
  show(".mem", f.memory_mode.value !== "none");
  show(".rew", f.reward_mode.value === "local_match");
  show(".voter", f.policy_default.value === "voter");
  show(".llm", f.policy_default.value === "llm");
  show(".mock", f.policy_default.value === "llm" && f.provider.value === "mock");
  show(".mino", f.minority_on.checked);
}

let lastValidation = null, previewKey = "this_config.first_round", vTimer = null;
function onChange() { toggleFields(); clearTimeout(vTimer); vTimer = setTimeout(validate, 250); }

async function validate() {
  const cfg = readConfig();
  try { lastValidation = await api("/api/validate", { method: "POST", body: JSON.stringify(cfg) }); }
  catch (e) { $("#validation").innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const v = lastValidation;
  if (!v.ok) {
    $("#validation").innerHTML = v.errors.map((e) => `<div class="err">✕ ${esc(e)}</div>`).join("");
    $("#estimate").innerHTML = ""; $("#preview").textContent = ""; $("#confirm-wrap").hidden = true;
    $("#btn-run").disabled = true; $("#btn-dry").disabled = true;
    return;
  }
  $("#btn-run").disabled = false; $("#btn-dry").disabled = false;
  const est = v.estimate;
  $("#validation").innerHTML = `<div class="ok">✓ 配置合法</div><div class="small muted">config_hash ${v.config_hash.slice(0, 16)}…</div>` +
    (est.model_notes || []).map((n) => `<div class="warn small">⚠ ${esc(n)}</div>`).join("");
  const cost = est.est_cost_usd === null ? "价格未知" : `$${est.est_cost_usd.toFixed(est.est_cost_usd < 1 ? 4 : 2)}`;
  $("#estimate").innerHTML = `<div class="est">
      <div class="card"><div class="k">模型调用</div><div class="v">${est.calls.toLocaleString()}</div></div>
      <div class="card"><div class="k">输入 tokens（估）</div><div class="v">${est.est_input_tokens.toLocaleString()}</div></div>
      <div class="card"><div class="k">费用（估）</div><div class="v">${est.paid ? cost : "免费"}</div></div></div>`;
  $("#confirm-wrap").hidden = !est.paid;
  renderPreview();
}
function renderPreview() {
  if (!lastValidation?.prompts) return;
  const [a, b] = previewKey.split(".");
  const p = lastValidation.prompts[a]?.[b];
  $("#preview").textContent = p ?? (lastValidation.prompts.other_arm_error ? `（另一臂不可用：${lastValidation.prompts.other_arm_error}）` : "（此条件没有另一臂）");
}
$$("#preview-seg button").forEach((b) => b.onclick = () => {
  $$("#preview-seg button").forEach((x) => x.classList.toggle("active", x === b));
  previewKey = b.dataset.p; renderPreview();
});

/* ---------------- dry run / run ---------------- */
$("#btn-dry").onclick = async () => {
  $("#run-msg").textContent = "试运行中（mock 模型，最多 20 轮）…";
  try {
    const r = await api("/api/dry-run", { method: "POST", body: JSON.stringify(readConfig()) });
    const last = r.population[r.population.length - 1] || {};
    $("#run-msg").innerHTML = `<span class="${r.leakage.passed ? "ok" : "err"}">试运行 ${esc(r.status)}：${r.rounds} 轮，检查了 ${r.leakage.prompts_checked} 条提示词，泄漏检查 ${r.leakage.passed ? "通过" : "失败"}</span>
      <span class="muted small">（最后一轮 state_modal_share = ${fmt(last.state_modal_share)}）</span>`;
  } catch (e) { $("#run-msg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};
$("#btn-run").onclick = async () => {
  const est = lastValidation?.estimate;
  if (est?.paid && !$("#confirm-cost").checked) { $("#run-msg").innerHTML = `<span class="err">这次运行会调用付费模型，请先勾选费用确认。</span>`; return; }
  try {
    const r = await api("/api/runs", { method: "POST", body: JSON.stringify({ config: readConfig(), confirm_cost: $("#confirm-cost").checked }) });
    $("#confirm-cost").checked = false;
    $("#run-msg").textContent = `已开始：run ${r.run_id}`;
    watchJob(r.job_id, r.run_id);
    showTab("monitor");
  } catch (e) { $("#run-msg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};

/* ---------------- monitor ---------------- */
let currentJob = null, monRows = [], monN = 1;
function watchJob(jobId, runId) {
  currentJob = jobId; monRows = [];
  $("#mon-title").textContent = `运行中：${runId}`; $("#btn-cancel").disabled = false; $("#mon-log").textContent = "";
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  const log = (s) => { const el = $("#mon-log"); el.textContent += s + "\n"; el.scrollTop = el.scrollHeight; };
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "run_started") { monN = ev.n_rounds; monRows = []; $("#mon-title").textContent = `运行中：${ev.run_id}`; log(`run ${ev.run_id} started at round ${ev.start_round}`); }
    else if (ev.type === "round") {
      monRows.push(ev);
      $("#mon-bar").style.width = `${100 * (ev.round + 1) / monN}%`;
      $("#mon-cards").innerHTML = cards([["round", `${ev.round + 1}/${monN}`], ["state_modal_label", ev.state_modal_label],
        ["state_modal_share", fmt(ev.state_modal_share)], ["state_entropy_norm", fmt(ev.state_entropy_norm)],
        ["switch_rate", fmt(ev.switch_rate)], ["invalid_rate", fmt(ev.invalid_rate)]]);
      lineChart($("#mon-chart"), [
        { name: "state_entropy_norm", pts: monRows.map((r) => [r.round, r.state_entropy_norm]) },
        { name: "state_modal_share", pts: monRows.map((r) => [r.round, r.state_modal_share]) }], { xLabel: "round", yMax: 1 });
      if (ev.round % 10 === 0) log(`round ${ev.round}: modal ${ev.state_modal_label} ${fmt(ev.state_modal_share)}, H_norm ${fmt(ev.state_entropy_norm)}`);
    } else if (ev.type === "done") {
      log(`run ${ev.run_id} → ${ev.status}${ev.error ? " — " + ev.error : ""}`);
      if (ev.summary) log(`summary: consensus=${ev.summary.consensus}, final ${ev.summary.final_modal_label} ${fmt(ev.summary.final_modal_share)}, invalid ${fmt(ev.summary.invalid_rate)}`);
    } else if (ev.type === "error") log("ERROR " + ev.message);
    else if (ev.type === "job_done") { log(`job ${ev.status}`); $("#btn-cancel").disabled = true; $("#mon-title").textContent += `（${ev.status}）`; es.close(); }
  };
  es.onerror = () => { log("（事件流断开）"); es.close(); $("#btn-cancel").disabled = true; };
}
$("#btn-cancel").onclick = async () => { if (currentJob) await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" }); };

function cards(items) { return items.map(([k, v]) => `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join(""); }

/* ---------------- charts ---------------- */
function lineChart(el, series, { xLabel = "", yMax = null } = {}) {
  const W = 900, H = 280, L = 44, R = 12, T = 12, B = 32;
  const all = series.flatMap((s) => s.pts).filter((p) => p[1] !== null && p[1] !== "" && !Number.isNaN(+p[1]));
  if (!all.length) { el.innerHTML = `<div class="muted">没有数据</div>`; return; }
  const xs = all.map((p) => +p[0]), ys = all.map((p) => +p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1), y0 = 0, y1 = yMax ?? Math.max(...ys, 1e-9);
  const sx = (x) => L + (x - x0) / (x1 - x0) * (W - L - R), sy = (y) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  let g = `<line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/><line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${H - B}"/>`;
  for (let i = 0; i <= 4; i++) { const y = y0 + (y1 - y0) * i / 4; g += `<text x="${L - 6}" y="${sy(y) + 4}" text-anchor="end">${fmt(y, 2)}</text><line class="axis" x1="${L}" x2="${W - R}" y1="${sy(y)}" y2="${sy(y)}" opacity=".35"/>`; }
  for (let i = 0; i <= 5; i++) { const x = x0 + (x1 - x0) * i / 5; g += `<text x="${sx(x)}" y="${H - B + 16}" text-anchor="middle">${fmt(x, x1 - x0 > 20 ? 0 : 1)}</text>`; }
  g += `<text x="${(W + L) / 2}" y="${H - 2}" text-anchor="middle">${esc(xLabel)}</text>`;
  series.forEach((s, i) => {
    const pts = s.pts.filter((p) => p[1] !== null && p[1] !== "" && !Number.isNaN(+p[1]));
    if (!pts.length) return;
    const d = pts.map((p, j) => `${j ? "L" : "M"}${sx(+p[0]).toFixed(1)},${sy(+p[1]).toFixed(1)}`).join("");
    g += `<path d="${d}" fill="none" stroke="${COLORS[i % COLORS.length]}" stroke-width="1.8"/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}</svg>
    <div class="legend">${series.map((s, i) => `<span><i style="background:${COLORS[i % COLORS.length]}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

/* ---------------- results ---------------- */
let runs = [], selected = new Set(), cmpMetric = "state_entropy_norm", cmpAxis = "round";
const popCache = {};
$("#btn-refresh").onclick = loadRuns;
async function loadRuns() {
  runs = await api("/api/runs");
  const head = `<tr><th></th><th>run</th><th>状态</th><th>实验</th><th>seed</th><th>标签集</th><th>N×轮</th><th>pairing</th><th>reward</th><th>memory</th><th>policy / model</th><th>共识</th><th>最终标签</th><th>份额</th><th>无效率</th><th>泄漏</th></tr>`;
  const body = runs.map((r) => {
    const s = r.summary || {};
    return `<tr class="${selected.has(r.run_id) ? "sel" : ""}">
      <td><input type="checkbox" data-run="${r.run_id}" ${selected.has(r.run_id) ? "checked" : ""}></td>
      <td><a data-open="${r.run_id}">${r.run_id}</a></td>
      <td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
      <td>${esc(r.experiment_id)}</td><td>${r.seed}</td><td>${esc(r.label_set_id)}</td>
      <td>${r.n_agents}×${r.rounds_done ?? 0}/${r.n_rounds}</td><td>${esc(r.pairing)}</td><td>${esc(r.reward_mode)}</td>
      <td>${esc(r.memory_mode === "none" ? "none" : `${r.memory_content} H=${r.H}`)}</td>
      <td>${esc(r.policy === "llm" ? `${r.provider}:${r.model}` : r.policy)}</td>
      <td>${s.consensus === undefined ? "–" : (s.consensus ? "✓" : "✕")}</td>
      <td>${esc(s.final_modal_label ?? "–")}</td><td>${fmt(s.final_modal_share, 2)}</td>
      <td>${fmt(s.invalid_rate, 3)}</td><td>${r.leakage_passed === undefined || r.leakage_passed === null ? "–" : (r.leakage_passed ? "✓" : "✕")}</td></tr>`;
  }).join("");
  $("#runs-table").innerHTML = head + (body || `<tr><td colspan="16" class="muted">还没有运行记录</td></tr>`);
  $$("#runs-table input[data-run]").forEach((c) => c.onchange = () => { c.checked ? selected.add(c.dataset.run) : selected.delete(c.dataset.run); loadRuns(); });
  $$("#runs-table a[data-open]").forEach((a) => a.onclick = () => openRun(a.dataset.open));
  renderCompare();
}
async function population(runId) {
  if (!popCache[runId] || runs.find((r) => r.run_id === runId)?.status === "running") popCache[runId] = (await api(`/api/runs/${runId}`));
  return popCache[runId];
}
async function renderCompare() {
  const ids = [...selected];
  $("#compare").hidden = !ids.length;
  if (!ids.length) return;
  const details = await Promise.all(ids.map(population));
  lineChart($("#cmp-chart"), details.map((d, i) => ({ name: `${ids[i]} (seed ${d.config.seed}, ${d.config.label_set_id})`,
    pts: d.population.map((r) => [+r[cmpAxis], r[cmpMetric] === "" ? null : +r[cmpMetric]]) })), { xLabel: cmpAxis, yMax: 1 });
  // winners (H4): per label set, which label won in each seed
  const byLs = {};
  details.forEach((d) => { const s = d.summary || {}; (byLs[d.config.label_set_id] ??= []).push({ seed: d.config.seed, label: s.consensus ? s.final_modal_label : `(${s.fragmentation ? "fragmented" : "no consensus"})` }); });
  $("#winners").innerHTML = `<h2>获胜标签 Winners by seed</h2>` + Object.entries(byLs).map(([ls, arr]) => {
    const counts = {}; arr.forEach((a) => counts[a.label] = (counts[a.label] || 0) + 1);
    const n = arr.length;
    return `<div class="small"><b>${esc(ls)}</b>：${arr.map((a) => `seed ${a.seed} → ${esc(a.label)}`).join("， ")}</div>
      <div class="bars">${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([l, c]) => `<div class="bar"><span>${esc(l)}</span><div class="fill" style="width:${100 * c / n}%"></div><span>${c}/${n}</span></div>`).join("")}</div>`;
  }).join("");
}
$$("#metric-seg button").forEach((b) => b.onclick = () => { $$("#metric-seg button").forEach((x) => x.classList.toggle("active", x === b)); cmpMetric = b.dataset.m; renderCompare(); });
$$("#axis-seg button").forEach((b) => b.onclick = () => { $$("#axis-seg button").forEach((x) => x.classList.toggle("active", x === b)); cmpAxis = b.dataset.a; renderCompare(); });

async function openRun(runId) {
  const d = await api(`/api/runs/${runId}`);
  const calls = await api(`/api/runs/${runId}/calls?limit=6`);
  const s = d.summary || {}, m = d.manifest || {};
  const canResume = m.status && !["completed", "failed_leakage"].includes(m.status) && m.status !== "running";
  const prior = s.prior;
  const el = $("#detail"); el.hidden = false;
  el.innerHTML = `<div class="row between"><h2>运行详情 ${esc(runId)}</h2>
      <div class="actions" style="margin:0">
        ${canResume ? `<button class="secondary" id="btn-resume">继续运行（resume）</button>` : ""}
        <a href="/api/runs/${runId}/export"><button class="secondary">下载全部数据 (zip)</button></a>
        <a href="/api/runs/${runId}/choice-model.csv"><button class="secondary">choice-model CSV (H3)</button></a></div></div>
    <div class="cards">${cards([["status", m.status], ["共识 consensus", s.consensus === undefined ? "–" : String(s.consensus)],
      ["T_consensus (round)", s.T_consensus_round ?? "–"], ["T_consensus (t_pc)", fmt(s.T_consensus_t_pc, 1)],
      ["最终标签", s.final_modal_label ?? "–"], ["最终份额", fmt(s.final_modal_share)], ["fragmentation", String(s.fragmentation ?? "–")],
      ["n_unique_last20%", s.n_unique_last20pct ?? "–"], ["invalid_rate", fmt(s.invalid_rate)], ["void_rate", fmt(s.void_rate)],
      ["泄漏检查", d.leakage ? (d.leakage.passed ? `通过 (${d.leakage.prompts_checked})` : "失败") : "–"],
      ["model", (m.model_versions || []).join(", ") || "–"]])}</div>
    ${s.flag_invalid ? `<div class="warn">⚠ 无效率超过 ${d.config.invalid_rate_flag}（${s.exclude_invalid ? "超过排除阈值，应排除" : "已标记"}）</div>` : ""}
    ${(m.model_notes || []).map((n) => `<div class="warn small">⚠ ${esc(n)}</div>`).join("")}
    ${m.error ? `<div class="err">${esc(m.error)}</div>` : ""}
    <div class="chart" id="detail-chart"></div>
    ${prior ? `<h2>先验校准 Study 0</h2><div class="small">有效选择 ${prior.n_valid}/${prior.n_total}，χ² p = ${fmt(prior.chi2_p, 4)}，max/min = ${fmt(prior.max_min_ratio, 2)}
       ${prior.flagged ? `<span class="err">⚠ 标签偏好被标记：${esc(prior.flag_reasons.join("; "))}</span>` : `<span class="ok">✓ 未触发标签偏好闸门</span>`}</div>
       <div class="bars">${prior.labels.map((l, i) => `<div class="bar"><span>${esc(l)}</span><div class="fill" style="width:${100 * prior.p0[i] / Math.max(...prior.p0)}%"></div><span>${fmt(prior.p0[i], 3)}</span></div>`).join("")}</div>
       <p class="small muted">把下面这行复制到“实验设置 → p0”，作为同一标签集后续运行的先验：</p><pre class="prompt">${prior.p0_smoothed.map((x) => x.toFixed(4)).join(", ")}</pre>` : ""}
    ${s.final_label_shares ? `<h2>最后 20% 轮次的标签份额</h2><div class="bars">${Object.entries(s.final_label_shares).sort((a, b) => b[1] - a[1]).map(([l, v]) => `<div class="bar"><span>${esc(l)}</span><div class="fill" style="width:${100 * v}%"></div><span>${fmt(v, 2)}</span></div>`).join("")}</div>` : ""}
    <h2>调用样本（前 6 条，完整提示词 + 原始输出）</h2>
    ${calls.map((c) => `<div class="small muted">round ${c.round} · ${esc(c.agent_id)} · attempt ${c.attempt} · ${esc(c.model_version)} · in ${c.tokens_in} / out ${c.tokens_out} tok · ${c.latency_ms} ms · T=${c.effective_temperature ?? "default"}</div>
      <pre class="prompt">${esc(c.prompt_text)}\n\n──── raw output ────\n${esc(c.raw_output)}   → ${c.valid ? `parsed: ${esc(c.parsed_label)}` : "INVALID"}</pre>`).join("") || `<div class="muted">此运行没有模型调用（规则策略）。</div>`}`;
  lineChart($("#detail-chart"), [
    { name: "state_entropy_norm", pts: d.population.map((r) => [+r.round, r.state_entropy_norm]) },
    { name: "state_modal_share", pts: d.population.map((r) => [+r.round, r.state_modal_share]) },
    { name: "round_entropy_norm", pts: d.population.map((r) => [+r.round, r.round_entropy_norm]) },
    { name: "switch_rate", pts: d.population.map((r) => [+r.round, r.switch_rate]) }], { xLabel: "round", yMax: 1 });
  const rb = $("#btn-resume");
  if (rb) rb.onclick = async () => { const r = await api(`/api/runs/${runId}/resume`, { method: "POST" }); watchJob(r.job_id, runId); showTab("monitor"); };
  el.scrollIntoView({ behavior: "smooth" });
}

/* ---------------- settings ---------------- */
async function loadKeys() {
  const m = await api("/api/meta");
  $("#keys").innerHTML = Object.entries(m.providers).map(([p, v]) =>
    `<div>${esc(p)}：${v.has_key ? `<span class="ok">✓ 已配置</span>` : `<span class="muted">未配置</span>`} <span class="muted small">(${esc(v.env)})</span></div>`).join("") +
    `<div class="small muted">文件：${esc(m.env_path)}</div>`;
}
$("#btn-key").onclick = async () => {
  try {
    await api("/api/settings/key", { method: "POST", body: JSON.stringify({ provider: $("#key-provider").value, key: $("#key-value").value }) });
    $("#key-value").value = ""; $("#key-msg").innerHTML = `<span class="ok">已保存</span>`; loadKeys();
  } catch (e) { $("#key-msg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};

/* ---------------- init ---------------- */
(async function init() {
  const m = await api("/api/meta");
  $("#cfg").elements.label_set_id.innerHTML = Object.entries(m.label_sets).map(([k, v]) => `<option value="${k}">${k}: ${v.labels.join(" ")}</option>`).join("");
  $("#models").innerHTML = m.anthropic_models.map((x) => `<option value="${x}">`).join("");
  buildPresets();
  $("#cfg").addEventListener("input", onChange);
  $("#cfg").addEventListener("change", onChange);
  applyPreset(PRESETS["Study B · 关键格 (无奖励+记忆)"]);
  const jobs = await api("/api/jobs");
  const live = jobs.find((j) => j.status === "running");
  if (live) watchJob(live.job_id, live.current_run || live.run_ids[0]);
})();
