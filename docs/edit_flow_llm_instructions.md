# Edit Flow LLM Instructions

Use these instructions when the GUI pauses for narrative cuts.

## Inputs

The GUI will provide:

- a narrative prompt file (`*.in.md`)
- a clip-index JSON file that maps timeline clips to source times
- transcript path(s)
- an expected output path

Read the full narrative prompt first. It contains the project-specific clip
list, transcript context, source-time rules, and any locked cuts that should not
be returned again.

## Task

Find only strong narrative cut candidates:

- explicit edit notes or restart declarations
- false starts with a cleaner restart
- true repetitions where one delivery is clearly stale or failed
- abandoned narrative threads
- self-corrections where the first phrase is genuinely abandoned
- mid-clip corrections or repeated fragments with clear boundaries

Do not cut:

- useful challenge/game-mechanic explanation
- intentional recap
- natural speaking cadence
- reset count, battle state, or run-context information
- ordinary breaths/clicks/silence unless the prompt explicitly asks for audio
  artifacts

When evidence is weak, leave it out. The GUI is meant to show a small,
defensible list, not a broad maybe pile.

## Output Contract

Return only raw JSON. No Markdown fences, no prose.

Use source times from the prompt, not rendered timeline times.

For single-source projects:

```json
[
  {
    "start_sec": 123.45,
    "end_sec": 126.78,
    "confidence": "medium",
    "type": "repetition",
    "reason": "Earlier failed take is replaced by a cleaner line shortly after."
  }
]
```

For split-source projects, include the source part:

```json
[
  {
    "part": "part2",
    "start_sec": 456.1,
    "end_sec": 461.3,
    "confidence": "medium",
    "type": "mid_clip_false_start",
    "reason": "Abandoned phrase before a clean restart in the next sub-segment."
  }
]
```

Allowed `type` values:

- `explicit_edit_note`
- `false_start`
- `repetition`
- `abandoned_thread`
- `full_restart`
- `self_correction`
- `mid_clip_false_start`
- `mid_clip_repetition`
- `mid_clip_self_correction`

Use `confidence: "high"` only when the cut is obvious and safe. Use
`confidence: "medium"` for true borderline candidates that deserve editor
review. Do not return `low` confidence rows.

## Boundary Rules

Prefer cut boundaries that preserve complete thoughts and avoid clipping words.
For mid-clip candidates, keep the range narrow and explain what clean line or
continuation replaces the removed fragment.

Never return a zero-length or near-zero-length cut. If the prompt asks for a
minimum duration, obey it.
