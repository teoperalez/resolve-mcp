---
name: gen1-marker-pipeline
description: For Gen 1 Pokémon challenge videos (RBY Red/Blue/Yellow) recorded with OBS chapter markers + RBYNewLayout overlay. Two-phase pipeline. Phase 1 (pre-Resolve): runs auto-editor on each source MP4, renames the audio track files, then injects fresh OBS chapter markers into the _ALTERED.fcpxml — remapping their timestamps through auto-editor's silence cuts. Phase 2 (in-Resolve, after FCPXML import): replays the RBYNewLayout session log (%APPDATA%\rbypc-frontend\logs\<session>\events.json) through the MARKER_RULES debounce filter to convert raw "Chapter NN" names into labelled, color-coded markers ("Brock Battle Start" in Sand, "Misty Battle Finish" in Sky, etc.). Use when the user says "run the gen 1 marker pipeline", "set up markers for the Gen 1 challenge", "auto-editor + markers for the RBY video", "label the chapter markers from the OBS recording", or whenever a Gen 1 challenge MP4 with baked-in chapter markers needs processing before cut analysis. Stop after phase 2 — does NOT do cut analysis, edit-timeline construction, or rendering.
---

# gen1-marker-pipeline

Two-phase pipeline for processing Gen 1 RBY challenge MP4s with baked-in OBS chapter markers and a corresponding RBYNewLayout session log.

## When to use

Trigger phrases:
- "run the gen 1 marker pipeline"
- "set up markers for the Gen 1 challenge"
- "auto-editor + markers for the RBY video"
- "label the chapter markers from the OBS recording"

When the user provides a Gen 1 challenge video folder (`<name>/<name> part N.mp4` × 1+ parts) where:
- Each MP4 has OBS-baked chapter markers (Hybrid MP4 recording with the `]` hotkey bound to chapter-marker insertion)
- A matching RBYNewLayout session log exists at `%APPDATA%\rbypc-frontend\logs\<sessionId>\events.json`

The skill produces FCPXML files with labelled timeline markers ready for import into Resolve. **It stops there** — no cut analysis, no edit-timeline construction, no rendering.

## Architecture

The skill mirrors the workflow inside `C:\Programming\FileOrganizer\organizer.py` but is self-contained (no dependency on FileOrganizer GUI being open) and uses the correct path to `C:\Programming\RBYNewLayout\scripts\session_marker_labels.py` (the FileOrganizer copy hardcodes `F:\...` which doesn't exist on this machine).

The bundled `scripts/session_marker_labels.py` is a copy of the RBYNewLayout module — so the skill works even when the RBYNewLayout repo is moved or absent. When updating MARKER_RULES upstream, copy the file into the skill again.

## Phase 1 — Pre-Resolve (FCPXML preparation)

Per MP4 in the input folder:

1. **Skip if `_ALTERED.fcpxml` already exists** (auto-editor was already run by FileOrganizer or a prior invocation). Use `--force-rerun` to re-run.
2. **Run auto-editor:** `auto-editor <video.mp4> --margin 0.1sec --edit audio:stream=0 --export resolve` (the exact args FileOrganizer uses). Output: `<stem>_ALTERED.fcpxml` + `<stem>_tracks/`.
3. **Rename audio tracks:** files in `<stem>_tracks/` are numeric (`0.wav`, `1.wav`, ...). Rename to `Stream 0.wav`, `Stream 1.wav`, ... and patch the FCPXML's `<asset>` references to match.
4. **Inject chapter markers:** read MP4 chapters via `ffprobe -v quiet -print_format json -show_chapters <video>`. For each chapter, find the kept FCPXML segment that contains the chapter's `start_time`. Remap to the new timeline position via `tl_offset + (src_t - src_start)`. Chapters that fall in a removed segment snap to the start of the next kept clip; chapters past the last clip are dropped (logged as `skipped_end`). Insert as `<marker value="<OBS name>" start="<remapped>" duration="1/<fps>s" completed="0">` children of `<sequence>`.

At end of phase 1, each FCPXML has timeline markers with raw OBS names (e.g. `Chapter 01`, `Chapter 02`). Labelling happens in phase 2.

Run phase 1 via:
```bash
python ~/.claude/skills/gen1-marker-pipeline/scripts/phase1.py <video.mp4> [<video2.mp4> ...]
# Or pass a folder to process every *.mp4 inside (skipping _ALTERED files):
python ~/.claude/skills/gen1-marker-pipeline/scripts/phase1.py <folder>
```

Output per MP4: stdout summary + the in-place FCPXML modification. Skill prints next-step instructions: "Open Resolve. Import each FCPXML (File → Import Timeline → Import AAF, EDL, XML). For each imported timeline, then run phase 2."

## Phase 2 — In-Resolve (marker labelling)

After the user imports an FCPXML into Resolve and switches to it as the current timeline:

1. **Discover source MP4** from the first V1 clip's media pool item.
2. **Read chapter markers** from the source MP4 via ffprobe (same as phase 1).
3. **Build clip table** from Resolve's `timeline.GetItemListInTrack("video", 1)`: `(tl_start, src_start, duration, item)` in frames.
4. **Load session log:** by default, picks the most-recently-modified session under `%APPDATA%\rbypc-frontend\logs\`. Use `--session <dir>` to override.
5. **Replay events through MARKER_RULES + debounce** to produce the ordered list of intended markers (label + color + note).
6. **Pair chapters with intended markers** by sorted positional index. For each chapter:
   - Map source frame → timeline frame via clip table (snap to next clip if in a removed segment)
   - If a marker already exists at that timeline frame, skip (duplicate)
   - Call `timeline.AddMarker(tl_frame, color, label, note, 1)` with the session-log fields
   - Also call `clip_item.AddMarker(clip_src_frame, color, label, note, 1)` so markers travel with the clip when copied to a production timeline
7. Print summary: `added=N clip_markers=M snapped_to_next=K no_following_clip=X duplicates=Y`.

Run phase 2 via:
```bash
python ~/.claude/skills/gen1-marker-pipeline/scripts/phase2.py [--session <dir>] [--no-label]
# --no-label: skip session-log lookup, keep raw OBS names
# --session: use a specific session log folder
```

Phase 2 must be run from a Python interpreter that can connect to Resolve's scripting API. The skill's `phase2.py` self-bootstraps `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` env vars.

## Color coding (from session_marker_labels.py)

Markers are colored by trainer type (Pokémon type chart), not by win/loss:

| Trainer | Color | Type |
|---|---|---|
| Brock | Sand | Rock |
| Misty | Sky | Water |
| Lt. Surge | Yellow | Electric |
| Erika | Green | Grass |
| Koga | Purple | Poison |
| Sabrina | Pink | Psychic |
| Blaine | Red | Fire |
| Giovanni | Cream | Ground |
| Lorelei | Cyan | Ice |
| Bruno | Cocoa | Fighting |
| Agatha | Lavender | Ghost |
| Lance | Fuchsia | Dragon |
| Champion (Rival 3) | Rose | — |
| Rival 1/2 | Mint | — |
| Intro | Cyan | — |
| Get Pokémon (pregame card) | Sky | — |
| First Pokémon received | Mint | — |
| Beat Champion | Rose | — |
| Post-Battle Tiercard | Yellow | — |
| Final Tierlist | Purple | — |
| Member Carousel | Sand | — |

The `battle-start` and `battle-end` events for the same trainer use the same color (e.g. both Brock markers = Sand).

## Inputs / outputs

### Phase 1 inputs
- Source MP4(s) with baked-in OBS chapter markers
- Auto-editor on PATH (`pip install auto-editor`)
- ffprobe on PATH (`winget install Gyan.FFmpeg`)

### Phase 1 outputs
- `<stem>_ALTERED.fcpxml` (in-place edit; injected markers with raw OBS names)
- `<stem>_tracks/` (renamed audio splits: `Stream 0.wav`, etc.)

### Phase 2 inputs
- Resolve running with the FCPXML-imported timeline as current
- `%APPDATA%\rbypc-frontend\logs\<sessionId>\events.json` (latest by default)

### Phase 2 outputs
- Timeline markers (labelled, color-coded) on the current Resolve timeline
- Matching clip markers on each V1 clip (for travel when copy-pasting clips to a production timeline)

## Edge cases handled

| Case | Handling |
|---|---|
| Chapter count ≠ session-log marker count | Pair by sorted positional index; extras on either side either get OBS names or are silently truncated. Warning printed. |
| Chapter falls in removed (silent) segment | Snap to start of next kept clip; log `(snapped)`. |
| Chapter past last kept clip | Skip; log `no_following_clip`; do NOT advance the intended-marker index (preserves pairing for subsequent chapters). |
| Existing marker at the same timeline frame | Skip as duplicate; log `skipped_dup`. |
| `events.json` missing or empty | Phase 2 falls back to raw OBS chapter names with `Blue` color, prints warning. |
| Source MP4 unreachable from media pool | Phase 2 errors with "Could not determine source file from timeline clips. Make sure the FCPXML source media is still at its original location." |
| Multiple session logs under `%APPDATA%\rbypc-frontend\logs\` | Latest by mtime is picked. Override with `--session <dir>`. Use `--list-sessions` to enumerate. |

## What this skill does NOT do

- **Cut analysis** — chapter markers ≠ false-start cuts. Run the cut-analysis pipeline (or `final-render-cut-qa` after rendering) separately.
- **Edit timeline construction** — no intro/outro, no V2 battle intros, no carousel layout. That belongs to the orchestrator workflow; for Gen 1, the equivalent marker pipeline lives in `RBYNewLayout` (separate project).
- **Audio mix** — no Fairlight, no A2 BGM, no fades. The chapter markers are reference points for downstream editing; they don't drive audio decisions.
- **Rendering** — exit when phase 2 finishes; user renders manually or via `render_timeline.py` separately.

## References

- `references/marker-rules.md` — full MARKER_RULES + debounce + label/color algorithm extracted from `session_marker_labels.py`
- `references/troubleshooting.md` — common failures + how to diagnose
- `references/file-organizer-parity.md` — diff between this skill and the original FileOrganizer GUI workflow

## Files

- `scripts/phase1.py` — auto-editor + track rename + chapter injection
- `scripts/phase2.py` — Resolve-side marker labelling
- `scripts/session_marker_labels.py` — copy of RBYNewLayout module (vendored for self-containment)
- `references/marker-rules.md`
- `references/troubleshooting.md`
- `references/file-organizer-parity.md`
