# Troubleshooting

## Phase 1 failures

### `ERROR: auto-editor not on PATH`
Install: `pip install auto-editor` in the active Python env, OR via the FileOrganizer GUI's bundled launcher. Verify with `where auto-editor`.

### `ERROR: ffprobe not on PATH`
Install ffmpeg: `winget install Gyan.FFmpeg` then restart terminal. ffprobe ships with ffmpeg.

### `auto-editor failed for <video> (exit N)`
Inspect the stderr excerpt the skill prints (first 500 chars). Common causes:
- Video file is corrupt or partially downloaded — check size + try playing it
- `--edit audio:stream=0` fails when the MP4 has no audio stream 0; rare for OBS recordings
- Disk full — `--export resolve` writes to the same folder as the source

### `auto-editor finished but _ALTERED.fcpxml not found`
auto-editor sometimes writes to a different name. List the source folder for `*.fcpxml` and verify the actual output name. If FileOrganizer recently was used, it may have moved/renamed the file.

### `No chapters in <video>; nothing to inject`
The MP4 has no embedded chapter markers. Possible causes:
- OBS wasn't configured with the Hybrid MP4 format (chapter markers only work on that format, not standard MP4)
- The `]` hotkey wasn't bound in OBS, so no chapter markers were created during recording
- The recording predates RBYNewLayout's marker integration
- The video was re-encoded (e.g. through Handbrake) which strips chapter metadata

Action: phase 1 will still produce the FCPXML; phase 2 will fall back to no markers. To verify chapters manually: `ffprobe -v quiet -print_format json -show_chapters <video>`.

#### Fallback path — session log without chapters (KNOWN GAP)

If the session log exists but the MP4 has no OBS chapters, the markers CAN still be derived — the session log's `events.json` records every battle with full SMPTE timecodes (`tc` field at 60fps), independent of OBS chapter integration. The current skill doesn't take this path; phase 2 assumes OBS chapters as the anchor.

**Manual workaround until the skill supports this:**
1. Inspect the session log: `python -c "import json; evs=json.load(open(r'<session-dir>\events.json')); [print(e['tc'], e['data'].get('leader')) for e in evs if e.get('category')=='battle' and e.get('name')=='battle-start']"`
2. Note that session timecodes are relative to SESSION START, not video recording start. If the user opened the RBY app N minutes before pressing Record on OBS, every timecode is offset by N. To map session-tc → video-tc, find a known anchor (e.g. the first observable battle in the video) and compute `offset = video_tc - session_tc`.
3. Subtract the offset from each session event's tc to get the video timestamp. Use those to place markers manually in Resolve UI.

**Proposed fix (future skill enhancement):**
- Phase 2 should accept `--from-session-log` mode that bypasses MP4 chapter reading entirely
- User provides the session-to-video time offset (`--session-offset HH:MM:SS`)
- Skill walks the session events, applies the offset, maps each event to a timeline frame via the V1 clip table, and labels via the existing MARKER_RULES + color algorithm

The Victreebel Red and Blue Ultra Minimum Battles (2026-05-16) recording is the canonical example: 15 battles in the session log (RIVAL × 2, BROCK, MISTY, ERIKA, LT.SURGE, GIOVANNI_GYM, KOGA, BRUNO, LORELEI, SABRINA, BLAINE, LANCE, AGATHA, RIVAL3), zero OBS chapters in either MP4 part. Until the fallback is implemented, markers must be placed manually.

### `No asset-clips in _ALTERED.fcpxml`
auto-editor produced an empty FCPXML — possibly the entire source was treated as silence. Re-run with `--margin 0.5sec` (looser margin) via the auto-editor CLI directly.

### `<marker> elements duplicated after re-running phase 1`
Phase 1 clears pre-existing markers from `<sequence>` before injecting (the "reset" semantic). If you see duplicates, the FCPXML may have markers in a different element location (e.g. inside `<asset-clip>` rather than `<sequence>`). Inspect the FCPXML and adjust the clearing logic in `phase1.py` if needed.

## Phase 2 failures

### `ERROR: cannot connect to Resolve. Is it running?`
- Resolve must be open with a project loaded
- `Preferences > System > General > External scripting using = Local` must be set
- Try restarting Resolve; the scripting API sometimes goes stale after heavy operations (see verify-fairlight-preset skill notes for the same pattern)

### `ERROR: cannot determine source MP4 from timeline clips`
The FCPXML imported but Resolve can't find the source media file. Either:
- The MP4 was moved/renamed after import — restore it to its original path or re-link in Resolve (right-click on offline clip in Media Pool → Relink Selected Clips)
- The first V1 clip is an intro/outro graphic, not the source video — phase 2 only checks V1; if the source is on V2 or A1-only, edit phase2.py to scan other tracks

### `No session log found; using raw OBS chapter names`
Expected when the recording wasn't paired with an RBYNewLayout session. Solutions:
- Pass `--session <abs_path>` to point at the right session folder if it's in a non-default location
- Run `python phase2.py --list-sessions` to see what's available under `%APPDATA%\rbypc-frontend\logs\`
- If no session exists at all (recording predates RBY integration), markers stay as `Chapter 01`, `Chapter 02`, etc. with Blue color — manually rename in Resolve UI

### `Chapter count (N) != intended marker count (M)`
The OBS chapter markers and the session log are misaligned. Causes:
- OBS missed a `]` hotkey press (RBY app fired the event but OBS didn't bake the chapter)
- OBS fired an extra chapter (user pressed `]` manually outside the event triggers)
- Session log includes events from a previous/next session (rare with mtime-based detection)

The skill pairs by sorted positional index, so the first N min(chapters, intended) get labelled and any extras get raw OBS names or are silently truncated. To diagnose:
- Compare chapter count from `ffprobe -show_chapters` against `intended` count from `python phase2.py --list-sessions` + manual `events.json` inspection
- If extras at the end, the labels still work for the first N
- If extras at the start, the first few labels are off-by-one — pass `--session <correct_dir>`

### Snapped markers landing wrong
"Snapped" means a chapter at source-time T fell in a silence-cut region (auto-editor removed it). The skill snaps to the start of the next kept clip. If this lands in the wrong battle, manually edit the marker in Resolve UI after import. Investigate why: was the OBS chapter fired during a long quiet moment that the auto-editor's silence detector classified as silence?

### `timeline AddMarker failed at frame X`
Resolve API returned False. Common causes:
- Frame is outside timeline bounds (very rare with chapter markers)
- Resolve scripting API is in a stuck state (see verify-fairlight-preset skill — same recurring issue; usually clears after a Resolve UI click or restart)

### `clip AddMarker failed at src=X`
The clip-level marker stamp failed. Less critical (timeline marker still placed); just means the marker won't travel if you copy-paste the clip elsewhere. Re-run after the API recovers.

## Path / config gotchas

### FileOrganizer hardcodes `F:\Programming\RBYNewLayout\scripts`
The original `resolve_map_fcpxml_markers.py` in `C:\Programming\FileOrganizer\` has this hardcoded sys.path entry. On this machine the repo is at `C:\Programming\RBYNewLayout\`, so the FileOrganizer copy silently disables labelling. This skill bundles `session_marker_labels.py` and uses its local copy, so it works regardless of where the original repo lives.

### `%APPDATA%\rbypc-frontend\logs\` location
On Windows this is `C:\Users\<user>\AppData\Roaming\rbypc-frontend\logs\`. The folder is created by the Electron app on first launch. If empty, no sessions have been recorded. If the user has multiple installations, sessions may also exist under `C:\Users\<user>\AppData\Roaming\RBY New Layout\logs\` — `session_marker_labels.default_logs_root()` returns the first form; pass `--session <abs_path>` to override.

### Resolve Python version
Resolve 21 external scripting requires Python 3.13 and a `PYTHON3HOME` that points at that Python install. If running `phase2.py` directly fails with import errors, invoke it from the repo venv after `uv sync --python 3.13.14`.

## Verifying the skill end-to-end

Manual verification on the Victreebel video (or any Gen 1 video):

1. Run phase 1: `python ~/.claude/skills/gen1-marker-pipeline/scripts/phase1.py "C:\Users\teope\Videos\Victreebel Red and Blue Ultra Minimum Battles"`
2. Confirm two FCPXML files were written (part 1 + part 2) and each has injected `<marker>` elements (grep `<marker` in the file)
3. Open Resolve, import each FCPXML, set as current timeline
4. Run phase 2: `python ~/.claude/skills/gen1-marker-pipeline/scripts/phase2.py`
5. In Resolve, scrub through and confirm markers appear at the right places with the right labels + colors
