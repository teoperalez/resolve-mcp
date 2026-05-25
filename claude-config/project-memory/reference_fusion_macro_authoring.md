---
name: Authoring Fusion .setting macros for the Edit Effects panel
description: Format and patterns for writing reusable Fusion macros that appear in the Edit page Effects panel under a category. Built from authoring StatCalloutHighlight.setting for stat/move callout highlights on Misty Red.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## Install location

`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Effects\<Category>\<MacroName>.setting`

For IRLPC project: `Templates/Edit/Effects/IRLPC/<Name>.setting`

**Requires Resolve restart** to register in Effects panel (per existing memory `reference_fusion_macro_install_path.md`). `comp.Paste()` is NOT a macro loader — there's no scripting API to register a macro mid-session.

## File format

Lua-like text format. Top-level structure:

```lua
{
    Tools = ordered() {
        MacroName = MacroOperator {
            CtrlWZoom = false,
            NameSet = true,
            CustomData = { HelpPage = "" },
            Inputs = ordered() {
                MainInput1 = InstanceInput { SourceOp = "InternalToolName", Source = "Input", Name = "Input" },
                ExposedControl = InstanceInput {
                    SourceOp = "InternalTool",
                    Source = "ParamName",
                    Name = "User-Visible Label",
                    Page = "Controls",
                    Default = 0.5,
                    MinScale = 0.0,
                    MaxScale = 1.0,
                },
                ...
            },
            Outputs = ordered() {
                MainOutput1 = InstanceOutput { SourceOp = "FinalTool", Source = "Output" },
            },
            ViewInfo = GroupInfo { Pos = { 0, 0 }, ... },
            Tools = ordered() {
                InternalTool1 = ToolType {
                    Inputs = {
                        ParamName = Input { Value = X },
                        OtherParam = Input { SourceOp = "OtherTool", Source = "OutputOrParam" },
                    },
                    ViewInfo = OperatorInfo { Pos = { 0, 0 } },
                },
                ...
            },
        }
    },
    ActiveTool = "MacroName"
}
```

Key points:
- `MacroOperator` wraps the whole thing
- `Inputs` block declares the macro's exposed parameters (what shows up in Inspector)
- Each `InstanceInput` binds to a specific internal tool's parameter via `SourceOp` + `Source`
- `Outputs` block declares the macro's outputs
- `Tools` block (inside MacroOperator) is the actual node graph
- Internal tools reference each other via `SourceOp` (name from the Tools block) + `Source` (output name like "Output" or input/param name)

## Probe before writing

**Always probe Fusion node IDs first** (per `feedback_fusion_node_ids.md`). Tutorial labels lie. Use:

```python
import DaVinciResolveScript as dvr
r = dvr.scriptapp('Resolve')
comp = r.Fusion().NewComp()
tool = comp.AddTool('CandidateName', 0, 0)  # returns None if invalid
# Inspect:
print(tool.GetAttrs())              # TOOLS_RegID = canonical name
for k, v in tool.GetInputList().items():
    print(k, v.GetAttrs().get('INPS_Name'))   # input names
comp.Close()
```

Confirmed canonical IDs (Resolve 19/20):
- `RectangleMask` — rectangle/rounded shape mask. Inputs: `Center`, `Width`, `Height`, `CornerRadius`, `Angle`, `Solid` (0=hollow outline, 1=filled), `BorderWidth`, `Soft Edge`, `Paint Mode`, `MaskWidth`/`MaskHeight` (output canvas size)
- `BSpline` — free-form spline mask
- `PolylineMask` — polygon mask (RegID, NOT "Polygon")
- `BitmapMask` — alpha-from-image mask
- `BrightnessContrast` — color adjustment. Inputs: `Gain`, `Brightness`, `Contrast`, `Gamma`, `EffectMask`
- `Background` — solid color generator. Inputs: `TopLeftRed`/`Green`/`Blue`/`Alpha` (also TopRight/BottomLeft/BottomRight for gradients), `UseFrameFormatSettings`, `Width`, `Height`, `EffectMask`
- `Merge` — composite. Inputs: `Background`, `Foreground`, `Blend`
- `ChannelBoolean` — channel math
- `Glow` — soft glow

NOT valid node types (despite Fusion UI showing them): `Polygon`, `Dilate`, `Erode`, `BorderMask`. Find equivalents via probing.

## Patterns

### Sharing parameters between two nodes

For two RectangleMask nodes that should track the same Center/Width/Height (e.g. inner-fill + border-ring sharing the same shape), connect via `SourceOp`/`Source`:

```lua
BorderMask = RectangleMask {
    Inputs = {
        Center = Input { SourceOp = "InnerMask", Source = "Center" },
        Width = Input { SourceOp = "InnerMask", Source = "Width" },
        Height = Input { SourceOp = "InnerMask", Source = "Height" },
        Solid = Input { Value = 0 },        -- differ in solid vs hollow
        BorderWidth = Input { Value = 0.004 },
    },
}
```

The user-exposed control then targets the SOURCE (InnerMask.Center), and the dependent (BorderMask.Center) follows automatically.

### Yellow border around a region

```
RectangleMask "InnerMask" (Solid=true)  →  BrightnessContrast (EffectMask=InnerMask)
RectangleMask "BorderMask" (Solid=false, BorderWidth=0.004, shape shared from InnerMask)
                                        →  Background (yellow, EffectMask=BorderMask, UseFrameFormatSettings=true)
Merge: BG=BrightnessContrast.Output, FG=Background.Output → MediaOut
```

### Brightness boost inside masked region

`BrightnessContrast` with `EffectMask` connected to the mask. `Gain = 1.20` for +20% brightness on the masked pixels only.

### Yellow background painted only on a ring

`Background` with `TopLeftRed/Green/Blue/Alpha` = (1, 0.9, 0, 1). Set `UseFrameFormatSettings = 1` so the background auto-sizes to the comp resolution. Then `EffectMask` connected to the ring mask makes the yellow visible only where the mask is white.

## Programmatic alternative (per-clip Fusion comp, no macro restart)

If you don't want to wait for restart, build the same node graph directly on a clip via:

```python
fc = clip.AddFusionComp()           # creates a new comp with MediaIn1, MediaOut1
tools = fc.GetToolList(False)        # discover existing nodes
mi = next(t for k,t in tools.items() if t.GetAttrs()['TOOLS_RegID']=='MediaIn')
mo = next(t for k,t in tools.items() if t.GetAttrs()['TOOLS_RegID']=='MediaOut')

inner = fc.AddTool('RectangleMask', x, y)
inner.SetInput('Center', [0.5, 0.5])
inner.SetInput('Width', 0.2)
inner.SetInput('Height', 0.1)

bc = fc.AddTool('BrightnessContrast', x+1, y)
bc.SetInput('Gain', 1.2)
bc.ConnectInput('Input', mi)
bc.ConnectInput('EffectMask', inner)

# ... etc

mo.ConnectInput('Input', merge)
```

`SetInput(name, value)` for scalars, `SetInput(name, [x,y])` for points. `ConnectInput(name, otherTool)` to wire up. `SetAttrs({'TOOLS_Name': 'NewName'})` to rename a node.

**Warning:** repeated comp-building operations can crash Resolve. After ~2-3 large comp builds, Resolve may disconnect. Workaround: smaller batches, add sleep between operations, or save and reopen Resolve between batches.

## Macro coords reference (Fusion normalized)

- Center: `[x, y]` where x=0 is left edge, x=1 is right edge; y=0 is BOTTOM, y=1 is TOP (inverted from screen pixels)
- 0.5, 0.5 = center of frame
- Width/Height: 0-1, fraction of frame width/height
- BorderWidth: small value (~0.003-0.008) for thin border, in normalized units

## Confirmed working example

`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Effects\IRLPC\StatCalloutHighlight.setting` (Misty Red 2026-05-15). Used as canonical reference for future highlight macros (HP-bar focus, move-tag callout, etc.) — duplicate, adjust node graph and inputs as needed.
