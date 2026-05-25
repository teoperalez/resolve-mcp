---
name: /watch skill location for downloading + transcribing YouTube videos
description: The /watch slash command lives in IRLPC Hyperframes — use it to grab + transcribe YouTube tutorials when researching effects (e.g. JB Fenn Fusion videos)
type: reference
originSessionId: 03124662-4e82-4cf2-9a70-a5e12df6cf17
---
The user's `/watch` skill — downloads a YouTube video via yt-dlp, extracts ~80 frames with ffmpeg, transcribes via faster-whisper (local GPU, no API key required), and surfaces frame paths + transcript — lives in the IRLPC Hyperframes project, not in resolve-mcp:

```
C:\Programming\IRLPC Hyperframes\.agents\skills\watch\scripts\watch.py
```

**Invoke from Bash:**
```bash
cd "/c/Programming/IRLPC Hyperframes" && python ".agents/skills/watch/scripts/watch.py" "<URL>"
```

The script writes its working dir + report to a temp directory and prints the path. The report is a markdown file with a list of frame-image paths (`Read` each one to view) and a full transcript. Useful flags: `--start MM:SS --end MM:SS` to focus on a section, `--max-frames N` to lower the cap.

**Reference videos already cached on this machine** (transcript + frames at the temp dirs noted; may be cleaned up):
- JB Fenn — "This Logo Effect Is Super Satisfying" (logo-flip Fusion tutorial): https://www.youtube.com/watch?v=YAh7mc9xyHI
- JB Fenn — pull-through portal transition: https://www.youtube.com/watch?v=Y8H830YPhZY
- JB Fenn — tracked text on walls/ground (planar tracker + corner pin): https://www.youtube.com/watch?v=E12L2bVPAbY
- JB Fenn — AI animation effect (DALL-E frame morph): https://www.youtube.com/watch?v=euKdisDTzF8

**Setup preflight:** `python ".agents/skills/watch/scripts/setup.py" --check` — exit 0 = ready, 2 = need ffmpeg/yt-dlp, 3 = no Whisper API key (faster-whisper local still works, no key required).

**When to reach for /watch from resolve-mcp:** any time the user references a Fusion/DaVinci tutorial by URL or by creator (JB Fenn, Casey Faris, etc.) — watching beats guessing the technique from the title.
