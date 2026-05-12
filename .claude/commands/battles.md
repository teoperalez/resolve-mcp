Run the full Pokémon trainer battle gap insertion pipeline:
  Step 1 — Transcribe A1 audio source → transcripts/<stem>.json
  Step 2 — Relay: detect_battles.py writes prompt; YOU analyze and write the JSON response
  Step 3 — Insert 1-second (60-frame) source footage gaps at each battle start on V1

Arguments are passed through to battle_workflow.py. Examples:
  /battles              → full pipeline
  /battles --dry-run    → Step 3 reports without modifying Resolve
  /battles --skip-transcribe  → skip Step 1 (use existing transcripts/)

All commands MUST be run from C:\Programming\resolve-mcp (use `cd /d` prefix).

---

## Execution procedure

### Step 1 — Transcribe (skip if --skip-transcribe in $ARGUMENTS)

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\transcribe_audio.py --model large-v3-turbo"
```

Wait for it to complete. It writes to `transcripts\<stem>.json` inside the project.

### Step 2 — Battle detection (relay mode)

Run detect_battles.py in the BACKGROUND (Bash run_in_background=true).
First, find the most recently modified .json in `C:\Programming\resolve-mcp\transcripts\` — that is `<stem>`.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_battles.py transcripts\<stem>.json --out transcripts\battles.json --plans-dir plans\prompts --timeout-sec 600"
```

detect_battles.py writes a prompt to `C:\Programming\resolve-mcp\plans\prompts\battle-detect-<stem>.in.md` and then polls for the corresponding `.out.md`.

YOU must complete the relay:
1. Poll with Read tool until the `.in.md` file appears (within a few seconds of starting)
2. Read the `.in.md` — it contains the full transcript. Identify every timestamp where the player fights a trainer for the FIRST TIME (not rematches). This includes:
   - Rival encounters (e.g., "Silver" or "Rival")
   - Gym Leader battles
   - Route trainers (Bug Catcher, Lass, Youngster, etc.)
   - Any named NPC battle start
3. Write ONLY the JSON array to the `.out.md` file (same path but `.out.md` extension) — NO markdown fences, NO explanation, just raw JSON:

```json
[
  {"timestamp_sec": 123.4, "trainer_name": "Rival 1", "description": "First rival battle starts"},
  {"timestamp_sec": 456.7, "trainer_name": "Falkner", "description": "Gym 1 battle starts"}
]
```

If there are no battles in the transcript, write: `[]`

Once you write `.out.md`, detect_battles.py detects it, validates the JSON, writes `transcripts\battles.json`, and exits.

### Step 3 — Verify results

After the background process completes (you will be notified), run insert_battle_gaps.py to apply or preview the gaps:

For dry-run:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps.py transcripts\battles.json --dry-run"
```

For real run (omit --dry-run):
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps.py transcripts\battles.json"
```

Report:
- How many battles were detected
- How many V1 clips were successfully extended (or would be extended in dry-run)
- How many were marker-only (insufficient handles)
- How many were skipped (timestamp outside timeline range)
