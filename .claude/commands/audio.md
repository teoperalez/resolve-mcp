Clear all clips from audio tracks A2–A5 on the active Resolve timeline.

Run this command via the Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\clear_audio_tracks.py $ARGUMENTS"
```

If `$ARGUMENTS` is empty, the default range A2–A5 is used. The user can pass `3 6` to clear A3–A6, etc.

Report the number of clips removed from each track. If Resolve is not connected, tell the user to open Resolve and set Preferences → General → External scripting → Local.
