---
name: Victreebel semantic V1 section colors
description: Corrected Resolve color-coding rules for the Victreebel RBY UMB visual tiercard pass, including the highlighted intro-card boundary and marker-color caveat
type: reference
originSessionId: local-codex-2026-06-01
---

Use `scripts/color_v1_content_sections.py` to color the Victreebel RBY UMB
timeline by **content type**, not trainer identity.

Current timeline: `Victreebel UMB CODEx visual tiercard V1 hold pass`.

Final V1 clip palette after the corrected pass:

- `Orange`: intro/highlighted opening card montage plus outro source asset
- `Lime`: leader intro plus leader/Elite/Champion battle UI sections
- `Teal`: Rival in-battle sections
- `Purple`: V1-only post-battle tiercard/data-card hold clips
- `Apricot`: final tierlist views
- `Green`: member carousel V1 bed
- Uncolored: ordinary gameplay/travel/non-special clips

Important boundary correction: the opening Orange section is **not** just files
with `intro` in the name, and it is **not** everything before the first battle.
For the current Victreebel timeline:

- V1 clip 1: `Blue Version Intro.mp4`, rel `0..2056`, Orange
- V1 clips 2..27: highlighted title/card montage from gameplay source media, rel
  `2056..10328`, Orange
- V1 clip 28: first normal Oak/gameplay scene, rel `10328..10529`, should be
  uncolored unless a future section rule explicitly covers it

This boundary was verified with:

- `E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\visual_tiercard_pass\early_v1_contact_sheet.png`

Latest artifacts:

- Report: `E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\visual_tiercard_pass\section_color_report.json`
- Screenshot: `E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\visual_tiercard_pass\after_section_color_pass_highlighted_intro_fix.png`
- DRT: `E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\visual_tiercard_pass\Victreebel UMB CODEx visual tiercard V1 hold pass - section colors highlighted intro fix.drt`

Final V1 counts from verification:

- Orange `28`
- Lime `479`
- Teal `7`
- Purple `9`
- Apricot `30`
- Green `2`
- Uncolored `427`

Resolve marker colors are a separate API domain. `TimelineItem.SetClipColor`
accepts clip colors such as `Orange`, `Lime`, `Teal`, and `Apricot`, but
`Timeline.AddMarker` rejects those names. Use marker-safe equivalents:

- Orange -> `Sand`
- Lime -> `Lemon`
- Teal -> `Cyan`
- Apricot -> `Cream`
- Purple -> `Purple`
- Green -> `Green`

Marker recoloring deletes and re-adds markers because Resolve has no direct
marker-color update API. Do not interrupt marker recolor runs. If only V1 clip
colors need changing, run `color_v1_content_sections.py --skip-markers`.
