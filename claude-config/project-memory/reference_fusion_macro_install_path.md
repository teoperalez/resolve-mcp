---
name: Fusion macro install path + reload mechanics
description: Where user .setting macros live so Resolve picks them up as Edit-page Effects, and how to trigger reload (no scripting API)
type: reference
originSessionId: 03124662-4e82-4cf2-9a70-a5e12df6cf17
---
User-installed Fusion macros that should appear in **Edit page → Effects Library → Effects → <Category> → <Name>** go to:

```
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Effects\<Category>\<Name>.setting
```

(Resolved on this machine: `C:\Users\teope\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Effects\<Category>\<Name>.setting`)

Other relevant install dirs:
- `…\Support\Fusion\Macros\` — generic Fusion macros (Effects Library → Tools tab in Fusion page, not Edit-page Effects)
- `…\Support\Fusion\Templates\Edit\Generators\<Category>\` — Edit-page Generators (Stirling Supply Co's ProtoV2 example lives here)
- `…\Support\Fusion\Templates\Edit\Transitions\<Category>\` — Edit-page Transitions

**Reloading after install — there is no scripting API for this.** You must do one of:
1. Restart Resolve (cleanest)
2. Fusion page → top menu → **Fusion → Reload Macros** (when available in the build)

`comp.Paste(content)` is a clipboard operation, NOT a macro loader — it returns False even for known-good macros (e.g. Star Glow.setting) when called from outside the active Fusion clipboard. Don't use it to validate `.setting` syntax.

**Validation strategy without restart:** parse the file in Python (brace balance, presence of `MacroOperator`, `InstanceInput`, `InstanceOutput`, `ActiveTool`) and probe `comp.AddTool(regid)` for each inner tool to verify RegIDs/input names exist. The live "drag from Effects Library" test is the only ground truth.

**Reactor's bundled macros (read-only, good syntax references):**
- `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Reactor\Deploy\Macros\Blur\Star Glow.setting` — clean MacroOperator + InstanceInput pattern
- `…\Macros\Flow\Billboard.setting` — multi-page Inputs (`Page = "Controls"`)
- `…\Templates\Edit\Generators\Stirling Supply Co\ProtoV2.setting` — example with embedded `BezierSpline` keyframe definitions
