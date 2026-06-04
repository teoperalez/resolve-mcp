@echo off
setlocal
cd /d "%~dp0\.."
".venv\Scripts\python.exe" "scripts\edit_flow_gui.py"
