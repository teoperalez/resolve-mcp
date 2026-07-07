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
