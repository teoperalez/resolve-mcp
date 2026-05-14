"""
Analyze the live Resolve V1 timeline (clip-by-clip) via LLM relay and color
cut candidates.

Colors:
  Orange = high confidence cut
  Yellow = medium confidence cut
  (other clips unchanged — default color kept)

Unlike the old transcript-only analyzer, this script:
  1. Enumerates every V1 clip on the active Resolve timeline
  2. Attaches any overlapping Whisper transcript text to each clip
  3. Asks the LLM to flag any clip whose narrative purpose cannot be established
     (e.g. empty-transcript artifacts like throat clears, mic checks, breath bursts)

Relay: writes plans/prompts/cut-analysis-<stem>.in.md, polls for .out.md.
Claude Code reads .in.md, writes ONLY a raw JSON array to .out.md, then this
script matches each flagged source-time range back to V1 clips and colors them.

Requires Resolve to be open with the target timeline active (true even for
--dry-run, since the clip list is the input to the LLM prompt).
"""
import sys
import os
import json
import time
import argparse
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PROMPTS_DIR     = Path('plans/prompts')
TRANSCRIPTS_DIR = Path('transcripts')
TIMEOUT_SEC     = 600


def latest_transcript() -> tuple[Path, str]:
    candidates = []
    for f in TRANSCRIPTS_DIR.glob('*.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                candidates.append(f)
        except Exception:
            pass
    if not candidates:
        raise FileNotFoundError(f'No transcript JSON with segments in {TRANSCRIPTS_DIR.resolve()}')
    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return candidates[0], candidates[0].stem


def gameplay_v1_clips(timeline) -> list:
    """
    Return TimelineItem objects for V1 clips from the dominant (gameplay)
    source only — excludes intro/outro/B-roll clips whose source-frame ranges
    can spuriously overlap gameplay source-frame ranges and cause cross-source
    false matches in apply_colors.
    """
    v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    if not v1:
        return []
    names = [c.GetName() for c in v1]
    dominant = Counter(names).most_common(1)[0][0]
    return [c for c in v1 if c.GetName() == dominant]


def enumerate_v1_clips(timeline, fps: float) -> tuple[list[dict], list[dict]]:
    """
    Return (gameplay_clips, structural_clips). Both lists hold dicts with
    seconds-resolution times: { idx, tl_start, tl_end, src_start, src_end,
    duration, source_name }. idx is 1-based and matches order on the timeline.

    The dominant source-name (the gameplay capture file) populates
    gameplay_clips; everything else (intro card, outro card, B-roll inserts
    from the assets bin) ends up in structural_clips. Structural clips are
    intentional pre-rendered content and should not be analyzed for cuts.
    """
    v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    tl_start_frame = timeline.GetStartFrame()

    # Identify the dominant source name = gameplay capture
    names = [c.GetName() for c in v1]
    if not names:
        return [], []
    dominant_name = Counter(names).most_common(1)[0][0]

    gameplay, structural = [], []
    for i, c in enumerate(v1, start=1):
        tl_in_frames = c.GetStart() - tl_start_frame
        entry = {
            'idx':         i,
            'tl_start':    tl_in_frames / fps,
            'tl_end':      (tl_in_frames + c.GetDuration()) / fps,
            'src_start':   c.GetLeftOffset() / fps,
            'src_end':     (c.GetLeftOffset() + c.GetDuration()) / fps,
            'duration':    c.GetDuration() / fps,
            'source_name': c.GetName(),
        }
        (gameplay if c.GetName() == dominant_name else structural).append(entry)
    return gameplay, structural


def attach_transcript_to_clips(clips: list[dict], segments: list) -> list[dict]:
    """
    For each clip, attach any Whisper segments whose source range overlaps the
    clip's source range. Modifies clips in place. Each clip gains:
      - `transcript`: list of {start_sec, end_sec, text} dicts (possibly empty)
    """
    for clip in clips:
        hits = []
        for s in segments:
            seg_start = float(s.get('start', 0))
            seg_end   = float(s.get('end', 0))
            if seg_start < clip['src_end'] and seg_end > clip['src_start']:
                txt = (s.get('text') or '').strip()
                hits.append({'start_sec': seg_start, 'end_sec': seg_end, 'text': txt})
        clip['transcript'] = hits
    return clips


def flatten_words(segments: list) -> list[dict]:
    """
    Flatten word-level timestamps across all transcript segments into a single
    list sorted by start time. Used by refine_cut_point() to snap cut edges to
    the largest word-gap near the LLM's proposed boundary.
    """
    out = []
    for s in segments:
        for w in s.get('words', []):
            try:
                out.append({
                    'word':  w.get('word', ''),
                    'start': float(w['start']),
                    'end':   float(w['end']),
                })
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda w: w['start'])
    return out


def refine_cut_point(t_sec: float, words: list[dict], tol: float = 0.3) -> float:
    """
    Find the largest word-gap within ±tol seconds of t_sec. Returns the midpoint
    of that gap, or t_sec unchanged if no candidate gap is found. The intent is
    'use Whisper as a guide, then zoom in and cut at the gap between words.'
    """
    best_gap = -1.0
    best_center = t_sec
    for w1, w2 in zip(words[:-1], words[1:]):
        gap = w2['start'] - w1['end']
        center = (w1['end'] + w2['start']) / 2.0
        if abs(center - t_sec) <= tol and gap > best_gap:
            best_gap   = gap
            best_center = center
    return best_center


def format_clip_line(c: dict) -> str:
    head = (f'[{c["idx"]:5d}] tl={c["tl_start"]:8.2f}-{c["tl_end"]:8.2f}s  '
            f'src={c["src_start"]:8.2f}-{c["src_end"]:8.2f}s  '
            f'dur={c["duration"]:5.2f}s')

    if not c['transcript']:
        return f'{head}  (NO TRANSCRIPT — empty / noise / artifact)'

    # Filter out empty text segments
    real = [t for t in c['transcript'] if t['text']]
    if not real:
        return f'{head}  (transcript present but blank)'

    if len(real) == 1:
        t = real[0]
        return f'{head}  [{t["start_sec"]:7.2f}-{t["end_sec"]:7.2f}s] "{t["text"]}"'

    # Multi-segment clip — expand each sub-segment onto its own indented line so
    # the LLM can see the internal boundaries that are candidates for mid-clip cuts.
    lines = [head]
    for t in real:
        lines.append(f'           sub [{t["start_sec"]:7.2f}-{t["end_sec"]:7.2f}s] "{t["text"]}"')
    return '\n'.join(lines)


def build_prompt(clips: list[dict]) -> str:
    body = '\n'.join(format_clip_line(c) for c in clips)
    n_empty = sum(1 for c in clips if not c['transcript'])
    return f"""You are reviewing CLIPS on a silence-stripped DaVinci Resolve timeline for cut candidates.

## Context

The footage has been silence-stripped by an auto-editor. True silence is gone — anything still on the timeline survived a silence threshold. BUT surviving the auto-editor does NOT make a clip part of the narrative. The auto-editor cannot distinguish between speech and a mic bump, a throat clear, a breath burst above the noise floor, a soundboard test, or a pre-roll fragment.

This means **every clip on the timeline needs to earn its place by serving the story**.

## Editorial principle (read carefully — this is the bias of the analysis)

**The burden is on you to articulate how each clip advances the narrative. If you cannot, FLAG IT.**

This is the INVERSE of "default to KEEP." For silence-stripped footage, the right default is "flag what you cannot justify." False positives are cheap — the editor un-flags them in 2 seconds in Resolve. False negatives are expensive — the editor has to re-listen to the whole video to catch them.

## Phase 1 — Read the transcript as continuous narrative

Before flagging anything, mentally read all the transcript text (attached to each clip below) as a continuous story:

- Overall challenge framing (e.g. "use Gen 1 Brock's team in Crystal")
- Each trainer fight as a mini-arc: setup → events → outcome → reflection
- Intro setup → gameplay → outro / wrap-up
- The streamer's natural speech patterns: hesitations, mild restatements, "ums" are part of HOW they speak — not signs to cut

## Phase 2 — Review each clip individually

For each clip below, ask:

> Does this clip advance the narrative? If yes, what role does it serve? If you cannot answer that question concretely, flag it.

The list below is **every V1 clip on the timeline** (in order). Each line shows:

- `[idx]` clip index (informational — for cross-reference if you want)
- `tl=A-B`  timeline position in the final edit (seconds)
- `src=C-D` source position in the original unedited recording (seconds) — **use these values in your output**
- `dur=Es` duration in seconds
- transcript text from Whisper overlapping the source range, or `(NO TRANSCRIPT — empty / noise / artifact)`

**Multi-segment clips.** When a clip contains more than one Whisper segment, each sub-segment is shown on its own `sub [...] "..."` line with its own source-time range. These internal boundaries are the natural cut points if you want to flag only part of the clip — see "Mid-clip cuts" below.

There are {len(clips)} clips total; {n_empty} have no transcript text.

## Categories of cuts

### HIGH confidence — clear flags (categories 1-4)

**1. Empty-transcript clips.** No Whisper text in the source range. Almost certainly throat clear, breath burst, mic bump, or pre-roll noise. EXCEPTION: a clip sitting inside an obviously excited moment (active yelling, laughter, mid-reaction-sequence) where Whisper sometimes misses non-word sounds — those can KEEP. When in doubt, flag.

**2. Pre-roll / mic-check / soundboard test.** "Check, check.", "Rolling?", "Is this on?", "Let me get this set up." Always cut.

**3. Whisper hallucination over noise.** A single period `.`, empty string, single isolated function word ("you", "and", "the", "I", "a") with no connection to surrounding sentences. Or a very short clip whose text is implausibly long, in a different language, or completely off-topic.

**4. Repeated identical short utterances back-to-back.** Whisper's "stutter" failure mode.

### MEDIUM confidence — narrative judgment (categories 5-7)

**5. False starts.** Speaker says a few words, audibly cuts themselves off, and restarts from scratch immediately after. Cut the first attempt.

  - YES cut: "I'm gonna— let me try Tackle here. I'm gonna use Tackle on this one." (cut "I'm gonna—")
  - NO  cut: "I'm gonna use Tackle here, and probably Defense Curl after that." (one flowing sentence)

**6. True repetitions implying a redo.** A line is delivered, then re-delivered noticeably cleaner within ~15s — usually a failed first take being re-recorded.

  - YES cut: 60s "Brock's Onix has 14 HP", 73s "So Brock's Onix is sitting at 14 HP remaining." → cut the first.
  - NO  cut: Returning to the same idea 2 minutes apart with new framing — normal storytelling.
  - NO  cut: Restating for emphasis ("we won, we actually won") — intentional.

**7. Abandoned narrative threads.** Setup mentioned ("we're going to try X strategy"), never followed through. Verify abandonment by scanning forward before flagging.

## Mid-clip cuts (sub-clip ranges)

A cut does not have to span a whole clip. The auto-editor's clip boundaries are arbitrary breath/pause points; the real false start or repetition may sit at the START or the END of a longer clip, with the rest of the clip being keep-worthy.

When a single clip contains multiple Whisper sub-segments (shown as multiple `sub [...]` lines), you can flag a SUBSET of the clip's source range. Use the boundaries between sub-segments as your cut points — those are where Whisper detected a natural pause, so they line up with the gaps between words.

Examples:

- **Trail-off + restart in one clip.** Clip with two sub-segments: `sub [400.0-403.5s] "and with that we're basically ready to move on because we are"` and `sub [403.6-408.0s] "And with that, we're basically ready to move on, and Misty gets a chance to show..."` — flag `start_sec=400.0, end_sec=403.5` (cut only the trailed-off first attempt; keep the clean restart).

- **Mid-sentence correction.** Clip with `sub [2587.0-2590.6s] "this Starmie wants Bubble Beam"` followed by `sub [2590.8-2594.0s] "actually wants Surf"` — flag the first sub-segment only.

- **Beginning of clip is a stutter, rest is the real line.** Flag from `clip.src_start` to the end of the first sub-segment.

If a clip has only ONE sub-segment shown (or no `sub` lines at all), output the whole-clip src range as before. Sub-clip ranges should always START or END at a sub-segment boundary — never in the middle of a word.

**`start_sec` must be strictly less than `end_sec` — at least 0.2s apart.** If the only thing to cut is a single aborted word or a momentary glitch, expand the range out to the nearest sub-segment boundary or by at least 0.3s on either side. Zero-length or single-point cuts cannot be applied as markers.

## What is NOT a cut candidate

- **Outro / wrap-up speech.** "Thanks for watching", "see you next time", "if you enjoyed", "shoutout to my members" — scripted, intentional, keep.
- **Mild filler / restatement that flows.** "Yeah, so we're gonna want to use Tackle here. Tackle does decent damage." — natural emphasis.
- **Natural hesitation that resolves.** "I think we're going to… actually let me check the HP first."
- **Recaps and reminders.** "Remember, this Bugsy fight is impossible for us."
- **Gameplay reactions.** Excited yells, frustration, surprise — these ARE the entertainment.

## Clips on the timeline

{body}

---

## Output

Respond with ONLY a raw JSON array (no markdown fences, no explanation outside the JSON):

[
  {{"start_sec": 12.15, "end_sec": 12.77, "confidence": "high", "type": "pre_roll",
    "reason": "Mic-check 'Check, check' — pre-roll, not part of narrative"}},
  {{"start_sec": 13.03, "end_sec": 13.43, "confidence": "high", "type": "artifact",
    "reason": "0.40s clip with no transcript — throat clear or breath burst"}},
  {{"start_sec": 187.0, "end_sec": 191.5, "confidence": "medium", "type": "false_start",
    "reason": "Begins describing Onix's HP, cuts off and restarts at 191.6s"}},
  {{"start_sec": 400.0, "end_sec": 403.5, "confidence": "medium", "type": "mid_clip_false_start",
    "reason": "Trail-off 'because we are' at start of long clip; flag only the first sub-segment, keep the clean restart that follows"}}
]

`start_sec` / `end_sec`: the **source-time range** to flag.
  - Whole-clip flag: use the clip's `src=A-B` values exactly.
  - Sub-clip flag: use a sub-segment's `[start-end]` values (or the clip's src_start through a sub-segment boundary, or a sub-segment boundary through the clip's src_end). Always align to a sub-segment boundary — never split inside a word.
`confidence`: `high` for categories 1–4 (clear artifacts/pre-roll/hallucinations); `medium` for categories 5–7 plus mid-clip cuts (narrative judgment).
`type`: one of `artifact`, `pre_roll`, `hallucination`, `false_start`, `repetition`, `abandoned_thread`. Prefix with `mid_clip_` (e.g. `mid_clip_false_start`, `mid_clip_repetition`) when the range is a strict subset of a single clip — this signals the apply step to place edge markers on the clip instead of coloring the whole thing.

For silence-stripped footage with {n_empty} empty-transcript clips, an empty array `[]` is almost certainly wrong — at minimum, empty-transcript clips that are not inside an obvious reaction sequence should be flagged.
"""


def poll_for_response(out_path: Path, timeout_sec: int) -> list:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            raw = out_path.read_text(encoding='utf-8').strip()
            return json.loads(raw)
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s — expected {out_path}')


def apply_colors(segments: list, fps: float, timeline, words: list[dict],
                 dry_run: bool) -> tuple[int, int, int]:
    """
    Apply cut flags to the live Resolve timeline.

    Returns (n_orange, n_yellow, n_subclip_markers).

    For each flagged range:
      - Find all V1 clips whose source range overlaps it.
      - If the range covers the whole clip (within 1-frame tolerance): SetClipColor.
      - If the range is a strict subset of a single clip (mid-clip flag):
          1. Snap start_sec and end_sec to the nearest large word-gap (±0.3s)
          2. SetClipColor (so the editor sees the clip is flagged)
          3. AddMarker(Red, 'Cut start') and AddMarker(Red, 'Cut end') on the clip
             at the refined source frames — the editor blades at the markers.

    Marker frame convention: TimelineItem.AddMarker takes the ABSOLUTE source
    frame (clip.GetLeftOffset() + offset). int(t_sec * fps) is that frame as
    long as the source media starts at frame 0 — true for all gameplay capture
    files in this pipeline.
    """
    # Identify gameplay vs structural clips. apply_colors must NEVER touch
    # structural clips (intro/outro/B-roll) — they are intentional pre-rendered
    # content. We ALSO defensively clear any color/markers that a prior buggy
    # run may have left on structural clips, so re-running this script always
    # converges to "structural clips are clean".
    all_v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                    key=lambda c: c.GetStart())
    if not all_v1:
        return 0, 0, 0
    dominant_name = Counter(c.GetName() for c in all_v1).most_common(1)[0][0]
    v1 = [c for c in all_v1 if c.GetName() == dominant_name]
    structural = [c for c in all_v1 if c.GetName() != dominant_name]

    n_orange = n_yellow = 0
    n_markers = 0

    if not dry_run:
        # Defensively clean structural clips of any stale cut-candidate state
        n_struct_cleared = 0
        for c in structural:
            if c.GetClipColor() in ('Orange', 'Yellow', 'Red'):
                c.ClearClipColor()
                n_struct_cleared += 1
            markers = c.GetMarkers() or {}
            for frame, m in markers.items():
                if m.get('customData') == 'cut_candidates':
                    c.DeleteMarkerAtFrame(frame)
                    n_struct_cleared += 1
        if n_struct_cleared:
            print(f'Cleared {n_struct_cleared} stale color/marker(s) from {len(structural)} structural clip(s)')

        # Idempotency: clear any prior cut-candidate markers on gameplay clips
        # too. Tagged with customData='cut_candidates' so we don't disturb
        # markers placed by other tools.
        n_cleared = 0
        for c in v1:
            markers = c.GetMarkers() or {}
            for frame, m in markers.items():
                if m.get('customData') == 'cut_candidates':
                    c.DeleteMarkerAtFrame(frame)
                    n_cleared += 1
        if n_cleared:
            print(f'Cleared {n_cleared} stale cut-candidate marker(s) from prior run')

    for seg in segments:
        s_start_sec = float(seg['start_sec'])
        s_end_sec   = float(seg['end_sec'])
        s_start_f   = int(s_start_sec * fps)
        s_end_f     = int(s_end_sec   * fps)
        conf        = seg.get('confidence', 'medium')
        color       = 'Orange' if conf == 'high' else 'Yellow'
        type_str    = seg.get('type', '')
        reason      = seg.get('reason', '')
        reason_short = reason[:70]

        explicit_subclip = type_str.startswith('mid_clip_')

        # Match clips whose source range overlaps the segment
        hits = [c for c in v1
                if c.GetLeftOffset() < s_end_f
                and c.GetLeftOffset() + c.GetDuration() > s_start_f]

        if not hits:
            print(f'  NOMATCH [{s_start_sec:.2f}-{s_end_sec:.2f}s]  {reason_short}')
            continue

        for clip in hits:
            c_start = clip.GetLeftOffset()
            c_end   = clip.GetLeftOffset() + clip.GetDuration()
            covers_whole = (s_start_f <= c_start + 1 and s_end_f >= c_end - 1)
            inside_clip  = (s_start_f >= c_start and s_end_f <= c_end)
            sub_clip = (not covers_whole) and inside_clip and (explicit_subclip or
                                                                (s_end_f - s_start_f) < (c_end - c_start))

            if sub_clip:
                # Snap each cut edge to the largest word-gap nearby
                refined_start = refine_cut_point(s_start_sec, words, tol=0.3)
                refined_end   = refine_cut_point(s_end_sec,   words, tol=0.3)
                rs_f = int(refined_start * fps)
                re_f = int(refined_end   * fps)
                # Clamp to clip bounds
                rs_f = max(rs_f, c_start)
                re_f = min(re_f, c_end - 1)

                drift_s = abs(refined_start - s_start_sec)
                drift_e = abs(refined_end   - s_end_sec)
                print(f'  {color:6s} sub-clip [{refined_start:.2f}-{refined_end:.2f}s]'
                      f' (snapped Δ{drift_s:.2f}/{drift_e:.2f}s)  {conf}  {reason_short}')

                if not dry_run:
                    clip.SetClipColor(color)
                    note = f'[{type_str}] {reason}'[:200]
                    clip.AddMarker(rs_f, 'Red', 'Cut start', note, 1, 'cut_candidates')
                    clip.AddMarker(re_f, 'Red', 'Cut end',   note, 1, 'cut_candidates')
                n_markers += 2
            else:
                print(f'  {color:6s} whole    [{s_start_sec:.2f}-{s_end_sec:.2f}s]'
                      f'  {conf}  {reason_short}')
                if not dry_run:
                    clip.SetClipColor(color)

            if color == 'Orange':
                n_orange += 1
            else:
                n_yellow += 1

    return n_orange, n_yellow, n_markers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('transcript', nargs='?',
                    help='Transcript JSON path (default: most recent in transcripts/)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Build the prompt and show what would be colored, but do not '
                         'modify clips in Resolve. Still requires Resolve to be open.')
    ap.add_argument('--timeout', type=int, default=TIMEOUT_SEC,
                    help=f'Relay timeout in seconds (default: {TIMEOUT_SEC})')
    ap.add_argument('--skip-relay', action='store_true',
                    help='Read existing cut-analysis-<stem>.out.md and apply colors '
                         'without re-running the relay (use after manually editing the .out.md)')
    args = ap.parse_args()

    if args.transcript:
        t_path = Path(args.transcript)
        stem   = t_path.stem
    else:
        t_path, stem = latest_transcript()

    print(f'Transcript: {t_path}')
    transcript = json.loads(t_path.read_text(encoding='utf-8'))

    # Connect to Resolve early — we need the V1 clip list to build the prompt.
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1
    project  = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print('ERROR: No active timeline.', file=sys.stderr)
        return 1
    fps = float(project.GetSetting('timelineFrameRate'))
    print(f'Timeline: {timeline.GetName()}  fps={fps:.2f}')

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / f'cut-analysis-{stem}.in.md'
    out_path = PROMPTS_DIR / f'cut-analysis-{stem}.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        print(f'Skip-relay: reading existing {out_path}')
        segments = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        if out_path.exists():
            out_path.unlink()

        clips, structural = enumerate_v1_clips(timeline, fps)
        clips = attach_transcript_to_clips(clips, transcript.get('segments', []))
        n_empty = sum(1 for c in clips if not c['transcript'])
        print(f'Enumerated {len(clips)} gameplay clips ({n_empty} have no transcript text)')
        if structural:
            print(f'Excluded {len(structural)} structural clip(s) (intro/outro/inserts):')
            for s in structural:
                print(f'  [{s["idx"]:5d}] tl={s["tl_start"]:7.2f}-{s["tl_end"]:7.2f}s  '
                      f'dur={s["duration"]:5.2f}s  {s["source_name"]}')

        in_path.write_text(build_prompt(clips), encoding='utf-8')
        print(f'Relay prompt -> {in_path}')
        print(f'Waiting for {out_path} ...')

        try:
            segments = poll_for_response(out_path, timeout_sec=args.timeout)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    print(f'\nReceived {len(segments)} cut candidate(s).')

    # Flatten word-level timestamps for sub-clip cut-edge refinement
    words = flatten_words(transcript.get('segments', []))

    n_orange, n_yellow, n_markers = apply_colors(segments, fps, timeline, words,
                                                  dry_run=args.dry_run)
    if args.dry_run:
        print(f'\nDRY RUN — no changes applied.')
    print(f'Colored: {n_orange} orange (high), {n_yellow} yellow (medium); '
          f'{n_markers} sub-clip cut-edge markers')
    return 0


if __name__ == '__main__':
    sys.exit(main())
