---
name: verify-fairlight-preset
description: Verify the Fairlight mixer preset (default "Standard Gameplay youtube") is applied to the current Resolve timeline. If missing, apply it AND save the project so it persists across Resolve restarts. Use BEFORE any render, BEFORE handing the timeline off for delivery, or anytime the user says "check the Fairlight preset", "verify the audio mix", "is the Fairlight preset applied", "make sure Fairlight is set up before rendering". Catches the silent failure mode where ApplyFairlightPresetToCurrentTimeline returns True but SaveProject was never called, so a Resolve crash loses the preset.
---

# verify-fairlight-preset

Idempotent verification skill. Returns one of:

- **APPLIED_AND_SAVED** — preset is on timeline + project saved. Safe to render.
- **APPLIED_BUT_UNSAVED** — preset is on timeline but `pm.SaveProject()` failed. Render will work in this session, but a Resolve crash before save loses the preset. Surface to user.
- **MISSING_NOW_APPLIED** — preset was not on timeline; this skill applied it + saved. Safe to render.
- **MISSING_CANNOT_APPLY** — preset was not on timeline AND apply failed (preset .dat missing from Resolve dir, API rejected, etc.). Surface diagnostic + halt render.

## Why this skill exists

Trigger event (Brock Red v3, 2026-05-22): `apply_fairlight_preset.py` reported `Result: True` and the script exited. The user assumed the preset persisted. It didn't — `pm.SaveProject()` was never called, then Resolve crashed before the next operation auto-saved, then on reopen the preset was gone. The 4K render shipped without the Fairlight FX chains + level routing — bad audio mix.

## Detection signature

The "Standard Gameplay youtube" preset (and any similar 3-track-named preset) changes the timeline in three observable ways:

1. **A1 track name** changes from `Audio 1` → `Dialogue 1` (or any name containing "Dialogue")
2. **A2 track name** changes from `Audio 2` → `Music 1` (or any name containing "Music")
3. **A2 is locked** (lock prevents accidental edits to the music bed)
4. **Track count** increases from 5 to 9 (preset adds A4-A9 as empty utility tracks)

Detection rule (all must be true):
- A1 track name matches regex `(?i)dialogue`
- A2 track name matches regex `(?i)music`
- A2 `GetIsTrackLocked('audio', 2)` returns `True`

If any check fails → preset is NOT applied.

## Inputs

Optional CLI args (none required; sensible defaults):
- `--preset <NAME>` — preset to verify/apply (default: `Standard Gameplay youtube`)
- `--type <TYPE>` — preset type subfolder (default: `CONSOLE_FLEXI`)
- `--timeline <NAME>` — switch to this timeline first (default: current)
- `--apply-if-missing` — if check fails, auto-apply (default: ON; pass `--no-apply` to verify-only)
- `--save-after-apply` — save project after successful apply (default: ON; pass `--no-save` to skip)
- `--verbose` — print track-by-track detection results

Exit codes:
- 0 → APPLIED_AND_SAVED or MISSING_NOW_APPLIED
- 1 → APPLIED_BUT_UNSAVED (warning)
- 2 → MISSING_CANNOT_APPLY (hard fail)

## Workflow

### Step 1 — Connect to Resolve + get current timeline

Fail fast if Resolve isn't running or no timeline is current.

### Step 2 — Run detection

For each of the 3 signature checks (A1 dialogue, A2 music, A2 locked), record pass/fail. Print verbose output if requested.

### Step 3a — All checks pass → return APPLIED_AND_SAVED

The preset is on the timeline. Verify the project is saved (`pm.SaveProject()` returns True) and return.

If SaveProject returns False (rare — Resolve is in a write-blocked state), return APPLIED_BUT_UNSAVED with a warning to the user.

### Step 3b — Any check fails → apply (if --apply-if-missing)

Invoke `apply_fairlight_preset.py` (the existing script under resolve-mcp/scripts/) with the same `--preset` + `--type` + `--timeline` args. Parse its output for `Result: True`.

After successful apply:
1. Re-run detection (Step 2) to confirm the signature is now present
2. Call `pm.SaveProject()` and verify it returns True
3. Return MISSING_NOW_APPLIED on success

If the apply step itself fails (Result: False, preset .dat missing, API exception), return MISSING_CANNOT_APPLY with the diagnostic message.

### Step 4 — Print verdict

```
=== Fairlight Preset Verification ===
Timeline: <name>
Preset: <name>
Result: APPLIED_AND_SAVED | APPLIED_BUT_UNSAVED | MISSING_NOW_APPLIED | MISSING_CANNOT_APPLY

[verbose mode also prints]:
  A1 name: 'Dialogue 1' ✓
  A2 name: 'Music 1' ✓
  A2 locked: True ✓
  Project saved: True ✓
```

## Integration points

### With `scripts/render_timeline.py` (pre-flight gate)

`render_timeline.py` should call this skill BEFORE `AddRenderJob`. If verify returns MISSING_CANNOT_APPLY or APPLIED_BUT_UNSAVED, refuse to render and surface the diagnostic. Pass `--auto-fix-fairlight` to render_timeline.py to enable auto-apply.

### With `/edittimeline` (Step 14.5)

After Step 14 (`apply_fairlight_preset.py`), insert a Step 14.5 invocation of this skill to guarantee the apply persisted. This prevents the Brock Red v3 silent-failure pattern from recurring.

### Standalone use

The user can invoke at any time:
- "verify the Fairlight preset on the current timeline"
- "is Fairlight applied?"
- "check the audio mix is set up before rendering"

## Limitations

- Detection only checks the 3-signature ("Standard Gameplay youtube" pattern). If a different preset is in use that doesn't rename A1/A2 to Dialogue/Music, detection will false-negative. Pass `--preset` to point at the right .dat; for custom presets, update `references/preset-signatures.md` to add new detection rules.
- `pm.SaveProject()` can return False on transient Resolve API states (the "stuck mutations" mode this codebase has hit). If save fails, the apply lasted but isn't durable — re-running this skill after Resolve recovers will re-save cleanly.
- The skill does NOT verify the preset's FX chain content (compressors, EQ, limiters, bus routing) — only the track-name + lock signature. Full content verification would require parsing the .dat file format; out of scope for this skill.

## Files

- `scripts/verify.py` — main entry point
- `references/preset-signatures.md` — detection signatures for known presets
- `references/integration-render-timeline.md` — patch suggestion for `render_timeline.py`
