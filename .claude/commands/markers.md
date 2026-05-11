Find gaps in A1 longer than N frames and place red markers at the end of each gap on both the timeline ruler and the V1 clip at that position.

Run this command via the Bash tool:
```
cmd.exe /c "C:\Programming\resolve-mcp\.venv\Scripts\python.exe C:\Programming\resolve-mcp\scripts\mark_audio_gaps.py $ARGUMENTS"
```

If `$ARGUMENTS` is empty, the default minimum gap is 5 frames. The user can pass a number like `30` to mark only larger gaps.

IMPORTANT — marker frame convention:
`TimelineItem.AddMarker()` requires an ABSOLUTE SOURCE FRAME: `clip.GetLeftOffset() + (gap_end - clip.GetStart())`.
The script handles this correctly. Do NOT use timeline-relative offsets — they land before the clip's in-point and are invisible.

Report the count of gaps found, their timeline frame positions, and whether both the timeline ruler and V1 clip markers were placed successfully.
