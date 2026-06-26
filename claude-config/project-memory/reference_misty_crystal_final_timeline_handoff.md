# Misty Crystal Final Timeline Handoff

Date: 2026-06-25

The canonical final Resolve timeline for the Misty Red/Blue Crystal Gym Leader Challenge is:

`Misty decision rebuild from saved cut decisions (edit)`

Project:

`New Project 3`

Do not use the older May timeline `Misty Red and Blue Crystal Gym Leader Challenge (cuts: all) (edit)` as final. Do not use the base timeline `Misty decision rebuild from saved cut decisions` as final; it is the pre-intro/outro/pre-music decision rebuild.

Durable handoff:

`docs/handoffs/misty-red-crystal-final-2026-06-25/README.md`

Final render:

`E:\Misty Red\Misty decision rebuild from saved cut decisions (edit)_FINAL_4K.mp4`

Final exports are in both:

- `docs/handoffs/misty-red-crystal-final-2026-06-25/`
- `E:\Misty Red\CODEx\final-timeline-handoff\`

Key QA:

- `3840x2160`, `60 fps`, timeline frames `216000` to `325191`
- V1 `544`, V2 `45`, A1 `580`, A2 `29`, A3 `1`
- Missing media `0`
- V2 battle intros `6`
- V2 carousel clips `39`
- A2 overlaps `0`
- A2 track `Music 1` locked
- One V1/A1 coverage exception is expected: the carousel visual underlay made by `layout_carousel.py`

Rebuild preference:

1. Prefer importing the exported DRP or DRT from the handoff folder.
2. If rebuilding procedurally, start from `misty_decision_rebuild.fcpxml`, then run intro/outro, battle intros, carousel layout, BGM/battle audio, battle BGM, A3 outro-audio fix, fades, and Fairlight preset exactly as documented in the README.
