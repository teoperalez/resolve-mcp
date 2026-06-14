# Waveform QA cut-review process

A lightweight, **browser-based** pipeline for reviewing and cutting non-word
segments (breaths, clicks, false starts, dead air) out of a talking-head /
gameplay edit — designed so cuts can be decided **without running DaVinci
Resolve** (useful on machines that can't run Resolve smoothly).

## Goal

The target timeline is free of repetitions, false starts, abandoned narrative
threads, self-correction fragments, explicit editor-note tangents, and audio
artifacts. Do not treat a timeline as cut-clean just because broad restart
ranges were removed; mid-segment dialogue problems and non-word artifacts need
their own review surface.

The cutter should do as much work automatically as possible. The user-facing
review set should be small and high precision: auto-cut confident whole-section
mistakes, auto-keep weak or speculative leads, and prompt the editor only for
true borderline cases after exhaustive checking, or for cuts that would require
splitting inside an FCPXML section. False positives are more costly than false
negatives; do not inflate the review queue just because something is
theoretically possible.

## Principle

Run cut review in four ordered passes:

- **Pass 1: broad narrative LLM review.** Scan the full dialogue, globally for
  split recordings, for explicit edit notes, repetitions, false starts,
  abandoned narrative threads, self-corrections, stale takes, and mid-segment
  restarts. This produces semantic cut suggestions only; the compiler decides
  whether any suggestion is section-safe enough to auto-apply.
- **Pass 2: waveform and n-gram detection.** Run deterministic waveform QA and
  repeated n-gram detection after the LLM output exists. Waveform can propose
  whole-section artifacts; n-grams are leads and should not bypass manual
  review by themselves.
- **Pass 3: artifact and short-clip detection.** Programmatically find FCPXML
  sections with no transcript words at the word level, extremely short clips,
  small waveform bursts that resemble mic bumps/throat clears, duplicate-text
  cluster artifacts, and likely transcription hallucinations.
- **Pass 4: candidate compiler.** Merge the LLM and all programmatic detector
  outputs, classify every candidate against FCPXML section boundaries, and emit
  the ranked manifest consumed by review and final assembly.

Every proposed cut is classified against FCPXML sections before it is applied or
shown to the editor:

- **Whole-section candidates**: if the candidate removes an entire FCPXML video
  section and its paired A1 section, and the cut is high-confidence, auto-cut it
  through section-safe metadata. Do not send obvious whole-section mistakes to
  HTML review.
- **Partial-section candidates**: if the candidate begins or ends inside an
  FCPXML section, do not trim it automatically. It must be medium or low
  confidence; a high-confidence partial-section candidate is downgraded before
  downstream scripts can apply it. Mark the containing section Pink and include
  it in the HTML review tool only when the candidate is strong enough to justify
  editor attention.
- **Weak candidates**: if the evidence is speculative, stylistic, or merely a
  heuristic lead, classify it as low confidence. Low-confidence candidates are
  written to the final timeline as Pink mark-only annotations; they are never
  cut automatically.
- **Edge cases**: reserve HTML review for meaningful editorial uncertainty,
  true borderline cases after exhaustive checking, possible
  hallucinations/artifacts with real evidence, and strong candidates that cannot
  be safely applied without splitting an FCPXML section.

For split recordings, keep audio-artifact review source-local but run narrative
review globally. False starts, redo takes, repetitions, and abandoned narrative
threads can cross part boundaries; Part 2 may replace, rehash, or invalidate a
line from Part 1. The approved cut manifest must keep the part/source identity
on every cut so those global decisions still apply to the correct FCPXML.

## Pipeline

| Step | Tool | Output |
|---|---|---|
| 1. Dump timeline clips | `scripts/dump_timeline_clips.py` | `clips.json` (V1 clips: start/dur/left/fps/color/src) |
| 2. Build narrative prompt | project wrapper | `narrative/*.in.md` + `clip_index.json` |
| 3. Broad narrative LLM review | orchestrator LLM dispatch | semantic JSON suggestions |
| 4. Waveform + n-gram detection | project wrapper / deterministic detectors | waveform and repeated-phrase candidate JSON |
| 5. Artifact + short-clip detection | project wrapper / deterministic detectors | artifact candidate JSON |
| 6. Compile ranked candidates | project wrapper section-safety compiler | high auto-cuts, medium review items, low mark-only items |
| 7. Build review UI | `scripts/build_cut_review.py` | small HTML review containing only medium-confidence unresolved cases |
| 8. *(editor reviews in browser)* | — | `pink_decisions.json` (downloaded) |
| 9. Compile approved source cuts | project wrapper | high auto-cuts + approved medium cuts |
| 10. Apply in final Resolve build + 4K | one deterministic final rebuild + `scripts/render_timeline.py --preset 4k` | final |

Victreebel RBY UMB uses `scripts/generate_victreebel_cut_candidates.py` as the
project wrapper. It emits one all-parts dialogue prompt under the project
`CODEx/cut_review` folder, then per-part review artifacts. The dialogue pass is
responsible for explicit edit notes, full restarts, repetitions, false starts,
abandoned threads, self-corrections, and mid-segment candidates. The wrapper
should automatically drop weak leads, auto-cut confident whole-section mistakes,
and keep the browser review page limited to strong partial-section or
mid-segment candidates plus rare artifact edge cases that cannot be resolved
safely without editor judgment.

After review, write the accepted source-time cuts to
`CODEx/approved_cuts_victreebel.json` with a `part` field on every cut, then run
`scripts/apply_victreebel_approved_cuts.py`. That wrapper is project-specific
because the corrected bases use explicit `_3.wav` A1 refs; it preserves the
paired audio/video refs while rippling approved cuts.

For Resolve-heavy projects, avoid repeated API timeline rebuilds after review.
Resolve `AppendToTimeline` calls can run for many minutes and make Resolve
temporarily non-responsive even when work is still progressing. Prefer this
shape: approve cuts and remaining timing decisions in lightweight artifacts,
derive/verify visual holds as data, then perform one deterministic final rebuild
that applies cuts, holds, BGM, battle audio, carousel layout, colors, final
verification, and DRT export in a single planned pass.

Step 1 is produced from the **current** Resolve timeline (run it before any
ripple edits so indices match). Steps 2–5 need no Resolve.

## The HTML review tool (`build_cut_review.py`)

One card per unresolved edge case (adjacent segments cluster into one card). Each
card should justify its existence; obvious keeps and obvious whole-section cuts
should already be resolved before this stage. Each card has:

- a **waveform** of `[before → SEGMENT → after]` with the segment highlighted;
- a **playable audio** snippet of that context with a **synced playhead** that
  turns red over the segment (+ an "IN PINK" badge);
- a **Keep/Cut** toggle per segment;
- **drag** on the waveform to mark a precise cut; **drag the box** to move it,
  **drag its edges** to resize, **×** to delete one, **right-click** to clear all;
- a **Preview result** button that plays the snippet with the cuts removed;
- a **Save** button → downloads `pink_decisions.json`
  (`{pink:{idx:keep|cut}, cuts:{group:[[snip_start,snip_end]...]}}`); the tool
  **pre-loads** the last saved decisions on rebuild.

`segmap.json` maps snippet-time → source-time per clip so the saved (snippet-time)
cuts translate to exact source trims in steps 5 and 7.

## Notes / gotchas

- Open `index.html` from `file://` — everything works offline (audio/img by
  relative path, Save via Blob download). Hard-refresh (`Ctrl+Shift+R`) after a
  rebuild to bust the browser cache.
- The waveform "voiced" test is energy **and** low zero-crossing (a vowel), so
  breaths/fricatives don't register as words. Keep thresholds conservative.
- Do not promote raw duplicate-word or immediate-phrase-repeat heuristics to
  HTML review by themselves. They are leads for the full-dialogue pass; context
  must prove the repeated token is an abandoned fragment rather than normal
  wording, an intervening number, or intentional cadence.
- When in doubt on a weak candidate, keep it out of the review page. A small
  number of precise, defensible review cards is better than a broad list that
  makes the editor re-audit obvious dialogue.
- When a case is still genuinely borderline after checking transcript context,
  word timings, neighboring clips, and whether the cut is FCPXML-section safe,
  route it to HTML review instead of guessing.
- Ripple-delete on a loaded timeline: `Timeline.DeleteClips([v1_item, a1_item], True)`
  ripples only V1/A1 and leaves a spanning A2 BGM clip intact (verified) — but
  always check the outro A/V stay synced after the ripple.
- The 1080p preview bakes a grade via ffmpeg `lutrgb` (slope/offset) + `eq`
  (saturation); pass the project's CDL with `--slope/--offset/--sat`. This is an
  approximation of the Resolve grade — the final 4K is rendered from Resolve.
- Historical case-study lessons from the retired Brock Red and Misty Red
  `audio-checks/` workspaces are preserved in `docs/brock_misty_cut_lessons.md`.
  Use that note for false-start QA, waveform thresholds, final-render review,
  and challenge-specific cut-boundary pitfalls without restoring old artifacts.
