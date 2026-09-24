# SPEC — Naming-game emergence experiments in Concordia Simulation Builder

Status: **APPROVED v1.0 (2026-09-24)** by Yuhan. All ⚑ decisions in §13 accepted as recommended (D9: specific model still to be named before the pilot). Nothing here is implemented yet.
Original brief: `docs/specs/naming-game-brief.md`.
Source: the implementation brief "Implementation brief: emergence experiments in an LLM agent simulator" (test.rtf). This SPEC keeps every non-negotiable invariant from the brief, fixes the inconsistencies found in review (§2), adds the controls the brief needs to support its own emergence tests (§3), and decides how to build it in this repo (§4).

Items marked **⚑ DECISION** were signed off on 2026-09-24 with the recommendations in §13.

---

## 0. Summary

| | |
|---|---|
| Can the experiments be done in this tool? | **Yes, but not on Concordia's Game Master / entity machinery.** Concordia routes every observation through LLM-written narration, wraps agent prompts in fixed role-play instructions, and keeps global state in LLM-read GM memory. That breaks invariants 1–4 and 6 of the brief. |
| Recommended build | A new, self-contained **protocol engine** inside the builder (`backend/experiments/naming_game/`). It reuses the builder's LLM provider layer, API-key handling, cancellation, logs folder and web UI, and does **not** use Concordia entities or GMs. |
| New features needed | Experiment config + validation; dyad scheduler for 3 topologies; private ring-buffer memory; versioned prompt templates; strict parser; nonce label generator + prior calibration; rule-based agent policies (null models, committed minority); append-only analyst store; metrics module; automated leakage tests + dry run; batch/matrix runner; CLI; API endpoints; one results page. |
| Biggest design changes vs the brief | (1) separate *self-persistence* from *social influence* (new `own_only` memory control; exposure variables split); (2) add non-LLM null models on the same scheduler; (3) fix label pool **per label set across seeds** (the brief regenerates per run, which makes its own path-dependence test impossible); (4) make the two prompt arms differ **only** in the payoff lines; (5) resolve the `success_failure_label` contradiction; (6) define the time axis as per-capita interactions so topologies are comparable. |
| Scale at the brief's defaults | ≈1.24 M model calls, ≈250–370 M input tokens, ≈25 h wall-clock at full within-round parallelism (§10). Pilot first to cut rounds. |

---

## 1. Research questions, hypotheses, and what counts as emergence

**RQ.** Can a population-level convention arise from local, private, pairwise interaction among LLM agents, with and without a task-contingent reward?

Two things must be kept apart, because they have different sources:

1. **The disposition to converge.** A tendency to repeat one's own past choice or to copy what a partner did. In LLMs this is largely a pretrained property (in-context imitation). Showing it exists is necessary but is **not** the emergence claim.
2. **Which convention wins.** If the winning label is arbitrary with respect to the agents' individual priors and differs across seeds (symmetry breaking, path dependence), then the population-level regularity was produced by the interaction history. **This is the emergence claim.**

Hypotheses (pre-register before full runs):

- **H1 (Study A).** With reward, memory and random dyads, normalized entropy of the population state falls well below the memory-none baseline, and the modal share reaches the consensus threshold (§7.2) in most seeds.
- **H2 (Study B).** Without reward, but with memory of own interactions, entropy still falls below the memory-none baseline. (Two-sided: failure to converge is an equally publishable answer.)
- **H3 (both).** The partner-exposure coefficient predicts the next choice over and above the label prior, label position and the agent's own previous choice (§7.4).
- **H4 (both).** The distribution of winning labels across seeds is more dispersed than the prior-predicted null (§7.5). A concentrated distribution on the prior's top label means the "convention" was a shared prior, not an emergent one.
- **H5 (Study A, topology).** Star converges through the hub (centralization); community topology shows more stable multi-convention fragmentation than random.

The simulator never sets an `emergence` flag. The analyst decides after the tests in §7 and the leakage audit (§8) pass.

---

## 2. Design review: issues found in the brief and resolutions

| # | Issue in the brief | Why it matters | Resolution in this SPEC |
|---|---|---|---|
| R1 | `personal_exposure` counts the focal label "as either own or partner choice". | Merges self-persistence with social influence. An agent that just repeats itself shows high "exposure" effects with zero social learning. | Split into `own_prev_choice`, `own_count_H`, `partner_count_H` (§7.4). |
| R2 | Memory arm always shows both own and partner choices. No control shows own history only. | Cannot tell whether convergence needs social information at all. | New `memory_content = own_only` control (Study B+, §3.3). |
| R3 | No mechanistic null model. | A neutral copying process (voter model) also reaches consensus in finite populations. "Consensus appeared" alone does not distinguish LLM dynamics from random drift. | Rule-based agent policies on the **same scheduler**: `prior_sample`, `voter(q)`, `majority_H`, `scripted_fixed` (§3.4). Compare curves and winner distributions. |
| R4 | Invariant 7 says labels are "regenerated or reshuffled per run". Test 2 requires the modal label to "differ across seeds more than label-prior predicts". | If the pool changes every run, "which label won" is not comparable across seeds and the prior is not measured for that pool. | Fixed pool per **label set**. Use `n_label_sets` (default 3) as a random factor; seeds are nested in label sets; each set gets its own prior calibration (§3.1). Presentation order is still reshuffled per prompt. |
| R5 | `feedback_mode = success_failure_label` vs. "Never say success, failure…". | Direct contradiction. | Rename to `match_indicator`, neutral wording: "(same label)" / "(different labels)". Robustness factor only, never in the core cells (§5.6). |
| R6 | Rewarded template has extra non-payoff sentences ("You will be told the other participant's choice after both choices are submitted. You will not be told other participants' choices."). The no-reward template never says there is a partner. | Arms differ in information structure, not just reward. The no-reward agent sees "the other participant chose X" in memory with no explanation of who that is. | One shared **interaction block** in both arms; the rewarded arm adds **only** the payoff block (§5.5). The plural "other participants'" line is dropped (it cues a population). ⚑ DECISION D1. |
| R7 | Feedback "after choices" in a stateless design. | Each choice is a fresh model call; nothing is "shown after" unless it is rendered into the next prompt. | Feedback exists only as the rendering of buffer records (+ optional cumulative points) in the next prompt (§5.6). `feedback_mode` is ignored and must be `choices_only` when `memory_mode = none`. |
| R8 | `memory_horizon_H` "also test 0" and `memory_mode = none`. | Two names for one condition. | `H = 0` is invalid; use `memory_mode = none`. Validation rejects `H = 0` with memory on. |
| R9 | "Round" means different things across topologies. Star has one dyad per round; random has N/2. | Entropy-by-round curves across topologies are not comparable; star leaves get very few interactions. | Primary time axis = **mean per-capita interactions** (§3.5). Star runs get `n_rounds` scaled so the median leaf reaches the same per-capita count, or are reported with that caveat. ⚑ DECISION D2. |
| R10 | Buffer rendering uses "Round {r}". | Absolute round numbers reveal elapsed global time. In star they reveal how rarely a leaf is chosen, which is indirect structure information. | Render relative order only ("Latest interaction", "2 interactions ago", …). The analyst log keeps absolute rounds. |
| R11 | Position bias is not checked; only label bias is. | LLMs prefer early/late list positions. With per-prompt reshuffling this becomes noise, but it has to be measured and controlled in the choice model. | Prior calibration also estimates P(choice \| position). Position enters the choice model as a covariate. |
| R12 | Label generator constraints are loose. | Near-duplicate nonces ("Zevu"/"Zevo") create confusion and fake "convergence" through misreading. | Pairwise edit distance ≥ 2, distinct first syllable, no dictionary, name or brand hits, no denylist substrings (§5.3). |
| R13 | Invalid output: "resample once", then unspecified. | Missing choices can silently bias memory. | After one retry, the dyad is **void**: no memory write, no payoff, logged. A run is flagged if its invalid rate is > 2 % and excluded if > 5 %. ⚑ DECISION D3. |
| R14 | Committed minority "locked to a non-modal label after round 50". | "Non-modal" is not a unique rule; 5 % of N = 24 is 1.2 agents. | Minority agents are rule-based (`scripted_fixed`, no LLM calls). Their label is the **least-used label over the previous 20 rounds** (ties broken by the RNG). Size is `round(frac × N)`: N = 24 gives 1 and 4 agents; recommend N = 48 for the minority study. |
| R15 | Temperature is left open. | At T = 0 the memory-none baseline collapses to the prior mode: trivial "consensus". Some reasoning models reject temperature entirely. | T > 0 is required. Default is the model's standard sampling (log the **effective** T). Validation rejects T = 0. ⚑ DECISION D4 (T level). |
| R16 | The rewarded + memory-none cell is not interpreted. | It measures **focal-point (Schelling) coordination from the shared prior**: the strongest non-emergent competitor explanation. | Kept and named explicitly as the "focal-point control" (§3.3). |
| R17 | Homogeneous population of one model. | Identical priors make prior-driven convergence easy. | Accept for Studies A/B (report as scope). Engine supports per-agent `model_id` for a later mixed-population study. |
| R18 | No pilot step, no stopping rule. | 300 rounds may be several times longer than needed, or too short in the no-reward arm. | Pilot phase (§3.6) fixes `n_rounds` before pre-registration. No adaptive early stopping in confirmatory runs. |

---

## 3. Experimental design

### 3.1 Label sets and prior calibration (Study 0; runs before anything else)

- Generate `n_label_sets` (default 3) pools of `label_pool_size` (default 10) nonce labels (§5.3). Freeze them in `labels/label_sets.json` with a hash.
- For each label set: 20 sterile agents × 20 choices, `policy = llm`, `memory_mode = none`, no partner block (the "isolated" template variant). Order is reshuffled per prompt.
- Outputs per label set: `p0(label)`, `p0(position)`, invalid rate.
- **Gate.** If any label has p0 > 0.25, or a chi-square test against uniform has p < 0.01 with max/min ratio > 3: flag. Either regenerate that set or keep it and carry `log p0` as a covariate (⚑ DECISION D5). The engine never proceeds silently.
- The `memory_mode = none, reward = none` cell of Study B differs from the calibration prompt only by the interaction block, so it doubles as a population-level check of the prior.

### 3.2 Study A — rewarded local naming game

Fixed: `reward_mode = local_match`, `feedback_mode = numeric_score`, `memory_mode = own_interactions_only`, `memory_content = own_and_partner`.

| Factor | Levels |
|---|---|
| topology | random_dyad, star, community |
| H | 1, 5, 10 |
| seeds | 30 in (random_dyad, H = 5); 10 elsewhere. Seeds are nested in label sets, spread evenly. |
| optional minority | after convergence (first round where consensus holds, §7.2) or at round 50 if not converged; size 5 % and 15 %; N = 48 recommended |

Primary outcomes: entropy trajectory vs memory-none baseline; T_consensus; fragmentation rate; star vs random; winner distribution vs prior (H4).

### 3.3 Study B — no task-contingent reward (core 2 × 2 + controls)

Core 2 × 2 (random_dyad, H = 5, 30 seeds per cell):

| | memory none | memory own_and_partner |
|---|---|---|
| reward none | prior baseline | **key cell: spontaneous convergence?** |
| reward local_match | **focal-point control** | shared with Study A (random, H = 5) |

Controls (recommended; 10–30 seeds each):

- **B+1 `own_only`, reward none.** The buffer shows the agent's own past choices only; the partner's choice is never rendered. It isolates self-persistence. Individual lock-in is expected; population convergence should **not** exceed the baseline if social information is what matters.
- **B+2 `own_only`, reward local_match**, feedback = points only. This is reinforcement without seeing the partner's label.
- **B+3 (optional) yoked exposure.** The partner label shown is replayed from a completed run of the same cell (matched agent × round). The loop between this population's behavior and what it sees is broken. It estimates the individual response function without feedback.

`feedback_mode` must be `choices_only` whenever `reward_mode = none`. A "you matched"-style cell without points is a separate robustness factor, never the no-reward arm.

### 3.4 Computational null models (no LLM; cheap; same scheduler)

These run through the identical scheduler, buffers and metrics, with a rule-based `policy`:

| policy | rule |
|---|---|
| `prior_sample` | independent draw from `p0` (per label set) |
| `voter(q)` | with prob. q copy the last partner's label, else repeat own last; first move from `p0` |
| `majority_H` | choose the most frequent partner label in the buffer (ties → own last → `p0`) — the classic memory-H naming-game rule |
| `scripted_fixed` | always the configured label (committed minority) |

Run ≥ 1 000 seeds per null model per cell (seconds of CPU). Uses:

1. Expected entropy curves and T_consensus under neutral copying.
2. The **prior-informed winner-distribution null** for H4.
3. Fitting q to the LLM runs as a descriptive "effective copying rate".

### 3.5 Time axis

- `round` = one scheduling step.
- `t_pc` = cumulative interactions per agent (mean across agents). Random and community: t_pc = round. Star: hub t_pc = round, leaf t_pc ≈ round/(N−1).
- All cross-topology comparisons use `t_pc`. Plots show both axes.

### 3.6 Pilot and pre-registration

1. Study 0 on all label sets.
2. Null models for all cells.
3. LLM pilot: 2 seeds per core cell with `n_rounds = 300`. Record per-cell T_consensus (or plateau).
4. Set confirmatory `n_rounds = max(3 × median plateau t_pc, 100)` per study; the same value across the cells being compared.
5. Freeze templates, label sets, config schema version, and the analysis script, then pre-register (OSF or similar).
6. Confirmatory runs. Pilot runs are never pooled with confirmatory runs.

---

## 4. Feasibility in this repo and the architecture decision

### 4.1 Why not Concordia's GM / entity path

| Brief invariant | Concordia behavior (verified in the installed 2.4 fork) | Verdict |
|---|---|---|
| 1–2 Private memory; no global info in prompts | The GM keeps all events in one memory bank that its LLM reads. Agent observations are **LLM-written** by the GM's `MakeObservation` from that global memory. | ✗ leakage cannot be ruled out |
| 3 Simultaneous commit, reveal only to the dyad | The sequential engine acts one entity at a time. The simultaneous engine's GM narrates all players together in one LLM-written scene. | ✗ |
| 4 No priming words; "two templates only" | `basic__Entity` prepends fixed instructions ("social science experiment… tabletop roleplaying game") plus three LLM reflection steps. `minimal__Entity` allows custom instructions but still wraps them in component labels and a GM-chosen call to action. | ✗ exact template control impossible |
| 6 Exact prompt per call logged | Prompts are assembled inside Concordia components. Only fragments are logged. | ✗ without deep patching |
| Replay / seeds | Concordia's internal random choices cannot be seeded from the builder. | ✗ |
| Cost | ≥ 4–5 LLM calls per agent action plus GM calls, versus 1 call per choice needed. | ✗ at ~1.2 M choices |

A Concordia-native build would require a custom GM (deterministic pairing, non-LLM resolution and observation) and a custom entity (raw prompt). That replaces nearly everything Concordia provides and still fights its act-component formatting. **Not recommended.**

### 4.2 Recommended: protocol engine inside the builder

Reuse from the builder:

- `services/llm_factory.py` providers, API keys, `TemperatureConfiguredModel`, cancellation hook, activity counters.
- The `logs/` folder convention; FastAPI app; SSE progress pattern (`simulations.py` execute stream); React app shell.
- `batch_runner.py` patterns (matrix expansion, status, cancel). Implemented as a new runner class; the Concordia batch runner is not modified.

Do not reuse: Concordia entities, GMs, memory banks, embedder, grounded variables, AI analysis report.

### 4.3 Required changes to the shared LLM layer (small, isolated)

| Change | Reason |
|---|---|
| `get_model(settings)` without loading the SentenceTransformer embedder | Faster startup; the embedder is unused. |
| `AnthropicModel.sample_text`: do **not** pass `seed` to `messages.create` | The current code forwards `seed` to the Anthropic API, which does not take one. Harmless for Concordia, which passes `None`, but this engine passes seeds. |
| `sample_text_with_meta(prompt, …) → (text, meta)` on each wrapper | Needs model version, finish reason, token usage, effective temperature, effective max tokens and latency for the calls log and budget tracking. |
| Allow a small effective output cap for this engine | `TemperatureConfiguredModel` uses `max(requested, settings.max_tokens)`. The OpenAI wrapper floors to 2 000 (non-reasoning) or 10 000 (reasoning) tokens. That is harmless for correctness, but record the effective value. Reasoning models are allowed but flagged (their hidden reasoning and ignored temperature change the interpretation). |

---

## 5. Engine specification

### 5.1 Module layout

```
backend/experiments/naming_game/
  config.py        # ExperimentConfig (pydantic, frozen), validation, canonical JSON + sha256
  labels.py        # nonce generator, label-set store, denylist screening
  templates/       # versioned prompt templates (v1/*.txt) + TEMPLATE_VERSION
  prompts.py       # build_agent_prompt()  ← the ONLY prompt constructor
  agents.py        # Agent (private ring buffer), policies: llm | prior_sample | voter | majority_H | scripted_fixed
  scheduler.py     # pairing per topology, run loop, commit_dyad()  ← the ONLY memory writer
  parser.py        # strict label parser
  store.py         # append-only analyst store (writer only; agents have no handle)
  metrics.py       # population + exposure + test statistics (reads store only)
  nulls.py         # vectorized null-model runs for large seed counts
  runner.py        # async run + matrix/batch runner, checkpoint/resume, cancellation
  cli.py           # python -m backend.experiments.naming_game.cli {calibrate|dry-run|run|matrix|metrics}
  tests/           # acceptance tests (§8)
```

### 5.2 `ExperimentConfig` (immutable; canonical JSON is hashed to `config_hash`)

| field | type / values | default | validation |
|---|---|---|---|
| `schema_version` | str | "1" | |
| `experiment_id` | `rewarded_naming` \| `no_reward_convergence` \| `prior_calibration` \| `null_model` | — | |
| `run_id` | str | uuid4 | |
| `seed` | int | — | required |
| `label_set_id` | str | — | must exist in the frozen label store |
| `n_agents` | 12 \| 24 \| 48 | 24 | even for random_dyad and community |
| `n_rounds` | int | 300 (pilot) | ≥ 1 |
| `pairing` | `random_dyad` \| `star` \| `community` \| `isolated` | random_dyad | `isolated` only for prior calibration |
| `topology_params` | `{n_blocks, p_within, hub_id}` | `{2, 0.9, "a00"}` | p_within ∈ (0,1] |
| `memory_mode` | `none` \| `own_interactions_only` | own_interactions_only | |
| `memory_content` | `own_and_partner` \| `own_only` | own_and_partner | |
| `memory_horizon_H` | int ≥ 1 | 5 | rejected when memory_mode = none |
| `memory_order` | `oldest_first` \| `newest_first` | newest_first | ⚑ DECISION D6 |
| `reward_mode` | `none` \| `local_match` | — | |
| `feedback_mode` | `choices_only` \| `match_indicator` \| `numeric_score` | — | `reward_mode = none` ⇒ ∉ {numeric_score}; `memory_mode = none` ⇒ choices_only |
| `payoff` | `{match, mismatch}` | `{100, -50}` | only when reward on |
| `show_cumulative_points` | bool | true | only with numeric_score |
| `label_pool_size` | 8 \| 10 | 10 | must equal the label set size |
| `n_stimuli` | int | 1 | > 1 later |
| `show_own_agent_id` | bool | true | ⚑ DECISION D7 |
| `policy_default` | `llm` \| `prior_sample` \| `voter` \| `majority_H` | llm | |
| `policy_params` | `{q}` | `{}` | q ∈ [0,1] for voter |
| `committed_minority` | `{frac, start_rule: "after_consensus"\|"round", start_round, label_rule: "least_used_20"}` \| null | null | |
| `yoked_source_run_id` | str \| null | null | B+3 only |
| `model` | `{provider, model_id, temperature, max_tokens_cap}` | — | temperature > 0 |
| `max_concurrency` | int | 24 | |
| `retry` | `{parse_retries: 1, api_retries: 5, backoff_s: 2}` | | |
| `invalid_rate_flag` / `_exclude` | float | 0.02 / 0.05 | |

Also keep a **run manifest** with: `config_hash`, `template_version` + template file hashes, `label_set_hash`, git commit of the repo, package versions, start/end time, provider-reported model versions, and the effective temperature and max tokens.

### 5.3 Labels

- Generator: CVCV (optionally CVCVC) from `C = {b d f g k l m n p r s t v z}` and `V = {a e i o u}`, title-cased.
- Reject when: in an English wordlist; a first name or brand (bundled lists); contains a denylist token as a substring; pairwise Levenshtein < 2 with another label in the set; same first two letters as another label; an alphabetical-sequence pattern.
- Store in `labels/label_sets.json` → `{label_set_id: {labels:[…], hash, generator_seed}}`. Label sets are **fixed across seeds** (R4).

### 5.4 Scheduler

Per round t, using independent RNG streams spawned from `seed` (`numpy.random.SeedSequence`): `pairing_rng`, `order_rng`, `minority_rng`, `tiebreak_rng`.

1. **Pairing.**
   - `random_dyad`: uniform random perfect matching.
   - `community`: agents are split into `n_blocks` fixed blocks. Build a matching by repeatedly taking the lowest-index unmatched agent and choosing a partner block by `p_within` vs `1 − p_within` (uniform over other blocks), then a uniform unmatched agent in that block. Fall back to any unmatched agent if the block is empty. Log the realized within-block share.
   - `star`: exactly one dyad (hub, uniform random leaf).
   - `isolated`: no dyads; each agent acts alone.
2. **Prompts.** For each dyad member, independently: `prompt = build_agent_prompt(agent, config, round, order_rng)`. The label order is shuffled independently per prompt.
3. **Choices.** Both calls are dispatched concurrently. Neither prompt can contain the other's current choice, because the call is built before choices exist. Enforce by construction and test.
4. **Parse.** On invalid output, retry once with the identical prompt and log `attempt = 2`. If still invalid, the dyad is **void**.
5. **Commit.** `commit_dyad(dyad, choices, config)` appends one record to each participant's buffer and nothing else. It computes the payoff if the reward is on.
6. **Log.** The analyst store gets one row per directed participant, plus a calls-log row per model call.
7. **Population row.** After all dyads, compute the round's population metrics (§7.1) in `metrics.py`. They are never passed back to agents.
8. **Checkpoint.** Store writes are append-only per round. Resume reconstructs the buffers from the interactions table (deterministic), so no separate state file is needed.

Within a round, all dyads run in parallel (bounded by `max_concurrency`). Rounds are strictly sequential.

Forbidden (enforced by tests): broadcasting the modal label; any population statistic in a prompt; one conversation thread shared across calls; carrying one dyad's text into a non-participant's prompt; any special prompt for the hub.

### 5.5 Prompt templates (v1, verbatim; rendered by `build_agent_prompt` only)

`templates/v1/base.txt`

```text
You are participant {agent_id}.
A situation is labeled {stimulus_id}.
{interaction_block}{payoff_block}Choose exactly one label from this list:
{shuffled_labels}

Reply with only the label.

Your own recent interactions, if any:
{own_buffer_or_none}
```

`templates/v1/interaction_block.txt`, used in **both** arms whenever `pairing ≠ isolated` (R6):

```text
You are paired with another participant, who chooses from the same list at the same time.
After both choices are submitted, each of you is shown the other's choice.

```

`templates/v1/payoff_block.txt`, **rewarded arm only**:

```text
Scoring rule for this pairing only:
If you and the other participant choose the same label, you receive {match_payoff} points.
If you choose different labels, you receive {mismatch_payoff} points.
Your objective is to maximize your own points across pairings.
{cumulative_line}
```

`cumulative_line` = `Your cumulative points so far: {total}` when `show_cumulative_points`, else empty.

Rendering rules:

- `{agent_id}` is omitted (the whole line is dropped) if `show_own_agent_id = false`.
- `{shuffled_labels}`: one label per line, preceded by "- ". The order comes from `order_rng`, per prompt.
- `{own_buffer_or_none}`: "None." if the buffer is empty or memory is off. Otherwise one line per record in `memory_order`, with **relative** indices (R10):
  - `own_and_partner`, `choices_only`: `- {k}: you chose {self}; the other participant chose {partner}.`
  - `own_and_partner`, `match_indicator`: … `the other participant chose {partner} (same label).` / `(different labels).`
  - `own_and_partner`, `numeric_score`: … `the other participant chose {partner}; you received {points} points.`
  - `own_only`, reward none: `- {k}: you chose {self}.`
  - `own_only`, `numeric_score`: `- {k}: you chose {self}; you received {points} points.`
  - where `{k}` = "Latest interaction", "2 interactions ago", …
- No other text anywhere. No "therefore", no evaluative words.

`build_agent_prompt` returns `(prompt_text, label_order_shown, memory_round_ids_included)`. Its output is the exact string sent as the single user message. The calls log records it verbatim together with the provider message structure.

### 5.6 Denylist and leakage guard

- The denylist is case-insensitive and word-boundary matched: consensus, agree*, disagree*, coordinat*, cooperat*, align*, success*, fail*, "common language", converge*, "the group", majority, most (as a quantifier), popular, winning, collective, everyone, population, other participants, and any digit sequence followed by "agents" or "%".
- Extra words for reward-off runs: points, score, reward, payoff, win, lose.
- The guard runs on **every** rendered prompt before dispatch. A hit aborts the run (fail-closed) and writes a leakage report.

### 5.7 Parser

- Normalize: strip whitespace, surrounding quotes or backticks, one trailing period; case-insensitive comparison.
- Valid iff the normalized output equals exactly one label in the pool.
- Anything else (extra words, two labels, empty output, a label not in the pool) is invalid. The raw text is always stored. Never fuzzy-map to the nearest label.

### 5.8 Policies

- `llm`: the prompt goes to the configured model.
- Rule policies (§3.4) implement the same interface `choose(agent, config, round, rngs) → label` and read **only** the agent's own buffer (plus `p0` for fallback). They produce no model calls but full log rows (`policy` column).
- Committed-minority agents: `scripted_fixed`, chosen from `minority_rng` at the start rule. They appear to partners exactly like other agents. Metrics are reported with and without them.

---

## 6. Analyst store (agents have no handle to it)

Layout: `logs/experiments/{experiment_id}/{run_id}/`

| file | content |
|---|---|
| `config.json`, `manifest.json` | §5.2 |
| `calls.jsonl` | one row per model call: `call_id, round, agent_id, attempt, prompt_text, prompt_sha256, provider_messages, raw_output, parsed_label, valid, model_version, finish_reason, tokens_in, tokens_out, latency_ms, effective_temperature, effective_max_tokens` |
| `interactions.csv` | one row per directed participant per dyad: `run_id, seed, config_hash, label_set_id, round, t_pc, dyad_id, agent_id, partner_id, policy, is_minority, stimulus_id, choice, partner_choice, match, void, points, cum_points, memory_records_included, label_order_shown, choice_position, reward_shown, feedback_text_shown, block_id, within_block` |
| `population.csv` | one row per round per stimulus: `round, t_pc_mean, entropy, entropy_norm, modal_label, modal_share, n_unique_labels, n_unique_last20pct, switch_rate, invalid_rate, void_rate` — each computed on (a) this round's choices and (b) the **population state** (each agent's latest valid choice) |
| `summary.json` | run-level outcomes (§7.2) |
| `leakage_report.json` | guard results; must be `passed: true` |

Writes are append-only and flushed each round. `metrics.py` may read the store; nothing in the agent path imports `store.py` for reading.

---

## 7. Metrics and analysis (computed; never judged by an LLM)

### 7.1 Population metrics

- Population state `s_i(t)` = agent i's latest valid choice. Shares `p_k(t)`.
- `entropy = −Σ p_k log2 p_k`; `entropy_norm = entropy / log2 K`.
- `modal_share = max_k p_k`; `n_unique_labels`.
- `switch_rate(t)` = share of agents acting at t whose choice ≠ their previous valid choice.

### 7.2 Run-level outcomes

- **Consensus:** `modal_share(state) ≥ 0.9` for ≥ `W` consecutive rounds, with `W = max(10, 0.05 × n_rounds)`. `T_consensus` = first round of that window (in `t_pc`). ⚑ DECISION D8 (threshold).
- **Fragmentation:** over the last 20 % of rounds, ≥ 2 labels each with mean share ≥ 0.3.
- **Final modal label** and **final modal share** (mean over the last 20 %).
- `n_unique_last20pct`, mean switch rate over the last 20 %, invalid and void rates.

### 7.3 Cell-level contrasts

- Entropy trajectories: mixed model `entropy_norm ~ condition × f(t_pc) + (1 | run)`. The key contrast is each memory cell vs the memory-none cell with the same reward, using equal `t_pc` windows.
- Consensus and fragmentation rates by cell (logistic, cluster by label set).
- LLM vs null models: overlay the median ± IQR curves. Compare `T_consensus` distributions (Kolmogorov–Smirnov) and the fitted voter q.

### 7.4 Individual choice model (H3)

For agent i at round t, over labels k (conditional logit, SE clustered by run; label-set fixed effects):

```
U_ik = β1·own_prev_ik + β2·own_count_H_ik + β3·partner_count_H_ik
     + β4·log p0_k + β5·position_ik + β6·(reward × partner_count_H_ik) + ε
```

- `own_prev` = 1 if k was i's last valid choice.
- `own_count_H` = times i chose k among the records in the prompt.
- `partner_count_H` = times partners chose k among the records in the prompt.
- `position` = displayed position of k.

Emergence-relevant evidence: β3 > 0 in `own_and_partner` cells (absent by construction in `own_only`), controlling for β1, β2, β4 and β5. The brief's `personal_exposure` and `local_partner_prevalence` are exported too, for continuity.

Exposure variables are computed **only from records actually rendered into that prompt** (`memory_records_included`), not from full history.

### 7.5 Path dependence and collective bias (H4)

- For each cell and label set: winners `w_s` across seeds (consensus runs only; fragmentation reported separately).
- Null: the distribution of winners under `majority_H` or fitted `voter(q)` with first moves from `p0`, 10 000 simulated seeds.
- Statistic: entropy of the winner distribution, plus P(winner = argmax p0). The p-value comes from the null simulation.
- **Collective bias** (in the Ashery et al. sense): P(winner = k) vs p0(k). Strong over-representation of a label that is only weakly favored individually is a collective bias; it is reported, not treated as emergence failure.

### 7.6 Emergence decision checklist (analyst, per study)

1. Entropy decline vs the memory-none baseline, beyond the null `prior_sample`.
2. The winner distribution is more dispersed than the prior-informed null.
3. β3 > 0 beyond β1, β2, β4, β5.
4. Study A: report the rate of stable multi-convention fragmentation. Local success does not imply global consensus.
5. `own_only` controls do not reproduce the population convergence.
6. The leakage audit passed for 100 % of included runs; invalid rate is under the threshold.

---

## 8. Automated acceptance tests (must pass before any paid run)

From the brief:

1. **Memory isolation.** After a round, a buffer grows iff the agent was in a non-void dyad. Non-participants' buffers are byte-identical.
2. **Prompt audit.** For every agent C and every dyad C did not join, no label pair or record from that dyad appears in C's next prompt. Checked with tagged dummy labels in dry run.
3. **No global stats.** Denylist and regex (`\d+\s*(agents|participants|%)`, "most", "majority") find no hit in any rendered prompt. (Templates therefore say "Latest interaction", never "Most recent".)
4. **Reward switch.** With `reward_mode = none`: no "points", "score", "reward", "success", "failure" in any prompt.
5. **Order randomization.** Over 100 draws, the two dyad members' label orders differ in > 90 % of draws. Each label's first-position frequency is within binomial bounds.
6. **Replay.** Same seed + config hash ⇒ identical pairings, label orders, minority assignment and rule-policy choices.
7. **Parser.** Prose, two labels, empty output or an out-of-pool label ⇒ invalid; the raw text is stored; nothing is coerced.

Added:

8. **Simultaneity.** Neither prompt of a dyad contains the partner's current-round choice. Asserted by building prompts before dispatch and scanning them.
9. **Arm symmetry.** Rendered prompts of paired reward/no-reward configs (same seed) differ **only** by `payoff_block` and buffer suffixes. Checked by diffing.
10. **Config validation.** All illegal combinations in §5.2 are rejected: reward none + numeric_score; memory none + H; T = 0; odd N with random_dyad; `match_indicator` in core cells.
11. **Hub neutrality.** The hub's prompts are template-identical to leaves' prompts.
12. **Resume.** A run killed at round r and resumed equals an uninterrupted run with the same seed (rule policies).
13. **Null-model sanity.** `majority_H` with N = 24, H = 5 reaches consensus in the large majority of 1 000 seeds (exact rate recorded on first implementation, then frozen as a regression test); `prior_sample` entropy stays within sampling noise of the analytic entropy of p0.
14. **Store isolation.** Static check: no module under `agents.py` or `prompts.py` imports `store` or `metrics`.
15. **Label hygiene.** Every label set passes the §5.3 rules. No label contains a denylist substring.

`dry_run` mode runs the whole pipeline with a mock model (uniform random, or `majority_H`) and zero network calls. The tests use it.

---

## 9. API, CLI and UI additions

**CLI (primary for batches):**

- `calibrate --label-set L1 --model …` runs Study 0.
- `run config.json`
- `matrix study_a.yaml` expands the factorial, estimates cost, asks for confirmation, then runs with resume.
- `metrics logs/experiments/…` recomputes all metrics.
- `nulls study_b.yaml --seeds 1000`

**API** (`/api/experiments/naming-game/…`):

| endpoint | purpose |
|---|---|
| `POST /validate` | config validation + cost estimate |
| `POST /dry-run` | pipeline with mock model; returns sample prompts + test results |
| `POST /calibrate` | Study 0 (SSE progress) |
| `POST /run` | single run (SSE: round, entropy, modal share, invalid rate) |
| `POST /matrix`, `GET /matrix/{id}`, `POST /matrix/{id}/cancel` | batch |
| `GET /runs`, `GET /runs/{id}/summary`, `GET /runs/{id}/export` | results (zip of the store) |

**UI:** one new top-level page, "Naming Game".

1. Config form with validation messages, prompt preview (the rendered example prompt for both arms), and a live cost estimate.
2. Run monitor: live entropy and modal-share lines.
3. Results: entropy/modal-share curves (median ± IQR by cell, LLM vs null), winners-by-seed table, fragmentation and consensus rates, invalid rates, leakage status.

The existing Concordia builder UI is untouched.

---

## 10. Budget and runtime (brief's defaults; recompute after the pilot)

Calls per run = choices = `n_agents × n_rounds` for random and community, `2 × n_rounds` for star.

| block | runs | calls |
|---|---|---|
| Study B core 2 × 2 × 30 | 120 | 864 000 |
| Study A random (H 1/5/10: 10/30/10 seeds), minus 30 shared with B | 20 new | 144 000 |
| Study A community 3 × 10 | 30 | 216 000 |
| Study A star 3 × 10 | 30 | 18 000 |
| Study 0 (per label set) | — | 400 × 3 |
| **Total** | **200** | **≈ 1.24 M** |

- Input tokens ≈ 200–300 per call ⇒ **≈ 250–370 M input tokens**. Output is ~3–5 tokens per call for non-reasoning models; reasoning models add hidden tokens and are not recommended for the confirmatory runs.
- Cost ≈ input tokens × the provider's current per-token price. Check before running; the CLI prints the estimate from `model_pricing.yaml`, which you maintain.
- Wall-clock: rounds are sequential. With ~24 concurrent calls per round at ~1–1.5 s latency, a 300-round run takes 5–8 min. The full matrix takes ~17–25 h, bounded by provider rate limits.
- Controls B+1/B+2 add 20–60 runs. The minority study (N = 48) adds cost proportional to N.
- The pilot will very likely cut `n_rounds` and therefore cost by a large factor.

---

## 11. Threats to validity (report in the paper)

- **Single-model population.** Shared priors make coordination easier. Generalize with ≥ 2 model families.
- **Instruction-following as a hidden goal.** Even without reward, "choose one label" plus visible partner history is a demand cue. The `own_only` control and the null models bound this.
- **Provider nondeterminism and silent model updates.** Log the model version per call; run cells interleaved, not sequentially.
- **Nonce labels still carry phonotactic preferences.** Handled by prior calibration and the log p0 covariate.
- **Construct scope.** A convention over nonce labels is the minimal institution (a Lewis convention). Extending the claim to richer institutions needs the later natural-language studies (e.g., Ashford Valley).

---

## 12. Implementation plan

| milestone | contents | done when |
|---|---|---|
| M1 core | config, labels, templates, prompts, parser, agents (rule policies), scheduler, store, dry run | tests 1–15 pass with the mock model |
| M2 LLM layer | `get_model`, Anthropic seed fix, `sample_text_with_meta`, concurrency and backoff | 1 real call per provider logged with meta |
| M3 metrics + nulls | §7 metrics, vectorized null models, summary.json | null-model sanity test passes; plots reproduce |
| M4 CLI + matrix | matrix expansion, cost estimate, resume | a 2-seed pilot matrix runs end-to-end |
| M5 API + UI | endpoints, Naming Game page | a run can be launched and inspected from the browser |
| M6 pilot | Study 0 + pilot + n_rounds decision | pre-registration draft |

---

## 13. Decisions (⚑) — accepted 2026-09-24

| id | question | accepted decision |
|---|---|---|
| D1 | Put the neutral interaction block in both arms, and drop "You will not be told other participants' choices"? | Yes to both. |
| D2 | Star: scale `n_rounds` to match leaf `t_pc`, or keep equal rounds and caveat? | Keep equal rounds for Study A comparability with the brief; add one scaled star cell as robustness. |
| D3 | Invalid-rate flag / exclude thresholds | 2 % / 5 % |
| D4 | Temperature | Provider default (≈1.0); log the effective value; T as a robustness factor later. |
| D5 | Label-prior gate: regenerate vs covariate | Regenerate once; if still biased, keep it and use the covariate. |
| D6 | Buffer order newest-first vs oldest-first | Newest-first. Oldest-first as robustness (recency effects in LLMs). |
| D7 | Show "You are participant {id}"? | Keep (brief fidelity); robustness cell without it. |
| D8 | Consensus threshold 0.9 and window W | 0.9, W = max(10, 5 % of rounds) |
| D9 | Core model(s) | One mid-size non-reasoning model for all confirmatory cells; a second family for replication. **Specific model IDs: still open — Yuhan to name before the M6 pilot.** |
