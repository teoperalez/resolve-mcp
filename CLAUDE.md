# CLAUDE.md — resolve-mcp

This MCP server lets Claude control DaVinci Resolve Studio directly via its Python scripting API. Read this before using the tools.

---

## Environment

- **Platform:** Windows (patched fork — screenshot and transcription fully work on Windows)
- **Server:** `C:\Programming\resolve-mcp`
- **Resolve paths (auto-detected):**
  - `fusionscript.dll` → `C:\Program Files\Blackmagic Design\DaVinci Resolve\`
  - Scripting Modules → `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\`
- **Transcription backend:** `faster-whisper` (CUDA GPU preferred, CPU fallback)

---

## First steps on every session

Always orient yourself before acting:

1. `get_project_info` — confirms what project is open and how many timelines exist
2. `get_current_timeline_info` — confirms which timeline is active, its frame rate, and resolution
3. `get_current_page` — confirms which Resolve page is active

If Resolve isn't connected, you'll get a clear error. Tell the user to check that Resolve is open and that **Preferences → General → External scripting using → Local** is set.

---

## Screenshot — use it liberally

`screenshot` captures the Resolve window (or full screen as fallback) and returns it as an image.

**Use it:**
- Before starting any visual task (color grading, Fusion, layout changes)
- After making changes to verify the result looks correct
- Whenever the user describes something visual that you can't confirm through data alone
- To confirm you're on the right page before page-specific operations

**Do not skip this.** Many Resolve operations have no readable confirmation; a screenshot is often the only way to verify success.

Screenshots are sent to Anthropic for analysis — remind the user if there's sensitive client footage visible.

---

## Indexing conventions

These are 1-based throughout the API:

| Parameter | Starts at |
|---|---|
| `track_index` | 1 |
| `clip_index` | 1 |
| `node_index` | 1 |
| Frame numbers | Timeline start frame (usually 0 or 86400 depending on timecode) |

When a user says "the second clip on track 1" that is `track_index=1, clip_index=2`.

---

## Track types

The `track_type` parameter accepts exactly these strings (case-sensitive):
- `"video"` — video tracks
- `"audio"` — audio tracks
- `"subtitle"` — subtitle tracks

---

## Page awareness

Some tools only work or make sense on a specific page. Use `open_page` first when needed:

| Task | Page required |
|---|---|
| Color grading, node graph, LUT, CDL | `"color"` |
| Thumbnail (`get_current_thumbnail`) | `"color"` |
| Fusion compositions | `"fusion"` |
| Rendering | `"deliver"` |
| Timeline editing, markers | `"edit"` or `"cut"` |
| Media import | `"media"` |

When in doubt, call `get_current_page` before a page-specific tool, and `open_page` if you need to switch.

---

## The escape hatch: `execute_resolve_code`

When no specific tool covers what you need, use `execute_resolve_code`. The following objects are pre-loaded in the execution namespace:

```python
resolve       # DaVinci Resolve application object
project       # Current project
mediaPool     # Media pool
timeline      # Current timeline
mediaStorage  # Media storage
```

**Good uses:**
- Reading a setting not exposed by a tool: `project.GetSetting("timelineFrameRate")`
- Batch operations on many clips at once
- Inspecting what methods are available: `print(dir(timeline))`
- Anything the Resolve scripting API supports but no tool wraps

**Caution:** This runs arbitrary Python. Always describe to the user what the code does before executing. Avoid writing code that deletes timelines, media pool items, or project files unless the user explicitly asked.

---

## Transcription workflow

1. Ask for the audio/video file path if the user hasn't provided one
2. Call `transcribe_audio` with the file path and optional model/language
3. The result includes `language`, `text` (full), and `segments` (timestamped)
4. If the user wants an SRT: `export_srt` with an output path
5. If the user wants markers in Resolve: `transcribe_and_add_subtitles`

**Model selection guide:**

| Use case | Model |
|---|---|
| Quick draft, long files | `tiny` or `base` |
| General use | `turbo` (default — large-v3-turbo) |
| Non-English, accented speech | `large` |
| Best accuracy regardless of speed | `large` |

The server logs whether it's using CUDA or CPU. If the user has a GPU and it's falling back to CPU, they may need to install CUDA drivers.

---

## Color grading workflow

1. Navigate to the clip: `get_node_graph(track_type, track_index, clip_index)`
2. Inspect the node structure (node indices, labels)
3. Apply changes: `set_lut`, `set_cdl`
4. Take a screenshot to verify the result
5. If you need more control: `execute_resolve_code` with the full Color API

CDL values follow this structure:
```python
{
    "slope": [r, g, b],    # Gain/contrast — 1.0 is neutral
    "offset": [r, g, b],   # Lift/brightness — 0.0 is neutral
    "power": [r, g, b],    # Gamma — 1.0 is neutral
    "saturation": 1.0      # 1.0 is neutral, 0 = desaturated
}
```

---

## Rendering workflow

1. `get_render_formats` — see what's available
2. `set_render_settings` — configure format, codec, resolution, output path
3. `add_render_job` — queue the job
4. `start_rendering` — begin
5. `get_render_status` — poll progress (call periodically)
6. `stop_rendering` — abort if needed

Always confirm the output path with the user before queuing a render. Render files can be large and will overwrite without warning.

---

## Safety rules

**Before destructive operations, warn the user:**
- Deleting timelines or clips via `execute_resolve_code`
- Overwriting render output to a path that already has files
- Modifying many clips in a batch without preview

**Never do without explicit user instruction:**
- Delete media pool items
- Clear the render queue
- Export or upload files
- Run `execute_resolve_code` that calls `.Delete()` on any object

**Backups:** If the user is about to do something irreversible, remind them to save the project first: **File → Save Project** or right-click in Project Manager → **Export Project**.

---

## Common errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `Could not connect to DaVinci Resolve` | Resolve not running or scripting not enabled | Open Resolve; set Preferences → General → External scripting → Local |
| `No active timeline` | No timeline loaded | Open a project and select a timeline in the Edit page |
| `Index out of range` | Clip/track index doesn't exist | Call `get_timeline_items` first to see what exists |
| `Failed to import DaVinciResolveScript` | Wrong fusionscript.dll path | Set `RESOLVE_SCRIPT_LIB` env var manually |
| `ffprobe/ffmpeg not found` | ffmpeg not installed or not on PATH | `winget install Gyan.FFmpeg`, then restart the terminal |

---

## Tips for effective collaboration

- **Ask before you act on ambiguity.** "Clip 1" could mean first in the pool or first on the timeline — clarify.
- **State what you're about to do** before calling tools that modify Resolve state.
- **Chain reads before writes.** Call `get_timeline_items` or `get_timeline_item_properties` to confirm the target before setting anything.
- **Use markers as breadcrumbs.** When working through a long timeline, add markers so the user can see where you've made changes.
- **Transcription on long files is chunked automatically.** Files over 5 minutes are split into 5-minute WAV chunks, transcribed in sequence, then stitched. This is transparent — just expect it to take longer.
- **For anything complex, prefer a screenshot loop:** take screenshot → describe what you see → make one change → take another screenshot → confirm.
