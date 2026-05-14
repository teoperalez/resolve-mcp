Run the full Resolve timeline editing pipeline in order. Each step runs to completion before the next begins.

Arguments: $ARGUMENTS (pass --dry-run to preview the battles step without modifying the timeline)

All commands MUST be run from C:\Programming\resolve-mcp (every command uses `cd /d` prefix).

---

## Pipeline ordering principle

**Cuts come first.** Applying cut candidates produces a NEW timeline (`(cuts: all)`) from FCPXML and discards anything that lives only on the old timeline (markers, audio placements, V2 overlays, color grades). Only operations whose state is portable — source-time decisions cached in JSON — survive a cut step. So the order is:

1. Operations that produce **portable JSON state** (transcript, battle source-time decisions, cut analysis)
2. **Apply cuts → new `(cuts: all)` timeline**
3. Operations that produce **timeline-resident state** (markers, intro/outro, V2 carousel, BGM, fades, Fairlight)

Re-running cut analysis later in the workflow would force redoing everything in category 3. Putting cuts up front means we only commit timeline-resident operations to the final cut basis.

---

## Pipeline order

### Step 1 — Clear audio tracks A2–A5

Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\clear_audio_tracks.py"
```
Wait for completion. Report clips removed. This cleans up audio from any prior workflow run on this video.

### Step 2 — Battle gap insertion (transcribe + detect + FCPXML rewrite)

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

**2d. Insert battle gaps via FCPXML (canonical IRLPC approach):**

Resolve's Python API CANNOT ripple-insert into existing timeline content. So the canonical approach is to modify the auto-editor's `_ALTERED.fcpxml` and import the modified version as a new timeline.

Locate the auto-editor's FCPXML — typically next to the source video at `<source-dir>/<video-name>_ALTERED.fcpxml`. The source video path can be read from `transcripts/<stem>.json`'s `"audio"` field.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps_fcpxml.py "<source-dir>\<video-name>_ALTERED.fcpxml" --battles transcripts\battles.json --import-to-resolve"
```

After import, the new `(battle-gaps)` timeline becomes current. All subsequent steps until cut application operate on it.

### Step 3 — Detect battle ends and place rough end markers

**3a. Run mark_battle_ends.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_battle_ends.py"
```
The script extracts frames from the source video around each battle's estimated end window and writes the relay prompt.

**3b. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-ends-<stem>.in.md` appears
- Read it. It lists image file paths (one per extracted frame) with timestamps for each battle.
- For each battle, read each listed image file using the Read tool and visually identify the best end frame
- Write ONLY a raw JSON array to the corresponding `.out.md`:
  ```json
  [{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 385.3, "confidence": "high", "notes": "Trainer defeat pose visible"}]
  ```
- mark_battle_ends.py detects `.out.md`, places green timeline markers labeled `<Trainer> Battle End`, and exits.

The source-time decisions get cached in the `.out.md` — they will be re-used (via `--skip-relay`) after cuts to re-place markers on the new timeline.

---

### Step 4 — Analyze cut candidates (LLM-flagged)

**4a. Run mark_cut_candidates.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_cut_candidates.py"
```

The script enumerates every V1 clip on the `(battle-gaps)` timeline, attaches overlapping Whisper transcript text (multi-segment clips show each sub-segment with its own timestamps), excludes structural clips (intro/outro/B-roll — though at this stage there are no structural clips yet on `(battle-gaps)`), and writes the clip-driven analysis prompt.

**4b. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\cut-analysis-<stem>.in.md` appears
- Read it. The prompt's editorial bias is **inverse of "default to KEEP"**: the burden is on the analyzer to articulate how each clip advances the narrative; if it can't, FLAG IT.
- Categories:
  - **HIGH**: empty-transcript noise (throat clears, breath bursts, mic bumps), pre-roll / mic-check, Whisper hallucinations, stuttered repeats
  - **MEDIUM**: false starts, true repetitions (failed-take redos), abandoned narrative threads
  - **MID-CLIP** (use `type` prefix `mid_clip_*`): when a single clip contains a false start + clean restart or a mid-sentence correction, flag the sub-range only — must be ≥0.2s
- For a ~30-min video with ~500 clips, the prompt is ~145KB. Dispatch ONE subagent (general-purpose, full context) to do the analysis — main thread reasoning will be shallow on this volume.
- Write ONLY a raw JSON array to the corresponding `.out.md`:
  ```json
  [{"start_sec": 12.15, "end_sec": 12.77, "confidence": "high", "type": "pre_roll", "reason": "..."},
   {"start_sec": 411.02, "end_sec": 412.56, "confidence": "medium", "type": "mid_clip_false_start", "reason": "..."}]
  ```
- mark_cut_candidates.py applies clip colors (Orange/Yellow) and red Cut start/Cut end markers for mid-clip flags.

Report how many clips were colored orange and yellow, plus how many sub-clip markers were placed.

### Step 5 — Apply cuts → produce HIGH and ALL FCPXMLs

Generate two cut variants and import both as new timelines. The `(cuts: all)` timeline becomes the new working basis; `(cuts: high)` remains available for A/B comparison.

The input FCPXML is the one produced by Step 2d (`*_ALTERED_BATTLEGAPS.fcpxml`, next to the source video). The cuts JSON is auto-detected from `plans/prompts/cut-analysis-<stem>.out.md`.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_cuts_to_fcpxml.py "<source-dir>\<video-name>_ALTERED_BATTLEGAPS.fcpxml" -o "<source-dir>" --import-to-resolve"
```

After import, the `(cuts: all)` timeline becomes current. **All subsequent steps operate on it.** The replay metadata sidecar (`*_cuts_replay.json`) captures the cuts so they can be reproduced on a sibling timeline if needed (e.g., to mirror downstream operations onto `(cuts: high)`).

Report:
- HIGH cuts: N deletes, N trims, N splits, X.XXs removed
- ALL cuts: N deletes, N trims, N splits, X.XXs removed

---

### Step 6 — Ripple delete short clips (< 5 frames) from V1 and A1

Micro-cleanup on the cut timeline. Run via Bash tool:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\remove_short_clips.py"
```
Wait for completion. Report clips removed.

### Step 7 — Mark A1 gaps > 5 frames on timeline ruler and V1 clips

Informational markers on the cut timeline.
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_audio_gaps.py"
```
Wait for completion. Report gap count and positions.

---

### Step 8 — Import assets and build edit timeline

The transcript from Step 2a is already available. Use it now to detect the game and run the full import pipeline.

**8a. Detect game and check game-specific manifest:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --check"
```
Infer GAME_KEY from the transcript in `transcripts\` (first ~3000 chars of `text` field). If any paths are missing or invalid, prompt the user before continuing.

**8b. Check shared assets (type icons, BGM, badges, gym leaders, Pokémon artwork):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --check-shared"
```
If status is `needs_paths`, prompt the user for each missing folder path and set them:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --set-shared-path ASSET_ID "PATH""
```

**8c. Import shared assets into sub-bins (skip if all already valid and bins exist):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --import-shared"
```

**8d. Import game-specific assets:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --do-import"
```

**8e. Classify Minimum Battles Series (relay — drives intro speed):**

Run `detect_minimum_battles.py` in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_minimum_battles.py"
```

Relay — YOU must complete this step:
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\min-battles-<stem>.in.md` appears
- Read it. Decide:
  - **True** if the player uses ≥8 different Pokémon AND repeatedly fights the same (or very similar) trainer with each (testing format)
  - **False** for any other playthrough
- Write ONLY a single JSON object to `.out.md`:
  ```json
  {"is_minimum_battles": false, "pokemon_count": 3, "trainers_attempted": ["Rival 1", "Falkner", "Bugsy"], "reasoning": "..."}
  ```
- The script caches to `transcripts/min-battles.json` and exits.

**8f. Build the edit timeline (intro prepended, clips shifted, outro appended):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_intro_outro.py --game GAME_KEY"
```

The script auto-reads `transcripts/min-battles.json`: intro plays at **100%** if `is_minimum_battles=true`, otherwise at **400%** (4x speed) — retime via ffmpeg pre-render cached at `~/.resolve-mcp/cache/retimed-intros/`.

After this step the new `(cuts: all) (edit)` timeline is the active timeline. All subsequent steps operate on it.

---

### Step 9 — Re-place + refine battle end markers on the edit timeline

The source-time end decisions from Step 3 are persisted in the `.out.md` and survive the cut step. Now we map them through the new V1 layout.

**9a. Re-place initial markers on the edit timeline (uses cached relay):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_battle_ends.py --skip-relay"
```
This reuses the `battle-ends-<stem>.out.md` from Step 3 and remaps source-seconds → timeline frames through the new edit timeline's V1 clips.

**9b. Refine to precise transition frames (parallel subagents, fresh relay):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\refine_battle_ends.py"
```
This extracts ~41 frames at 0.25s steps in a ±5s window around each rough estimate (~246 frames total for 6 battles) and writes `plans/prompts/battle-ends-refine-<stem>.in.md`.

Relay — YOU must complete this step:
- Poll until the `.in.md` appears.
- Read it. For each battle, spawn ONE Haiku subagent (parallel, `model: "haiku"`) with that battle's dense frame list and the visual-pattern guidance from the prompt. Each subagent Reads its 41 frames and returns one JSON object with the precise `end_sec`.
- Collect all responses into a single JSON array and write to the corresponding `.out.md` (raw JSON, no fences).

The script clears the existing green markers and replaces them with refined ones (typical drift after refinement: wins within ±0.5s, gave_ups within ±2s).

### Step 10 — Find Member Carousel Start

Locate the first V1 clip after the last Battle End that displays the "Member Carousel" overlay (Pokémon sprite at bottom-left + member name in yellow text + gym badge at bottom-right).

**10a. Run find_member_carousel.py in the BACKGROUND:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\find_member_carousel.py"
```
The script extracts the first frame of each candidate clip (and the previous clip's last frame) for up to 30 clips after the last battle marker, then writes a relay prompt.

**10b. Relay — YOU must complete this step:**
- Poll until `plans/prompts/member-carousel-<edit-tl-stem>.in.md` appears.
- Spawn ONE Haiku subagent (`model: "haiku"`) with the prompt. It scans candidate first-frames sequentially until it finds one with the carousel style, then checks the previous clip's last frame to decide whether the carousel actually started in the previous clip.
- Haiku writes the JSON object directly to the corresponding `.out.md`.

The script places a yellow `Member Carousel Start` marker at the chosen clip's start.

### Step 11 — Layout the carousel section (V1 extend + V2 with bottom crop)

Reshape the timeline so the carousel plays continuously underneath the streamer-action cuts.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\layout_carousel.py"
```

This script:
1. Copies all V1 clips between `Member Carousel Start` and the outro to V2.
2. Sets `CropBottom=530` on each V2 clip (exposes the V1 layer's bottom strip).
3. Deletes the original V1 clips in that range.
4. Replaces them with ONE extended V1 clip that plays the source continuously from the carousel start to the outro's start frame.

Pass `--crop-bottom N` to override the crop value, or `--dry-run` to preview without modifying the timeline.

### Step 12 — A2 audio pipeline (BGM + battle audio + fades)

Fill A2 with dynamic music: Dual Screen Lovelife → chained random general BGM → looped battle audio during battles → -3dB crossfades at every battle boundary.

**12prep. Defensive clear A2–A5 on the edit timeline:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\clear_audio_tracks.py"
```
Defensive: Step 5's apply_cuts_to_fcpxml.py now drops the auto-editor's 4 linked audio refs (r4/r6/r8/r10 → 1.wav-4.wav) by default, so the imported (cuts: all) timeline has V1+A1 only and the new edit timeline inherits that. This sweep is a no-op in the typical case but catches any A2-A5 content if `--keep-linked-audio` was passed to apply_cuts or if A2-A5 were populated by hand for testing. The Fairlight preset expects A2-A5 free for BGM/battle audio placement.

**12a. Classify BGM tracks if not already done (one-time per project):**

Check whether `~/.resolve-mcp/bgm-tags.json` exists. If it doesn't, run both classifier stages now. If it does, skip to 12b.

If the cache is missing — start `classify_bgm.py` in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\classify_bgm.py"
```

Relay — YOU must complete this step:
- Poll until `plans/prompts/bgm-tags.in.md` appears.
- Spawn ONE Haiku subagent (`model: "haiku"`) with the prompt. It classifies every BGM filename into `battle_rival`, `battle_gym`, `battle_generic`, `general`, or `exclude` and writes the JSON object directly to `plans/prompts/bgm-tags.out.md`.

After `classify_bgm.py` exits, run the audio-feature pass to confirm/reclassify ambiguous picks:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\analyze_bgm_audio.py"
```

This adds BPM / RMS / spectral centroid / onset rate to each tag entry. It reports mismatches between the name-tag and audio classification. Review the mismatches and decide whether to manually correct any in `~/.resolve-mcp/bgm-tags.json` before continuing.

**12b. Classify battle types (rival / gym / other):**

Start `classify_battles.py` in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\classify_battles.py"
```

Relay — YOU must complete this step:
- Poll until `plans/prompts/battle-types.in.md` appears.
- Read the prompt. For each battle, classify as `rival` / `gym` / `other` using the surrounding transcript context. Write a single JSON object to the `.out.md`:
  ```json
  {"0": {"type": "rival", "reasoning": "..."}, "1": {"type": "gym", "reasoning": "..."}, ...}
  ```
- The script caches to `transcripts/battle-types.json` and exits.

**12c. Place Dual Screen Lovelife on A2 (intro-speed-aware offset):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_bgm.py --game GAME_KEY"
```

**12d. Chain general BGM between battles:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_bgm.py --seed 1"
```
Filters to `general`-tagged tracks only. Truncates at each battle start; picks a new track at each battle end.

**12e. Place looped battle audio (one track per battle type):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_audio.py --rival-track ""Take them down!.mp3"" --gym-track ""Big Baddies.mp3"" --other-track ""A new Challenger.mp3"""
```
Auto-picks the alphabetical-first track in each tag if `--rival-track` / `--gym-track` / `--other-track` are omitted. Loops within each battle interval; truncates the last loop at the battle end.

**12f. Apply -3dB fades at battle boundaries:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_audio_fades.py"
```
Pre-renders fade variants via ffmpeg (half-sine = constant power = -3dB), then replaces the existing clips with the faded variants. Fades pre-battle BGM end, battle audio start/end (first/last loop), post-battle BGM start, and the very last A2 clip.

### Step 13 — Apply Fairlight mixer preset (FX + levels + routing)

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_fairlight_preset.py --timeline ""<edit timeline name>"""
```

The script installs the bundled `assets/fairlight-presets/CONSOLE_FLEXI/Standard Gameplay youtube.dat` into Resolve's Fairlight Presets directory (if not already there), switches to the edit timeline, and calls `Project.ApplyFairlightPresetToCurrentTimeline("Standard Gameplay youtube")`. This applies the full mixer state: track names + subtypes, FX chains (compressors / EQ / limiters), levels, bus routing.

If Apply returns False (rare — happens after a true cold install on a new machine), restart Resolve once and re-run.

---

## Final summary

After all thirteen steps complete, print a summary table:

| Step | Result |
|------|--------|
| 1. Clear audio tracks | N clips removed from A2–A5 |
| 2. Battle gaps | N battles found, N extended, N marker-only |
| 3. Battle end markers (rough) | N green markers placed |
| 4. Cut candidates | N orange (high), N yellow (medium), N sub-clip markers |
| 5. Apply cuts | HIGH: N deletes / X.XXs removed; ALL: N deletes / Y.YYs removed |
| 6. Short clip removal | N clips ripple deleted from (cuts: all) |
| 7. Gap markers | N gaps marked on (cuts: all) |
| 8. Import + edit timeline | Game detected, N shared + N game files imported, edit timeline created with intro at X% |
| 9. Battle end markers (refined) | N markers refined on edit timeline |
| 10. Member Carousel Start | Marker placed at v1[N] (TC HH:MM:SS:FF) |
| 11. Carousel layout | N clips copied to V2 with CropBottom=530, V1 extended to outro |
| 12. A2 audio | DSL + N general BGM + N battle audio loops + N fade variants |
| 13. Fairlight preset | "Standard Gameplay youtube" applied |

The final timeline name is `<original> (cuts: all) (edit)`. The `(cuts: high)` sibling remains in the project as a less-aggressive alternative. The `(battle-gaps)` and original timelines can be deleted or kept for reference.

---

## Final manual step — Normalize Audio (UI only)

The Resolve scripting API does NOT expose `NormalizeAudio`. Tell the user to do this in the UI:

> **Edit page** (or Fairlight page):
>
> 1. Click the first clip on the track you want to normalize, then press **Ctrl+Shift+End** to select every clip out to the end.
> 2. **Right-click** any selected clip → **Normalize Audio Levels…**
> 3. Set:
>    - **Normalization Mode** → `Sample Peak Program`
>    - **Target Level** → `-9.0 dBFS`
>    - **Set Level** → `Relative`
>    - **Reference** → `Independently` (each clip's own peak)
> 4. Click **Normalize**.
> 5. Repeat for every audio track that needs leveling (A1 dialogue, A2 music/battles, plus any others in the Fairlight preset).
>
> The Fairlight preset's limiter on the master bus will catch any peaks after this; the per-track normalize just gives the mixer a consistent input level to work with.
