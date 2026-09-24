# Implementation notes (v1.0, 2026-09-24)

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
13. **Anthropic sampling.** Temperature is sent only to models that accept it (Haiku 4.5, Sonnet/Opus 4.6). Opus 4.7+/Sonnet 5/Opus 5 reject temperature, so the provider default is used and logged. Sonnet 5 and Opus 5 get `thinking: {type: disabled}`. Opus 5.5 and Fable cannot disable reasoning and are flagged in the UI and the manifest. No seed is ever sent to a provider.

## Verified

- `pytest`: 53 tests, including SPEC §8 tests 1–15, run offline with the mock model.
- Test 13 frozen value: over 1000 seeds, `majority_H` (N = 24, H = 5, 100 rounds) reaches consensus in 100 % of seeds. The regression floor is 0.99.
- One real smoke run: `claude-haiku-4-5`, 12 agents × 3 rounds = 37 calls (one prose answer was retried). Leakage passed, 0 invalid after retry, about $0.007. It is a plumbing test only and is not data.

## Not built yet (next milestones)

- Vectorized null-model runner for 10 000-seed H4 winner-distribution nulls. Rule policies already run through the real scheduler (≈0.13 s per 300-round run).
- Fitting the conditional logit (H3). The engine exports `choice-model.csv`; fit it in R or statsmodels.
- The mixed model for entropy trajectories, the KS tests, and fitting the voter `q`.
- Yoked exposure control B+3 (`yoked_source_run_id` is rejected by validation).
- `n_stimuli > 1`, and mixed-model populations (per-agent `model_id`).
- Anthropic Message Batches (50 % cheaper) for large matrices. Rounds are sequential, so batching would need one batch per round.
