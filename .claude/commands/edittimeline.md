Run the full Resolve timeline editing pipeline in order. Each step runs to completion before the next begins.

Arguments: $ARGUMENTS (pass --dry-run to preview the battles step without modifying the timeline)

All commands MUST be run from C:\Programming\resolve-mcp (every command uses `cd /d` prefix).

---

## Pipeline order

### Step 1 — Clear audio tracks A2–A5

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\clear_audio_tracks.py"
```
Wait for completion. Report clips removed.

### Step 2 — Battle gap insertion (relay mode)

**2a. Transcribe A1 audio:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\transcribe_audio.py --model large-v3-turbo"
```
Wait for completion. Note the stem (filename without .json) in `transcripts\`.

**2b. Run detect_battles.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_battles.py transcripts\<stem>.json --out transcripts\battles.json --plans-dir plans\prompts --timeout-sec 600"
```

**2c. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-detect-<stem>.in.md` appears
- Read it and identify every first-time trainer battle start timestamp from the transcript
- Write ONLY a raw JSON array to the corresponding `.out.md` (no markdown fences):
  ```json
  [{"timestamp_sec": 123.4, "trainer_name": "Rival 1", "description": "..."}]
  ```
- detect_battles.py detects the `.out.md`, writes `transcripts\battles.json`, and exits

**2d. Insert or preview gaps:**

If --dry-run in $ARGUMENTS:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps.py transcripts\battles.json --dry-run"
```
Otherwise:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps.py transcripts\battles.json"
```

### Step 3 — Ripple delete short clips (< 5 frames) from V1 and A1

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\remove_short_clips.py"
```
Wait for completion. Report clips removed.

### Step 4 — Mark A1 gaps > 5 frames on timeline ruler and V1 clips

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_audio_gaps.py"
```
Wait for completion. Report gap count and positions.

### Step 5 — Import assets and build edit timeline

The transcript from Step 2a is already available. Use it now to detect the game and run the full import pipeline.

**5a. Detect game and check game-specific manifest:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --check"
```
Infer GAME_KEY from the transcript in `transcripts\` (first ~3000 chars of `text` field). If any paths are missing or invalid, prompt the user before continuing.

**5b. Check shared assets (type icons, BGM, badges, gym leaders, Pokémon artwork):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --check-shared"
```
If status is `needs_paths`, prompt the user for each missing folder path and set them:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --set-shared-path ASSET_ID "PATH""
```

**5c. Import shared assets into sub-bins (skip if all already valid and bins exist):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --import-shared"
```

**5d. Import game-specific assets:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --do-import"
```

**5e. Build the edit timeline (intro prepended, clips shifted, outro appended):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_intro_outro.py --game GAME_KEY"
```

---

## Final summary

After all five steps complete, print a summary table:
| Step | Result |
|------|--------|
| Clear audio tracks | N clips removed from A2–A5 |
| Battle gaps | N battles found, N extended, N marker-only |
| Short clip removal | N clips ripple deleted |
| Gap markers | N gaps marked |
| Import + edit timeline | Game detected, N shared files + N game files imported, edit timeline created |
