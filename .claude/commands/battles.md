Run the full Pokémon trainer battle gap insertion pipeline:
  Step 1 — Transcribe A1 audio source → transcripts/<stem>.json
  Step 2 — Relay: detect_battles.py writes prompt; YOU analyze and write the JSON response
  Step 3 — Insert 1-second (60-frame) source footage gaps at each battle start on V1

Arguments are passed through to battle_workflow.py. Examples:
  /battles              → full pipeline
  /battles --dry-run    → Step 3 reports without modifying Resolve
  /battles --skip-transcribe  → skip Step 1 (use existing transcripts/)

---

## Execution procedure

### Step 1 — Transcribe (skip if --skip-transcribe in $ARGUMENTS)

Run via Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\transcribe_audio.py"
```

Wait for it to complete. It outputs a JSON file to `C:\Programming\resolve-mcp\transcripts\`.

### Step 2 — Battle detection (relay mode)

Run detect_battles.py in the BACKGROUND (Bash run_in_background=true):
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\detect_battles.py transcripts/<stem>.json --out transcripts/battles.json --plans-dir plans/prompts --timeout-sec 600"
```

Replace `<stem>` with the actual transcript filename (most recently modified .json in transcripts/).

detect_battles.py writes a prompt to `C:\Programming\resolve-mcp\plans\prompts\battle-detect-<stem>.in.md` and then polls for the corresponding `.out.md`.

YOU must complete the relay:
1. Read the `.in.md` file (poll with Read tool until it appears — it appears within a few seconds of the background process starting)
2. Analyze the transcript text inside the prompt: identify every timestamp where the player fights a trainer for the FIRST TIME (not rematches). Pokémon trainers: Gym Leaders, rival encounters, route trainers (Bug Catcher, Lass, etc.) — any named battle start counts.
3. Write ONLY the JSON array to the `.out.md` file (same path but `.out.md` extension) — NO markdown fences, NO explanation, just raw JSON:

```json
[
  {"timestamp_sec": 123.4, "trainer_name": "Brock", "description": "First gym battle starts"},
  {"timestamp_sec": 456.7, "trainer_name": "Bug Catcher", "description": "Route 2 trainer encounter"}
]
```

If there are no battles in the transcript, write: `[]`

Once you write `.out.md`, detect_battles.py will detect it, validate the JSON, and automatically run insert_battle_gaps.py.

### Step 3 — Verify results

After the background process completes (you will be notified), report:
- How many battles were detected
- How many V1 clips were successfully extended
- How many were marker-only (insufficient handles)
- How many were skipped

If `--dry-run` was passed, report what would have happened without any timeline changes.
