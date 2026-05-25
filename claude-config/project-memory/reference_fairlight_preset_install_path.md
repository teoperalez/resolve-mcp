---
name: Fairlight preset filesystem location + scripting API
description: Where Resolve stores Fairlight mixer presets on disk, what subfolder corresponds to which preset type, and the scripting API that applies them
type: reference
originSessionId: fdcb3861-fc35-47c6-990f-ddc3ccd0f436
---

DaVinci Resolve stores Fairlight presets as `.dat` files under the Preferences directory, in subfolders keyed by preset TYPE:

- **Windows:** `%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences\Fairlight\Presets\<TYPE>\<Name>.dat`
- **macOS:** `~/Library/Preferences/Blackmagic Design/DaVinci Resolve/Fairlight/Presets/<TYPE>/<Name>.dat`
- **Linux:** `~/.config/Blackmagic Design/DaVinci Resolve/Fairlight/Presets/<TYPE>/<Name>.dat`

**Preset type subfolders observed:**
- `CONSOLE_FLEXI/` — Fairlight Configuration Presets (the full mixer state: track FX, levels, routing, bus structure). What you save via Mixer → Preset Library → Save New with filter "Fairlight Configuration Presets".
- `AUTOMIX/`, `DYN/`, `EQ/`, `BatchFades/`, `MacroFX/` — narrower preset types per Fairlight feature.

**Scripting API:**
`Project.ApplyFairlightPresetToCurrentTimeline(name: str) -> bool` takes the preset NAME (no `.dat`, no subfolder) and applies it to whatever timeline is current. Returns True on success. There is NO corresponding "save preset" API — saving is UI-only. There is also NO API for `NormalizeAudio` (Edit/Fairlight clip context-menu feature). Both must be done in the UI.

**Travel-with-the-repo pattern:** copy the `.dat` file into `assets/fairlight-presets/<TYPE>/<Name>.dat` in the repo. A script (`scripts/apply_fairlight_preset.py` in resolve-mcp) syncs the repo file into the platform-specific Presets dir on first run, then calls `ApplyFairlightPresetToCurrentTimeline`. Resolve typically picks up newly-copied preset files immediately without a restart, but if `Apply` returns False after a fresh install, restart Resolve once and re-run.
