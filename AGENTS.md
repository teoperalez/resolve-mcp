# AGENTS.md — resolve-mcp

This MCP server lets Codex control DaVinci Resolve Studio directly via its Python scripting API. Read this before using the tools.

---

## Environment

- **Platform:** Windows (patched fork — screenshot and transcription fully work on Windows)
- **Server:** `C:\Programming\resolve-mcp`
- **Resolve paths (auto-detected):**
  - `fusionscript.dll` → `C:\Program Files\Blackmagic Design\DaVinci Resolve\`
  - Scripting Modules → `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\`
- **Transcription backend:** `faster-whisper` (CUDA GPU preferred, CPU fallback)
- **CUDA DLLs (Windows):** `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` must be installed — Windows does not bundle these. Run once after setup: `uv sync --extra transcription --extra cuda-win`

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

## Edit timeline process memory

When running or modifying the full `/edittimeline` workflow, preserve these
invariants. They were added after real project failures and should travel to
future projects:

- Use `.claude/commands/edittimeline.md` as the canonical step order. Every
  step is wrapped with `scripts/audit_step.py snapshot --step <id>` before the
  command and `scripts/audit_step.py audit --step <id>` after it.
- If an audit fails, stop. Read `_data/audits/<step_id>_report.json`, explain
  the violations/regressions, and do not continue until the timeline is fixed or
  the user explicitly accepts the deviation.
- After a step audit passes, `scripts/audit_step.py audit` exports a Resolve
  native `.drt` checkpoint under `_data/drt-checkpoints/`. Treat that DRT as the
  durable timeline checkpoint for any API-built/API-modified section. If DRT
  export fails, the audit must fail and the pipeline must stop.
- Preserve timeline markers, clip-level markers, and clip colors across every
  derived timeline. If a step cuts or ripples, remap those annotations; do not
  silently drop them.
- Cuts are FCPXML-section safe. Fully covered FCPXML sections may be removed.
  Part-way cuts inside an FCPXML section should be marked Pink for manual review
  and left uncut unless the user explicitly asks for a surgical edit.
- Gameplay V1 clips must have aligned A1 dialogue coverage. Intro/outro assets
  are exempt. `audit_step.py` enforces this globally via `v1_has_a1_coverage`.
- For Gen 1 Red/Blue/Yellow timelines where leader intros are discrete
  video/audio insertions, those leader-intro sections are protected structural
  content just like the channel intro/outro. Cut application must not trim or
  remove them, and every audit after placement must fail if any leader-intro
  video or audio clip identity/count is lost. Insert those Gen 1 intros at 2x
  speed using `place_battle_intros.py --gen1-insert --gen1-speed 2`; the script
  creates cached retimed media instead of depending on Resolve retime metadata.
  For retimed intro media, remember Resolve's `AppendToTimeline` frame domains:
  video `startFrame`/`endFrame` are native media frames, while the ripple
  duration is timeline frames. Mixing those makes 24fps retimed intros too long
  and lets A1 gameplay audio resume under the leader video.
- For Gen 1 Red/Blue/Yellow battle gaps, leader/E4/champion battles are handled
  by the discrete intro insertion and should be excluded from ordinary
  pre-battle gap insertion. Use `insert_battle_gaps_fcpxml.py
  --only-gen1-non-bosses` for the battle-gap step on those projects.
- For the Victreebel Red/Blue Ultra Minimum Battles handoff timelines, pair all
  work with the handoff file at
  `E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\VICTREEBEL_PASSOFF.md`.
  The verified corrected-base rebuild tool is
  `scripts\rebuild_victreebel_rby_timeline.py`. The verified approved-cuts
  final rebuild bridge is
  `scripts\rebuild_victreebel_final_from_review_spine.py`, which consumes the
  approved live V1/A1 review spine, restores the dropped Champion marker,
  applies source-derived holds, inserts non-boss gaps and 2x Gen 1 leader
  intros, supports resume after Resolve scripting bridge interruptions, and
  exports a DRT/self-audit report before downstream BGM/battle-audio/carousel
  and color passes. The first approved-cuts full rebuild still missed true
  post-battle V1 hold replacement; the verified repair helper is
  `scripts\apply_victreebel_visual_hold_fix.py`. It duplicates the final
  timeline, replaces only V1 over the intended post-battle hold spans, verifies
  exactly one Purple V1 clip per hold, and uses the old post-battle rule:
  from each `Beat ...`/finish marker, search backward to the last battle-overlay
  segment as the hold source anchor, then extend through the data card until the
  next main-UI segment; for Champion, extend through the post-battle card until
  the first `Final Tierlist` marker.
- Resolve timeline rebuilds through the Python API are slow and heavy. For
  cut-review projects, avoid repeated partial API rebuilds for cuts, holds, BGM,
  carousel, and cleanup. Keep approvals and timing decisions as source/remap
  metadata while the review timeline is lightweight, then run one deterministic
  heavy rebuild after cuts are approved and holds/BGM/downstream placements are
  known, so the user can walk away and come back to a validated final timeline.
- Battle-intro clips must exist on V2. `place_battle_intros.py` verifies the API
  placement and writes `_data/qa-reports/battle-intros-placements.json`; the
  Step 9 audit also checks V2 intro presence.
- A2-A5 must not receive auto-editor linked audio. `apply_cuts_to_fcpxml.py`
  drops those refs by default, while preserving embedded gameplay audio on A1.
  The intentional exception is project music: A2 BGM/battle audio plus intro or
  outro music on their designated tracks.
- Do not defensively wipe A2-A5 after the edit timeline is built. If the Step 6
  audit says those tracks are populated, investigate the source instead of
  deleting content blindly.
- When restoring missing narration, rebuild the segment from the
  `_ALTERED.fcpxml`/current FCPXML sections. Do not append a continuous raw
  source span unless the FCPXML section is continuous; otherwise the replacement
  can reinsert silences that auto-editor already removed.
- User/manual colors are meaningful. Pink on V1/A1 means delete/review; Pink on
  A2 means a mistaken or unreasonably short music clip; Yellow on A2 means trim
  trailing silence. Consult `_data/manual-pass/detection_notes.md` when present
  before changing QA detector behavior.
- For Pokemon Red/Blue RBYNewLayout projects, do not infer battle markers from
  transcript guesses when session logs exist. Read the matching
  `%APPDATA%\rbypc-frontend\logs\...\events.json`, replay markers with
  `C:\Programming\RBYNewLayout\scripts\session_marker_labels.py`, and map marker
  elapsed time to source time with the MP4 `creation_time` minus
  `meta.json.startedAt`. If a project has separate part files and only part 2
  has valid markers, keep the part FCPXMLs/media separate, map markers only into
  part 2, then merge/remap into the combined deliverable. For Gen 1 leader
  intros, prefer Blue-specific intro files (`SurgeBlue.mp4`, `ErikaBlue.mp4`,
  etc.) when present and fall back to the standard leader intro (`Brock.mp4`,
  `Misty.mp4`, `Lorelei.mp4`, etc.) when no Blue-specific version exists.
- Before re-running auto-editor or transcription on split Gen 1 recordings,
  sanity-check which extracted WAV is dialogue with
  `scripts\detect_dialogue_audio.py`. Dialogue should be mostly quiet except
  during speech and should transcribe as high-probability speech. Reject tracks
  that are constant BGM, desktop audio/alerts, or music mixed under speech.
  When there is a full 5-track export, the historical FCPXML/A1 primary track
  can remain the default. When a travel/single-mic setup yields only 3
  subtracks, do not assume track 1; use the detector's chosen track for the
  auto-editor stream selector and for transcription.

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

## Common editing operations (ready-to-run scripts)

These scripts live in `scripts/` and are self-contained — they set their own environment, so no PYTHONPATH export is needed. Run them with the project venv's Python:

```
PYTHON = C:\Programming\resolve-mcp\.venv\Scripts\python.exe
```

### Clear audio tracks

Deletes all clips from audio tracks START through END (default A2–A5). Not a ripple delete — gaps stay.

```bash
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\clear_audio_tracks.py [start=2] [end=5]"
```

### Ripple delete short clips

Ripple deletes clips shorter than N frames from **V1 and A1** (default: < 5 frames). Both tracks are processed together so linked clips delete as a pair.

```bash
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\remove_short_clips.py [min_frames=5]"
```

### Mark audio gaps

Finds gaps in **A1** longer than N frames (default: > 5 frames) and places red markers at the **end of each gap** on:
- The timeline ruler
- The V1 clip at that position

```bash
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\mark_audio_gaps.py [min_gap_frames=5]"
```

### Color cut candidates (relay)

Analyzes the **live Resolve V1 timeline clip-by-clip** via LLM relay. Colors V1 clips: **Orange** = high confidence cut, **Yellow** = medium confidence cut.

The analyzer enumerates every V1 clip, attaches any overlapping Whisper transcript text to each, and asks the LLM to flag clips whose narrative purpose cannot be established. Clips from non-gameplay source media (intro card, outro card, B-roll inserts) are automatically excluded — only clips from the dominant gameplay source are analyzed.

**Editorial bias:** the inverse of "default to KEEP". The auto-editor's silence threshold keeps everything above the noise floor — not only speech — so anything left on the timeline must earn its place. **If a clip's narrative purpose cannot be articulated, FLAG IT.** Empty-transcript clips (throat clears, breath bursts, mic bumps, mic checks) are the highest-priority flags and were invisible to the old transcript-only approach.

Categories:
- HIGH: empty-transcript noise, pre-roll / mic-check, Whisper hallucination, stuttered repeats
- MEDIUM: false starts, true repetitions (failed-take redos), abandoned narrative threads

**Mid-clip cuts.** A single V1 clip often contains multiple Whisper sub-segments — a false start + a clean restart, a mid-sentence correction, an aborted word followed by a real take. The prompt shows each sub-segment on its own `sub [start-end] "text"` line so the LLM can flag a SUBSET of a clip's source range. Output `type` is prefixed `mid_clip_*` (e.g. `mid_clip_false_start`, `mid_clip_repetition`). When the apply step sees a mid-clip flag it:
1. Snaps each cut edge to the largest word-gap within ±0.3s (uses Whisper word-level timestamps as a guide, then cuts at the actual gap between words)
2. Sets the parent clip's color (Yellow/Orange)
3. Places two `Red` markers on the clip — **Cut start** at the refined source frame, **Cut end** at the refined end frame — using `customData='cut_candidates'` for idempotent re-runs

The editor blades at the two red markers and deletes the marked section. Sub-clip ranges must be at least 0.2s apart; the prompt rejects zero-length flags.

```bash
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\mark_cut_candidates.py [transcript.json] [--dry-run] [--skip-relay]"
```

`--skip-relay`: reapply colors from an existing `plans/prompts/cut-analysis-<stem>.out.md` without re-running the LLM. Use after manually editing the .out.md or after clearing stale clip colors and re-running with the same analysis.

### Apply cuts → generate HIGH-only and ALL-cuts timelines

After cut candidates are flagged (and optionally edited by the user), `apply_cuts_to_fcpxml.py` produces two ripple-cut FCPXML variants from the auto-editor's FCPXML and imports both as new Resolve timelines:

- `*_CUTS_HIGH.fcpxml` — only high-confidence cuts removed
- `*_CUTS_ALL.fcpxml`  — high + medium cuts removed

The two imported timelines are auto-named `... (cuts: high)` and `... (cuts: all)` (suffix appended via the FCPXML `<project name>` attribute). The ALL-cuts timeline is set as current — **all downstream pipeline steps (BGM, carousel, Fairlight, etc.) run on the ALL-cuts timeline**.

**Linked-audio refs dropped by default.** The auto-editor stacks 1 video + 4 audio asset-clips at each spine position (refs r2 + r4/r6/r8/r10 — the latter four are the WAV splits from `<video>_tracks/1.wav`-`4.wav`). On Resolve import these would land on A2-A5, blocking the Fairlight preset that expects those tracks free. The script auto-detects the video ref via `<asset hasVideo="1">` declarations and emits only video-ref clips in the output spine; the video's embedded audio still maps to A1, giving a clean V1+A1 timeline. Pass `--keep-linked-audio` to preserve the auto-editor's 4 audio refs (old behavior).

```bash
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\apply_cuts_to_fcpxml.py INPUT_ALTERED_BATTLEGAPS.fcpxml [--cuts plans/prompts/cut-analysis-<stem>.out.md] [-o OUT_DIR] [--import-to-resolve]"
```

**Algorithm.** Auto-editor FCPXML stacks 1 video + N linked audio `<asset-clip>` elements per timeline position. The script:
1. Parses the spine, groups asset-clips by `offset` (5 per position for typical 1-video + 4-audio output)
2. For each position, decides keep / delete / trim_start / trim_end / split / multi vs. the source-time cut intervals
3. Applies the SAME action across all refs in the position (V + linked A stay synchronized)
4. Maintains a cumulative timeline-shift, ripple-lefts every subsequent position
5. Remaps `<marker>` entries by the same shift; drops markers that fall inside removed ranges

**Replay metadata.** A sidecar `*_cuts_replay.json` captures both variants' source-frame cuts AND the resulting removed timeline ranges (in frames), plus the raw per-flag records with reasons. This data is sufficient to:
- Reproduce the cuts on a sibling timeline
- Translate timeline coordinates between HIGH and ALL variants (e.g. to mirror a marker placed on (cuts: all) onto (cuts: high))
- Apply additional downstream operations to (cuts: high) that mirror what was done on (cuts: all)

### Battle intros on V2 (rival + gym leader graphics)

Two scripts overlay pre-battle intro graphics on V2 for every major-boss fight:

```bash
# 10a. (prerequisite) Classify each battle as rival / gym / other
.venv\Scripts\python scripts\classify_battles.py     # relay → transcripts/battle-types.json

# 10b. Identify the rival's starter type + per-battle canonical location (skip if no rivals)
.venv\Scripts\python scripts\classify_rival_starter.py  # relay → transcripts/rival-starter.json

# 10c. Place V2 intros — 5s ending at each battle start, on the clip before the battle
.venv\Scripts\python scripts\place_battle_intros.py [--dry-run] [--include-other] [--overlap-sec 5]
```

**Intro file selection:**

- **Gym / Elite 4 / Champion** → `{trainer_lower}-battle-intro.mov` from the `battle-intros` bin. Trainer names are slugified to filename (e.g. `Lt. Surge` → `ltsurge-battle-intro.mov`). 22 known intros: brock, misty, ltsurge, erika, sabrina, koga, blaine, blue, falkner, bugsy, whitney, morty, jasmine, chuck, pryce, clair, will, bruno, karen, janine, lance, red.

- **Rival** → `silver-<location>-<starter_type>-battle-intro.mov` from the `silver-battle-intros` bin. Two pieces:
  - **starter_type** = the rival's starter (fire/water/grass) — fixed for the whole video, determined by `classify_rival_starter.py`. In Gen 2 the rival picks the starter with type advantage over the player's pick: player Chikorita → rival fire, player Cyndaquil → rival water, player Totodile → rival grass.
  - **location** is one of `cherrygrove`, `azalea`, `burnedtower`, `goldenrod`, `victoryroad`, `indigoplateau`, `mtmoon`. Identified per battle by **team composition** (the deterministic signal):
    - starter only → cherrygrove
    - Gastly+Zubat (no Haunter, no Magnemite) → azalea
    - Haunter+Zubat (no Magnemite) → burnedtower
    - Magnemite present → goldenrod
    - Fully evolved + Magneton/Gengar/Crobat/Sneasel → victoryroad
  - And cross-checked by position relative to gym leaders: between Bugsy and Whitney = azalea; between Whitney and Morty = burnedtower; between Pryce and Clair = goldenrod; between Clair and E4 = victoryroad. Don't trust explicit transcript mentions of locations — the streamer may describe surroundings while the actual fight is elsewhere.

**Placement.** Each intro is placed on V2 with its TAIL aligned to the battle start frame and HEAD at `battle_frame - min(5s, intro_duration)`. Video only (mediaType=1); the intro's audio is dropped so it doesn't conflict with the A2 BGM/battle-audio pipeline (Step 13). V2 is the correct track for these overlays since carousel layout (Step 12) only fills V2 from the carousel start onward, leaving V2 free for the gameplay section.

**Idempotency.** Before each placement run, the script sweeps V2 for clips whose name ends in `-battle-intro.mov` and deletes them. Re-running after fixing `rival-starter.json` (e.g. correcting a location) does the right thing without manual cleanup.

Relay protocol (Codex's job): read `plans/prompts/cut-analysis-<stem>.in.md` (a clip list with attached transcripts and a categorized prompt), write ONLY the JSON cut array to the `.out.md`. The clip list can be ~500+ entries on a typical 30-min video — dispatch a subagent with a fresh context if the prompt is large.

---

### Critical: marker frameId conventions

There are **two `AddMarker` calls with different frame conventions** — mixing them up has bitten this codebase repeatedly.

**`TimelineItem.AddMarker(frameId, ...)`** (clip-level marker) — `frameId` is the **absolute source frame**.

```python
# CORRECT — visible on the clip
src_frame = clip.GetLeftOffset() + (gap_end - clip.GetStart())
clip.AddMarker(src_frame, color, name, note, duration, customData)

# WRONG — marker lands before the clip's in-point, invisible
clip.AddMarker(gap_end - clip.GetStart(), ...)
```

**`Timeline.AddMarker(frameId, ...)`** (ruler-level marker) — `frameId` is **relative to timeline start**, NOT the absolute internal frame.

```python
# CORRECT
abs_frame = clip.GetStart() + offset      # e.g. 230486 (absolute internal)
rel_frame = abs_frame - timeline.GetStartFrame()
timeline.AddMarker(rel_frame, 'Green', name, note, 1)

# WRONG — marker lands 1 hour past target
# (default timelines start at 01:00:00:00 = frame 216000 @ 60fps;
#  passing the absolute frame double-counts that offset)
timeline.AddMarker(abs_frame, 'Green', name, note, 1)
```

`Timeline.GetMarkers()` also returns keys as **relative-to-start** frames, so the round-trip stays consistent if you stay in relative space.

`MediaPoolItem.AddMarker()` (source clip in media pool) uses the source-frame convention but shows in the bin, NOT on cut-up timeline items. Always use `TimelineItem.AddMarker` with source frames for timeline visibility.

`refine_battle_ends.py` and the updated `mark_battle_ends.py` use the relative-frame fix. `insert_battle_gaps.py` and `mark_audio_gaps.py` have TODOs flagging the same likely bug — verify before trusting their ruler-marker positions.

### Refine battle end markers (precision second pass)

After `mark_battle_ends.py` places rough markers (frames sampled every ~10s across the whole battle window), `refine_battle_ends.py` does a tight ±5s @ 0.25s pass around each estimate (~41 frames per battle) and refines via a parallel subagent per battle.

```bash
# Full run: dense extract → relay → replace markers
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\refine_battle_ends.py"

# Reuse existing refine .out.md without re-extracting frames or re-relaying
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\refine_battle_ends.py --skip-relay"
```

**Relay (Codex's job):** read `plans/prompts/battle-ends-refine-<stem>.in.md`, then dispatch **one Haiku subagent per battle in parallel** — each gets that battle's ~41 frame paths and a single-decision instruction (find the first frame where the post-battle Crystal stats overlay appears for WINs, or the first non-battle frame for GAVE_UPs). Each subagent returns one JSON object; concatenate into an array and write to the `.out.md`. The script then clears existing green markers and replaces them with refined ones.

Typical drift after refinement: wins land within ±0.5s; gave_ups within ±2s (no clean defeat flourish to lock onto).

### Asset import + intro/outro insertion (`/import` skill)

The `/import` skill (`.Codex/commands/import.md`) runs a full 6-step pipeline:

1. Detects game version from `transcripts/*.json` (most recent file, first ~3000 chars)
2. **Imports shared global assets** (type icons, BGM, badges, gym leaders, Pokémon artwork) into sub-bins inside "assets" — prompts for folder paths on first run, reuses stored paths after
3. Checks game-specific manifest paths; prompts for any missing/invalid
4. Imports game-specific assets into the `"assets"` bin
5. Builds a new timeline with intro prepended, all clips shifted right, outro appended

#### Shared asset commands (cross-project, stored under `"shared"` key in manifest)

```bash
# Check which shared folder paths are configured
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --check-shared"

# Set a shared folder path (all 5 IDs: type_icons, bgm, badges, gymleaders, pokemon_art)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --set-shared-path type_icons "C:\PATH\TO\FOLDER""

# Import all shared bins (files collected recursively from each folder)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --import-shared [--dry-run]"

# Import only one specific bin (avoids re-importing already-loaded bins)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --import-shared --only gymleaders"
```

Shared bins created under "assets" in Resolve: `types`, `bgm`, `badges`, `gymleaders`, `pokemon-art`.

#### Game-specific asset commands

```bash
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --check"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --do-import"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY"
```

All `import_assets.py` modes support `--dry-run`.

#### Intro retime (4x for non–Minimum Battles videos)

`insert_intro_outro.py` retimes the placed intro after placement. By default the speed is auto-detected:

1. Reads `transcripts/min-battles.json` if it exists (produced by `detect_minimum_battles.py`)
2. If `is_minimum_battles=true` → keeps intro at **100%**
3. Otherwise → retimes intro to **400%** (4x), so the intro plays in ~4s instead of ~17s
4. Recomputes the gameplay shift using the placed intro's post-retime `GetDuration()`

```bash
# Classify the video first (LLM relay — see below)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\detect_minimum_battles.py"

# Then build the edit timeline (auto-picks 100% or 400%)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY"

# Force a specific speed (overrides auto-detect)
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY --intro-speed 100"
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY --intro-speed 400"
```

**Retime implementation:** Resolve's `TimelineItem.SetProperty` doesn't expose Speed in the current API (only `RetimeProcess`, the interpolation method, is settable). So the retime is done by pre-rendering the intro to a separate file via ffmpeg (`-filter:v setpts=PTS/<speed_factor> -an`), then importing that into the "assets" bin and placing it as the intro. The pre-rendered file is cached at `~/.resolve-mcp/cache/retimed-intros/<stem>__<speed>pct.mp4` and reused on subsequent runs — first run takes a few extra seconds, subsequent runs hit the cache. Audio is dropped during retime (the intro audio at 4x sounds bad anyway and the existing pipeline doesn't place intro audio on a track).

**Minimum Battles classifier:** `detect_minimum_battles.py` uses the same relay pattern as `detect_battles.py` — writes `plans/prompts/min-battles-<stem>.in.md` with the transcript and waits for Codex to write a single-object JSON `{"is_minimum_battles": bool, "pokemon_count": N, "trainers_attempted": [...], "reasoning": "..."}` to the `.out.md`. Result cached in `transcripts/min-battles.json`. A Minimum Battles Series = player uses ≥8 different Pokémon AND repeatedly fights the same (or similar) trainer — when those signals are present the intro should NOT be retimed (the viewer is settling in for a long test format).

**Asset catalog:** `assets/catalog.json` (committed to git) — defines game asset slots (`assets` section per game) and the 5 shared folder bins (`shared_assets` array at top level).
**Manifest:** `~/.resolve-mcp/manifest.json` (machine-local, not in git) — stores actual file paths under `asset_group` keys for game assets and under `"shared"` for shared folders.
**Asset groups:** Multiple games sharing the same generation (e.g., `pokemon_crystal` + `pokemon_gold_silver` both use `gsc`) share paths — set up once, reused for all.

### Battle gap insertion workflow

Detects first-time trainer battle starts via transcription + LLM relay, then inserts 1 second (60 frames) of source footage at each position.

**Three scripts, or run the combined pipeline:**

```bash
# Full pipeline
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\battle_workflow.py [--dry-run]"

# Or step by step:
# 1. Transcribe A1 audio source
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\transcribe_audio.py"
# 2. Detect battles (relay — see below)
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\detect_battles.py transcripts/4.json"
# 3. Insert gaps
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\insert_battle_gaps.py transcripts/battles.json"
```

**Relay mode (Step 2):** `detect_battles.py` writes a prompt to `plans/prompts/battle-detect-<stem>.in.md` and polls for `plans/prompts/battle-detect-<stem>.out.md`. Codex must:
1. Read the `.in.md` file
2. Analyze the transcript (identify first-time trainer battle starts, output JSON)
3. Write ONLY the JSON array to the `.out.md` file — no markdown fences, no explanation

The script auto-detects the `.out.md` and continues. Timeout: 10 minutes.

**Gap insertion note:** `insert_battle_gaps.py` extends the V1 clip's out-point using `AppendToTimeline` with source frames. If a clip has fewer than 60 frames of tail trim (handle), it places an orange "Battle" marker instead and skips the extension. Always do a `--dry-run` first.

### Member Carousel detection + layout

After the last Battle End marker, the video transitions into a "Member Carousel" / "Member Thank You" section where an overlay (Pokémon sprite at bottom-left + member name in yellow text + gym badge at bottom-right) cycles through patrons. Two scripts:

**`find_member_carousel.py`** — locates the first V1 clip whose first frame shows the carousel overlay. Extracts first-frame + previous-clip's-last-frame for up to 30 candidates after the last green marker, writes a relay prompt. Codex dispatches a single Haiku subagent that classifies frames sequentially (Phase 1: find candidate with carousel; Phase 2: check previous clip's last frame). Places a yellow `Member Carousel Start` marker.

**`layout_carousel.py`** — reshapes the carousel section so the overlay plays continuously while streamer cuts overlay above:
- Copies all V1 clips between `Member Carousel Start` and the outro onto V2
- Sets `CropBottom=530` on each V2 clip (V1's bottom strip — the carousel — shows through where V2 is cropped)
- Deletes the original V1 clips in that range
- Appends ONE extended V1 clip from carousel start to outro start, with source range continuing past the original V1 clip's out-point so the underlying source plays through without time cuts

This relies on the gameplay source file having enough handle frames past the original V1 clip's end (typically true — original capture is 47+ min, edit timeline is 28 min). Always `--dry-run` first to verify the extended source range doesn't exceed the source file's length.

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

For pipeline-end deliverables, use `scripts/render_timeline.py` which wraps Resolve's built-in YouTube presets:

```bash
# QA pass: 720p H.264 via YouTube - 720p preset (review-quality)
.venv\Scripts\python scripts\render_timeline.py --preset qa

# Final: 4K H.264 via YouTube - 2160p preset (production-quality)
.venv\Scripts\python scripts\render_timeline.py --preset 4k
```

Output filename: `<timeline-name>_QA_720p.mp4` / `<timeline-name>_FINAL_4K.mp4`.
Default output dir: next to the source video (auto-detected by walking up from the transcript's `audio` field). Override with `--output-dir`.

The script blocks until the render completes, polling `IsRenderingInProgress` and `GetRenderJobStatus` every 10s.

**Two-pass workflow for /edittimeline:** render QA first, then ask user to approve before kicking off the 4K render. Reasoning: a 30-min 4K-source timeline takes ~2h to QA-render and ~3-4h to 4K-render — committing to 4K without first verifying the cut would be expensive.

**Manual API equivalents** (for ad-hoc renders outside the standard preset):

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
| GPU runtime failure mid-transcription | CUDA DLLs missing from venv (Windows-only) | `.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` |
| `Failed to create new timeline` (insert_intro_outro) | A timeline with that name already exists | Script auto-generates a unique name; if error persists, delete stale `(edit)` timelines in Resolve |

### `insert_intro_outro.py` — clips overlap the intro / intro is double-length

**Root cause:** `AppendToTimeline` clipInfo `startFrame`/`endFrame` are **native clip frames**, and `GetClipProperty("Video Duration")` may return a native frame count, not timeline frames. On a 60fps timeline, a 30fps source clip occupies **2× as many timeline frames** as its native frame count.

**Symptoms:**
- Intro or outro clip appears stretched to double its expected length (adjusting handles restores correct length — this is the giveaway)
- Gameplay clips start under the intro (overlap) because the shift amount was half what it should be

**Fix applied in `insert_intro_outro.py`:**
1. Intro and outro are placed **without `startFrame`/`endFrame`** — Resolve uses the full clip at its natural duration
2. After placing the intro, the script reads back `intro_item.GetDuration()` — the actual timeline frame count with all fps conversion applied — and uses that for the shift
3. `mpi_duration_frames()` reads native FPS via `GetClipProperty('FPS')` for accurate dry-run estimates

**Rule of thumb for future scripts:** place the clip first, then call `item.GetDuration()` — it is always authoritative regardless of source fps. Do not compute shift distances from raw `GetClipProperty` values without fps conversion.

**Also:** capture `orig_tl` and `orig_end = orig_tl.GetEndFrame()` **before** `pool.CreateEmptyTimeline()` — that call switches the current timeline to the new empty one.

---

## Tips for effective collaboration

- **Ask before you act on ambiguity.** "Clip 1" could mean first in the pool or first on the timeline — clarify.
- **State what you're about to do** before calling tools that modify Resolve state.
- **Chain reads before writes.** Call `get_timeline_items` or `get_timeline_item_properties` to confirm the target before setting anything.
- **Use markers as breadcrumbs.** When working through a long timeline, add markers so the user can see where you've made changes.
- **Transcription on long files is chunked automatically.** Files over 5 minutes are split into 5-minute WAV chunks, transcribed in sequence, then stitched. This is transparent — just expect it to take longer.
- **For anything complex, prefer a screenshot loop:** take screenshot → describe what you see → make one change → take another screenshot → confirm.
