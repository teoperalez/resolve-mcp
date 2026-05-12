# resolve-mcp (Windows Edition)

Connect **DaVinci Resolve Studio** to **Claude AI** through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), enabling AI-assisted video editing, color grading, Fusion compositing, transcription, and more — all through natural language.

This is a **Windows-patched fork** of [barckley75/resolve-mcp](https://github.com/barckley75/resolve-mcp) with two Mac-only features ported to work cross-platform:

- **Screenshots** — replaced macOS Quartz/screencapture with `pywin32` + `Pillow` (targets the Resolve window by name)
- **Transcription** — replaced `mlx-whisper` (Apple Silicon only) with `faster-whisper` (CUDA GPU or CPU fallback, all platforms)

> **Not affiliated with Blackmagic Design or Anthropic.**

---

## How it works

```
Claude (MCP Client)
    ↓
resolve-mcp Server  (FastMCP, Python)
    ↓
DaVinciResolveScript  (fusionscript.dll)
    ↓
DaVinci Resolve Studio  (must be running)
```

No addon or plugin is needed inside Resolve. The MCP server talks directly to Resolve's native scripting API through `fusionscript.dll`.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| DaVinci Resolve Studio | Free version has limited scripting. 19.0+ for AI tools (Magic Mask, Smart Reframe, etc.) |
| Python 3.10+ | [python.org](https://www.python.org/downloads/) |
| uv | Package manager — see install below |
| ffmpeg | Required for transcription chunking. `winget install Gyan.FFmpeg` |
| CUDA GPU (optional) | faster-whisper uses it automatically; falls back to CPU if unavailable. RTX 2060 or better recommended. |

**Install uv (Windows):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then open a new terminal so `uv` is on your PATH.

---

## Installation

### 1. Clone this repo

```powershell
git clone https://github.com/barckley75/resolve-mcp C:\Programming\resolve-mcp
cd C:\Programming\resolve-mcp
```

### 2. Install dependencies

```powershell
uv sync --extra transcription
```

This creates `.venv\` and installs everything: `mcp`, `faster-whisper`, `pywin32`, `Pillow`, `onnxruntime`, and all transitive deps.

> **Note:** `onnxruntime` is pinned to `<1.21.0` in `pyproject.toml` because versions 1.21+ dropped Python 3.10 wheels. This is handled automatically.

### 2b. Install CUDA libraries for GPU transcription (Windows only)

Windows does not ship CUDA DLLs. CTranslate2 (the faster-whisper backend) needs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` to run on GPU — without them the model loads but crashes mid-inference with a CUDA runtime error and falls back to CPU (very slow).

```powershell
uv sync --extra transcription --extra cuda-win
```

> **This step is not needed on Linux** — CUDA is bundled in the PyPI wheels there.
>
> Without this, `medium.en` on CPU takes ~1.5–3h for a 45-minute file. With a GPU (RTX 2060+) it takes ~8–12 minutes.

### 3. Enable scripting in DaVinci Resolve

1. Open DaVinci Resolve Studio
2. **Preferences → General → External scripting using → Local**
3. Click **Save**

### 4. Register the MCP server

**For Claude Code (CLI):**
```powershell
claude mcp add resolve -- uv --directory C:\Programming\resolve-mcp run resolve-mcp
```

**For Claude Desktop** (if installed — `%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "resolve": {
      "command": "C:\\Users\\<you>\\.local\\bin\\uv.exe",
      "args": ["--directory", "C:\\Programming\\resolve-mcp", "run", "resolve-mcp"]
    }
  }
}
```
Replace `<you>` with your Windows username. Find the exact uv path with `where uv`.

### 5. Restart Claude

For Claude Code: start a new session. For Claude Desktop: quit and reopen.

### Verify it works

With Resolve open and a project loaded:

> "What project do I have open in Resolve?"

> "Take a screenshot of Resolve."

---

## Editing Scripts

Ready-to-run Python scripts for common editing operations. Each script is self-contained — no external environment setup needed. Run them with the project venv's Python.

**Python executable:** `C:\Programming\resolve-mcp\.venv\Scripts\python.exe`

> **Requirement:** DaVinci Resolve must be open with a project and timeline loaded.
> **Python version:** The venv must use Python 3.13 (matches the `fusionscript.dll` Resolve 21 ships with). If you see a segfault on import, recreate the venv: `py -3.13 -m venv .venv && .venv\Scripts\pip install -e .`

### `scripts/clear_audio_tracks.py`

Deletes all clips from audio tracks START through END. Not a ripple delete — gaps remain.

```cmd
.venv\Scripts\python.exe scripts\clear_audio_tracks.py          # clears A2–A5 (default)
.venv\Scripts\python.exe scripts\clear_audio_tracks.py 3 6      # clears A3–A6
```

### `scripts/remove_short_clips.py`

Ripple deletes clips shorter than N frames from V1 and A1 simultaneously.

```cmd
.venv\Scripts\python.exe scripts\remove_short_clips.py          # removes clips < 5 frames (default)
.venv\Scripts\python.exe scripts\remove_short_clips.py 10       # removes clips < 10 frames
```

### `scripts/battle_workflow.py` (+ `transcribe_audio.py`, `detect_battles.py`, `insert_battle_gaps.py`)

Full pipeline for Pokémon stream editing: transcribes A1 audio → Claude Code identifies first-time trainer battles → inserts 1-second (60-frame) gaps of source footage at each battle start.

```cmd
rem Full pipeline
.venv\Scripts\python.exe scripts\battle_workflow.py [--dry-run]

rem Individual steps
.venv\Scripts\python.exe scripts\transcribe_audio.py [--model medium.en]
.venv\Scripts\python.exe scripts\detect_battles.py transcripts/4.json
.venv\Scripts\python.exe scripts\insert_battle_gaps.py transcripts/battles.json [--gap-frames 60] [--dry-run]
```

**Relay mode:** `detect_battles.py` uses the same relay pattern as IRLPC Hyperframes — it writes a prompt to `plans/prompts/battle-detect-<stem>.in.md` and waits (up to 10 min) for Claude Code to write the JSON response to the corresponding `.out.md`. No Anthropic API key needed; Claude Code running in the conversation IS the LLM.

### `scripts/mark_audio_gaps.py`

Finds gaps in A1 longer than N frames and places red markers at the **end of each gap** on the timeline ruler and the corresponding V1 clip.

```cmd
.venv\Scripts\python.exe scripts\mark_audio_gaps.py             # marks gaps > 5 frames (default)
.venv\Scripts\python.exe scripts\mark_audio_gaps.py 30          # marks gaps > 30 frames
```

**Marker note:** `TimelineItem.AddMarker()` requires an **absolute source frame** (`clip.GetLeftOffset() + timeline_offset`), not a clip-relative offset. Using a plain timeline offset places the marker before the clip's in-point and it will be invisible. The scripts handle this correctly.

### Asset import + intro/outro: `scripts/import_assets.py` + `scripts/insert_intro_outro.py`

The `/import` slash command (`.claude/commands/import.md`) drives a full pipeline:

1. **Detect game** from the most recent transcript in `transcripts/`
2. **Import shared global assets** (type icons, BGM, badges, gym leaders, Pokémon artwork) into sub-bins inside "assets" — prompted for folder paths on first run only, stored globally after
3. **Validate game-specific asset paths** against `~/.resolve-mcp/manifest.json`; prompt for any missing/invalid
4. **Import game assets** into the `"assets"` bin
5. **Build an edited timeline**: new timeline with intro prepended, all original clips shifted right by the intro's exact duration, outro video appended to V1, outro audio appended to A3

#### Shared asset commands (cross-project, path set once per machine)

```cmd
rem Check shared folder paths
.venv\Scripts\python.exe scripts\import_assets.py --check-shared

rem Set a shared folder path (IDs: type_icons, bgm, badges, gymleaders, pokemon_art)
.venv\Scripts\python.exe scripts\import_assets.py --set-shared-path type_icons "C:\Path\To\TypeIcons"

rem Import all shared bins into Resolve (files collected recursively)
.venv\Scripts\python.exe scripts\import_assets.py --import-shared --dry-run
.venv\Scripts\python.exe scripts\import_assets.py --import-shared

rem Import only one specific shared bin (avoids re-importing already-loaded bins)
.venv\Scripts\python.exe scripts\import_assets.py --import-shared --only gymleaders
```

Shared bins created under "assets" in Resolve: `types`, `bgm`, `badges`, `gymleaders`, `pokemon-art`.

#### Game-specific asset commands

```cmd
rem Check which game asset paths are needed / already valid
.venv\Scripts\python.exe scripts\import_assets.py --game pokemon_crystal --check

rem Set a missing game asset path
.venv\Scripts\python.exe scripts\import_assets.py --game pokemon_crystal --set-path intro "E:\GSC Assets\GSCPC Intro Short.mp4"

rem Import game assets into Resolve
.venv\Scripts\python.exe scripts\import_assets.py --game pokemon_crystal --do-import --dry-run
.venv\Scripts\python.exe scripts\import_assets.py --game pokemon_crystal --do-import

rem Build edited timeline (uses current timeline as source by default)
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal --dry-run
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal

rem If the current Resolve timeline is not the gameplay source, target it explicitly:
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal --source-timeline "My Gameplay Timeline"

rem Force intro speed (auto-detected from transcripts/min-battles.json otherwise)
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal --intro-speed 400
.venv\Scripts\python.exe scripts\insert_intro_outro.py --game pokemon_crystal --intro-speed 100
```

**Intro retime:** by default the intro is retimed to 4x speed (400%) so it plays in ~4s instead of ~17s. The exception is **Minimum Battles Series** videos (player uses 8+ different Pokémon, repeatedly fighting the same trainer with each) — those keep the intro at full length since the viewer is settling in for a long test format. Detection runs via LLM relay:

```cmd
rem Classify the video first (writes transcripts/min-battles.json)
.venv\Scripts\python.exe scripts\detect_minimum_battles.py
```

`insert_intro_outro.py` reads that cache to decide automatically. `--intro-speed N` overrides. Retime is applied via `TimelineItem.SetProperty('Speed', ...)` after the intro is placed; if SetProperty doesn't take, the script warns and falls back to 100%.

**Asset catalog** (`assets/catalog.json`, committed to git) defines game asset slots per game and the 5 shared folder bins (`shared_assets` array). Games sharing the same generation (e.g., Crystal + Gold/Silver both use `gsc`) share paths — set up once, reused for all.

**Manifest** (`~/.resolve-mcp/manifest.json`, machine-local, not in git) stores game asset paths under `asset_group` keys and shared folder paths under the `"shared"` key.

**fps / endFrame convention:** All `AppendToTimeline` clipInfo dicts use `startFrame`/`endFrame` in **native clip frames** (not timeline frames), and `endFrame` is **exclusive** (first frame NOT included). For a clip with native in-point `L` and `D` timeline frames of content on a `TL_fps` timeline from a `clip_fps` source: `endFrame = L + round(D * clip_fps / TL_fps)`. For asset clips placed at full length (intro, outro), **omit startFrame/endFrame entirely** — let Resolve use the full clip, then read back `item.GetDuration()` for the true timeline-frame count. Specifying endFrame beyond the native source range causes Resolve to freeze the last frame, doubling the clip's apparent length.

**GetEndFrame() is exclusive:** `timeline.GetEndFrame()` returns one-past-the-last-occupied frame. To place the outro with no gap: `recordFrame = new_start + (orig_end - orig_start) + intro_tl_frames` (no `+1`).

### `scripts/close_gaps.py`

Closes small gaps (≤ N frames, default 1) between clips on V1 and A1 using a delete-and-re-insert strategy. Larger gaps (battle gaps, etc.) are preserved.

```cmd
rem Preview what would be closed without changing anything
.venv\Scripts\python.exe scripts\close_gaps.py --dry-run
.venv\Scripts\python.exe scripts\close_gaps.py --timeline "My Timeline (edit)" --dry-run

rem Close gaps on the current timeline (or a named one)
.venv\Scripts\python.exe scripts\close_gaps.py
.venv\Scripts\python.exe scripts\close_gaps.py --timeline "My Timeline (edit)"
.venv\Scripts\python.exe scripts\close_gaps.py --max-gap 2
```

**Always dry-run first.** The script deletes all clips on the track and re-inserts them at corrected positions — verify the gap count looks right before running live.

**fps handling:** `endFrame` passed to `AppendToTimeline` must be in native clip frames. For clips at a different fps than the timeline (e.g. 30fps intro/outro on a 60fps timeline) `GetDuration()` (timeline frames) must be scaled: `round(GetDuration() * clip_fps / timeline_fps)`. Without this, a 30fps clip gets doubled in length (frozen last frame) on every re-insert.

**Typical workflow:** After `insert_intro_outro.py`, run `close_gaps.py --dry-run` on the new edit timeline. With the correct `endFrame` exclusive convention in place, the result should be 0 gaps. If 1+ gaps remain, run without `--dry-run` to close them.

### `scripts/mark_battle_ends.py`

Detects the end of each trainer battle using a relay: writes a prompt containing the full battle transcript and frame paths to `plans/prompts/battle-ends-<stem>.in.md`, waits for Claude to write the JSON response to `.out.md`, then places green "Battle End" markers on the timeline.

```cmd
rem Full run: extract frames, write prompt, wait for relay, place markers
.venv\Scripts\python.exe scripts\mark_battle_ends.py

rem Skip relay (re-use existing .out.md) — just re-place markers
.venv\Scripts\python.exe scripts\mark_battle_ends.py --skip-relay

rem Preview marker positions without placing them
.venv\Scripts\python.exe scripts\mark_battle_ends.py --dry-run
```

**Requires:** `transcripts/battles.json` (from `detect_battles.py`), a full transcript JSON in `transcripts/`, and ffmpeg on PATH for frame extraction.

**Relay:** Claude (in the active conversation) must read the `.in.md`, reason contextually about the transcript and frame images, and write ONLY a raw JSON array to the `.out.md`. Timeout: 10 minutes.

**Marker frame convention:** `Timeline.AddMarker(frameId, ...)` expects `frameId` **relative to timeline start**, NOT the absolute internal frame. With a default 01:00:00:00 start at 60fps, passing an absolute frame (e.g. `clip.GetStart()`) places the marker 1 hour past the intended position. The script subtracts `timeline.GetStartFrame()` before calling `AddMarker` — copy this when adding new ruler markers.

### `scripts/refine_battle_ends.py`

Second-pass refinement that pinpoints the precise end frame of each battle using dense sampling + parallel per-battle subagents. Run AFTER `mark_battle_ends.py` has placed initial markers.

```cmd
rem Full run: dense extract → relay → replace markers
.venv\Scripts\python.exe scripts\refine_battle_ends.py

rem Reuse existing refine .out.md (skip frame extraction + relay)
.venv\Scripts\python.exe scripts\refine_battle_ends.py --skip-relay

rem Preview without modifying Resolve
.venv\Scripts\python.exe scripts\refine_battle_ends.py --dry-run
```

**How it works:** Loads the initial estimates from `battle-ends-<stem>.out.md`, extracts ~41 frames at 0.25s steps in a ±5s window around each estimate (~246 frames for 6 battles), writes a refinement prompt to `plans/prompts/battle-ends-refine-<stem>.in.md`. In the relay, Claude spawns one Haiku subagent per battle in parallel — each one Reads every frame in its list and identifies the exact transition (post-battle Crystal stats overlay appearing for WINs, first non-battle frame for GAVE_UPs). Once the `.out.md` is written, the script clears existing green markers and places refined ones.

**Typical drift after refinement:** wins land within ±0.5s of the true transition (frame-precise for clean wins); gave_ups are more approximate (no clean defeat flourish to lock onto).

---

## Usage

All 52 tools work on Windows. Below are example prompts for each category.

### Project & Navigation

```
"What project is open and how many timelines does it have?"
"Switch to the Color page"
"What page am I on?"
```

### Media Pool

```
"Import all .mp4 files from C:\Users\me\Footage\ into the media pool"
"Show me the media pool structure"
"Create a new timeline called 'Rough Cut' at 4K 24fps"
```

### Timeline & Markers

```
"What clips are on video track 1?"
"Move the playhead to 01:00:05:00"
"Add a red marker at frame 150 called 'Fix color here'"
"List all markers on the timeline"
```

### Clip Properties

```
"What are the properties of clip 2 on video track 1?"
"Set the opacity of the first clip to 80%"
"Zoom in on clip 3 (video track 1) to 110%"
```

### Color Grading

```
"Show me the node graph for clip 1 on video track 1"
"Apply the LUT at C:\LUTs\Kodak5219.cube to node 1 of clip 1"
"Lift the shadows slightly — set CDL slope to 1.1 for clip 2"
```

### AI / DaVinci Neural Engine (Resolve 19+)

```
"Run scene cut detection on the current timeline"
"Create a Magic Mask on clip 3 to isolate the person"
"Apply Smart Reframe to clip 1 for 9:16 vertical"
"Stabilize clip 2 on video track 1"
"Generate English subtitles from the audio"
"Enable voice isolation on audio track 1"
```

### Transcription (faster-whisper, local)

```
"Transcribe C:\Videos\interview.mp4"
"Transcribe using the medium model in Spanish"
"Export an SRT from C:\Videos\podcast.wav to C:\Desktop\podcast.srt"
"Transcribe the audio and add subtitle markers to the timeline"
"List the available Whisper models"
```

Transcription uses CUDA if available, otherwise CPU. Default model: `large-v3-turbo`.

| Alias | Model | Speed | Accuracy |
|---|---|---|---|
| `tiny` | tiny | Fastest | Low |
| `base` | base | Fast | Fair |
| `small` | small | Moderate | Good |
| `medium` | medium | Slow | Good |
| `large` | large-v3 | Slow | High |
| `turbo` | large-v3-turbo | Moderate | High (default) |

### Screenshot

```
"Take a screenshot of Resolve"
"What does the color page look like right now?"
```

Targets the DaVinci Resolve window directly. Falls back to full-screen capture if the window isn't found.

### Rendering

```
"What render formats are available?"
"Set up a render: ProRes 422 HQ, 1920x1080, output to C:\Exports\"
"Queue a render job and start rendering"
"What's the render status?"
"Stop rendering"
```

### Fusion Compositing

```
"List the Fusion comps on clip 1"
"Add a new Fusion composition to clip 2 called 'Title Anim'"
"Insert a Fusion title into the timeline (3 seconds)"
"Export the Fusion comp from clip 1 to C:\Comps\title.comp"
```

### Timeline Export

```
"Export the timeline as an FCPXML to C:\Exports\timeline.fcpxml"
"Export as EDL"
```

### Power Tool

```
"Run this Python code in Resolve: print(project.GetSetting('timelineFrameRate'))"
"Use execute_resolve_code to get all clip names from track 1"
```

`execute_resolve_code` runs arbitrary Python with `resolve`, `project`, `mediaPool`, `timeline`, and `mediaStorage` pre-loaded. Anything the Resolve scripting API supports, Claude can do.

---

## Full Tool Reference

| Category | Tool | Description |
|---|---|---|
| **Project** | `get_project_info` | Name, version, timeline count |
| | `open_page` | Switch to media/cut/edit/fusion/color/fairlight/deliver |
| | `get_current_page` | Active page name |
| **Media Pool** | `get_media_pool_structure` | Folder/clip hierarchy |
| | `import_media` | Import files into the pool |
| | `create_timeline` | New timeline with name/res/fps |
| **Timeline** | `get_current_timeline_info` | Name, res, fps, frame count |
| | `get_timeline_items` | Clips on a specific track |
| | `append_to_timeline` | Add clip from pool to end |
| | `set_current_timecode` | Move playhead |
| | `get_current_timecode` | Current playhead position |
| | `add_marker` | Place marker with color/name/note |
| | `get_markers` | All markers on timeline |
| **Clip Properties** | `get_timeline_item_properties` | Pan, tilt, zoom, opacity, crop, etc. |
| | `set_timeline_item_property` | Modify any property |
| **Color** | `get_node_graph` | Color nodes for a clip |
| | `set_lut` | Apply LUT file to a node |
| | `set_cdl` | Apply CDL values to a node |
| **Rendering** | `get_render_formats` | Available codecs/formats |
| | `get_render_settings` | Current render config |
| | `set_render_settings` | Configure format/codec/size |
| | `add_render_job` | Queue a job |
| | `start_rendering` | Begin render queue |
| | `get_render_status` | Check job progress |
| | `stop_rendering` | Halt rendering |
| **AI/Neural Engine** | `create_magic_mask` | AI subject isolation |
| | `regenerate_magic_mask` | Refresh existing mask |
| | `smart_reframe` | Auto-reframe for aspect ratio |
| | `stabilize` | AI stabilization |
| | `detect_scene_cuts` | Auto scene detection |
| | `create_subtitles_from_audio` | Built-in Resolve speech-to-text |
| **Audio** | `get_voice_isolation_state` | Check voice isolation |
| | `set_voice_isolation_state` | Toggle voice isolation |
| **Fusion** | `get_fusion_comp_list` | List compositions on clip |
| | `add_fusion_comp` | Create new composition |
| | `import_fusion_comp` | Load .comp file |
| | `export_fusion_comp` | Export composition |
| | `load_fusion_comp` | Activate composition |
| | `delete_fusion_comp` | Remove composition |
| | `rename_fusion_comp` | Rename composition |
| | `create_fusion_clip` | Merge clips into Fusion clip |
| | `insert_fusion_generator` | Insert generator |
| | `insert_fusion_composition` | Insert blank composition |
| | `insert_fusion_title` | Insert title |
| **Export** | `export_timeline` | AAF/EDL/FCP XML/OTIO/ALE/CSV |
| | `export_current_frame` | Save current frame as still |
| **Media** | `get_current_thumbnail` | PNG thumbnail of current frame |
| | `screenshot` | DaVinci Resolve window capture |
| **Transcription** | `transcribe_audio` | faster-whisper transcription |
| | `transcribe_and_add_subtitles` | Transcribe + add to timeline |
| | `export_srt` | Save transcript as SRT |
| | `list_whisper_models` | Available model sizes |
| **Code** | `execute_resolve_code` | Run arbitrary Python with Resolve API |

---

## Troubleshooting

### "Could not connect to DaVinci Resolve"
- Resolve must be open with a project loaded
- Check **Preferences → General → External scripting using → Local**
- Restart Resolve after changing scripting settings

### "Failed to import DaVinciResolveScript"
- The server auto-detects Windows paths. If it fails, set them manually in the MCP env:
  ```json
  "env": {
    "RESOLVE_SCRIPT_LIB": "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll",
    "PYTHONPATH": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\"
  }
  ```

### "No active timeline"
- Open a project in Resolve and make sure a timeline is active before using timeline tools

### Screenshot captures wrong area / black image
- Make sure Resolve is not minimized — it must be visible on screen
- If using multiple monitors, the window rect capture should still work; if not, the tool falls back to full-screen

### faster-whisper is slow
- Without a CUDA GPU it runs on CPU — use a smaller model: `"Transcribe using the tiny model"`
- For GPU, ensure CUDA drivers are installed. The server logs whether it's using cuda or cpu.

### MCP server not appearing in Claude Code
- Run `claude mcp list` to confirm it's registered
- Run `uv --directory C:\Programming\resolve-mcp run resolve-mcp` manually to see startup errors
- Make sure you started a new Claude Code session after adding the MCP server

### Updating the code
Any Python change is picked up on the next tool call. If you add or rename tools, restart your Claude session so the updated schema loads.

---

## Important Warnings

- **No undo.** Claude can modify or delete timelines, clips, and render jobs. Keep project backups.
- **`execute_resolve_code` runs arbitrary Python.** Review code in tool calls before approving.
- **Screenshots are sent to Anthropic** for visual analysis. Be aware of client confidentiality and NDA obligations — don't use the screenshot tool if sensitive footage is on screen.
- **Resolve Studio required** for full API access. The free version restricts some scripting functionality.
- This is an unofficial third-party project. Not supported by Blackmagic Design or Anthropic.

---

## License

MIT. See original repo: [barckley75/resolve-mcp](https://github.com/barckley75/resolve-mcp)

Built with the [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic.
