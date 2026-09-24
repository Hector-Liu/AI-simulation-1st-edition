# CLAUDE.md — Naming Game Simulator

Research software for Yuhan (UCSB): LLM naming-game experiments on convention emergence. The design is `docs/SPEC-naming-game-v1.0.md`; what the code actually does, and what is missing, is in `docs/IMPLEMENTATION_NOTES.md`.

## Hard rules
- Invariants (SPEC §0/§5): private memory only; no population statistics in prompts; denylist guard on every prompt; exact prompts logged; label order reshuffled per prompt; `build_agent_prompt()` is the only prompt constructor and `commit_dyad()` the only memory writer; agents never read the store.
- No paid model calls until `venv/bin/python -m pytest tests -q` passes. Show the cost estimate and get Yuhan's OK before any batch or matrix run.
- Never ask an LLM to judge emergence. Metrics are computed.
- `.env` holds API keys and must never be committed. `logs/` is gitignored.
- Frozen label sets (`naming_game/data/label_sets.json`) must never be regenerated once runs exist.
- Reply to Yuhan in Chinese. Keep code, prompts and specs in English.

## Run
- App: `./start.sh` (or double-click `一键启动.command`) → http://127.0.0.1:8765
- Tests: `venv/bin/python -m pytest tests -q`
