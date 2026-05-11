Ripple delete clips shorter than N frames from V1 and A1 simultaneously on the active Resolve timeline.

Run this command via the Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\remove_short_clips.py $ARGUMENTS"
```

If `$ARGUMENTS` is empty, the default threshold is 5 frames. The user can pass a number like `10` to use a different threshold.

Report how many clips were ripple deleted and from which tracks. If Resolve is not connected, tell the user to open Resolve and set Preferences → General → External scripting → Local.
