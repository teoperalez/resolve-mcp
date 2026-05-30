# Waveform QA cut-review process

A lightweight, **browser-based** pipeline for reviewing and cutting non-word
segments (breaths, clicks, false starts, dead air) out of a talking-head /
gameplay edit — designed so cuts can be decided **without running DaVinci
Resolve** (useful on machines that can't run Resolve smoothly).

## Principle

In any cut phase, split decisions two ways:

- **Completely obvious mistakes / false starts** (high-confidence: empty/no-voiced
  content, breaths/clicks, clear failed-take restarts) → **auto-cut directly**
  (ripple V1+A1, protect the BGM bed).
- **Any questionable / borderline case** → do **not** auto-cut. Build the HTML
  review tool and let the editor decide. Borderline non-words are content
  judgments; the auto-categorizer stays conservative.

## Pipeline

| Step | Tool | Output |
|---|---|---|
| 1. Dump timeline clips | `scripts/dump_timeline_clips.py` | `clips.json` (V1 clips: start/dur/left/fps/color/src) |
| 2. Waveform categorize | `scripts/waveform_qa.py` | `categories.json` + `waves_candidates.png` contact sheet |
| 3. Build review UI | `scripts/build_cut_review.py` | `review/index.html` + `assets/` + `segmap.json` |
| 4. *(editor reviews in browser)* | — | `pink_decisions.json` (downloaded) |
| 5. 1080p preview | `scripts/build_cut_preview.py` | `CUTS_PREVIEW_1080p.mp4` |
| 6. *(editor approves)* | — | — |
| 7. Apply in Resolve + 4K | `Timeline.DeleteClips(items, True)` + `scripts/render_timeline.py --preset 4k` | final |

Step 1 is produced from the **current** Resolve timeline (run it before any
ripple edits so indices match). Steps 2–5 need no Resolve.

## The HTML review tool (`build_cut_review.py`)

One card per questionable segment (adjacent segments cluster into one card). Each
card has:

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
- Ripple-delete on a loaded timeline: `Timeline.DeleteClips([v1_item, a1_item], True)`
  ripples only V1/A1 and leaves a spanning A2 BGM clip intact (verified) — but
  always check the outro A/V stay synced after the ripple.
- The 1080p preview bakes a grade via ffmpeg `lutrgb` (slope/offset) + `eq`
  (saturation); pass the project's CDL with `--slope/--offset/--sat`. This is an
  approximation of the Resolve grade — the final 4K is rendered from Resolve.
