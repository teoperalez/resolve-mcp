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
    clip's source range. Modifies clips in place. Each clip gains a `transcript`
    key holding a list of {start_sec, end_sec, text} dicts (possibly empty).
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


def format_clip_line(c: dict) -> str:
    if c['transcript']:
        # Join transcript snippets with ' | '. Strip surrounding whitespace.
        text_field = ' | '.join(t['text'] for t in c['transcript'] if t['text'])
        if not text_field:
            text_field = '(transcript present but blank)'
        else:
            text_field = f'"{text_field}"'
    else:
        text_field = '(NO TRANSCRIPT — empty / noise / artifact)'
    return (f'[{c["idx"]:5d}] tl={c["tl_start"]:8.2f}-{c["tl_end"]:8.2f}s  '
            f'src={c["src_start"]:8.2f}-{c["src_end"]:8.2f}s  '
            f'dur={c["duration"]:5.2f}s  {text_field}')


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
    "reason": "Begins describing Onix's HP, cuts off and restarts at 191.6s"}}
]

`start_sec` / `end_sec`: the **source-time range** of the clip you're flagging — use the `src=` values shown above (NOT the `tl=` values). One JSON entry per clip you want flagged.
`confidence`: `high` for categories 1–4 (clear artifacts/pre-roll/hallucinations); `medium` for categories 5–7 (narrative judgment).
`type`: one of `artifact`, `pre_roll`, `hallucination`, `false_start`, `repetition`, `abandoned_thread`.

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


def apply_colors(segments: list, fps: float, timeline, dry_run: bool) -> tuple[int, int]:
    v1 = timeline.GetItemListInTrack('video', 1) or []
    n_orange = n_yellow = 0

    for seg in segments:
        s_start = int(seg['start_sec'] * fps)
        s_end   = int(seg['end_sec']   * fps)
        conf    = seg.get('confidence', 'medium')
        color   = 'Orange' if conf == 'high' else 'Yellow'
        reason  = seg.get('reason', '')[:70]

        # Match clips whose source range overlaps the segment
        hits = [c for c in v1
                if c.GetLeftOffset() < s_end
                and c.GetLeftOffset() + c.GetDuration() > s_start]

        if hits:
            print(f'  {color:6s}  [{seg["start_sec"]:.1f}-{seg["end_sec"]:.1f}s]'
                  f'  {conf}  {reason}')
            for clip in hits:
                if not dry_run:
                    clip.SetClipColor(color)
            if color == 'Orange':
                n_orange += len(hits)
            else:
                n_yellow += len(hits)
        else:
            print(f'  NOMATCH [{seg["start_sec"]:.1f}-{seg["end_sec"]:.1f}s]  {reason}')

    return n_orange, n_yellow


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

    if args.dry_run:
        print('\nDRY RUN — would color:')
        for seg in segments:
            color = 'Orange' if seg.get('confidence') == 'high' else 'Yellow'
            print(f'  {color:6s}  [{seg["start_sec"]:.1f}-{seg["end_sec"]:.1f}s]'
                  f'  {seg.get("confidence", "?")}  {seg.get("reason", "")[:70]}')
        return 0

    n_orange, n_yellow = apply_colors(segments, fps, timeline, dry_run=False)
    print(f'\nColored: {n_orange} orange (high confidence), {n_yellow} yellow (medium confidence)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
