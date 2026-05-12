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

### Step 3 — Detect battle ends and place end markers

**3a. Run mark_battle_ends.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_battle_ends.py"
```
The script extracts frames from the source video around each battle's estimated end window and writes the relay prompt.

**3b. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-ends-<stem>.in.md` appears
- Read it. It lists image file paths (one per extracted frame) with timestamps for each battle.
- For each battle, read each listed image file using the Read tool and visually identify the best end frame:
  1. Trainer defeat screen (trainer sprite/portrait in defeated pose) — preferred
  2. Post-battle breakdown overlay the creator uses
  3. First non-battle frame (overworld, town, any screen without battle UI)
- Write ONLY a raw JSON array to the corresponding `.out.md` (no markdown fences):
  ```json
  [{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 385.3, "confidence": "high", "notes": "Trainer defeat pose visible"},
   {"battle_index": 1, "trainer_name": "Falkner", "end_sec": 741.0, "confidence": "medium", "notes": "First overworld frame after battle"}]
  ```
- mark_battle_ends.py detects `.out.md`, places green timeline markers labeled `<Trainer> Battle End`, and exits.

Report how many markers were placed.

---

### Step 4 — Ripple delete short clips (< 5 frames) from V1 and A1

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\remove_short_clips.py"
```
Wait for completion. Report clips removed.

### Step 5 — Mark A1 gaps > 5 frames on timeline ruler and V1 clips

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_audio_gaps.py"
```
Wait for completion. Report gap count and positions.

### Step 6 — Analyze transcript and color cut candidates

**6a. Run mark_cut_candidates.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_cut_candidates.py"
```

**6b. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\cut-analysis-<stem>.in.md` appears
- Read it. It contains the full segmented transcript with timestamps.
- Analyze and identify:
  1. **Non-speech artifacts** — throat clears, coughs, mic bumps that passed the silence filter. These show up as Whisper transcribing a single period, an isolated word ("you", "the"), or very short implausible text. Keep genuine laughter and reactions.
  2. **False starts, repetitions, topic changes** — speaker abandons a thought mid-sentence, repeats content just said within ~30 s, or pivots significantly from one strategy/Pokémon to another in a way that would confuse a viewer. Use game/challenge context to judge.
- Write ONLY a raw JSON array to the corresponding `.out.md` (no markdown fences):
  ```json
  [{"start_sec": 12.3, "end_sec": 14.1, "confidence": "high", "type": "non_dialogue", "reason": "..."},
   {"start_sec": 45.0, "end_sec": 52.3, "confidence": "medium", "type": "false_start", "reason": "..."}]
  ```
- mark_cut_candidates.py detects `.out.md`, colors V1 clips (Orange = high, Yellow = medium), and exits.

Report how many clips were colored orange and yellow.

---

### Step 7 — Import assets and build edit timeline

The transcript from Step 2a is already available. Use it now to detect the game and run the full import pipeline.

**7a. Detect game and check game-specific manifest:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --check"
```
Infer GAME_KEY from the transcript in `transcripts\` (first ~3000 chars of `text` field). If any paths are missing or invalid, prompt the user before continuing.

**7b. Check shared assets (type icons, BGM, badges, gym leaders, Pokémon artwork):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --check-shared"
```
If status is `needs_paths`, prompt the user for each missing folder path and set them:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --set-shared-path ASSET_ID "PATH""
```

**7c. Import shared assets into sub-bins (skip if all already valid and bins exist):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --import-shared"
```

**7d. Import game-specific assets:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --do-import"
```

**7e. Classify Minimum Battles Series (relay — drives intro speed):**

Run `detect_minimum_battles.py` in the BACKGROUND (Bash run_in_background=true):
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_minimum_battles.py"
```

Relay — YOU must complete this step:
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\min-battles-<stem>.in.md` appears
- Read it. It contains the transcript and the definition of a Minimum Battles Series.
- Decide:
  - **True** if the player uses ≥8 different Pokémon AND repeatedly fights the same (or very similar) trainer with each (testing format)
  - **False** for any other playthrough — including challenges with a small fixed team, full game runs, etc.
- Write ONLY a single JSON object to `.out.md` (no markdown fences):
  ```json
  {"is_minimum_battles": false, "pokemon_count": 3, "trainers_attempted": ["Rival 1", "Falkner", "Bugsy"], "reasoning": "..."}
  ```
- The script caches to `transcripts/min-battles.json` and exits.

**7f. Build the edit timeline (intro prepended, clips shifted, outro appended):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_intro_outro.py --game GAME_KEY"
```

The script auto-reads `transcripts/min-battles.json`: intro plays at **100%** if `is_minimum_battles=true`, otherwise at **400%** (4x speed). Pass `--intro-speed 100|400` to override.

---

## Final summary

After all seven steps complete, print a summary table:
| Step | Result |
|------|--------|
| Clear audio tracks | N clips removed from A2–A5 |
| Battle gaps | N battles found, N extended, N marker-only |
| Battle end markers | N green markers placed |
| Short clip removal | N clips ripple deleted |
| Gap markers | N gaps marked |
| Cut candidates | N orange (high confidence), N yellow (medium confidence) |
| Import + edit timeline | Game detected, N shared files + N game files imported, edit timeline created |
