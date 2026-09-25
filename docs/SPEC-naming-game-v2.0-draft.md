# SPEC v2.0 (DRAFT) — Naming-game experiments: revised design and software changes

Status: **DRAFT (2026-09-24). Step 1 implemented** (rooms, templates v2, controls B2R/A2R/NS2, label-set manager, metrics, ops). See `IMPLEMENTATION_NOTES.md` § v2 step 1. Decisions of 2026-09-24 amend this draft: three preset label sets plus unlimited custom sets instead of ten fixed sets; control rooms are optional and launched separately; OpenAI is the second family (model TBD); default temperature 1.0.
Supersedes: `SPEC-naming-game-v1.0.md` where they differ. Sections of v1 not mentioned here stay in force.
Inputs:
- the reviewer memo "命名博弈实验设计审阅意见" (2026-09-24), with P1-1…P3-8;
- the full review package `Review_Naming_Game_Guide_v0.1.md` (EIC, R1–R3, DA, editor decision; items R1…R9, S1…S10). Items that are not in the memo are marked **[pkg]**;
- `Naming_Game_Experiment_Guide.md` v0.1;
- `IMPLEMENTATION_NOTES.md`.
Companion for human review (Chinese): `Review_Response_and_Design_v2.md` / `.docx`.

Decisions that need Yuhan's sign-off are marked **⚑ Dxx** and collected in §11.

---

## 0. Summary of changes

| Area | v1 | v2 |
|---|---|---|
| Core design | 2 × 2 (reward × memory none/own_and_partner); the rewarded memory cell shared with Study A (numeric_score) | **2 × 3** (reward × memory none / own_only / own_and_partner), all with `choices_only` feedback. Score feedback becomes its own factor (P1-1, P1-3) |
| Primary contrast for social influence | memory vs memory-none | **own_and_partner vs own_only** (H2a, H1a). Memory-none is secondary (P1-3) |
| Label prior p0 | Study 0 (isolated template) | **Prompt-matched p0** from each arm's memory-none cell (plus round-0 choices of every cell). Study 0 is kept only as a label gate and as a "context sharpening" measure (P1-2) |
| H3 | β3 > 0 treated as emergence evidence | Mechanism evidence only. **Causal counterfactual probes**; richer choice model (P1-4) |
| H4 statistic | winner-distribution entropy per label set | **Prior-sensitivity exponent γ** plus winner rank in matched p0, pooled over 10 label sets, compared with noisy null models. A(k) is descriptive only (P2-1, P2-2) |
| Label sets | 3 (L1–L3) | **10**, regenerated with stricter screening and a human review. No formal data exist yet, so L1–L3 are replaced rather than patched (P2-1, reply 2) |
| Primary outcome | consensus / T_consensus | **entropy_final** = mean normalized state entropy over the last 20 % of rounds. Consensus is secondary; its threshold is checked against a measured noise floor (P2-4) |
| Null claims | two-sided test | SESOI + **TOST** equivalence (P2-3) |
| Agent id in prompt | shown (aNN) | **hidden by default**; aNN only as a robustness cell (P2-5) |
| Templates | v1 | **v2**: own_only interaction block without the "shown the other's choice" sentence; payoff objective without "across pairings" (reply 1, P3-3) |
| Micro → macro | — | **fitted_logit** rule policy fitted on probe data; predicts macro outcomes out of sample (P2-9) |
| Manipulation check | — | self-report probe (human-coded) **plus** a behavioural check from the probes (P2-6) |
| Second model family | TBD | Open-weights model through an OpenAI-compatible server with **logprobs** (P2-7) |
| Exploratory | star / community / minority as Study A rows | star (t_pc-scaled, cheap), community with p_within ∈ {0.8, 0.9, 0.99}, minority grid 2–30 %, temperature 0.7 / 1.0 (P3-1, P3-2, P3-4) |
| Feedback-loop control [pkg] | B+3 yoked replay not implemented | **Prior-replay cells B2-R / A2-R**: the partner label shown is drawn i.i.d. from the arm's matched p0, not from the partner. The feedback loop is cut; the framing is identical. Confirmatory control |
| Exposure vs social framing [pkg] | — | **Non-social framing cell NS2**: same closed loop as B2, but the partner's choice is presented as "the reference label shown". Secondary control |
| Path dependence [pkg] | only across-seed winner dispersion | **H4b**: the early state (shares at t_pc = 3) predicts the winner beyond label-specific constants, compared with the same statistic under the nulls. Optional **planted-history** manipulation (E5) |
| T_consensus [pkg] | KS test | Survival analysis (Kaplan–Meier; Cox stratified by label set) on the t_pc axis; right-censoring handled |
| Ops | — | model snapshot pinning, interleaved cell order, pilot/confirmatory separation, per-condition invalid-rate report, random tie-breaks for modal labels (P3-5–P3-7, reply 6) |

---

## 1. Constructs and terminology (P2-8)

- **Rewarded arm:** "convention in the naming-game sense" (Baronchelli et al. 2006), a minimal form of a Lewis convention. It is not a full Lewis convention: there is no common knowledge.
- **No-reward arm:** "shared behavioural regularity." It is called a convention only if the probes show a **conditional-conformity structure**: in the no-reward arm, the probability of choosing k rises with partner exposure, beyond self-persistence. That is an empirical result, not an assumption.
- **Emergence claim (unchanged in spirit):** which regularity wins is (a) not fixed by the prompt-matched prior, (b) path-dependent across seeds, and (c) either predicted from the individual choice function (**weak emergence, explained micro → macro**) or not (**higher-order history effects**). Both outcomes of (c) are reportable (§7.6).

---

## 2. Hypotheses (revised)

| id | Statement | Test | Family |
|---|---|---|---|
| **H2a** | No reward: `entropy_final(own_and_partner) < entropy_final(own_only)` at H = 5 | mixed model (§7.3); TOST if not significant | **primary** |
| **H4** | The winner distribution is **less prior-determined** than the noisy-voter null: γ̂ < γ_null (§7.5) | γ, simulation p-value | **primary if the power simulation gives ≥ 0.8 at the planned N, otherwise secondary (⚑ D14)** |
| **H4b** [pkg] | Early state predicts the winner beyond label constants more strongly than under the noisy-voter null | multinomial logit, §7 step 4b | secondary (becomes primary H4 if γ power is < 0.8) |
| **H7** [pkg] | Closing the loop matters: `entropy_final(B2) < entropy_final(B2-R)`, and likewise A2 < A2-R | as H2a | **confirmatory control** (secondary family) |
| H1a | Reward: `entropy_final(own_and_partner) < entropy_final(own_only)` | as H2a | secondary |
| H2b / H1b | Each memory cell < its arm's memory-none cell | as H2a | secondary |
| H3 | Causal partner-exposure effect: in counterfactual probes, P(choose k) rises with the number of partner-k records, holding own records fixed | probe regression (§6.1) | secondary (mechanism) |
| H6 | `fitted_logit`, fitted on probe data, predicts LLM macro outcomes (entropy_final, T_consensus, γ, fragmentation rate) within its 90 % predictive interval | posterior-predictive check (§7.6) | secondary |
| H8 [pkg] | Social framing matters beyond exposure: `entropy_final(B2) < entropy_final(NS2)` (no reward) | as H2a | secondary |
| H5 | Community topology: fragmentation rate rises with p_within; star winners track the hub's individual prior [pkg] | logistic; winner vs hub-prior rank | exploratory |
| E1–E5 | Score feedback (numeric_score vs choices_only); H length; temperature; committed-minority tipping curve; planted history [pkg] | descriptive / curve fit | exploratory |

Multiple comparisons (P3-8): Holm within the primary family (2 tests) and within the secondary family. Exploratory results are labelled as such and not corrected.

---

## 3. Experimental design (revised)

### 3.1 Label sets (P2-1)

- **Generate 10 sets × 10 CVCV labels** (L1–L10). Sets must be disjoint.
- Screening adds to v1 §5.3:
  - (a) bundled lists of common words in the major languages that use Latin script (EN, ES, PT, IT, FR, DE, NL, TR, ID/MS, TL, plus Chinese pinyin syllable pairs and Japanese romaji);
  - (b) rejection of any label within edit distance 1 of a word in a bundled **frequency** list of common English words (removes *Kife*~knife, *Sefe*~safe);
  - (c) no near-homographs of common brands or technical terms (*Vifi*~WiFi).
- (d) [pkg] **token-count balance**: every label in a set has the same number of tokens under the primary model's tokenizer. For Anthropic this is measured with the token-counting endpoint as the count difference between a fixed carrier sentence with and without the label; for the open model the tokenizer is used directly. The token count is also exported as a diagnostic covariate.
- (e) [pkg] the language lists also include Swahili.
- **Human review gate:** the tool exports a review sheet. Yuhan (and ideally one more person) mark each label ok / replace. Replacements come from the same generator. Then freeze: `label_sets.json` gets a hash and a `frozen_at` date. **Freeze before the first pilot run.** After that, the v1 rule "never regenerate" applies.
- L1–L3 are replaced, not kept. They have only smoke-test and mock data, which never count as study data.

### 3.2 Study 0 (kept, role narrowed)

- Isolated template, 20 agents × 20 choices per label set. That is 400 calls/set, 4 000 calls in total, about $0.8 on Haiku.
- Uses:
  - (a) **label gate**: v1 rule. On a flag, regenerate that set once; if it is still flagged, keep it and report;
  - (b) **context sharpening**: compare p0_isolated with the prompt-matched p0_B and p0_A (§3.4); report the KL divergence and the entropy difference.
- It is **no longer** the source of p0 for nulls, covariates or first moves.

### 3.3 Core 2 × 3 design (P1-1, P1-3)

Fixed across core cells:
- random_dyad, N = 24, H = 5, newest-first;
- `feedback_mode = choices_only`, `show_cumulative_points = false`;
- agent id hidden;
- template v2;
- matched seeds: the same 30 (label set, seed) pairs, 10 label sets × 3 seeds, used in **every** cell.

|  | memory none | own_only | own_and_partner |
|---|---|---|---|
| **no reward** | B0: prior baseline → p0_B | B1 (was B+1) | **B2: key cell** |
| **local_match reward** | A0: focal-point control → p0_A | A1 | **A2** |

- Within each memory column, the two reward arms differ **only** by the payoff block. Test 9 enforces this for all three columns.
- Between own_only and own_and_partner, prompts differ by (i) the second sentence of the interaction block and (ii) the partner clause in memory lines. Both differences are reported. The manipulation check (§6.3) tests whether (i) changes the perceived task.
- Crossed (label set, seed) pairs across cells mean every contrast is **paired within label set × seed**. The same seed gives the same pairing schedule and label orders (common random numbers).

### 3.3a Loop and framing controls [pkg]

| cell | settings | question |
|---|---|---|
| **B2-R** prior replay | as B2, but `partner_source = prior_replay`: every record's partner label is drawn i.i.d. from p0_B(ls) with the `policy` RNG stream; the agent's own choice goes nowhere | Does convergence need the closed interaction loop? (H7) |
| **A2-R** prior replay | as A2, with p0_A; the payoff is computed against the replayed label | as above, reward arm |
| **NS2** non-social framing | as B2 (the closed loop stays: the label shown is the partner's real choice), but `framing = nonsocial`: the interaction block and the memory lines describe a "reference label", not another participant | Social framing vs plain in-context exposure (H8) |

Each has 30 runs with the same (label set, seed) pairs.
- Prior replay replaces the editor's full yoked replay (B+3). Full yoked replay stays as an exploratory option for a later version.
- Prior replay is stationary exposure: it tests the loop, not the time course of exposure.
- NS2 templates (verbatim, guarded):
  - interaction block: `After you choose, a reference label from the same list is shown to you.`
  - memory line: `- {k}: you chose {self}; the reference label shown was {partner}.`

### 3.4 Prompt-matched priors (P1-2)

- With the agent id hidden and `choices_only` feedback, the round-0 prompt of the own_and_partner cell of an arm is **byte-identical** to the prompts of that arm's memory-none cell: both use the standard interaction block and show "None." as the buffer. Therefore:
  - `p0_B(ls)` = choice frequencies pooled over B0 runs of label set `ls`, plus round 0 of B2;
  - `p0_A(ls)` likewise from A0, plus round 0 of A2.
- **own_only cells (B1, A1) use the shorter interaction block (§4)**, so their round-0 prompts differ from B0/A0 by one sentence. Round 0 alone gives only 72 choices per label set in these cells, which is too few for a 10-label prior. Their matched priors `p0_B1` and `p0_A1` therefore come from two small **prior cells**, B0′ and A0′: memory none, with `interaction_variant = own_only` so that the prompt is identical to round 0 of B1/A1. Each uses 20 agents × 20 rounds per label set, 8 000 calls in total (about $1.5), and round 0 of B1/A1 is pooled in. The difference p0_B1 vs p0_B is reported: it measures the effect of the removed sentence on first choices.
- Each cell's p0 must come from its own prompt family. A test asserts byte-identity of the round-0 prompts (rendering from matching agents and orders) before any pooling.
- Score-feedback cells (§3.5) show "Your cumulative points so far: 0" in round 0, so their prompts are not identical to A0. They use their own pooled round-0 choices: `p0_S`.
- **Uncertainty:** priors are stored with counts. Null simulations and H4 draw p0 from Dirichlet(counts + 0.5) per replicate, so estimation error is propagated.
- **Placebo (reply 3):** in B0/A0 (stateless calls, hidden ids), `own_prev_history` must have a zero coefficient after controlling for log p0. A non-zero estimate signals a misspecified p0.

### 3.5 Score-feedback factor (was Study A; exploratory E1)

- **S2**: reward, own_and_partner, `numeric_score`, cumulative points shown. This is the brief's Study A cell.
- **S1**: reward, own_only, `numeric_score`. This is the old B+2.
- 30 runs each, with the same (label set, seed) pairs.
- Contrast S2 vs A2 = the effect of explicit score feedback.
- H factor (E2): S2 with H ∈ {1, 10}, 10 runs each.

### 3.6 Probes (new; §6)

Probes are stateless single calls outside the simulation dynamics. They never write to any agent memory, and they are logged to `logs/probes/…`:
- P-CF counterfactual partner-label probe;
- P-LOCK lock-in probe;
- P-MC manipulation check.

### 3.7 Null models (revised)

- All rule policies get an **innovation term ε**: with probability ε the agent draws from the matched p0, otherwise it applies the rule. ε is calibrated from the lock-in probe as 1 − P(stay | unanimous buffer). This matches the temperature noise of the LLM. Without ε, voter dynamics are absorbing, and the null "winner ∝ p0" would be too optimistic (critique of P2-2).
- Policies: `prior_sample`; `voter(q, ε)`; `majority_H(ε)`; `fitted_logit(θ)` (§6.1, P2-9); `scripted_fixed`.
- Each null runs 10 000 seeds per cell with the vectorized implementation (`nulls.py`), using matched p0 per label set.

### 3.8 Exploratory blocks (P3-1, P3-2, P3-4)

- **Community (H5):** first draw a **null-model phase diagram** [pkg]: noisy majority_H and fitted voter, p_within ∈ {0.8, 0.9, 0.95, 0.98, 0.99}, 2 and 3 blocks, coexistence rate. Then run the LLM (A2 settings, choices_only) at the 3 p_within values closest to the null transition, 10 runs each.
- **Star:** A2 settings with n_rounds scaled so that the median leaf reaches t_pc ≈ 50. For N = 24 that is about 1 150 rounds, 2 300 calls/run, about $0.7/run. 10 runs. Star is cheap (2 calls/round); the reason to downgrade it is low information, not cost. Prediction [pkg]: star winners are closest to the hub's individual prior, i.e. the weakest symmetry breaking of all topologies.
- **Committed minority (E4):** N = 48, A2 settings. The fractions are chosen from a null-model sweep [pkg]: default {5, 10, 20, 30} %, plus up to 3 more levels near the null tipping point, 5 runs each. Fit a logistic tipping curve. Explicitly exploratory.
  - **Minority label rule changed [pkg]:** `random_nonmodal`, i.e. uniform among the labels that are not modal at activation. The label's matched p0 is reported. v1's "least used in the last 20 rounds" rule is kept as an option; it tends to pick the lowest-prior label and so confounds tipping with prior.
- **Planted history (E5) [pkg]:** a transient scripted minority (frac 25 %) plays a pre-registered low-p0 label in rounds 0…k−1 (k = 10), then the agents are released back to the LLM policy. Question: does the final winner follow the planted label more often than the nulls predict? 10 runs in B2 and 10 in A2 settings. It reuses the minority machinery with `end_round`.
- **Temperature (E3):** in the pilot, Haiku at T ∈ {0.7, 1.0} on the core cells. The confirmatory value is chosen in the pilot (⚑ D19). The other value is run as a robustness replicate of B1/B2 only.

### 3.9 Pilot → preregistration (P3-6)

1. Label sets: generate, human review, freeze. Run Study 0 per set.
2. Pilot: 6 core cells × 5 (label set, seed) pairs × 2 temperatures [pkg: ≥ 5 seeds]. **Plateau** [pkg] = the first round at which the absolute OLS slope of state_entropy_norm over a sliding 20-round window stays below 0.002 per round for 20 consecutive windows. Estimate plateau t_pc, run-level SD of entropy_final, invalid rates per condition, and p0_A / p0_B.
3. Probes: P-LOCK (gives ε and the noise floor), P-CF (gives θ for fitted_logit), P-MC (human coding).
4. Nulls and the **power simulation** (§7.7). Set n_rounds = max(3 × the upper quartile of plateau t_pc over cells, 100). Set the number of seeds and the SESOI.
5. Freeze templates (v2 hashes), label sets, schema, model snapshot and the analysis script; export the prereg bundle (§8.6); preregister.
6. Confirmatory runs, **interleaved** in a random cell order (§8.5). Pilot data are never pooled.

### 3.10 Second model family (P2-7)

- An open-weights instruct model (Qwen or Llama family) served by an OpenAI-compatible server that supports `logprobs` and `seed` (self-hosted vLLM, or a hosted provider; ⚑ D13).
- Replicates the 6 core cells (10 label sets × 2 seeds) and all probes.
- With logprobs, p0 and the probe responses are **exact label probabilities**: the sum of token logprobs of each label continuation under the chat template. This needs far fewer calls.

---

## 4. Template v2 (verbatim changes)

Agent id line: **removed by default** (`show_own_agent_id = false`). The robustness cell `id_shown` renders `You are participant {agent_id}.` with the aNN ids.

`interaction_block.txt` (own_and_partner and memory-none cells; unchanged from v1):
```text
You are paired with another participant, who chooses from the same list at the same time.
After both choices are submitted, each of you is shown the other's choice.
```

`interaction_block_own_only.txt` (**new**, own_only cells):
```text
You are paired with another participant, who chooses from the same list at the same time.
```

`payoff_block.txt` (**changed**: the objective sentence):
```text
Scoring rule for this pairing only:
If you and the other participant choose the same label, you receive {match_payoff} points.
If you choose different labels, you receive {mismatch_payoff} points.
Your objective is to maximize your own points.
{cumulative_line}
```

⚑ D11: accept these three template changes. "A situation is labeled s0." stays for fidelity with the brief. The id "s0" could hint at other situations; this is reported as a minor limitation.

`TEMPLATE_VERSION = "v2"`. Both v1 and v2 files stay in the repo; the manifest records the version and the hashes.

---

## 5. Metrics (revised)

### 5.1 Run-level primary outcome (P2-4)

`entropy_final` = mean over the last 20 % of rounds of `state_entropy_norm`, where state = each agent's latest valid choice. Written to `summary.json`. One value per run.

### 5.2 Noise floor and consensus threshold (critique of P2-4)

- The lock-in probe gives `p_stay(k)` = P(choose k | buffer unanimous on k).
- The expected steady-state modal share of a fully converged population is about `mean_k p_stay(k)`.
- The consensus threshold τ (default 0.9, D8) is **validated**: if the expected converged share is below τ + 0.03, set τ = expected share − 0.05 and preregister it.
- The noise floor comes from the probe, not from Study 0: Study 0 measures the unconditional prior, not stability after convergence.

### 5.2a Threshold sensitivity and stable fragmentation [pkg]

- Consensus and T_consensus are reported at τ ∈ {0.8, 0.9, 0.95} together with the calibrated τ.
- **Fragmentation v2** = at least 2 labels with mean share ≥ 0.3 over the last 20 % of rounds, **and** both labels' share slopes over that window are within ±0.001 per round, **and** the mean switch rate is below the lock-in-probe noise level × 1.5. Otherwise the run is "not yet converged". This separates stable coexistence from slow convergence.

### 5.3 Ties (reply 6)

- Modal-label ties are broken by the `tiebreak` RNG stream seeded by (seed, round), no longer alphabetically.
- `population.csv` gets a `modal_tie` flag.
- For the final winner (highest mean share over the last 20 %), ties are also broken by RNG, and `winner_tie = true` is recorded. Tied runs are excluded from H4 in a sensitivity analysis.

### 5.4 Choice-model export (P1-4, reply 3)

One row per (choice, candidate label k) in `choice-model.csv`:
- `chosen`
- `own_prev_visible`: k is the most recent own record *in this prompt*; 0 when no record is shown
- `own_prev_history`: k was the last valid own choice at all (placebo in memory-none cells)
- `own_count_H`, `partner_count_H`: from rendered records only
- `partner_last`: the latest rendered record has partner = k
- `matched_k`: count of rendered records where self = partner = k (win-stay)
- `recency_w_partner`: Σ over partner-k records of w(age), with w = 1 / age
- `position` (0-based) plus `pos_first` and `pos_last` indicators; analysts code full dummies
- `log_p0_matched` (arm-matched, per label set)
- `token_count` of k [pkg]
- `pre_consensus` [pkg]: 1 if the round is before the first round at which the calibrated consensus condition starts to hold. The observational H3 model uses the pre-consensus window as its main sample, because after consensus own and partner counts are almost collinear.
- The observational model uses **label-specific constants** (per label set × arm) [pkg] instead of log p0; log p0 stays in the export for the probe model and for H4.
- `label_set_id`, `run_id`, `seed`, `cell_id`, `reward`, `memory_content`

### 5.5 Reports

- Invalid rate and void rate **by cell** (P3-5), with a flag when cells differ by more than 1 percentage point. If flagged, the analysis plan includes a sensitivity analysis that re-weights or excludes void dyads.

---

## 6. Probes (new module `probes.py`)

General rules:
- Probe prompts are rendered by the single constructor `build_agent_prompt()`, from **synthetic agents with synthetic record buffers**. There is no string surgery on logged prompts.
- Every probe prompt passes the denylist guard.
- Probes use the same model snapshot and temperature as the runs they refer to.
- Results go to `logs/probes/{probe_id}/`: `probe.json` (design), `calls.jsonl`, `results.csv`, `manifest.json`.
- Probes never import or write the simulation store.

### 6.1 P-CF: counterfactual partner-label probe (P1-4, H3; fits `fitted_logit`)

Two designs; ⚑ D15 chooses one or both.

**Replacement design (as in the review).** Sample 1 000 logged prompts from B2/A2 runs (choices_only). Rebuild each prompt's buffer from the interaction rows. Replace every partner label with a uniformly drawn label ≠ the original, and keep own labels, order and all other text. Re-render and call r = 5 times per prompt (or read logprobs).
- Effect = Δ P(choose k) as a function of Δ partner_count_H(k).
- Restricted to `choices_only` cells: in numeric_score cells a changed partner label would contradict the points line.

**Factorial design (recommended).** For each label set and focal label k:
- dose d ∈ {0, …, 5} partner-k records among H = 5;
- own labels fixed to "neutral" labels (≠ k) drawn per prompt;
- partner-k records placed at random positions;
- the list order is randomized as usual.
Size: 10 sets × 10 labels × 6 doses × 2 arms × r = 5 → 6 000 calls (about $1.2 on Haiku).
- Dose–response curves per arm.
- Adding recency (whether the latest record is k) gives `partner_last`.
- Adding own-k doses gives self-persistence.

Estimation:
- conditional logit on probe data with the §5.4 covariates;
- θ̂ is saved as `fitted_logit` parameters (JSON, hashed).
- Model adequacy is checked on **held-out label sets** (calibration curve, log score) before θ̂ is used in H6.

### 6.2 P-LOCK: lock-in probe (noise floor, ε)

- For each label set, label k and arm: a buffer of H records, all "you chose k; the other participant chose k".
- r = 20 → 10 × 10 × 2 × 20 = 4 000 calls.
- Outputs p_stay(k), ε = 1 − mean p_stay, and the noise floor (§5.2).

### 6.3 P-MC: manipulation check (P2-6)

- **Self-report:** the full prompt of a cell, with "Reply with only the label." replaced by `Before choosing, describe in one sentence what this task asks you to do.`
  - The wording is guarded against the denylist.
  - Collect 50 per core cell, 300 in total.
  - Export a **blinded** coding sheet: condition hidden, order shuffled.
  - Codes: {match/same-as-other, pick-any/preference, maximize-points, other}.
  - Two coders; report Cohen's κ.
- **Behavioural check (added):** the P-CF dose–response slope in the no-reward arm vs the reward arm. A positive no-reward slope is behavioural evidence that agents treat the task as coordination even without reward. It is also the "conditional conformity" criterion of §1.
- Limitation: LLM self-reports are not a valid window on the causes of choices, and the question itself can prime a coordination reading. Self-report is supporting evidence only.

---

## 7. Analysis plan (software exports; fitting is done in R or Python)

1. **Primary H2a:**
   - model: `entropy_final ~ memory_content * reward + (1 | label_set/seed_pair)` on the 2 × 3 core;
   - scale: beta regression (logit link) or a linear mixed model on logit(entropy_final);
   - contrast: own_and_partner − own_only within no reward;
   - if not significant: **TOST** with the preregistered SESOI.
2. **SESOI (P2-3, ⚑ D16):** default Δ = 0.10 in entropy_final. Alternatively, set it from data: 0.5 × the run-level SD from the pilot, or the own_only-vs-voter null difference. Choose before seeing confirmatory data.
3. **H1/H2b:** same model, other contrasts. Holm correction.
4. **H4:**
   - model: P(winner = k | ls) ∝ p0_matched(k | ls)^γ; estimate γ by multinomial ML over all consensus runs of a cell, pooled across label sets;
   - reference points: γ = 1 means "prior replayed" (neutral copying with prior innovation), γ > 1 means amplification (collective bias), γ → 0 means symmetry breaking;
   - p-values: compare γ̂ with the simulated γ distributions of noisy voter, noisy majority_H and fitted_logit, using the same N, rounds, ε and Dirichlet-sampled p0;
   - also report the rank of the winner in p0_matched, P(winner = argmax p0), and A(k) = P(win = k) / p0(k) (descriptive only: it is unstable for small p0).
   - **Three-tier reading (replacing the review's A(k) tiers):**
     - γ̂ within the voter null band → the prior decides;
     - γ̂ within the majority/fitted_logit band → collective bias explained by the interaction mechanism;
     - γ̂ below all null bands → path dependence / symmetry breaking beyond the modelled mechanism.
4b. **H4b (within-run path dependence) [pkg]:** multinomial logit of the winner on label-specific constants (which absorb the prior) plus the state shares at t_pc = 3. The coefficient on early share is compared with its distribution under the noisy-voter and fitted_logit nulls. Every copying dynamic is path-dependent to some degree, so the claim is about **excess** path dependence, not its existence.
5. **H3:** probe regressions (§6.1); observational choice model (label constants, pre-consensus window, run-clustered SEs; agent random intercepts as a robustness check) as description.
5b. **T_consensus [pkg]:** Kaplan–Meier curves by cell on the t_pc axis; Cox model stratified by label set; runs without consensus are right-censored at n_rounds.
5c. **H7 / H8:** same model as H2a with the B2-R / A2-R / NS2 cells.
6. **H6 (micro → macro):** simulate `fitted_logit` (θ̂ from probes) on the same scheduler with 1 000 seeds per core cell. Report where the LLM's entropy_final, T_consensus, γ̂ and fragmentation rate fall in the simulated predictive distributions.
   - Inside the 90 % band → weak emergence, explained by the individual choice function.
   - Outside the band **and** the individual model passes its held-out adequacy check → evidence of higher-order history effects.
   - Outside the band but the individual model fails its check → inconclusive (misspecification).
7. **Power simulation (§3.9 step 4; P2-1):**
   - for H2a: the pilot SD plus the SESOI, simulated under the mixed model;
   - for H4: generate winners under γ = 1 (null) and under γ = γ_alt (⚑ D14 default 0.5) with nulls, and find how many runs give power 0.8 at α = 0.05;
   - output: runs per cell, and whether H4 enters the primary family.
8. **Emergence checklist (revises v1 §7.6):**
   1. entropy_final(own_and_partner) < own_only (H2a / H1a), and the closed loop matters (H7: B2 < B2-R). [pkg: the v1 "below the prior_sample null" item was dropped as redundant with the memory-none baseline];
   2. γ̂ below the voter band (H4) and/or excess early-state path dependence (H4b);
   3. the probe dose–response is positive (a social-influence **mechanism** exists; necessary, not sufficient);
   4. the H6 result is reported as either "explained" or "higher-order";
   5. fragmentation v2 rates are reported (local success ≠ global consensus); B1 (not S1) is the "no social information" control [pkg D5: convergence in S1 is reinforcement learning from payoffs and does not count against emergence];
   6. 100 % leakage audit passed; invalid rate under the thresholds in every included cell.

---

## 8. Software changes

### 8.1 Config (schema_version "2")

| field | change |
|---|---|
| `show_own_agent_id` | default **false** |
| `template_version` | new, "v2" default; "v1" allowed for replication |
| `cell_id` | new, free label ("B2", "A1", …) used in reports and priors |
| `partner_source` [pkg] | new: `actual` \| `prior_replay` (partner label drawn from the arm's matched p0 via `p0_ref`) |
| `framing` [pkg] | new: `social` \| `nonsocial` (NS2 templates) |
| `committed_minority` | adds `end_round` (planted history) and `label_rule ∈ {random_nonmodal (default), least_used_20, fixed:<label>}` |
| `interaction_variant` | new: `standard` \| `own_only`. Defaults to own_only when memory_content = own_only; may be set explicitly on memory-none prior cells (B0′/A0′) |
| `phase` | new: `pilot` \| `confirmatory` \| `probe` \| `null`. Store path `logs/{phase}/…`. Confirmatory runs refuse p0 or θ derived from confirmatory data |
| `p0_ref` | new: reference to a stored prior `{prior_id, sha256}`; mutually exclusive with explicit `p0`. The resolved p0 (and its counts) are copied into the manifest |
| `policy_params` | adds `epsilon` (voter, majority_H), `theta_ref` (fitted_logit) |
| `model.pin_version` | new: exact model version string. A call returning another version aborts the run (`failed_model_drift`) |
| `model.provider` | adds `openai_compat` (base_url, api-key env name, `seed`, `logprobs` support) |
| validation | `numeric_score` still requires reward; own_only renders `interaction_block_own_only`; `id_shown` cells require `robustness_cell` |

### 8.2 Priors (`priors.py`, new)

- `derive_prior(cell_runs, label_set) → {counts, p0, p0_smoothed, source_run_ids, prompt_sha256_set}`.
- Asserts that all source round-0 prompts are byte-identical to the memory-none prompt family of the arm.
- Stored in `priors/{model_version}/{arm}/{label_set}.json` with a hash; the API and UI list them.

### 8.3 Probes (`probes.py`, new)

- P-CF (both designs), P-LOCK, P-MC, as in §6.
- Supports sampling mode (r repeats) and logprob mode (openai_compat).
- Exports the blinded P-MC coding sheet and imports coded results.
- `fit_logit.py` (analysis helper) fits θ from P-CF with numpy/scipy and saves it as `theta/{model_version}/{fit_id}.json`, including the held-out adequacy metrics.

### 8.4 Rule policies and nulls

- Add ε to voter and majority_H.
- Add `fitted_logit(θ)`: it computes the §5.4 covariates from **visible records only** plus position, and samples from the softmax.
- `nulls.py`: vectorized over seeds (numpy) for random_dyad and community; the scheduler path stays the reference implementation. A test checks that the two agree in distribution (KS on T_consensus and entropy_final; 2 000 seeds).
- H4 helper: γ estimation, and simulation of γ null bands with Dirichlet-sampled p0.

### 8.5 Matrix runner

- Crossed design helper: `cells × (label_set, seed) pairs`.
- **Interleaved execution order**, drawn from a seeded shuffle and saved as `schedule.json`, with timestamps.
- Resume skips completed runs.
- Cost estimate per block; confirmation required.
- Per-cell invalid-rate monitor that warns when cells diverge by more than 1 pp.

### 8.6 Preregistration bundle (new CLI/API)

`prereg-bundle` writes a zip with:
- template files and hashes;
- `label_sets.json` and its hash;
- config schema;
- the planned matrix (cells, pairs, n_rounds);
- prior ids;
- θ id;
- ε;
- SESOI;
- the analysis script version;
- the model pin.

### 8.7 UI

- **New "Study plan" page:** shows the design matrix (cells × label sets × seeds) with progress per cell, the phase badge, a budget meter, and the "next step" in the protocol (§9). Launches a whole block (for example "Core 2 × 3, pilot") after a cost confirmation.
- **Setup:** presets regrouped to the v2 cells (B0/B1/B2/A0/A1/A2, S1/S2, exploratory). A p0 selector: uniform / stored prior (matched arm suggested automatically) / explicit. A phase selector. The id-shown robustness toggle sits under Advanced.
- **New "Probes" page:** P-LOCK, P-CF, P-MC with cost estimates, progress, dose–response plots, a download of the blinded coding sheet and an upload of the coded sheet.
- **Results:** entropy_final as the headline metric, per-cell invalid-rate table, H4 panel (winner ranks, γ̂ against null bands) for a selected block, and an H6 panel (LLM outcome against the fitted_logit predictive band).
- Everything stays in English. The existing single-run workflow is unchanged.

### 8.8 Tests (added to v1 §8)

| # | test |
|---|---|
| 16 | Arm symmetry for all memory columns: within a column, reward and no-reward prompts differ only by the payoff block (choices_only everywhere) |
| 17 | Round-0 prompts of B2 equal B0 prompts byte-for-byte (same for A2/A0); B1/A1 form their own prompt family; `derive_prior` refuses mismatched sources |
| 18 | Probes never write to the simulation store and never modify agent buffers; probe prompts are built by `build_agent_prompt` and pass the guard |
| 19 | P-CF factorial: the rendered dose equals the design; own records never contain the focal label |
| 20 | `fitted_logit` reads visible records only (own_only hides partner labels) |
| 21 | ε-policies: ε = 0 reproduces the v1 policies exactly; ε = 1 equals prior_sample |
| 22 | Vectorized nulls match scheduler nulls in distribution |
| 23 | Modal and winner ties use the RNG and are flagged; the result is reproducible |
| 24 | `pin_version` mismatch aborts with `failed_model_drift` |
| 25 | `phase = confirmatory` refuses a p0 or θ derived from confirmatory runs |
| 26 | Hidden id: no `participant a\d\d` in any prompt unless `id_shown`; hub prompt identical to leaf prompts |
| 27 | Label hygiene v2 (extended lists, edit-distance-1 rule, equal token counts, `frozen_at` present) |
| 28 | Prior replay: partner labels shown to an agent are independent of every other agent's choices (permutation test on a mock run); commit_dyad stays the only writer |
| 29 | Non-social framing: prompts pass the guard and contain no "participant"; within NS2, prompts differ from B2 only in the interaction block and memory-line wording |
| 30 | Minority `random_nonmodal`: the label is never the modal label at activation; `end_round` releases the agents back to the base policy |

---

## 9. User workflow (target, v2)

1. **Label sets:** Study plan → "Generate candidate label sets" → download the review sheet → mark ok / replace → upload → **Freeze**. The app shows the hash and `frozen_at`.
2. **Study 0:** Study plan → "Run Study 0 (all sets)". Cost confirmation, then gate results per set.
3. **Pilot:** Study plan → "Core 2 × 3 pilot (4 pairs × 2 temperatures)". Monitor, then Results.
4. **Priors:** Study plan → "Derive matched priors from pilot" → review p0_A / p0_B against p0_isolated.
5. **Probes:** Probes page → P-LOCK → P-CF → P-MC. Download the blinded coding sheet, code it, upload it.
6. **Fit and nulls:** "Fit fitted_logit (held-out check)" → "Run nulls + power simulation" → the app proposes n_rounds, runs per cell, SESOI and the primary family, for Yuhan to accept.
7. **Freeze and preregister:** "Export prereg bundle".
8. **Confirmatory:** Study plan → launch the blocks in an interleaved order. Monitor.
9. **Analysis:** Results → block downloads (run-level table, choice-model data, probe data, H4 and H6 panels) → run the analysis script in R or Python → emergence checklist.

Steps 1–2 and 4–7 are new. Single runs (the current Setup → Monitor → Results path) remain available for ad-hoc work.

---

## 10. Budget (Haiku 4.5, estimator of the current engine, id hidden)

| block | runs | calls | est. cost |
|---|---|---|---|
| Core 2 × 3 (6 cells × 30), 300 rounds | 180 | 1 296 000 | $259 |
| Score feedback S1/S2 (2 × 30) | 60 | 432 000 | $119 |
| H ∈ {1, 10} on S2 (2 × 10) | 20 | 144 000 | $43 |
| Community p_within × 3 (30) | 30 | 216 000 | $62 |
| Star, t_pc-scaled (10) | 10 | 23 000 | $7 |
| Minority N = 48, 7 levels × 5 | 35 | 504 000 | ≈ $145 |
| Pilot (6 cells × 5 pairs × 2 T) | 60 | 432 000 | $86 |
| Loop / framing controls B2-R, A2-R, NS2 (3 × 30) [pkg] | 90 | 648 000 | ≈ $135 |
| Planted history E5 (2 × 10) [pkg] | 20 | 144 000 | ≈ $30 |
| Study 0 (10 sets) + prior cells B0′/A0′ + probes (P-LOCK 4 000, P-CF 6 000, P-MC 300) | — | ≈ 22 300 | ≈ $5 |
| **Total** | | **≈ 3.86 M** | **≈ $891** |

- The pilot is expected to lower n_rounds. At 150 rounds the core costs about $125 instead of $259.
- The second model family is not included; its cost depends on hosting.
- Wall-clock: about 5–8 min per 300-round run at 24 concurrent calls.

---

## 11. Decisions for Yuhan (⚑)

| id | decision | recommendation |
|---|---|---|
| D10 | Adopt the 2 × 3 core with choices_only; Study A score feedback as a separate factor | yes |
| D11 | Template v2 (id hidden, own_only interaction block, objective without "across pairings") | yes |
| D12 | Regenerate all 10 label sets (L1–L3 included) with extended screening and a human gate | yes (no formal data exist yet) |
| D13 | Second family: self-hosted vLLM or a hosted OpenAI-compatible provider with logprobs | hosted first (no GPU admin), vLLM if exact seeds are required |
| D14 | H4 in the primary family only if the power simulation gives ≥ 0.8; γ_alt = 0.5 | yes |
| D15 | P-CF design: factorial (recommended) and/or replacement | factorial as the main design, replacement as a check (both are cheap) |
| D16 | SESOI for entropy_final | derive from the pilot (0.5 × run-level SD), but not below 0.05 |
| D17 | Star: exploratory, t_pc-scaled | yes |
| D18 | Minority: exploratory grid 2–30 %, 5 runs per level | yes |
| D19 | Confirmatory temperature (0.7 vs 1.0) | choose in the pilot: the higher T that keeps invalid < 2 % and the noise floor above τ |
| D21 [pkg] | Prior-replay cells B2-R/A2-R as the preregistered loop control (instead of full yoked replay) | yes |
| D22 [pkg] | Non-social framing cell NS2 (no-reward arm only) | yes |
| D23 [pkg] | Planted history E5 as exploratory | yes, if the budget allows |
| D24 [pkg] | Token-count balance as a label-screening rule | yes |
| D20 | Primary model | Haiku 4.5, pinned to the snapshot seen in the pilot (`claude-haiku-4-5-20251001` at present) |
