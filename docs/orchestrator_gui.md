# Resolve Orchestrator GUI

`scripts/orchestrator_gui.py` is the canonical workflow runner for full edit
generation. `scripts/orchestrator_run.py` exposes the same catalog from the
command line for inspection and recovery.

## Launch

```powershell
.venv\Scripts\python.exe scripts\orchestrator_gui.py
```

Installed entrypoint:

```powershell
resolve-orchestrator-gui
```

CLI:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py profiles
.venv\Scripts\python.exe scripts\orchestrator_run.py plan --profile <profile_id>
.venv\Scripts\python.exe scripts\orchestrator_run.py status --profile <profile_id>
.venv\Scripts\python.exe scripts\orchestrator_run.py validate
.venv\Scripts\python.exe scripts\orchestrator_run.py run --profile <profile_id> --full
.venv\Scripts\python.exe scripts\orchestrator_run.py prompt --profile <profile_id> --task narrative_cut_review --write
.venv\Scripts\python.exe scripts\orchestrator_run.py prompt --profile <profile_id> --task narrative_cut_review --dispatch
.venv\Scripts\python.exe scripts\orchestrator_llm_dispatch.py --profile <profile_id> --task narrative_cut_review
.venv\Scripts\python.exe scripts\orchestrator_auto_editor.py --profile <profile_id> --dry-run
```

Installed CLI:

```powershell
resolve-orchestrator
```

## What It Models

`config/orchestrator_workflows.json` defines:

- project profiles: concrete project paths and parameters
- tools: reusable command templates
- workflows: ordered deterministic, review, and LLM-prompt steps that call tools
- LLM tasks: why an LLM is needed, inputs, output contract, and handoff paths
- review surfaces: currently an FCPXML segment table with keep/cut/manual_fit
  decisions

The GUI keeps every configured workflow step visible. Steps are colored by
project status:

- green: all declared outputs exist
- orange: required inputs are missing
- blue: running
- red: failed
- neutral: ready

Use `Run / Redo Selected` to rerun any selected step. Use `Redo From Selected`
to rerun the selected step plus later full-run downstream steps. Manual-only
review gates are not forced unless they are explicitly selected.

Full workflow runs skip completed output-producing steps, so interrupted runs
can be restarted without replaying finished work. Use selected-step redo when a
specific step must be regenerated.

Use `Review Outputs` on a workflow step or `Review Selected` on the Artifacts
tab to inspect generated files. FCPXML artifacts open in the FCPXML segment
review table, HTML review pages open directly, and JSON/text artifacts open in a
read-only preview window.

The Gen 1 RBY Ultra Minimum Battles workflow shape is:

1. Run or reuse the auto-editor dialogue pass that produces the raw FCPXML.
2. Build a lightweight V1/A1 review base.
3. Generate the narrative LLM packet and deterministic cut candidates.
4. Stop for the cut-decision review surface.
5. Compile approved source-time cuts.
6. Rerun faster-whisper and audit final-base FCPXML A1 sections for dialogue.
7. Extract any source audio needed by assembly.
8. Launch Resolve only for one final assembly step that builds the completed
   timeline with approved cuts, visual holds, Gen 1 intros, BGM/game audio,
   carousel layout, and validation-ready structure.
9. Apply the configured Fairlight preset, then write a Computer Use handoff for
   Resolve's manual track/audio normalization command.

The catalog also includes reusable templates for:

- `irl_review_first`: IRL/general A-roll videos. No Pokemon assets, no battle
  detection, no BGM/battle-audio automation. Uses timeline clip dump,
  transcription, waveform QA, HTML review, IRL narrative LLM packets, Fairlight,
  and render.
- `pokemon_gym_leader_challenge`: standard Pokemon Gym Leader Challenge or solo
  challenge videos. Uses intro/outro asset import, battle detection, FCPXML
  battle gaps, battle type/rival starter LLM dispatch, V2 battle intro overlays,
  A2 BGM/battle audio, fades, member carousel, Fairlight, and render.
- `gen1_rby_umb_review_first`: the current Ultra Minimum Battles shape. Uses
  review-first cuts, one Resolve final-assembly pass, Gen 1 non-boss gap policy,
  a final fresh-Whisper A1/FCPXML dialogue audit, discrete 2x Gen 1 leader
  intros, Fairlight preset application, and a Computer Use normalization
  handoff.

## Customizing Workflows

Add a project profile for each video and point it at a workflow id. Use
`paths` and `parameters` for project-specific values. Workflow tools and
commands can reference:

- `{repo}`
- `{python}`
- `{project_dir}`
- `{codex_dir}`
- any key in the profile's `paths` or `parameters`

A Gen 1 RBY UMB profile normally sets:

```json
"parameters": {
  "pipeline_script": "scripts/run_rby_umb_pipeline.py",
  "carousel_max_candidates": 30,
  "post_intro_gap_sec": 1.0,
  "fairlight_preset": "Standard Gameplay youtube",
  "fairlight_preset_type": "CONSOLE_FLEXI",
  "audio_normalization_target_db": -9.0
}
```

The workflow then uses a generic tool:

```json
{
  "tool": "profile_pipeline_stage",
  "args": {"stage": "final-assembly"},
  "requires_resolve": true
}
```

That expands to:

```powershell
.venv\Scripts\python.exe scripts/run_rby_umb_pipeline.py --stage final-assembly
```

Only finish steps that touch the Resolve project should set
`"requires_resolve": true`. Earlier steps must write FCPXML, manifests, prompt
packets, decisions, audio extracts, and other source/remap metadata without
opening Resolve. When a `requires_resolve` step runs, the runner launches
Resolve if needed, loads or creates the profile's Resolve project, and then runs
the command. The assembly command is responsible for creating/importing the final
timeline, so no temporary review timeline is created during bootstrap.

This keeps sequencing, gating, status, LLM dispatch, stage cache records, and
manual cut-decision pauses inside the reusable RBY UMB runner. A future project
should keep `pipeline_script` pointed at
`scripts/run_rby_umb_pipeline.py` and change profile paths/parameters for the
source media, dialogue audio, session log, source start, structural cut ranges,
assets, and artifact outputs.

Every workflow step must resolve to a Python-backed command. Check this with:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py validate
```

The validator checks:

- every workflow step has a `tool` or direct `command`
- every referenced tool exists
- every tool command is Python-backed
- every configured profile expands all of its workflow steps into commands

## Tool Dependencies

The GUI checks local tooling at startup and through the `Check Tools` button.
If a required tool is missing, it shows an install dialog with the command and
can run the command after confirmation.

Current checks:

- Codex CLI, required for automatic LLM dispatch:
  `npm install -g @openai/codex`
- auto-editor, required for auto-editor FCPXML generation in the active Python:
  `.venv\Scripts\python.exe -m pip install auto-editor`
- VS Code CLI, optional but useful for opening prompt/output files:
  install VS Code and enable the `code` command on PATH

The CLI scripts also fail with the same actionable command if the dependency is
missing.

## Auto-Editor Tab

The Auto-Editor tab exposes the repeatable settings that affect the raw dialogue
spine:

- input media/audio, usually the extracted dialogue WAV
- raw FCPXML output path
- export mode, usually `final-cut-pro`
- margin, edit expression, when-normal action, when-silent action
- frame rate
- preview mode and extra raw auto-editor args

`Preview` runs auto-editor with `--preview`. `Run Auto-Editor` writes the
configured raw FCPXML. `Review FCPXML` opens the output in the FCPXML segment
review tab.

For game/challenge variants, create a new workflow or duplicate an existing one
and change its `tooling`, `steps`, and `llm_tasks`. Examples:

- Gen 1 Red/Blue/Yellow UMB: `battle_gap_mode=fcpxml_non_boss_only`,
  `leader_intro_mode=gen1_discrete_v2_2x`
- ordinary Gen 2 projects: use battle gaps for all detected first-time trainer
  battles and Gen 2 rival/gym intro selection
- non-Minimum Battles: run the minimum-battles classifier before intro/outro so
  intro speed can be selected deterministically

## Adding A New Profile

Use the GUI `Projects > New` button for normal project creation. It asks for the
project/source folder first, then runs:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_detect_project.py --project-dir "E:\New Project"
```

The detector scans source media in that folder and matches it against
`%APPDATA%\rbypc-frontend\logs\*/events.json` plus `meta.json`. When a matching
RBYNewLayout log exists, the GUI creates the profile without asking for manual
fields and fills:

- `project_dir`, `codex_dir`
- `workflow_id`, `game_version`, `challenge_type`
- `source_media`, `source_name`
- `session_dir`, `session_events`, `session_meta`, `session_started_at`

Manual entry is only used when the detector returns `needs_manual=true`, meaning
no matching log was found for that folder.

Minimum profile shape after detection/manual fallback:

```json
{
  "id": "new_project_id",
  "name": "New Project Name",
  "workflow_id": "gen1_rby_umb_review_first",
  "game_version": "pokemon_red_blue",
  "challenge_type": "ultra_minimum_battles",
  "project_dir": "E:/New Project",
  "codex_dir": "{project_dir}/CODEx",
  "parameters": {
    "pipeline_script": "scripts/run_rby_umb_pipeline.py",
    "timeline_fps": 60
  },
  "paths": {
    "candidate_manifest": "{codex_dir}/cut_review/cut_candidates.json",
    "narrative_prompt": "{codex_dir}/cut_review/narrative/review.in.md",
    "narrative_clip_index": "{codex_dir}/cut_review/narrative/clip_index.json",
    "narrative_output": "{codex_dir}/cut_review/narrative/review.out.json",
    "waveform_candidates": "{codex_dir}/cut_review/waveform_candidates.json",
    "ngram_candidates": "{codex_dir}/cut_review/ngram_candidates.json",
    "artifact_candidates": "{codex_dir}/cut_review/artifact_candidates.json",
    "programmatic_candidates": "{codex_dir}/cut_review/programmatic_candidates.json",
    "approved_narrative": "{codex_dir}/cut_review/approved_narrative_cuts.json",
    "approved_source_cuts": "{codex_dir}/cut_review/approved_source_cuts.json"
  }
}
```

If the stage scripts are already generic, skip a per-project pipeline script and
create workflow steps that call those tools directly. Keep project-specific
paths and flags in `parameters` so the workflow remains portable.

## Content-Type Parameters

Common profile parameters used by the templates:

- `workflow_config`: usually `{repo}/config/orchestrator_workflows.json`
- `timeline_fps`: usually `60`
- `source_media`: source video/audio for transcription
- `dialogue_audio`: WAV/dialogue track used by waveform review
- `whisper_model`: e.g. `large-v3-turbo` or `medium.en`
- `video_track`: usually `1`
- `clips_json`, `review_clips_json`, `categories_json`, `html_clips`,
  `html_segmap`, `html_decisions`: cut-review artifacts
- `review_fcpxml`, `fcpxml_review_artifact`,
  `fcpxml_review_decisions`: FCPXML segment-review artifacts

Pokemon/Gym Leader parameters:

- `game_key`: asset catalog key such as `pokemon_crystal`
- `input_fcpxml`, `battle_gaps_fcpxml`, `battles_json`, `transcript_json`
- `battle_gap_frames`: usually `60`
- `import_to_resolve_flag`: `--import-to-resolve` or empty
- `battle_intro_overlap_sec`: usually `5`
- `carousel_marker_names`: e.g. `Member Carousel Start,Member Carousel`
- `rival_track_arg`, `rival_track`, `gym_track_arg`, `gym_track`,
  `other_track_arg`, `other_track`: optional battle-audio overrides

Gen 1 Ultra Minimum Battles parameters:

- `pipeline_script`: normally `scripts/run_rby_umb_pipeline.py`
- `carousel_max_candidates`: visual candidates checked after the last battle
- `review_fcpxml`: optional exported review FCPXML for section review
- `post_intro_gap_sec`: expected duration between the source timeline markers
  `Intro Hold Gap Start`/`Intro Gap Start` and `Gameplay Start`; defaults to
  `1.0` and is validated against the marker interval
- `fairlight_preset` and `fairlight_preset_type`: Fairlight preset applied
  after the final timeline is assembled
- `audio_normalization_target_db`: target level written into the Computer Use
  normalization handoff; defaults to `-9.0`
- `a1_dialogue_audit_report`: fresh-Whisper report for final-base FCPXML A1
  sections that contain no recognized dialogue
- `source_start_sec` and `source_start_reason`: optional source-time trim before
  the run begins
- `structural_source_cuts`: optional locked/structural source-time ranges that
  must still flow through review before becoming approved cuts
- `pipeline_cache_dir`: optional override for per-stage cache/checkpoint JSON;
  defaults to `{codex_dir}/orchestrator_cache`
- `pipeline_stop_report`: optional override for missing-data stop reports;
  defaults to `{codex_dir}/orchestrator_stop.json`

Cut-candidate policy:

- Build the broad narrative LLM prompt first and dispatch it through the
  orchestrator LLM step.
- After LLM feedback exists, run deterministic waveform, n-gram, and
  artifact/short-clip detectors.
- Compile all suggestions through the FCPXML section-safety policy.
- High-confidence candidates are auto-cut only when they remove complete
  auto-editor/FCPXML sections.
- Medium-confidence candidates are sent to the HTML/manual review surface.
- Low-confidence candidates are not cut; final Resolve assembly adds Pink
  timeline markers for them.

For Gen 1 Red/Blue/Yellow UMB workflows, the tooling policy remains:

- non-boss battle gaps only
- leader/E4/champion fights handled by discrete intro insertion
- leader intros inserted as 2x retimed video/audio clips
- the structural intro/outro step derives the post-intro gameplay gap from the
  source timeline markers `Intro Hold Gap Start`/`Intro Gap Start` and
  `Gameplay Start`
- after approved cuts compile, `a1-dialogue-audit` reruns faster-whisper and
  stops the workflow if any final-base FCPXML A1 clip has no overlapping
  recognized dialogue
- if A1 overlaps the marker interval, the marker-derived insert creates the
  silent A1 gap and shifts markers at/after the insert point; V1 bridges the
  inserted second with the intro-card hold, then the first post-gap V1 clip is
  extended left by the same duration so it starts with the shifted A1 dialogue
  section; `intro_outro_report` records the marker mapping, gap bounds, and V1
  bridge events
- the Fairlight preset is applied after clip coloring; the next step writes a
  handoff telling the Codex agent to use Computer Use to unlock A2 if needed,
  drag-select all audio clips only, right-click the center/body of the longest
  visible selected A2 clip, choose `Normalize Audio Levels...`, and click
  `Normalize`
- review, cut, hold, audio, and layout decisions collected as metadata before
  the single Resolve final-assembly pass
- if required assets or marker-derived data are unavailable, stop and ask the
  user whether to provide/fix the data, update the profile path, or explicitly
  approve a fallback

## LLM Dispatch Flow

The LLM tab can generate a prompt packet or run the selected LLM task directly.
The packet includes the task reason, shared instructions, prompt text, expected
output path, and JSON contract. The GUI never applies LLM output directly; the
output is reviewed and saved into approved-cut artifacts before deterministic
scripts consume it.

When a workflow run reaches an `llm_prompt` step, the orchestrator writes the
packet, opens/reuses Code with the prompt and expected output file when
`llm_open_code_workspace=true`, sends the prompt through Codex CLI when
available, and confirms that the expected output artifact exists and satisfies
the configured JSON contract. The generated packet is written next to the source
prompt as `*.llm_packet.md`, so script-generated `.in.md` prompts are not
overwritten.

Dispatch profile parameters:

- `llm_dispatch_mode`: `auto`, `codex_cli`, or `code_workspace`. `auto` prefers
  Codex CLI and falls back to a Code workspace wait.
- `llm_open_code_workspace`: opens/reuses Code with the prompt and output file
  for visibility.
- `llm_timeout_sec`: maximum wait for Codex CLI or Code-workspace feedback.
- `llm_model`: optional Codex model override. Empty means use the Codex default.

The automatic path runs:

```powershell
codex --ask-for-approval never exec --cd C:\Programming\resolve-mcp --sandbox read-only --output-last-message <raw-output> -
```

The orchestrator feeds the packet on stdin, reads Codex's final response, strips
Markdown fences if present, validates the expected JSON array/object shape, and
writes the normalized feedback to the configured `output_path`.

The LLM/review steps are also script-backed:

- `scripts/orchestrator_prompt_packet.py`
- `scripts/orchestrator_llm_dispatch.py`
- `scripts/orchestrator_fcpxml_review.py`

LLM-needed cases currently listed in the catalog:

- narrative cut review
- minimum-battles classification
- first-time battle detection
- battle type classification
- rival starter/location classification
- battle-end visual refinement
- member carousel visual detection
- BGM library classification

## FCPXML Segment Review

The FCPXML Review tab loads an FCPXML and displays video-backed `asset-clip`
segments. Select rows and mark them:

- `keep`: no exported decision
- `cut`: safe only when the downstream tool knows how to remove that full
  segment
- `manual_fit`: partial or uncertain cuts that should be handled by a stricter
  editor tool or human Resolve pass

Export writes `resolve_fcpxml_segment_decisions_v1`, which is intentionally a
decision artifact rather than an immediate timeline mutation.

## Artifact Status

The GUI's Artifacts tab and the CLI `status` command are driven by the same
workflow metadata. Required missing inputs show a step as `missing`; existing
outputs show a step as `done`. This is intentionally lightweight and does not
replace each stage script's deeper audit.
