# Next Editing Machine Handoff

Generated: 2026-06-04

Use this note when moving the external SSD to the next editing machine. The
repository branch and the external SSD handoff folder together are the source of
truth for picking up the current editing work.

## Git State

- Repository: `https://github.com/teoperalez/resolve-mcp.git`
- Branch: `codex/gym-leader-intro-bgm`
- Pull this branch before continuing Resolve work.

## External SSD

The external SSD is mounted as `E:` on the current machine. All project assets
and DRT handoff files were consolidated there.

Top-level handoff folder:

```text
E:\CODEx_Final_Timeline_Handoffs
```

Important files:

```text
E:\CODEx_Final_Timeline_Handoffs\README.md
E:\CODEx_Final_Timeline_Handoffs\FINAL_TIMELINE_HANDOFF_MANIFEST.json
E:\CODEx_Final_Timeline_Handoffs\EXTERNAL_SSD_ASSET_VERIFICATION.json
E:\CODEx_Final_Timeline_Handoffs\_Recovered_C_Drive_DRTs
```

Project asset roots on the SSD:

```text
E:\Brock Red
E:\Misty Red
E:\Victreebel Red and Blue Ultra Minimum Battles
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo
```

The Victreebel and Mewtwo RBYNewLayout session logs were also copied to the SSD
and the rebuild scripts prefer these external copies when present:

```text
E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\session-log
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\session-log
```

Each project also has a project-local handoff directory:

```text
<project root>\CODEx\final-timeline-handoff
```

## DRT Status

- Brock Red: final DRT exported from Resolve project `Brock Minimum Battles 2 audio update`, timeline `Timeline 4`.
- Misty Red: final/current edit DRT present.
- Victreebel RBY UMB: final/latest DRT checkpoints present, including the latest intro/BGM checkpoint copies recovered from `C:`.
- Mewtwo RBY UMB Redo: DRT checkpoints present, but they are clearly labeled `NOT FINAL` because the edit is still at review/checkpoint stage.

## Mewtwo Current Stage

The current Mewtwo state is intentionally stopped at cut review:

- Fresh Resolve timeline: `Mewtwo RBY UMB redo review base`
- V1/A1-only review base is built.
- Cut candidates are generated.
- Game-audio bridge WAV is extracted.
- Final rebuild, BGM, carousel, and delivery are blocked until review approvals exist.

Mewtwo artifacts on the SSD:

```text
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\cut_review\cut_candidates_mewtwo.json
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\cut_review\review\index.html
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\cut_review\narrative\mewtwo_narrative_cut_review.in.md
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\Mewtwo Red and Blue Ultra Minimum Battles Redo_tracks\Mewtwo Red and Blue Ultra Minimum Battles Redo_3.wav
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\mewtwo_pipeline_order_report.json
```

Review/candidate counts:

- 2 locked manual restart cuts
- 5 waveform auto candidates
- 71 waveform review candidates
- 1241 V1 clips indexed

## Mewtwo Resume Commands

Run from `C:\Programming\resolve-mcp` after opening Resolve and setting external
scripting to Local. The Mewtwo and Victreebel rebuild scripts now prefer the
`E:` project roots when they are mounted, with the current machine's `C:` paths
left as fallbacks.

If the review decisions have not been saved yet, review:

```text
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\cut_review\review\index.html
```

Then copy/save decisions to:

```text
E:\Mewtwo Red and Blue Ultra Minimum Battles Redo\CODEx\cut_review\review\pink_decisions.json
```

Continue in order:

```powershell
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage apply-html-decisions
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage compile-approved-cuts
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage final-base
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage gen1-intros
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage bgm-dry-run
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage bgm
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\find_member_carousel.py --max-candidates 30
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage carousel-dry-run
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage carousel
C:\Programming\resolve-mcp\.venv\Scripts\python.exe scripts\run_mewtwo_rby_umb_pipeline.py --stage validate-order --strict
```

The pipeline is designed to fail loudly if a required review or downstream
artifact is missing.
