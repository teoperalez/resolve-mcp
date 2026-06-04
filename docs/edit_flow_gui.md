# Resolve Edit Flow GUI

`scripts/edit_flow_gui.py` is a Tkinter front end for the review-first editing
pipeline. It is profile driven: each video/project workflow lives in
`config/edit_flow_profiles.json`, and the GUI runs the configured commands,
pauses at the narrative-cut handoff, collects decisions, then resumes the
deterministic build steps.

## Launch

From `C:\Programming\resolve-mcp`:

```powershell
.venv\Scripts\python.exe scripts\edit_flow_gui.py
```

Or double-click:

```text
scripts\launch_edit_flow_gui.cmd
```

Or run the built executable:

```text
bin\ResolveEditFlow.exe
```

If the package is installed in the venv, this also works:

```powershell
resolve-edit-flow-gui
```

The GUI checks Resolve on startup. If it cannot connect, open DaVinci Resolve
Studio and confirm **Preferences -> General -> External scripting using ->
Local**.

## Build The Executable

```powershell
uv sync --extra gui-build
.venv\Scripts\python.exe scripts\build_edit_flow_exe.py
```

The executable is written to `bin\ResolveEditFlow.exe`. It is a launcher for
this repo's workflow: keep it inside the repo so it can find `config\`,
`scripts\`, and `.venv\Scripts\python.exe`.

## Current Workflow

The initial bundled profile is `Mewtwo RBY UMB Redo`.

1. Click **Prepare Cuts**.
   This runs the lightweight review-base build and generates:
   - the narrative LLM prompt
   - the clip index/transcript mapping
   - waveform auto/review candidates
   - the browser waveform review artifacts

2. Click **Open Prompt** or **Copy Prompt**.
   Give that prompt to the LLM. The GUI also writes a compact handoff bundle at:
   `CODEx/cut_review/llm_handoff.json`.
   The handoff bundle includes the stable LLM contract from
   `docs/edit_flow_llm_instructions.md`.

3. Paste the LLM's raw JSON array into **Paste LLM Cut JSON**, then click
   **Parse Into Table**.

4. Review the candidate table.
   - `llm` candidates come from the pasted LLM output.
   - `auto` candidates come from waveform QA and default to `CUT`.
   - `review` candidates come from waveform QA and default to `KEEP`.
   Double-click or use the decision buttons to flip selected rows.

5. Click **Save Decisions**.
   The GUI writes:
   - the raw LLM rows to the configured narrative output file
   - accepted LLM/auto source-time cuts to the approved-cuts input consumed by
     the pipeline
   - Pink waveform decisions to `pink_decisions.json` for
     `apply_cut_review_decisions_native.py`
   - a sidecar decision audit JSON beside the approved-cuts file

6. Click **Continue Build**.
   The GUI runs the configured finish steps in order and streams output into the
   log panel. Optional/skip-gated steps are skipped when their input artifacts
   are missing.

   For the Mewtwo profile, the `final-base` step is the visual-hold rebuild:
   `build_mewtwo_rby_fcpxml.py` derives/loads `mewtwo_hold_regions.json` and
   applies V1-only holds for intro cards, post-battle data cards, and the final
   tierlist while leaving A1 as the approved dialogue spine.

## Profile Format

Profiles live in `config/edit_flow_profiles.json`.

Important fields:

- `project_dir`, `codex_dir`: base folders for the project.
- `paths`: named artifacts. Values can reference `{repo}`, `{python}`,
  `{project_dir}`, `{codex_dir}`, and other path keys.
- `html_reviews`: waveform review pages and their `pink_decisions.json`
  destinations.
- `prepare_steps`: commands run before the LLM pause.
- `finish_steps`: commands run after decisions are saved.

Commands are arrays, not shell strings. They run from the repo root, so relative
script paths like `scripts/run_mewtwo_rby_umb_pipeline.py` are fine.

Use `skip_unless_all_exist` on a step to skip it unless named path artifacts
exist. Use `optional: true` if a failing step should log the failure and allow
later steps to continue.
