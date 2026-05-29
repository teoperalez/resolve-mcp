Run the full Resolve timeline editing pipeline in order. Each step runs to completion before the next begins, and every step is bracketed by `audit_step.py snapshot` (before) + `audit_step.py audit` (after) so that any unexpected change is caught immediately instead of compounding through downstream steps.

Arguments: $ARGUMENTS (pass --dry-run to preview the battles step without modifying the timeline)

All commands MUST be run from C:\Programming\resolve-mcp (every command uses `cd /d` prefix).

---

## Step-level audit (read this first)

Every step `N` is wrapped:

```
1. cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step <step_id>"
2. <the step's actual command(s)>
3. cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step <step_id>"
```

If the audit exits with a non-zero code: STOP. Read `_data/audits/<step_id>_report.json` and surface the violations + regressions to the user. Do not proceed to the next step until the user has decided how to handle them (re-run the step, accept the deviation, or abort).

When the audit passes, it automatically exports a Resolve-native `.drt` checkpoint to `_data/drt-checkpoints/` and records that path in the report's `drt_checkpoint` field. This is mandatory for any API-built or API-modified section; if the checkpoint export fails, the audit fails and the pipeline stops. Use the DRT as the durable Resolve-native recovery point for that step.

Scope declarations for every step live in `scripts/audit_scopes.py`. The audit checks two things:
- **Diff vs scope** — the changes actually observed must fall within the step's declared `allowed_changes`. Any other change is a violation.
- **Preservation** — entries in `must_preserve` (e.g., Green battle-end markers, Magenta carousel marker, A2 clip continuity) survive the step. A lost marker that was placed by a prior step is flagged as a *regression*.

Steps that create a new timeline (1d, 4, 6f) switch the audit into "derived expectations" mode (V1 clip count delta, source pool preserved, new TL name contains expected suffix, A2-A5 empty on the new TL when required).

---

## Pipeline ordering principle

**Cuts come first.** Applying cut candidates produces a NEW timeline (`(cuts: all)`) from FCPXML and discards anything that lives only on the old timeline (markers, audio placements, V2 overlays, color grades). Only operations whose state is portable — source-time decisions cached in JSON — survive a cut step. So the order is:

1. Operations that produce **portable JSON state** (transcript, battle source-time decisions, cut analysis)
2. **Apply cuts → new `(cuts: all)` timeline**
3. **Build edit timeline → new `(cuts: all) (edit)` timeline** (intro/outro, also a new TL)
4. Operations that produce **timeline-resident state** (markers, V2 carousel, A2 audio, Fairlight)

Re-running cut analysis later in the workflow would force redoing everything in categories 3–4. Putting cuts up front means we only commit timeline-resident operations to the final edit basis.

**Reorganization vs the previous pipeline:**
- The old Step 1 (clear A2-A5 on the original timeline) has been removed — that timeline is replaced twice (battle-gaps, cuts: all) and Step 4 already drops the auto-editor's linked audio refs. The clear was a no-op.
- The old Step 7 (mark A1 gaps on `(cuts: all)`) has been moved to Step 7 below — AFTER the edit timeline is built — so its ruler markers survive on the timeline of record.
- The old Step 13d ↔ 13e have been inverted: battle audio now lands on A2 BEFORE the between-battle BGM chain. The BGM chain then derives battle ranges from existing A2 clip boundaries (via `place_battle_bgm.py --respect-existing-a2`, on by default), eliminating the overlap risk that came from BGM and battle audio fighting over the same frames.
- The old defensive `clear_audio_tracks` of A2-A5 (was Step 13prep) has been removed. The Step 6 audit declares "A2-A5 must be empty on the new edit timeline" — if they aren't, the audit fails and the user investigates rather than silently nuking content.

---

## Pipeline order

### Step 0 — Session-log marker preflight

Run this before any transcript, battle-detection, or FCPXML rewrite work:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\preflight_session_markers.py"
```

This writes `transcripts\session-markers-preflight.json`.

Read the JSON before continuing:

- If `should_embed_session_markers=true`, the project has an RBYNewLayout
  session log. Treat those markers as canonical from the start of the pipeline.
  Do not infer RBY battle markers from transcript guesses when the preflight has
  mapped session-log markers to source media. Preserve/remap those markers
  through every FCPXML-derived timeline, and use timeline `* Battle Start`
  markers as canonical for Gen 1 leader intro placement.
- If `should_embed_session_markers=false`, continue with the normal transcript
  battle-detection flow below.
- If source media is split into multiple part files, use `markers_by_media` from
  the preflight to know which part(s) receive valid session markers. Do not
  collapse separate part files into a single combined MP4 just to simplify
  marker mapping.
- If the report says a session log exists but marker replay or source-media
  mapping failed, stop and surface the report. Do not continue until the user
  decides whether to proceed without embedded markers.

### Step 0b — Dialogue audio sanity check for split Gen 1 sources

Before re-running auto-editor or transcription on split source files, identify
the dialogue audio track deliberately:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_dialogue_audio.py --video "<source-dir>\<part-file>.mp4" --out _data\dialogue-audio-<part>.json --fail-weak"
```

The expected dialogue track is mostly quiet except when the streamer speaks,
and Whisper should see high-probability speech during active regions. Tracks
that are pure BGM, desktop audio/alerts, or music mixed under speech should not
be treated as the dialogue driver for auto-editor or transcription.

When an export has the full 5-track layout, the historical FCPXML/A1 primary
track convention can be trusted by default, while still writing the sanity
report. When a travel/single-mic setup produces only 3 extracted subtracks,
do not assume track 1; use the detector's chosen path for auto-editor stream
selection and transcription. For example, if the detector picks
`<stem>_3.wav`, run auto-editor with the corresponding audio stream selector
instead of blindly using FileOrganizer's default `audio:stream=0`.

### Step 1 — Battle gap insertion (transcribe + detect + FCPXML rewrite)

**1-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step1_battle_gaps"
```

**1a. Transcribe A1 audio:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\transcribe_audio.py --model large-v3-turbo"
```
Wait for completion. Note the stem (filename without .json) in `transcripts\`.

**1b. Run detect_battles.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\detect_battles.py transcripts\<stem>.json --out transcripts\battles.json --plans-dir plans\prompts --timeout-sec 600"
```

**1c. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-detect-<stem>.in.md` appears
- Read it and identify every first-time trainer battle start timestamp from the transcript
- Write ONLY a raw JSON array to the corresponding `.out.md` (no markdown fences):
  ```json
  [{"timestamp_sec": 123.4, "trainer_name": "Rival 1", "description": "..."}]
  ```
- detect_battles.py detects the `.out.md`, writes `transcripts\battles.json`, and exits

**1d. Insert battle gaps via FCPXML (canonical IRLPC approach):**

Resolve's Python API CANNOT ripple-insert into existing timeline content. So the canonical approach is to modify the auto-editor's `_ALTERED.fcpxml` and import the modified version as a new timeline.

Locate the auto-editor's FCPXML — typically next to the source video at `<source-dir>/<video-name>_ALTERED.fcpxml`. The source video path can be read from `transcripts/<stem>.json`'s `"audio"` field.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps_fcpxml.py "<source-dir>\<video-name>_ALTERED.fcpxml" --battles transcripts\battles.json --import-to-resolve"
```

For Gen 1 Red/Blue/Yellow projects with discrete leader/E4/champion intro
insertions, those boss battles get real timeline time from the intro insertion
step. Insert ordinary battle gaps only for non-boss battles:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step1_rby_non_boss_battle_gaps"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_battle_gaps_fcpxml.py "<source-dir>\<video-name>_ALTERED.fcpxml" --battles transcripts\battles.json --only-gen1-non-bosses --import-to-resolve"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step1_rby_non_boss_battle_gaps"
```

After import, the new `(battle-gaps)` timeline becomes current. All subsequent steps until cut application operate on it.

**1-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step1_battle_gaps"
```
Verifies the new TL's name contains `(battle-gaps)`, V1 clip count delta is non-negative, source media pool is preserved.

---

### Step 2 — Rough battle end markers

**2-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step2_mark_battle_ends_rough"
```

**2a. Run mark_battle_ends.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_battle_ends.py"
```
The script extracts frames from the source video around each battle's estimated end window and writes the relay prompt.

**2b. Relay — YOU must complete this step:**
- Poll with Read tool until `C:\Programming\resolve-mcp\plans\prompts\battle-ends-<stem>.in.md` appears
- Read it. It lists image file paths (one per extracted frame) with timestamps for each battle.
- For each battle, read each listed image file using the Read tool and visually identify the best end frame
- Write ONLY a raw JSON array to the corresponding `.out.md`:
  ```json
  [{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 385.3, "confidence": "high", "notes": "Trainer defeat pose visible"}]
  ```
- mark_battle_ends.py detects `.out.md`, places green timeline markers labeled `<Trainer> Battle End`, and exits.

The source-time decisions get cached in the `.out.md` — they will be re-used (via `--skip-relay`) after cuts to re-place markers on the new edit timeline.

**2-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step2_mark_battle_ends_rough"
```
Allowed: Green ruler markers added. Must preserve: all clips, all non-Green markers.

---

### Step 3 — Analyze cut candidates (LLM-flagged)

**3-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step3_mark_cut_candidates"
```

**3a. Run mark_cut_candidates.py in the BACKGROUND (run_in_background=true):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_cut_candidates.py"
```

The script enumerates every V1 clip on the `(battle-gaps)` timeline, attaches overlapping Whisper transcript text (multi-segment clips show each sub-segment with its own timestamps), excludes structural clips (intro/outro/B-roll — though at this stage there are no structural clips yet on `(battle-gaps)`), and writes the clip-driven analysis prompt.

**3b. Relay — YOU must complete this step:**
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

**3-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step3_mark_cut_candidates"
```
Allowed: V1 colors change to Orange/Yellow/empty, Red clip-level markers added. Must preserve: all clips, Green ruler markers from Step 2.

---

### Step 4 — Apply cuts → produce HIGH and ALL FCPXMLs

**4-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step4_apply_cuts"
```

Generate two cut variants and import both as new timelines. The `(cuts: all)` timeline becomes the new working basis; `(cuts: high)` remains available for A/B comparison.

The input FCPXML is the one produced by Step 1d (`*_ALTERED_BATTLEGAPS.fcpxml`, next to the source video). The cuts JSON is auto-detected from `plans/prompts/cut-analysis-<stem>.out.md`.

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_cuts_to_fcpxml.py "<source-dir>\<video-name>_ALTERED_BATTLEGAPS.fcpxml" -o "<source-dir>" --import-to-resolve"
```

After import, the `(cuts: all)` timeline becomes current. **All subsequent steps operate on it.** The replay metadata sidecar (`*_cuts_replay.json`) captures the cuts so they can be reproduced on a sibling timeline if needed (e.g., to mirror downstream operations onto `(cuts: high)`).

Report:
- HIGH cuts: N deletes, N trims, N splits, X.XXs removed
- ALL cuts: N deletes, N trims, N splits, X.XXs removed

**4-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step4_apply_cuts"
```
Verifies the new TL's name contains `(cuts: all)` and the source pool is preserved.

**4c. Verify cut quality (audio-aware) — separate pass:**

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\verify_pipeline.py --report-only"
```

If `--report-only` reports >0 flags in pink/yellow, decide whether to fix inline via repair scripts or proceed and revisit:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\verify_pipeline.py --fix"
```

---

### Step 5 — Ripple delete short clips (< 5 frames) from V1 and A1

**5-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step5_remove_short_clips"
```

Micro-cleanup on the cut timeline.
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\remove_short_clips.py"
```
Wait for completion. Report clips removed.

**5-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step5_remove_short_clips"
```
Allowed: V1/A1 short-clip removals + ripple shifts. Must preserve: V2 and A2-A5 contents (should be empty/intro-only at this point).

---

### Step 6 — Import assets and build edit timeline

**6-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step6_build_edit_timeline"
```

The transcript from Step 1a is already available. Use it now to detect the game and run the full import pipeline.

**6a. Detect game and check game-specific manifest:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --check"
```
Infer GAME_KEY from the transcript in `transcripts\` (first ~3000 chars of `text` field). If any paths are missing or invalid, prompt the user before continuing.

**6b. Check shared assets (type icons, BGM, badges, gym leaders, Pokémon artwork):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --check-shared"
```
If status is `needs_paths`, prompt the user for each missing folder path and set them:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --set-shared-path ASSET_ID "PATH""
```

**6c. Import shared assets into sub-bins (skip if all already valid and bins exist):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --import-shared"
```

**6d. Import game-specific assets:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\import_assets.py --game GAME_KEY --do-import"
```

**6e. Classify Minimum Battles Series (relay — drives intro speed):**

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

**6f. Build the edit timeline (intro prepended, clips shifted, outro appended):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\insert_intro_outro.py --game GAME_KEY"
```

The script auto-reads `transcripts/min-battles.json`: intro plays at **100%** if `is_minimum_battles=true`, otherwise at **400%** (4x speed) — retime via ffmpeg pre-render cached at `~/.resolve-mcp/cache/retimed-intros/`.

After this step the new `(cuts: all) (edit)` timeline is the active timeline. All subsequent steps operate on it.

**6-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step6_build_edit_timeline"
```
This audit serves as the **A2-A5 empty gate** (replacement for the old Step 13prep defensive clear). It verifies:
- The new TL's name contains `(edit)`
- A2, A3, A4, A5 all have zero clips on the new TL

If A2-A5 are NOT empty, the audit fails. Do not run a clear — investigate what placed content on them (likely a leftover from a previous pipeline run that wasn't properly cleaned). Decide manually whether to clear or to abort.

**6g. Verify after edit-timeline build (audio-aware QA, separate pass):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\verify_pipeline.py --report-only"
```

Reads `*_gap_warnings.json` from Step 1d and flags lime any battles where `insert_battle_gaps_fcpxml.py` couldn't supply the full 60-frame pre-roll. If lime flags exist, run `repair_lime_battle_gaps.py` OR manually trim in Resolve.

---

### Step 7 — Mark A1 gaps > 5 frames on timeline ruler and V1 clips

**Moved from the old Step 7 position** so the ruler markers land on the timeline of record (the edit TL) instead of being discarded when Step 6 builds the new TL.

**7-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step7_mark_audio_gaps"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_audio_gaps.py"
```

**7-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step7_mark_audio_gaps"
```
Allowed: Red ruler + clip-level markers added. Must preserve: all clips, all non-Red markers (the Green markers from earlier will be re-placed in Step 8 — but until then must not disappear).

---

### Step 8 — Re-place + refine battle end markers on the edit timeline

The source-time end decisions from Step 2 are persisted in the `.out.md` and survive the cut + edit-timeline steps. Now we map them through the new V1 layout.

**8a. Re-place initial markers on the edit timeline (uses cached relay):**

**8a-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step8a_replace_battle_end_markers"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\mark_battle_ends.py --skip-relay"
```
Reuses the `battle-ends-<stem>.out.md` from Step 2 and remaps source-seconds → timeline frames through the new edit timeline's V1 clips.

**8a-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step8a_replace_battle_end_markers"
```

**8b. Refine to precise transition frames (parallel subagents, fresh relay):**

**8b-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step8b_refine_battle_ends"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\refine_battle_ends.py"
```
Extracts ~41 frames at 0.25s steps in a ±5s window around each rough estimate (~246 frames total for 6 battles) and writes `plans/prompts/battle-ends-refine-<stem>.in.md`.

Relay — YOU must complete this step:
- Poll until the `.in.md` appears.
- Read it. For each battle, spawn ONE Haiku subagent (parallel, `model: "haiku"`) with that battle's dense frame list and the visual-pattern guidance from the prompt. Each subagent Reads its 41 frames and returns one JSON object with the precise `end_sec`.
- Collect all responses into a single JSON array and write to the corresponding `.out.md` (raw JSON, no fences).

The script clears the existing Green markers and replaces them with refined ones (typical drift after refinement: wins within ±0.5s, gave_ups within ±2s).

**8b-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step8b_refine_battle_ends"
```
Allowed: Green ruler markers removed AND added (the refine step is delete-then-replace). Must preserve: all clips, Red and Magenta markers.

---

### Step 9 — Place major-boss battle intros

For each rival / gym leader / Elite 4 / champion battle, overlay a 5-second pre-battle intro graphic on V2 (covering the last 5s of the V1 clip that runs into the battle).

Exception: for Gen 1 Red/Blue/Yellow projects whose leader intros are discrete
video + audio files (for example `Brock.mp4` plus `audio\Brock.mp3` under
`C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros`), do not use the silent
V2 overlay mode. Use `place_battle_intros.py --gen1-insert`, which creates a
derived timeline, inserts the leader intro video/audio as real timeline time,
and ripples later clips/markers right. In this mode, timeline `* Battle Start`
markers from Step 0 are canonical when present; transcripts are only a fallback
when no such markers exist. After placement, these Gen 1 leader intro video
and audio clips are protected structural sections like the channel intro/outro:
cut steps must not trim or remove them, and every later audit fails if any
leader-intro clip identity/count disappears.

**9a. Classify battle types (prerequisite — relay):**

Start `classify_battles.py` in the BACKGROUND. This classifies each battle as `rival` / `gym` / `other` — needed BOTH by battle-intro placement (Step 9c) AND by the A2 battle-audio pipeline (Step 12d). Run once here, both steps reuse the cached `transcripts/battle-types.json`.

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

**9b. Classify rival's starter + per-battle location (relay — only runs if there are rival battles):**

Start `classify_rival_starter.py` in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\classify_rival_starter.py"
```

Relay — YOU must complete this step (skip if no rival battles in `transcripts/battle-types.json`):
- Poll until `plans/prompts/rival-starter.in.md` appears.
- Read it. Identify the rival's starter type and per-battle location.
- Write a single JSON object to `.out.md`:
  ```json
  {
    "rival_starter_type": "grass",
    "confidence": "high",
    "evidence": "...",
    "reasoning": "...",
    "rivals_by_battle_index": { "0": "cherrygrove", "5": "azalea", "7": "burnedtower" }
  }
  ```
- The script caches to `transcripts/rival-starter.json` and exits.

**9c. Place the intros:**

**9-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step9_place_battle_intros"
```

Normal overlay mode:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_intros.py"
```

Gen 1 discrete insert mode:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step9_place_battle_intros_gen1"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_intros.py --gen1-insert --gen1-speed 2"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step9_place_battle_intros_gen1"
```

**9-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step9_place_battle_intros"
```
Allowed: V2 clip additions + idempotent V2 sweep removals. Must preserve: V1 contents, A1 contents, Green and Red markers.

If the user asks to stop for manual review after leader intro placement, stop
after the Step 9 audit passes. Do not continue to carousel layout, A2 music,
Fairlight, normalization, or render steps.

---

### Step 10 — Find Member Carousel Start

**10-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step10_find_member_carousel"
```

Run find_member_carousel.py in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\find_member_carousel.py"
```

Relay — YOU must complete this step:
- Poll until `plans/prompts/member-carousel-<edit-tl-stem>.in.md` appears.
- Spawn ONE Haiku subagent with the prompt. It scans candidate first-frames sequentially until it finds one with the carousel style, then checks the previous clip's last frame to decide whether the carousel actually started in the previous clip.
- Haiku writes the JSON object directly to the corresponding `.out.md`.

The script places a Magenta `Member Carousel Start` marker at the chosen clip's start.

**10-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step10_find_member_carousel"
```
Allowed: one Magenta ruler marker added. Must preserve: everything else.

---

### Step 11 — Layout the carousel section (V1 extend + V2 with bottom crop)

**11-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step11_layout_carousel"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\layout_carousel.py"
```

**11-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step11_layout_carousel"
```
Allowed: V2 clip additions; V1 carousel range deletions + replacements; V1 modifications. Must preserve: A1 contents, Green markers, Magenta carousel marker.

---

### Step 12 — A2 audio pipeline (BGM + battle audio + fades)

Fill A2 with dynamic music. **Reordered vs the old pipeline**: battle audio is placed FIRST (12d), then the between-battle BGM chain fills the complement (12e), eliminating the overlap risk that came from BGM and battle audio fighting over the same frames.

**12a. Classify BGM tracks if not already done (one-time per project):**

Check whether `~/.resolve-mcp/bgm-tags.json` exists. If it doesn't, run both classifier stages now. If it does, skip to 12c.

If the cache is missing — start `classify_bgm.py` in the BACKGROUND:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\classify_bgm.py"
```

Relay — YOU must complete this step:
- Poll until `plans/prompts/bgm-tags.in.md` appears.
- Spawn ONE Haiku subagent with the prompt. It classifies every BGM filename into `battle_rival`, `battle_gym`, `battle_generic`, `general`, or `exclude` and writes the JSON object directly to `plans/prompts/bgm-tags.out.md`.

After `classify_bgm.py` exits, run the audio-feature pass:
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\analyze_bgm_audio.py"
```

**12b. Battle types are already classified** in Step 9a; `transcripts/battle-types.json` is reused.

**12c. Place Dual Screen Lovelife on A2 (intro-speed-aware offset):**

**12c-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step12c_place_bgm_dsl"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_bgm.py --game GAME_KEY"
```

**12c-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step12c_place_bgm_dsl"
```
Allowed: A2 clip(s) added. Must preserve: all other tracks + all markers.

**12d. Place battle audio on A2 (INVERTED — now BEFORE the BGM chain):**

**12d-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step12d_place_battle_audio"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_audio.py --rival-track ""Take them down!.mp3"" --gym-track ""Big Baddies.mp3"" --other-track ""A new Challenger.mp3"""
```
Auto-picks the alphabetical-first track in each tag if `--rival-track` / `--gym-track` / `--other-track` are omitted. Loops within each battle interval; truncates the last loop at the battle end.

**Gen 1 discrete leader-audio crossfade exception.** For RBY projects where
Step 9 inserted real 2x leader intro video/audio on V1/A3, and the desired
battle music is the same leader audio continuing after the intro, use the
project-specific marker-driven placer instead of the generic BGM-tagged battle
audio command:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step victreebel_battle_audio_crossfades"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_victreebel_battle_audio.py"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step victreebel_battle_audio_crossfades"
```

This script reads the live timeline markers directly. Rival ranges get
`CODEx\assets\leader-audio\Rival.mp3` on A2 from battle start to finish with a
fade-out. Leader/E4/champion ranges continue the matching retimed
`__2x_resolve2` audio source on A2, starting 1 second before the `Leader Intro
End` marker. The existing A3 leader intro audio is replaced with a frame-exact
WAV fade-out variant, so A3 fades out while A2 fades in during the 60-frame
overlap. The audit permits only A2 additions and same-duration A3 leader-audio
fade replacements, while still preserving V1/A1/markers and rejecting A2
overlaps.

**12d-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step12d_place_battle_audio"
```
Allowed: A2 clip additions. Must preserve: V1/V2/A1/A3, DSL clip from 12c (no A2 clip removed before the first battle), no A2 overlaps.

**12e. Chain general BGM in the COMPLEMENT of battle A2 ranges:**

**12e-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step12e_place_battle_bgm"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\place_battle_bgm.py --seed 1"
```
`place_battle_bgm.py` uses `--respect-existing-a2` by default: it scans A2, treats DSL as the start anchor and each later contiguous clip group as a battle range, and fills only the gaps between them. The script never re-reads `battles.json` or green markers in this mode, so there is no overlap risk with 12d.

**Final segment override** (after the last battle, up to the outro): plays a fixed sequence — `Dual Screen Lovelife` → `Motivated By Clouds` → `Roll Me in Stardust` — then chains random `audio_classification: "energetic"` tracks until the outro starts. Pass `--final-sequence ""` to disable.

**12e-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step12e_place_battle_bgm"
```
Allowed: A2 clip additions. Must preserve: V1/V2/A1/A3, all battle-audio clips placed by 12d, no A2 overlaps.

**12f. Apply -3dB fades at battle boundaries:**

Skip this generic fade step for battle clips already processed by
`place_victreebel_battle_audio.py`; that script bakes the Rival fade-outs and
the A3→A2 leader crossfades. Only run a follow-up fade pass if the specific
timeline still needs between-battle/general-BGM fades, and wrap it with a
scope that preserves the Gen 1 leader-audio fade replacements.

**12f-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step12f_apply_audio_fades"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_audio_fades.py"
```
Pre-renders fade variants via ffmpeg (half-sine = constant power = -3dB), then replaces the existing clips with the faded variants. Fades pre-battle BGM end, battle audio start/end (first/last loop), post-battle BGM start, and the very last A2 clip.

**12f-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step12f_apply_audio_fades"
```
Allowed: A2 clip add/remove/modify (the fade pre-render replaces each affected clip with a new MPI). Must preserve: A2 total frame coverage roughly unchanged, V1/V2/A1/A3 contents, all markers.

**12g. Verify A2 audio coverage (separate audio-aware QA pass):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\verify_pipeline.py --report-only"
```

If brown flags appear, run `repair_brown_bgm.py` (trims BGM end at battle start) and re-run `place_battle_audio.py --only-battles N,N` for the now-uncovered battles. Then re-run `apply_audio_fades.py`.

---

### Step 13 — Apply Fairlight mixer preset (FX + levels + routing)

**13-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step13_apply_fairlight_preset"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\apply_fairlight_preset.py --timeline ""<edit timeline name>"""
```

The script installs the bundled `assets/fairlight-presets/CONSOLE_FLEXI/Standard Gameplay youtube.dat` into Resolve's Fairlight Presets directory (if not already there), switches to the edit timeline, and calls `Project.ApplyFairlightPresetToCurrentTimeline("Standard Gameplay youtube")`. This applies the full mixer state: track names + subtypes, FX chains (compressors / EQ / limiters), levels, bus routing.

If Apply returns False (rare — happens after a true cold install on a new machine), restart Resolve once and re-run.

**13-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step13_apply_fairlight_preset"
```
Allowed: A2 lock state changes to True. Must preserve: all clips on all tracks (the preset modifies mixer state, not clips), all markers.

If anything other than the A2 lock changes, the audit will flag it — investigate before continuing.

---

### Step 14 — Normalize audio (UI step, then confirm)

**This step is the only manual operation in the pipeline.** Tell the user to do it in the Resolve UI:

> **Edit page (or Fairlight page):**
>
> 1. Click the first clip on each audio track, then press **Ctrl+Shift+End** to select every clip to the end of that track.
> 2. **Right-click** any selected clip → **Normalize Audio Levels…**
> 3. Settings:
>    - **Normalization Mode** → `Sample Peak Program`
>    - **Target Level** → `-9.0 dBFS`
>    - **Set Level** → `Relative`
>    - **Reference** → `Independently` (each clip's own peak)
> 4. Click **Normalize**.
> 5. Repeat for **A1 (Dialogue)**, **A2 (Music)**, **A3 (Music 2 / outro audio)**.

**Ask the user via AskUserQuestion** to confirm audio normalization is done before proceeding.

**14-snap (before user starts):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step14_normalize_audio"
```
(In practice, since this is a manual UI step, run snap first → ask the user → wait → run audit. The snapshot captures clip names/colors; the audit will tolerate modifications but not added/removed clips.)

**14-audit (after user confirms):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step14_normalize_audio"
```

**14c. Final pre-render verify (audio-aware QA pass):**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\verify_pipeline.py --report-only"
```

If any flags appear, prefer fixing them BEFORE rendering.

---

### Step 15 — Render QA 720p

After audio normalization is confirmed, render a fast 720p pass for review.

**15-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step15_render_qa"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\render_timeline.py --preset qa"
```

Output: `<source-dir>\<timeline-name>_QA_720p.mp4` (uses Resolve's `YouTube - 720p` built-in preset). A ~30-min timeline typically renders in 90-120 minutes on a single NVIDIA GPU using H.264 NVENC with 4K-source downscaling.

This step blocks until the render completes. After it does, **ask the user** to review and approve before kicking off the 4K final render.

**15-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step15_render_qa"
```
Allowed: no timeline changes (render writes to disk only). Must preserve: everything.

---

### Step 16 — Render 4K final (after QA approval)

Once the user approves the QA pass:

**16-snap:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py snapshot --step step16_render_4k"
```

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\render_timeline.py --preset 4k"
```

Output: `<source-dir>\<timeline-name>_FINAL_4K.mp4` (uses Resolve's `YouTube - 2160p` built-in preset). Expect ~2-4 hours for a ~30-min timeline.

If the user wants changes, hold here — don't start the 4K render until the QA is approved.

**16-audit:**
```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python.exe scripts\audit_step.py audit --step step16_render_4k"
```

---

## Final summary

After all sixteen steps complete, print a summary table:

| Step | Result |
|------|--------|
| 1. Battle gaps | N battles found, N extended, N marker-only |
| 2. Battle end markers (rough) | N green markers placed |
| 3. Cut candidates | N orange (high), N yellow (medium), N sub-clip markers |
| 4. Apply cuts | HIGH: N deletes / X.XXs removed; ALL: N deletes / Y.YYs removed |
| 5. Short clip removal | N clips ripple deleted from (cuts: all) |
| 6. Import + edit timeline | Game detected, N shared + N game files imported, edit timeline created with intro at X% |
| 7. Audio gap markers | N gaps marked on edit timeline |
| 8. Battle end markers (refined) | N markers refined on edit timeline |
| 9. Battle intros (V2) | N rival + M gym intros placed; rival starter type detected |
| 10. Member Carousel Start | Marker placed at v1[N] (TC HH:MM:SS:FF) |
| 11. Carousel layout | N clips copied to V2 with CropBottom=530, V1 extended to outro |
| 12. A2 audio | DSL + N battle audio loops + N general BGM + N fade variants |
| 13. Fairlight preset | "Standard Gameplay youtube" applied (A2 now locked) |
| 14. Normalize audio | Confirmed by user (UI step) |
| 15. QA 720p render | `<stem>_QA_720p.mp4` rendered, X.X GB, Y min runtime |
| 16. Final 4K render | `<stem>_FINAL_4K.mp4` rendered, X.X GB, Y min runtime |

The final timeline name is `<original> (cuts: all) (edit)`. The `(cuts: high)` sibling remains in the project as a less-aggressive alternative. The `(battle-gaps)` and original timelines can be deleted or kept for reference.

**A2 lock-after-Fairlight note:** Step 13's Fairlight preset locks A2 (Music). If you need to re-run any audio placement (Steps 12c-12f) after the preset is applied, unlock A2 first with `tl.SetTrackLock('audio', 2, False)`.

**Audit reports:** every step writes `_data/audits/<step_id>_pre.json`, `_post.json`, and `_report.json`. The report carries the violations, regressions, expected-observed deltas, and audio-check counts. Surface the report path to the user whenever an audit fails.

---

## QA tooling reference

The pipeline ships with an audio-aware verification + repair layer that catches the most common quality issues automatically. The step-level audit (`scripts/audit_step.py`) wraps `verify_pipeline.py`'s detectors and adds state-diff regression detection.

### `scripts/audit_step.py`

`snapshot --step ID` writes a pre-step snapshot. `audit --step ID` re-snapshots, diffs against the pre, validates the diff against the step's scope in `audit_scopes.py`, and runs `verify_pipeline.py` checks. Exit code = number of violations. Outputs land in `_data/audits/`.

### `scripts/verify_pipeline.py`

Scans the current timeline and auto-flags 5 issue classes using the editor's color convention:

| Color  | Issue                                  | Detection method |
|--------|----------------------------------------|------------------|
| Pink   | Cut lands in speech / tiny remnant     | RMS speech-active probe in source ±40ms of cut edge |
| Yellow | Missed repetition / stutter cluster    | 2+ adjacent <0.5s clips within 1.5s window |
| Lime   | Battle pre-roll missing                | First 60 frames of battle clip not ≥60% silent |
| Teal   | Unwanted pre-roll                      | 60+ silent frames at clip start but no battle within ±5s |
| Brown  | BGM tagged general/exclude overlaps a battle | A2 clip name → bgm-tags.json tag → battle TL range overlap |

Flags:
- `--report-only` (default): scan + write `_data/qa-reports/<stem>.json`, no color changes
- `--no-pink`: skip the audio-based checks (instant — useful for fast structure-only QA)
- `--from-timeline`: harvest existing clip colors as authoritative flags
- `--fix`: after reporting, dispatch matching `repair_*.py` for each flag
- `--preserve-manual`: don't overwrite clips that already have a color

### `scripts/repair_*.py` (5 scripts)

- **`repair_pink_cuts.py`** — tiny clips (<0.3s) ripple-deleted; larger clips have their cut edge snapped to nearest silence; unrecoverable cases recolored Purple
- **`repair_yellow_repetitions.py`** — ripple-deletes flagged clips
- **`repair_lime_battle_gaps.py`** — steals 60 frames from previous V1 clip's right-handle
- **`repair_teal_extra_gap.py`** — trims unwanted pre-roll off clip start
- **`repair_brown_bgm.py`** — trims BGM end at battle start

All accept `--dry-run` and re-color repaired clips Navy or Mint so the changes are visible.
