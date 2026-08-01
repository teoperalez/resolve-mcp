# Deterministic GSC Gym Leader Challenge routing

Every Pokémon Crystal/GSC Gym Leader Challenge video must use the dedicated
zero-LLM workflow `gsc_gym_leader_deterministic_single_build` from
`F:\Programming\resolve-mcp-codex`.

Run `.venv\Scripts\python.exe scripts\run_gsc_gym_deterministic_workflow.py`
with `build-offline` before acquiring Resolve, then use `resolve-dry-run` only
after the recording is final and exclusive Resolve access has been granted.
The canonical contract is in `docs/deterministic_gsc_gym_workflow.md` and
`config/orchestrator_workflows.json`.

Never substitute the generic `pokemon_gym_leader_challenge` workflow, legacy
manual assembly, or an LLM inference step. The workflow has one hard 600-second
budget and fails closed on missing or ambiguous telemetry, assets, receipts, or
geometry. Preserve protected timeline edits. Corrections belong in the
deterministic planner, validators, and regression tests, not in one-off repair
scripts. RBY UMB continues to use its separate Gen 1 deterministic workflow.
