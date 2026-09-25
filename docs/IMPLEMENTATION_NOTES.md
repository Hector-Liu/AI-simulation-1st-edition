# Implementation notes (v1.0 → v2 step 1, 2026-09-24)

How this engine implements `SPEC-naming-game-v1.0.md`, where it had to make a
choice the SPEC left open, and what is not built yet. Read this before
pre-registration.

## Architecture

A standalone protocol engine. It does **not** import Concordia (SPEC §4.1, decision #5).
It keeps the same ideas as the old builder (provider layer, logs folder, web
UI) in a much smaller codebase:

| module | role |
|---|---|
| `config.py` | immutable `ExperimentConfig`, every validation rule of §5.2, canonical JSON → `config_hash` |
| `labels.py` | CVCV nonce generator, screening rules (§5.3), frozen store `data/label_sets.json`, denylist guard (§5.6) |
| `templates/v1/` | verbatim prompt text (§5.5) + buffer-line formats |
| `prompts.py` | `build_agent_prompt()`, the only prompt constructor |
| `agents.py` | `Agent` (private ring buffer), rule policies |
| `scheduler.py` | pairing, run loop, `commit_dyad()` (the only memory writer), resume |
| `parser.py` | strict parser (§5.7) |
| `llm.py` | Anthropic / OpenAI-compatible / mock clients returning text + metadata |
| `store.py` | append-only analyst store (§6) |
| `metrics.py` | population metrics, run summary, Study 0 prior + gate, H3 export |
| `runner.py` | background jobs, cost estimate, matrix expansion, dry run |
| `transcript.py` | readable per-round transcripts (who met whom, choices, outcome) as .txt and .csv |
| `api.py`, `web/` | local web app (single process) |
| `cli.py` | command line |

## Choices the SPEC left open

1. **Randomness.** Every draw uses `SeedSequence(seed, spawn_key=(stream, round[, agent]))`, with streams pairing, order, minority, tiebreak and policy. Draws therefore do not depend on async completion order, and resume needs no RNG state. Replay (test 6) and resume (test 12) both rely on this.
2. **`config_hash` excludes `run_id` and `notes`.** Two runs with the same design and seed share a hash.
3. **Study 0 population.** `n_agents` is limited to 12/24/48, except that 20 is also allowed when `pairing = isolated` (SPEC §3.1 asks for 20 sterile agents).
4. **Payoff block layout.** A blank line follows the payoff block, as it does after the interaction block. When `show_cumulative_points = false`, the cumulative line is removed entirely, not left as an empty line.
5. **`majority_H` ties.** Partner-label ties go to the agent's own last choice if it is among the tied labels. Otherwise they are broken by a p0-weighted draw. With an empty buffer, the first move is drawn from p0.
6. **`voter(q)` under `own_only`.** No partner label is visible, so the agent always repeats itself. Rule policies see exactly what the LLM would see.
7. **Committed minority.** Activation happens at the first round after the consensus window completes, or at `start_round`, whichever comes first. The label is the least-used label over the previous 20 rounds (all pool labels counted, ties broken by the minority RNG). Members are drawn uniformly without replacement. Minority agents are `scripted_fixed`: they make no calls, and their prompts are still rendered and logged. Star + minority is rejected.
8. **Invalid rate.** The flag and exclude thresholds (D3) apply to choices that are still invalid after the retry, i.e. choices that void a dyad. First-attempt failures are visible in `calls.jsonl` (`attempt = 1`, `valid = false`).
9. **Parser strictness.** Markdown emphasis (`**Laba**`) and trailing `!` are invalid. Only whitespace, one layer of quotes or backticks, and one trailing period are stripped.
10. **Modal-label ties** in `population.csv`: the alphabetically first label.
11. **p0** is an explicit config field (hashed). If it is empty, p0 is uniform. After Study 0, copy `p0_smoothed` (add-0.5 smoothing) from the calibration run into later configs for the same label set.
12. **Label screening data.** Snapshots of `/usr/share/dict/web2` (3–6 letters) and `propernames` are bundled, together with a small hand-made brand list. Words from other languages are **not** screened (e.g. *Soru* means "question" in Turkish). Check label sets by eye before pre-registration.
13. **Anthropic sampling.** Temperature is sent only to models that accept it (Haiku 4.5, Sonnet/Opus 4.6). Opus 4.7+/Sonnet 5/Opus 5 reject temperature, so the provider default is used and logged. Sonnet 5 and Opus 5 get `thinking: {type: disabled}`. Opus 5.5 and Fable cannot disable reasoning: they are flagged in the UI and the manifest, sent `output_config.effort = low`, and given a 2048-token output floor so hidden reasoning is not cut off (the effective cap is logged per call). No seed is ever sent to a provider.

## Verified

- `pytest`: 55 tests, including SPEC §8 tests 1–15, run offline with the mock model.
- Test 13 frozen value: over 1000 seeds, `majority_H` (N = 24, H = 5, 100 rounds) reaches consensus in 100 % of seeds. The regression floor is 0.99.
- One real smoke run: `claude-haiku-4-5`, 12 agents × 3 rounds = 37 calls (one prose answer was retried). Leakage passed, 0 invalid after retry, about $0.007. It is a plumbing test only and is not data.

## Not built yet (next milestones)

- Vectorized null-model runner for 10 000-seed H4 winner-distribution nulls. Rule policies already run through the real scheduler (≈0.13 s per 300-round run).
- Fitting the conditional logit (H3). The engine exports `choice-model.csv`; fit it in R or statsmodels.
- The mixed model for entropy trajectories, the KS tests, and fitting the voter `q`.
- Yoked exposure control B+3 (`yoked_source_run_id` is rejected by validation).
- `n_stimuli > 1`, and mixed-model populations (per-agent `model_id`).
- Anthropic Message Batches (50 % cheaper) for large matrices. Rounds are sequential, so batching would need one batch per round.


---

## v2, step 1 (design decisions of 2026-09-24)

Implemented from `SPEC-naming-game-v2.0-draft.md` together with Yuhan's decisions:

| Decision | What was built |
|---|---|
| Six-room design (2 × 3), rooms chosen by hand | `rooms.py` defines B0/B1/B2/A0/A1/A2. Each config carries a `cell_id`, and validation rejects a config whose settings do not match its room. The **Study Plan** page shows the 2 × 3 grid: tick any rooms, pick label sets, runs per set, agents, rounds, H, model, temperature and phase, then launch. Each room opens a panel with its entropy curves, winners and a table of runs; every run opens a detail dialog |
| Control rooms are optional and run separately | B2R / A2R (prior replay, `partner_source = prior_replay`) and NS2 (`framing = nonsocial`) appear in their own section of the Study Plan. Their results are listed like any other room. A replay room derives its prior from finished B0 / A0 runs on the same label set, model and temperature (`priors.py`), or from an explicit uniform prior |
| 3 preset label sets + unlimited custom sets | New presets P1–P3 were generated, screened (English dictionary, names, brands, a curated multilingual list in `data/problem_words.txt`) and **picked by hand**. The v1 sets L1–L3 are kept read-only as "legacy" so old runs stay readable. The **Label sets** page creates, clones, edits and deletes custom sets (`user_data/label_sets.json`). Errors (duplicates, spaces, banned strings) block saving; hygiene problems are shown as warnings. A set becomes locked once it has runs |
| OpenAI as the second family (model not chosen yet) | The **API & Models** page stores OpenAI model IDs together with a user-entered price, and has a test button. Reasoning models are flagged |
| Temperature | Default **1.0**, set explicitly and logged. See "Temperature" below |
| Template v2 | Agent id hidden by default; own-only rooms use an interaction paragraph without "each of you is shown the other's choice"; the payoff objective reads "maximize your own points"; non-social templates for NS2. The v1 templates are kept for replaying old configs |
| Metrics | `entropy_final` (primary); consensus at τ = 0.8 / 0.9 / 0.95; `fragmentation_stable`; seeded random tie-breaks with tie flags; extended choice-model columns (`own_prev_visible`, `own_prev_history`, `partner_last`, `matched_k`, `recency_w_partner`, `pos_first`, `pos_last`, `pre_consensus`) |
| Ops | `phase` (pilot / confirmatory / exploratory / test; mock runs are always test); `pin_version = auto` stops a run if the model version changes; Study Plan batches run in a shuffled (interleaved) order; confirmatory runs may only use priors derived from pilot runs |
| Minority | `random_nonmodal` label rule (default) and `end_round` (planted history) |

Tests: 76 in total (v1 acceptance tests 1–15, SPEC v2 tests 16/17/23/24/26/28–30, rooms, study-plan expansion, label sets, priors, API).

### Temperature: why 1.0 and not 0.5

Temperature T rescales the model's choice probabilities to p^(1/T), so T = 0.5 roughly **squares** them. Nonce-word priors are often uneven, and squaring makes the most-preferred label much more dominant in round 0. With T = 0.5, every room, including the no-memory baseline, would therefore tend to "agree" on the prior favourite before any interaction happens. That creates a floor effect for H2a (key vs own-only) and pushes H4 towards "the prior decides". T = 1.0 samples from the model's own distribution, which is the natural reference point for a prior. It is also the provider default, so behaviour is comparable across providers. Low temperatures are best run as a robustness factor (for example 0.7 in the pilot). The UI lets you set any value above 0.

### Still to build (next steps)

- Probes (P-CF counterfactual, P-LOCK lock-in, P-MC manipulation check) and the Probes page.
- Vectorized null models with the innovation term ε; γ estimation; the H4b early-state test; the power simulation.
- `fitted_logit` policy (H6); the prereg bundle export.
- Token-count balance for labels (D24) and the edit-distance-to-common-English rule. Until then, human review of label sets is the safeguard.
