# File Organizer parity — what this skill mirrors, what it changes

## Functions ported from FileOrganizer

| Source: `C:\Programming\FileOrganizer\organizer.py` | This skill |
|---|---|
| `run_auto_editor_on()` (line 948) | `phase1.py: run_auto_editor()` |
| `build_auto_editor_args()` | `phase1.py: build_auto_editor_args()` — same CLI flags (`--margin 0.1sec --edit audio:stream=0 --export resolve`) |
| `rename_auto_editor_tracks_and_update_fcpxml()` (line 1088) | `phase1.py: rename_tracks_and_patch_fcpxml()` — same `N.wav` → `Stream N.wav` rename + FCPXML asset-ref patch |
| `read_mp4_chapters()` (line 1120) | `phase1.py: read_mp4_chapters()` — identical ffprobe call + parsing |
| `inject_chapters_into_fcpxml()` (line 1163) | `phase1.py: inject_chapters_into_fcpxml()` — same segment-table remapping + `<marker>` insertion |
| `_parse_fcpxml_time()` / `_format_fcpxml_time()` | `phase1.py` — identical helpers |

| Source: `C:\Programming\FileOrganizer\resolve_map_fcpxml_markers.py` | This skill |
|---|---|
| `_bootstrap_resolve_api()` | `phase2.py: _bootstrap_resolve_api()` — identical |
| `get_resolve()` | `phase2.py: get_resolve()` — identical |
| `get_chapters_from_mp4()` | `phase2.py: get_chapters_from_mp4()` — identical |
| `main()` clip-mapping loop | `phase2.py: main()` — identical pair-by-index + AddMarker logic |

| Source: `C:\Programming\RBYNewLayout\scripts\session_marker_labels.py` | This skill |
|---|---|
| Entire module | `scripts/session_marker_labels.py` — vendored copy |

## Key changes from FileOrganizer

### 1. Path fix for session_marker_labels.py
FileOrganizer hardcodes `_SML_SCRIPTS_DIR = r"F:\Programming\RBYNewLayout\scripts"` which doesn't exist on this machine (the repo lives at `C:\Programming\RBYNewLayout\`). The hardcoded check `if os.path.isdir(_SML_SCRIPTS_DIR)` is False → no add to sys.path → import fails silently → labelling is permanently disabled on the FileOrganizer side.

This skill vendors `session_marker_labels.py` directly into `scripts/` and imports it from the skill dir. The import always succeeds; the skill never falls back to raw OBS chapter names unless `--no-label` is explicitly passed.

### 2. "Reset" semantic in chapter injection
FileOrganizer's `inject_chapters_into_fcpxml()` ONLY appends `<marker>` children to `<sequence>`. It doesn't clear pre-existing ones. So re-running auto-editor + injection on the same FCPXML produces duplicate markers.

This skill clears all existing `<marker>` children of the first `<sequence>` before injecting fresh ones, and logs the clear count. Re-running is now idempotent.

### 3. Phase 1 / phase 2 split into separate scripts
FileOrganizer combines auto-editor + track rename + chapter injection into the GUI's "Generate Tracks" button (with optional `ae_inject_markers_var` checkbox for the third step). Marker labelling lives in the separate `.bat`-launched script. Linear conversion is awkward when the user just wants the pipeline run.

This skill exposes two named-step scripts (`phase1.py`, `phase2.py`) that are independently invocable from the command line.

### 4. Self-contained skill, no FileOrganizer dependency
The skill's `phase1.py` doesn't import anything from FileOrganizer — it's standalone, vendoring the relevant functions. The skill works even if FileOrganizer is uninstalled / moved.

### 5. Better error messaging
- Skill prints `next-step instructions` after phase 1 completes (where to import the FCPXML, how to run phase 2).
- Skill explicitly distinguishes "session_marker_labels missing" from "no session log found" — FileOrganizer conflates them.
- Skill validates `auto-editor` and `ffprobe` on PATH before processing; FileOrganizer fails later in the subprocess call.

## What FileOrganizer has that this skill does NOT

- **GUI** — FileOrganizer is a Tkinter app with project grouping, normalization, backup, batch processing. The skill is CLI-only.
- **Project file organization** — `organize.py`'s namesake feature (normalizing project file names, grouping by camera/date) is not part of this skill. Use FileOrganizer for that.
- **resolve_assemble_final_timeline.py** — assembles a multi-clip timeline; not needed for the gen 1 marker workflow.
- **resolve_remap_markers_to_timeline.py** — promotes markers from source timeline to a production timeline. The skill stops at phase 2 (marker labels on the source FCPXML timeline). If you copy clips to a production timeline later, run FileOrganizer's `remap_markers_to_timeline.bat`.
- **promote_resolve_markers.bat** + `resolve_clip_markers_to_timeline.py` — alternative direct-OBS workflow that bypasses auto-editor (used when no silence trimming is wanted). Not implemented in this skill.

## When to use which

| Goal | Use |
|---|---|
| Trim silences via auto-editor, then label OBS markers | **This skill** |
| Same as above but with GUI controls + project file management | FileOrganizer's "Generate Tracks" tab |
| Skip auto-editor, label OBS markers directly on imported clips | FileOrganizer's `promote_resolve_markers.bat` |
| Move labelled markers from a source timeline to a production timeline | FileOrganizer's `remap_markers_to_timeline.bat` |
| Assemble individual clips into a single timeline | FileOrganizer's `assemble_final_timeline.bat` |

## Sync responsibility

When MARKER_RULES, leader labels, or color mappings change in `C:\Programming\RBYNewLayout\scripts\session_marker_labels.py` (or its `utils/sessionLog-main.js` counterpart), copy the updated `session_marker_labels.py` into this skill's `scripts/` dir. The skill won't auto-pick-up upstream changes.
