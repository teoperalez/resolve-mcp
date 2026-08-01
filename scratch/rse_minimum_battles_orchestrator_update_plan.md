# RSE / Generic Minimum Battles Orchestrator Update Plan

Goal: add a review-first orchestrator workflow for videos like `Roxanne
Minimum Battles 19`: multi-part Pokemon minimum-battles count videos with RSE
assets, one-second A1 dialogue gaps, continuous V1 visual holds, continuous A2 BGM, and explicit
marker semantics.

This is a sibling workflow to `gen1_rby_umb_review_first`, not a replacement.
The existing RBY UMB workflow remains for Gen 1 session-log-driven videos.

## Architectural Decisions

1. Add a new workflow id:
   - `generic_minimum_battles_review_first`

2. Add the first seed profile:
   - `roxanne_rse_minimum_battles_19`

3. Add a new pipeline bridge:
   - `scripts/run_minimum_battles_pipeline.py`

4. Reuse the existing orchestrator catalog tool:
   - `profile_pipeline_stage`
   - `profile_pipeline_stage_strict`

   Do not add a redundant `profile_minimum_battles_stage` unless a future GUI
   label separation becomes useful.

5. Keep `gap_plan.json` as a first-class artifact.
   The approved edit structure must drive gaps and markers. The final builder
   must not infer structural gaps or markers from transcript vibes.

6. Add a separate first-class `structure_decisions.json`.
   This is the human/LLM-approved semantic structure. A deterministic compiler
   converts it into frame-accurate `gap_plan.json`.

7. Build a final-base FCPXML before the A1 dialogue audit.
   The audit must inspect the post-cut, post-gap A1 FCPXML, so the correct
   order is:
   - compile approved source cuts;
   - compile approved structure;
   - compile gap plan;
   - build final-base FCPXML;
   - run A1 dialogue audit;
   - import/assemble in Resolve.

8. Do not reuse the RBY session-log, Gen 1 intro, or RBY BGM stages.

## Seed Profile Values

Suggested profile values:

- `game_version`: `pokemon_emerald` or `pokemon_ruby_sapphire`
- `challenge_type`: `minimum_battles_multi_pokemon`
- `project_dir`: `F:/Roxanne Minimum Battles 19`
- `codex_dir`: `{project_dir}/CODEx`
- `pipeline_script`: `scripts/run_minimum_battles_pipeline.py`
- `source_parts`: JSON list of part MKVs
- `used_source_parts`: optional JSON list if part 1 exists but should not be
  used in the stitched review/final timeline
- `asset_root`: `F:/RSE Assets`
- `layout_root`: `F:/Programming/RSENewLayout`
- `intro_asset`: `F:/Programming/RSENewLayout/RSE Short intro.mp4`
- `outro_asset`: `F:/RSE Assets/RSE Assets.mp4`
- `background_infinite_asset`: `F:/RSE Assets/RSE Assets Infinite.mkv`
- `bgm_dir`: `F:/Programming/RSENewLayout/audio/bgm`
- `timeline_fps`: `60`
- `auto_editor_margin`: `0.1sec`
- `auto_editor_edit`: `audio:stream=0`
- `auto_editor_export`: `resolve`
- `dialogue_track_index`: `4`
- `gap_frames`: `60`
- `marker_offset_frames`: `34`
- `audio_normalization_target_db`: `-9.0`
- `fairlight_preset`: `Standard Gameplay youtube`
- `fairlight_preset_type`: `CONSOLE_FLEXI`

Important profile/editor note: complex fields such as `source_parts`,
`used_source_parts`, and playlists should be stored as real JSON arrays in the
profile and read by the pipeline script from the active profile. They should not
be passed as catalog command placeholders.

## Workflow Stages

Initial workflow stages:

1. `input-preflight`
2. `auto-editor-multi`
3. `review-base`
4. `narrative-prompt`
5. `narrative-llm-review`
6. `programmatic-candidates`
7. `compile-cut-candidates`
8. `apply-html-decisions`
9. `compile-approved-cuts`
10. `structure-decisions`
11. `gap-plan`
12. `final-base-fcpxml`
13. `a1-dialogue-audit`
14. `rse-assets-preflight`
15. `resolve-final-assembly`
16. `bgm`
17. `clip-colors`
18. `fairlight`
19. `audio-normalization-handoff`
20. `validate-order`

Do not call:

- `gen1-intros`
- RBYNewLayout session marker replay
- RBY leader intro placement
- `place_rby_umb_bgm.py` unless it is generalized first

## Input Preflight

Add `input-preflight` before running auto-editor.

Responsibilities:

- Validate `source_parts` / `used_source_parts`.
- Validate `intro_asset`, `outro_asset`, `background_infinite_asset`, and
  `bgm_dir`.
- Validate `timeline_fps`, `dialogue_track_index`, `gap_frames`, and
  `marker_offset_frames`.
- Validate auto-editor is available.
- Write `{codex_dir}/minimum_battles/input_preflight.json`.

If required media or paths are missing, stop with concrete user choices:

1. provide or regenerate the missing data;
2. update the project profile path/setting in the orchestrator GUI;
3. explicitly approve a named fallback.

## Auto-Editor Multi-Part Support

Create:

- `scripts/orchestrator_auto_editor_multi.py`

It should run auto-editor for each selected source part:

```powershell
auto-editor "F:\Roxanne Minimum Battles 19\Roxanne Minimum Battles 19 part N.mkv" --margin 0.1sec --edit audio:stream=0 --export resolve
```

Output contract:

```json
{
  "schema": "minimum_battles_auto_editor_parts_v1",
  "fps": 60,
  "dialogue_track_index": 4,
  "parts": [
    {
      "index": 1,
      "source_media": "...part 2.mkv",
      "fcpxml": "...part 2_ALTERED.fcpxml",
      "dialogue_audio": "...part 2_tracks/4.wav",
      "track_folder": "...part 2_tracks",
      "raw_duration_frames": 0,
      "edited_duration_frames": 0
    }
  ]
}
```

Write the manifest to:

- `{codex_dir}/minimum_battles/auto_editor/parts_manifest.json`

## Review Base Builder

Create:

- `scripts/build_minimum_battles_fcpxml.py`

Responsibilities:

- Parse all part `_ALTERED.fcpxml` files.
- Build a stitched review FCPXML with:
  - V1 gameplay clips in part order;
  - A1 dialogue clips using the selected dialogue track;
  - per-part source metadata preserved for cut review and final remapping.
- Produce:
  - `{codex_dir}/cut_review/review_base.fcpxml`
  - `{codex_dir}/cut_review/review_base_manifest.json`
  - `{codex_dir}/cut_review/clips_for_review.json`
  - `{codex_dir}/minimum_battles/source_map.json`

The review base must not include final intro/outro, final visual holds, BGM, carousel, or
final markers.

Important audit choice:

- Prefer generating a stitched dialogue WAV and using it as the final-base A1
  audit input.
- If per-part dialogue WAVs are kept as separate FCPXML assets, generalize
  `audit_fcpxml_a1_dialogue.py` so it audits each A1 asset against the matching
  audio file instead of assuming one audio source.

## Cut Candidate / Narrative Review

Reuse the review-first architecture and HTML/FCPXML review surfaces, but create
generic minimum-battles wrappers where RBY-specific session-log assumptions
would leak.

Create:

- `scripts/generate_minimum_battles_cut_candidates.py`

Prompt/review output should cover:

- cut candidates;
- narrative cuts;
- Pokemon section starts and ends;
- significant battle pre-roll points;
- mid-video recap/ad slots;
- unevolved-form failure propagation markers;
- final outro recap marker;
- member carousel start marker.

LLM suggestions are allowed, but only approved structure flows into
`structure_decisions.json`.

## Structure Decisions Contract

Create:

- `{codex_dir}/minimum_battles/structure_decisions.json`

Schema:

```json
{
  "schema": "minimum_battles_structure_decisions_v1",
  "fps": 60,
  "items": [
    {
      "id": "pokemon_start_articuno",
      "kind": "pokemon_start",
      "label": "Articuno",
      "part_index": 1,
      "source_frame": 23938,
      "review_frame": 23938,
      "approved": true,
      "marker": {
        "add": true,
        "type": "pokemon_start",
        "name": "Articuno"
      }
    }
  ]
}
```

Allowed `kind` values:

- `pokemon_start`
- `pokemon_end`
- `significant_battle_pre_roll`
- `recap_ad_slot`
- `unevolved_failure_propagation`
- `final_outro_recap`
- `member_carousel_start`

## Gap Plan Contract

Create:

- `{codex_dir}/minimum_battles/gap_plan.json`

Schema:

```json
{
  "schema": "minimum_battles_gap_plan_v1",
  "fps": 60,
  "gap_frames": 60,
  "marker_offset_frames": 34,
  "gaps": [
    {
      "id": "gap_articuno_start",
      "source_item_id": "pokemon_start_articuno",
      "kind": "pokemon_start",
      "part_index": 1,
      "source_frame": 23938,
      "review_frame": 23938,
      "post_cut_frame": 23800,
      "final_gap_start_frame": 24822,
      "gap_frames": 60,
      "v1_hold": {
        "extend": true,
        "continuous": true,
        "track_index": 1,
        "duration_frames": 60,
        "name": "continuous V1 cover"
      },
      "marker": {
        "add": true,
        "type": "pokemon_start",
        "name": "Articuno",
        "frame": 24856
      }
    }
  ]
}
```

Correct policy:

- Add a 60-frame A1 gap for Pokemon starts, recap/ad-safe slots, and
  significant battle pre-rolls only when a Pokemon section has multiple battles.
- Cover every A1 gap with an extended, unbroken V1 clip on track 1. Do not use
  still images, freeze-frame assets, or higher-track overlays for visual holds.
- Keep A2 music continuous through every gap.
- Do not infer a marker merely because a gap exists.
- Add markers only for:
  - Pokemon starts;
  - unevolved-form failure propagation;
  - final outro recap;
  - member carousel start.
- Allow explicit late recap exceptions where V1 hold duration differs from the
  A1 gap. Such exceptions must carry `exception_reason`.

## Final Base FCPXML Builder

Extend `scripts/build_minimum_battles_fcpxml.py` with a final-base mode.

Responsibilities:

- Apply approved source cuts.
- Apply `gap_plan.json`:
  - open 60-frame A1 dialogue gaps;
  - extend V1 continuously across normal A1 gaps;
  - place markers at approved marker points, usually
    `final_gap_start_frame + marker_offset_frames`.
- Add intro:
  - `RSE Short intro.mp4` from frame 0;
  - 59-frame blur dissolve ending at gameplay start if supported by the FCPXML
    path used by the current pipeline.
- Start gameplay after the profile-derived intro duration.
- Add RSE outro and member carousel ending structure.
- Add Text+ callouts only from explicit user/project data.
- Write:
  - final-base FCPXML;
  - final manifest;
  - gap/marker report;
  - source remap report.

## A1 Dialogue Audit

Run after `final-base-fcpxml` and before Resolve final assembly.

Required behavior:

- Rerun faster-whisper on the final A1 dialogue source(s).
- Fail if any final-base FCPXML A1 clip has no overlapping recognized dialogue.
- Treat coughs, throat clears, and short non-word noises as review/cut
  candidates rather than valid final dialogue.

## RSE Asset Preflight / Relink

Add `rse-assets-preflight` after the final-base audit and before Resolve final
assembly.

Responsibilities:

- Import or relink:
  - intro;
  - outro;
  - background infinite;
  - BGM folder;
  - generated part WAVs/FCPXML media.
- Validate no focused missing media remains for:
  - source part MKVs;
  - part track WAVs;
  - RSE assets;
  - BGM folder.

Prefer explicit profile paths over fuzzy filename search because the RSE assets
have been renamed.

## BGM Bed

Create:

- `scripts/place_minimum_battles_bgm.py`

RSE/Roxanne rule:

- A2 is continuous from frame 0 until final gameplay/outro handoff.
- BGM must not cut around A1 gaps.
- Default behavior can use sequential tracks in folder order or a configured
  playlist.
- A3 is reserved for outro/music tail beginning at the outro/card start.

Profile parameters:

- `bgm_dir`
- `bgm_playlist`
- `bgm_start_track`
- `bgm_crossfade_frames` default `59`
- `outro_bgm_track`

## Carousel / Final Recap

Reuse `scripts/layout_carousel.py` only if the final marker contract matches
the new workflow.

Required marker names should be profile-configurable:

- `final_outro_recap_marker_names`
- `member_carousel_marker_names`

For this challenge style:

- final outro recap marker is separate from member carousel start;
- member carousel starts at the approved final marker;
- member carousel section can reuse the existing visual layout logic when the
  marker contract is compatible.

## Validation

Add validators for the new workflow:

1. `parts_manifest` has valid source media, FCPXML, dialogue audio, and part
   ordering.
2. `structure_decisions` contains only approved, known item kinds.
3. `gap_plan` contains only known gap kinds and marker kinds.
4. Every planned A1 gap is exactly `gap_frames`, default 60.
5. Every normal planned gap has continuous V1 coverage for at least the A1 gap duration.
6. V1 hold exceptions carry `exception_reason`.
7. A2 has no gaps from frame 0 through the configured handoff/end.
8. Markers only exist for approved marker reasons.
9. Marker in-gap placement is within tolerance:
   - default `final_gap_start_frame + 34`;
   - default tolerance: +/-12 frames.
10. Intro does not overlap A1 dialogue.
11. Final A1 dialogue audit passes.
12. Focused missing-media check passes.
13. Final timeline has expected tracks:
   - V1 gameplay/intro/outro;
   - continuous V1 visual holds, not V2 stills/overlays;
   - A1 dialogue;
   - A2 BGM;
   - A3 outro/music tail.

## Config / CLI Wiring

Update `config/orchestrator_workflows.json`:

- add workflow `generic_minimum_battles_review_first`;
- use `profile_pipeline_stage` and `profile_pipeline_stage_strict`;
- add profile `roxanne_rse_minimum_battles_19`;
- add paths for:
  - `input_preflight_report`
  - `parts_manifest`
  - `source_map`
  - `structure_decisions`
  - `gap_plan`
  - `gap_marker_report`
  - `final_fcpxml`
  - `final_manifest`
  - `rse_assets_report`
  - `bgm_report`
  - `clip_color_report`
  - `fairlight_report`
  - `audio_normalization_instructions`

Run:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py validate
.venv\Scripts\python.exe scripts\orchestrator_run.py plan --profile roxanne_rse_minimum_battles_19
```

## Suggested Implementation Order

1. Add config-only workflow/profile skeleton and validate it.
2. Add `scripts/run_minimum_battles_pipeline.py` with first-class stage names,
   cache/status behavior, and stop reports.
3. Add semantic validators for `parts_manifest`, `structure_decisions`, and
   `gap_plan`.
4. Add multi-part auto-editor stage and parts manifest.
5. Add stitched review-base builder and source map.
6. Reuse/adapt cut review stages until approved source cuts compile.
7. Add structure decision compiler and `gap_plan.json`.
8. Add final-base FCPXML builder for A1 gaps, continuous V1 holds, markers, intro/outro.
9. Add A1 dialogue audit support for the final-base FCPXML.
10. Add RSE asset preflight and Resolve final assembly.
11. Add continuous BGM placement.
12. Add carousel/final recap handling.
13. Add final timeline validators and QA reports.
14. Only then run the new profile end-to-end on Roxanne 19.

## Implementation Status

Started implementation in the first slice:

- Added the `roxanne_rse_minimum_battles_19` seed profile.
- Added the `generic_minimum_battles_review_first` workflow.
- Added `scripts/run_minimum_battles_pipeline.py` with the stage graph,
  cache/status handling, input preflight, stop reports, and explicit
  not-yet-implemented stops for later builders.
- Added `scripts/orchestrator_auto_editor_multi.py` for profile-driven
  multi-part auto-editor runs and `parts_manifest.json` generation.
- Added artifact validators for input preflight, auto-editor part manifests,
  structure decisions, gap plans, and A1 dialogue audit reports.
- Verified JSON/catalog/script smoke checks:
  - `python -m json.tool config/orchestrator_workflows.json`
  - `python -m py_compile scripts/run_minimum_battles_pipeline.py scripts/orchestrator_auto_editor_multi.py src/resolve_mcp/orchestrator/artifact_validators.py`
  - `scripts/orchestrator_run.py validate --json`
  - `scripts/orchestrator_run.py plan --profile roxanne_rse_minimum_battles_19 --json`
