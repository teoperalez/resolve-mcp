# Resolve Orchestrator GUI Shortcut

When the user says "GUI", "the GUI", "orchestrator", or "workflow GUI" in this repo, use the Resolve orchestrator GUI.

Primary launch command from `C:\Programming\resolve-mcp`:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_gui.py
```

Installed entry points exposed by `pyproject.toml`:

```powershell
resolve-orchestrator-gui
resolve-orchestrator
```

Useful CLI checks:

```powershell
.venv\Scripts\python.exe scripts\orchestrator_run.py profiles
.venv\Scripts\python.exe scripts\orchestrator_run.py validate
.venv\Scripts\python.exe scripts\orchestrator_run.py status --profile <profile_id>
```

Docs live at `docs/orchestrator_gui.md`.
