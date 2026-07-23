# AGENTS.md - resolve-mcp

This MCP server lets Codex control DaVinci Resolve Studio through Resolve's
Python scripting API. For full edit generation, the Python orchestrator GUI is
the canonical interface.

---

## Environment

- **Platform:** Windows
- **Server:** `C:\Programming\resolve-mcp`
- **Python:** use `.venv\Scripts\python.exe`
- **Resolve scripting:** Preferences -> General -> External scripting using -> Local
- **Transcription backend:** `faster-whisper` with CUDA preferred and CPU fallback

---

## First Steps On Every Resolve Session

Before using Resolve tools, orient yourself:

1. `get_project_info`
2. `get_current_timeline_info`
3. `get_current_page`

If Resolve is not connected, tell the user to open Resolve and confirm external
scripting is set to Local.

---

## Orchestrator-Only Edit Workflow

When the user asks for the GUI, orchestrator, workflow GUI, or a full edit
generation run, use:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_gui.py
```

Command-line inspection and recovery go through:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py profiles
.venv\Scripts\python.exe scripts\orchestrator_run.py status --profile <profile_id>
.venv\Scripts\python.exe scripts\orchestrator_run.py run --profile <profile_id> --full
```

Do not reconstruct a full edit by chaining individual legacy scripts. The
orchestrator catalog defines the allowed steps, order, inputs, outputs, LLM
dispatches, review gates, and Resolve-required stages.

Full runs skip completed output-producing steps. Stage scripts also write
per-step cache/checkpoint JSON under the project's CODEx folder, so interrupted
runs can be resumed from the GUI status or from a selected step.

The normal workflow should run autonomously except for the cut-decision review
surface. If a required asset or data source is missing, including session
markers, hold-region data, source media, audio, or review decisions, stop and
ask the user how to proceed. Present concrete choices:

1. provide or regenerate the missing data;
2. update the project profile path/setting in the orchestrator GUI;
3. explicitly approve a named fallback.

Do not invent marker data, infer battle markers from transcripts when canonical
session logs are expected, or silently fall back to prompt-file/manual workflows
outside the orchestrator.

### Marker-Derived Gameplay Gap

For RBY UMB intro/gameplay marker gaps, do not create a black V1 hole or an
A1-only offset. When the project markers `Intro Hold Gap Start` / `Intro Gap
Start` and `Gameplay Start` require a one-second insert, open that silent gap on
A1 and shift timeline markers at or after the insert point by the same extra
amount so downstream Gen 1 intro placement reads the corrected positions. V1
must match the manual repair pattern: the intro-card hold remains continuous
through the inserted A1 silence and ends at the shifted `Intro Hold Gap Start`
marker, then the first post-gap V1 gameplay/dialogue clip is extended left by
the same insert amount so it begins with the shifted A1 clip. This preserves the
gameplay spine without leaving black picture under the playhead.

### Visual Hold Semantics

In this repository's edit workflows, a visual hold means an extended, unbroken
V1 video clip over the full hold range. It does not mean a still-image asset, a
freeze-frame PNG, a rendered hold video, or a higher-track overlay. A1 may
continue as cut dialogue underneath, but V1 must be continuous on track 1 until
the hold range ends.

### Final A1 Dialogue Audit

Before the final Resolve assembly proceeds, run the orchestrator's
`a1-dialogue-audit` step. It reruns faster-whisper on the dialogue audio and
fails if any final-base FCPXML A1 clip has no overlapping recognized dialogue.
Treat findings such as coughs, throat clears, and short non-word noises as
review/cut candidates instead of allowing them into the finished timeline.

### Fairlight Preset Before Handoff

Before passing any finished Resolve timeline back to the user for review or
render, apply the repo Fairlight preset to that exact timeline and save the
project:

```powershell
.venv\Scripts\python.exe scripts\apply_fairlight_preset.py --timeline "<timeline name>"
```

The default preset is `Standard Gameplay youtube` with type `CONSOLE_FLEXI`.
Do not describe a timeline as ready until the apply script reports
`Result: True` and `pm.SaveProject(): True`.

### Continuous BGM Bed Placement

A2 BGM must be a continuous music bed made from clips at their real source
durations. When placing BGM through Resolve `AppendToTimeline`, remember that
`recordFrame` is in timeline frames, but audio `startFrame` / `endFrame` are in
the media item's source-frame units. Do not pass 60fps timeline durations as
`endFrame` for 30fps-tagged WAV files; that doubles the Resolve timeline span
and leaves long silent tails. Verification must compare the actual A2 clip
starts, durations, and source left offsets against the generated BGM placement
plan, not merely check that A2 has no timeline gaps.

### Computer Use Audio Normalization

When the orchestrator reaches the `audio-normalization-handoff` step, the
Resolve Normalize Audio command must be run through Computer Use exactly this
way:

1. Unlock A2 if it is locked.
2. Drag-select all audio clips only, across the populated audio lanes. Do not
   select video clips and do not use Ctrl+A.
3. Verify the audio multi-clip selection is still active.
4. Right-click the center/body of the longest visible selected A2 clip, away
   from fade handles and clip edges.
5. Choose `Normalize Audio Levels...` from that selected audio clip context
   menu.
6. Use `Sample Peak Program`, the configured target level, and Independent clip
   reference when Resolve shows that option.
7. Click `Normalize`, then save the Resolve project.

If the right-click collapses the multi-selection, close the menu and redo the
audio-only drag selection before choosing Normalize. If any video clip is
selected, normalization is invalid; clear the selection and start over.

---

## Screenshots

Use `screenshot` liberally for visual Resolve tasks:

- before visual edits;
- after changes;
- when the user describes something visual;
- before page-specific operations if the visible state matters.

Screenshots may expose client footage, so warn the user when sensitive footage
is visible.

---

## Indexing And Track Conventions

Resolve API indices are 1-based:

| Parameter | Starts at |
|---|---|
| `track_index` | 1 |
| `clip_index` | 1 |
| `node_index` | 1 |
| Frame numbers | timeline start frame |

Track type strings are case-sensitive:

- `"video"`
- `"audio"`
- `"subtitle"`

---

## Page Awareness

Use `open_page` when a task needs a specific Resolve page:

| Task | Page |
|---|---|
| Timeline editing, markers | `"edit"` or `"cut"` |
| Color grading, node graph, LUT, CDL | `"color"` |
| Fusion compositions | `"fusion"` |
| Rendering | `"deliver"` |
| Media import | `"media"` |

---

## Escape Hatch

Use `execute_resolve_code` only when no specific tool or orchestrator step
covers the task. It exposes:

```python
resolve
project
mediaPool
timeline
mediaStorage
```

Describe the intended operation before running arbitrary Resolve Python,
especially for edits, deletes, batch operations, or render changes.

---

## Rendering

For orchestrator deliverables, use the configured render step. For ad-hoc
renders outside the orchestrator, confirm the output path before queueing
anything, because render files can be large and may overwrite existing files.

QA renders should happen before final 4K renders unless the user explicitly
approves skipping QA.

---

## Safety

Before destructive operations, warn the user. Never delete media pool items,
clear the render queue, export/upload files, or run Resolve `.Delete()` calls
unless the user explicitly asked for that exact operation.

Preserve user/manual timeline state. Markers, clip-level markers, colors, and
manual review decisions are meaningful workflow data, not disposable decoration.
