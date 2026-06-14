# Resolve Orchestrator GUI Shortcut

When the user says "GUI", "the GUI", "orchestrator", "workflow GUI", or asks how to run the Mewtwo edit surface in this repo, do not say it is missing. It was restored on `main` in commit `b995aa3` as the Resolve edit orchestrator.

Primary launch command from `C:\Programming\resolve-mcp`:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_gui.py
```

Installed entry points exposed by `pyproject.toml`:

```powershell
resolve-orchestrator-gui
resolve-orchestrator
resolve-edit-flow-gui
```

Useful CLI checks:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py profiles
.venv\Scripts\python.exe scripts\orchestrator_run.py validate
.venv\Scripts\python.exe scripts\orchestrator_run.py status --profile mewtwo_rby_umb_redo
```

Docs live at `docs/orchestrator_gui.md`. The Mewtwo profile is `mewtwo_rby_umb_redo` in `config/orchestrator_workflows.json`.
