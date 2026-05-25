---
name: Resolve marker color names — 'Orange' is INVALID via the scripting API
description: The Resolve UI offers Orange as a marker color, but the Python API silently rejects it. Tested set of valid color strings included
type: reference
originSessionId: fdcb3861-fc35-47c6-990f-ddc3ccd0f436
---

The DaVinci Resolve scripting API accepts 16 specific strings for marker colors. `'Orange'` is NOT in this list — calling `Timeline.AddMarker(frame, 'Orange', name, note, 1, '')` returns False with no other error, even though the UI shows Orange as a valid choice.

**Valid colors (tested on Resolve Studio 21):**

| Color | Vibe |
|---|---|
| Blue | bright blue |
| Cyan | aqua |
| Green | bright green — used for Battle End markers |
| Yellow | bright yellow — used for Member Carousel Start |
| Red | bright red — used for audio gaps |
| Pink | bright pink |
| Purple | bright purple |
| Fuchsia | hot pink |
| Rose | dusty pink |
| Lavender | soft purple |
| Sky | light blue |
| Mint | pale green |
| Lemon | yellow-green |
| Sand | light orange/tan — **use instead of `'Orange'`** for Battle Start markers |
| Cocoa | brown |
| Cream | off-white |

**Invalid (silently rejected):** Orange, White, Black, Gray, Magenta, Brown, anything not in the table above.

**Impact on resolve-mcp scripts that previously used 'Orange':**
- `insert_battle_gaps.py` — Battle Start markers were silently failing. Now uses `'Sand'`.
- `find_member_carousel.py` already uses `'Yellow'` for carousel start (works fine).
- `mark_audio_gaps.py` uses `'Red'` (works).
- `mark_battle_ends.py` uses `'Green'` (works).

When debugging "AddMarker returned False" the FIRST thing to check is the color string, BEFORE assuming collision or frame issues.

The same caveat probably applies to `TimelineItem.AddMarker` (clip markers) and `MediaPoolItem.AddMarker` — but those weren't tested in the same session. Stick to the 16 valid colors for all three.
