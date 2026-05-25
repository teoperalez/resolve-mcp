---
name: Fusion node IDs are not their UI labels
description: Always probe live Fusion via comp.AddTool/GetInputList to discover real RegIDs and input names — guessing from the Inspector or from tutorial transcripts will fail silently
type: feedback
originSessionId: 03124662-4e82-4cf2-9a70-a5e12df6cf17
---
When generating Fusion `.setting` macros (or driving comps via `execute_resolve_code`), **never guess node RegIDs or input names from a tutorial transcript or the Inspector UI label**. Resolve fails silently — `comp.AddTool("DropShadow")` returns `None` instead of raising, and macros with bad RegIDs install but don't appear in the Effects Library.

**Always probe first** by adding the candidate tool to a live Fusion comp and reading its `GetInputList()`:

```python
t = comp.AddTool(candidate_regid, -50, -50)
if t:
    print('OK regid=', t.GetAttrs().get('TOOLS_RegID'))
    for k, inp in t.GetInputList().items():
        a = inp.GetAttrs()
        print(f"  {a.get('INPS_ID'):30} | {a.get('INPS_Name')}")
    t.Delete()
```

Confirmed mismatches (UI/tutorial → real RegID + real input name):

| UI / tutorial says | Real RegID | Real input name |
|---|---|---|
| "Drop Shadow" | `Shadow` | `LightDistance` (not `DropDistance`), `Softness` (not `Blur`) |
| "Lens Blur" | `Defocus` | `XDefocusSize` + `LockXY=1` (not `BlurSize`) |
| "Duplicate" | `Trails` | `NumberOfPrerollFrames` + `GainRed` (Duplicate3D exists but is 3D-only — won't sit in a 2D pipeline) |
| "Glow Size" | `Glow` | `XGlowSize` + `LockXY=1` (not `GlowSize`) |
| "PTR Speed" / "Border Type" | `CameraShake` | `Speed`, `OverallStrength`, `Edges` (not `PTRSpeed`/`BorderType`) |
| Lua boolean `Loop = true` | `Loader` | `Loop = 1` (numeric, not Lua boolean) |

**Why:** the Inspector panel shows display names (e.g. "Drop Distance"), Fenn-style YouTube tutorials reference UI labels, but the macro syntax requires the underlying `INPS_ID`. The Reactor-bundled macros at `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Reactor\Deploy\Macros\` are good reference for canonical syntax, but they cover a small slice of nodes — many you'll need (Shadow, Defocus, Trails, etc.) aren't covered there.

**How to apply:** before writing any new `.setting` template or `execute_resolve_code` chunk that names tools/inputs, run a short probe in the live `logo-flip-fusion-test` timeline (or any Fusion comp clip). Cache the discovered names in the script as constants so future iterations don't have to re-probe.
