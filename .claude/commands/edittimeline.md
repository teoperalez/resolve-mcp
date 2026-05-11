Run the full Resolve timeline editing pipeline in order. Each step runs to completion before the next begins.

Arguments: $ARGUMENTS (pass --dry-run to do a dry run on the battles step without modifying the timeline)

---

## Pipeline order

### Step 1 — Clear audio tracks A2–A5

Run via Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\clear_audio_tracks.py"
```
Wait for completion. Report clips removed.

### Step 2 — Battle gap insertion (relay mode)

**2a. Transcribe A1 audio:**
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\transcribe_audio.py"
```
Wait for completion. Note the transcript filename in `transcripts/`.

**2b. Run detect_battles.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\detect_battles.py transcripts/<stem>.json --out transcripts/battles.json --plans-dir plans/prompts --timeout-sec 600"
```

**2c. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-detect-<stem>.in.md` appears
- Read it and identify every first-time trainer battle start timestamp
- Write ONLY a raw JSON array to the corresponding `.out.md` (no markdown fences):
  ```json
  [{"timestamp_sec": 123.4, "trainer_name": "Brock", "description": "..."}]
  ```
- detect_battles.py will detect the `.out.md` and run insert_battle_gaps.py automatically
- If `--dry-run` is in $ARGUMENTS, pass it: `detect_battles.py ... && insert_battle_gaps.py ... --dry-run`
  (Actually detect_battles.py passes --dry-run through if it's in the battles.json insert step — check battle_workflow.py)

Wait for the background process completion notification. Report battle results.

### Step 3 — Ripple delete short clips (< 5 frames) from V1 and A1

Run via Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\remove_short_clips.py"
```
Wait for completion. Report clips removed.

### Step 4 — Mark A1 gaps > 5 frames on timeline ruler and V1 clips

Run via Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\mark_audio_gaps.py"
```
Wait for completion. Report gap count and positions.

---

## Final summary

After all four steps complete, print a summary table:
| Step | Result |
|------|--------|
| Clear audio tracks | N clips removed from A2–A5 |
| Battle gaps | N battles found, N extended, N marker-only |
| Short clip removal | N clips ripple deleted |
| Gap markers | N gaps marked |
