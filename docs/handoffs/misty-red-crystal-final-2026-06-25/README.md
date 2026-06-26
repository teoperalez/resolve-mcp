# Misty Red Crystal Final Timeline Handoff

Date: 2026-06-25

## Canonical Final Timeline

The final timeline is exactly:

`Misty decision rebuild from saved cut decisions (edit)`

It is in Resolve project:

`New Project 3`

Do not confuse it with these older or intermediate timelines:

- `Misty Red and Blue Crystal Gym Leader Challenge (cuts: all) (edit)` - older May render/timeline.
- `Misty decision rebuild from saved cut decisions` - base imported decision rebuild before intro/outro/music/carousel/final edit steps.

Current final timeline state:

- Start frame: `216000`
- End frame: `325191`
- Duration: `109191` frames at `60 fps`
- Resolution: `3840x2160`
- Markers: `17`
- V1 clips: `544`
- V2 clips: `45`
- A1 clips: `580`, track name `Dialogue 1`
- A2 clips: `29`, track name `Music 1`, locked
- A3 clips: `1`, track name `Music 2`

Final render:

`E:\Misty Red\Misty decision rebuild from saved cut decisions (edit)_FINAL_4K.mp4`

Verified after render:

- Video: H.264, `3840x2160`, `60 fps`
- Audio: AAC
- Duration: `1819.861333` seconds
- Size: `2531091876` bytes
- Resolve render job status: `Complete`, `100%`

## Durable Timeline Exports

Use these first if the next agent only needs to restore or inspect the final state.

Repo copies:

- `docs/handoffs/misty-red-crystal-final-2026-06-25/New Project 3 - Misty decision rebuild final - 2026-06-25.drp`
- `docs/handoffs/misty-red-crystal-final-2026-06-25/Misty decision rebuild from saved cut decisions (edit) - FINAL - 2026-06-25.drt`
- `docs/handoffs/misty-red-crystal-final-2026-06-25/misty_final_timeline_2026-06-25_fcpxml_1_10_Info.fcpxml`
- `docs/handoffs/misty-red-crystal-final-2026-06-25/misty_final_timeline_2026-06-25_fcpxml_1_9.fcpxml`
- `docs/handoffs/misty-red-crystal-final-2026-06-25/misty_final_timeline_2026-06-25_fcp7.xml`
- `docs/handoffs/misty-red-crystal-final-2026-06-25/final_timeline_summary.json`

Project-folder copies:

- `E:\Misty Red\CODEx\final-timeline-handoff\New Project 3 - Misty decision rebuild final - 2026-06-25.drp`
- `E:\Misty Red\CODEx\final-timeline-handoff\Misty decision rebuild from saved cut decisions (edit) - FINAL - 2026-06-25.drt`
- `E:\Misty Red\CODEx\final-timeline-handoff\misty_final_timeline_2026-06-25_fcpxml_1_10_Info.fcpxml`
- `E:\Misty Red\CODEx\final-timeline-handoff\misty_final_timeline_2026-06-25_fcpxml_1_9.fcpxml`
- `E:\Misty Red\CODEx\final-timeline-handoff\misty_final_timeline_2026-06-25_fcp7.xml`
- `E:\Misty Red\CODEx\final-timeline-handoff\final_timeline_summary.json`

Resolve's FCPXML 1.10 exporter created a package directory containing `Info.fcpxml`; the extracted plain file is `misty_final_timeline_2026-06-25_fcpxml_1_10_Info.fcpxml`. The FCPXML 1.9 export also produced a normal plain file.

## Rebuild Artifacts

The repo handoff folder includes `rebuild-artifacts/` with the sidecars needed to rebuild or audit the decision-rebuild path:

- User saved decisions from Downloads:
  - `Misty Red and Blue Crystal Gym Leader Challenge_cut_review_decisions.json`
- Decision normalization and approved cuts:
  - `misty_review_decisions_normalized.json`
  - `misty_decision_approved_cuts_for_fcpxml.json`
- Base decision-rebuild timeline inputs:
  - `misty_decision_rebuild.fcpxml`
  - `misty_decision_rebuild_markers.json`
- QA/report files:
  - `resolve_import_report.json`
  - `resolve_import_validation.json`
  - `outro_audio_a3_report.json`
  - `final_edit_qa_report.json`
  - `battle-intros-placements.json`
- Detection context:
  - `misty_dialogue_audio_detection.json`
  - `misty_section_safe_cuts.json`

The live project copies remain under:

`E:\Misty Red\CODEx\cut_review\decision_rebuild\`

## Procedural Rebuild Notes

Fastest restore path:

1. Import `New Project 3 - Misty decision rebuild final - 2026-06-25.drp`, or import the DRT into an existing Resolve project.
2. Confirm the active/current timeline is `Misty decision rebuild from saved cut decisions (edit)`.
3. Confirm `final_timeline_summary.json` track counts and markers match.

Procedural rebuild path:

1. Ensure `C:\Programming\resolve-mcp\transcripts` points at `E:\Misty Red\transcripts`.
2. Import `misty_decision_rebuild.fcpxml` into Resolve. This is the base timeline named `Misty decision rebuild from saved cut decisions`.
3. Run intro/outro insertion:

```powershell
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal --source-timeline "Misty decision rebuild from saved cut decisions"
```

This creates `Misty decision rebuild from saved cut decisions (edit)`. It auto-detects `transcripts/min-battles.json` as not minimum battles and uses the 400 percent retimed intro.

4. Run the downstream edit steps on `Misty decision rebuild from saved cut decisions (edit)`:

```powershell
.venv\Scripts\python.exe scripts\place_battle_intros.py --overlap-sec 5
.venv\Scripts\python.exe scripts\layout_carousel.py
.venv\Scripts\python.exe scripts\place_bgm.py --game pokemon_crystal
.venv\Scripts\python.exe scripts\place_battle_audio.py --rival-track "Take them down!.mp3" --gym-track "Big Baddies.mp3" --other-track "A new Challenger.mp3"
.venv\Scripts\python.exe scripts\place_battle_bgm.py --seed 1
.venv\Scripts\python.exe scripts\apply_audio_fades.py
.venv\Scripts\python.exe scripts\apply_fairlight_preset.py --timeline "Misty decision rebuild from saved cut decisions (edit)"
```

5. Apply the A3 outro-audio fix if it is not already present. The recorded final state has one A3 clip:

- Outro video starts at frame `323988`
- Outro video name: `GSC outro.mp4`
- A3 audio clip: `GSC outro w audio.mov`
- Report: `outro_audio_a3_report.json`

6. Save the project and export/render as needed.

## Final QA Notes

`final_edit_qa_report.json` recorded:

- Missing media: `0`
- V2 battle intro clips: `6`
- V2 carousel clips: `39`
- A2 overlap count: `0`
- A2 is locked after Fairlight preset application
- `gameplay_v1_missing_a1_count: 1` is the expected carousel visual underlay created by `layout_carousel.py`, not an ordinary gameplay dialogue-coverage failure.

`verify_pipeline.py --report-only` still reported Pink/Yellow/Lime editorial flags. Those correspond to reviewed cut decisions and known battle pre-roll holds, not Brown/Teal structural music failures.

## Battle Intro Placements

The final V2 battle intros are:

- Rival 1: `silver-cherrygrove-grass-battle-intro.mov`
- Falkner: `falkner-battle-intro.mov`
- Bugsy: `bugsy-battle-intro.mov`
- Rival 2: `silver-azalea-grass-battle-intro.mov`
- Whitney: `whitney-battle-intro.mov`
- Rival 3: `silver-burnedtower-grass-battle-intro.mov`

The placement audit is in `battle-intros-placements.json`.
