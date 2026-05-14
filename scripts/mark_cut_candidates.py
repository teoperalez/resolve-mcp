"""
Analyze transcript via LLM relay and color V1 clips as cut candidates.

Colors:
  Orange = high confidence cut
  Yellow = medium confidence cut
  (other clips unchanged — default color kept)

Relay: writes plans/prompts/cut-analysis-<stem>.in.md, polls for .out.md.
Claude Code reads .in.md, writes ONLY a raw JSON array to .out.md, then
this script colors matching V1 clips and exits.
"""
import sys
import os
import json
import time
import argparse
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


def build_prompt(transcript: dict) -> str:
    segs = transcript.get('segments', [])
    lines = [f'[{s["start"]:.2f}–{s["end"]:.2f}] {s.get("text", "").strip()}'
             for s in segs]
    body = '\n'.join(lines)
    return f"""You are identifying cut candidates in a Pokémon gameplay commentary transcript.

The footage has already been silence-stripped by an auto-editor. True silence is gone, but brief sounds above the noise floor (throat clears, coughs, mic bumps, breath bursts) remain — and Whisper hallucinates these into garbled short transcriptions. The video typically also has a scripted intro and outro that ARE intentional commentary.

## Transcript (Whisper segments, timestamps in seconds)

{body}

---

## Phase 1 — Read for narrative comprehension FIRST

Before identifying ANY cuts, mentally read the entire transcript as a continuous narrative — not as discrete Whisper segments. The Whisper segment boundaries are mostly arbitrary breath/pause points; the real "sentences" cross multiple segments. Understand:

- The overall challenge framing (e.g., "use Gen 1 Brock's team in Crystal")
- Each trainer fight as a mini-arc with setup → events → outcome → reflection
- The arc of the video: intro setup → gameplay → outro / wrap-up
- The streamer's natural speech patterns: hesitations, mild restatements, "ums", and conversational connectors are part of HOW they speak, not signs to cut

**Default action is KEEP.** Cut only when you can articulate a concrete editorial reason that a viewer would notice and benefit from.

## Phase 2 — Identify cuts in two categories

### Category A: Whisper hallucination over non-speech (HIGH confidence cuts)

Cut when Whisper had no real speech to transcribe and invented something from noise:

- The text is a single period `.`, empty, or just punctuation
- The text is a single isolated word ("you", "the", "and", "I", "a") with NO connection to the surrounding sentences
- A very short segment (< 1.5s typical) whose text is implausibly long, in a different language, or completely off-topic
- Repeated identical short utterances back-to-back (Whisper's "stutter" failure mode)

DO NOT cut: genuine short reactions like "yes!", "no", "oh!", "wow", "let's go", "got it", laughter, sighs that fit the moment.

### Category B: False starts / true repetitions / abandoned threads (MEDIUM, sometimes HIGH confidence)

Only cut when the surrounding narrative confirms it. Three sub-types:

**B1. Real false starts** — speaker says a few words, audibly cuts themselves off, and restarts the same thought from scratch immediately after. The first attempt should be cut so the take is clean.

  - YES cut: "I'm gonna— let me try Tackle here. I'm gonna use Tackle on this one."  (cut "I'm gonna—" through the dash)
  - NO  cut: "I'm gonna use Tackle here, and then probably Defense Curl after that." (one flowing sentence, no restart)

**B2. True repetitions implying a redo** — the speaker delivers a line, pauses, and re-delivers a noticeably cleaner version of the same line within ~15s. This usually means they messed up the first take and re-recorded.

  - YES cut: 60s mark "Brock's Onix has 14 HP", 73s mark "So Brock's Onix is sitting at 14 HP remaining."  → cut the first.
  - NO  cut: Returning to the same idea 2 minutes apart with new framing or new information — that's normal storytelling.
  - NO  cut: Restating a fact for emphasis ("we won, we actually won") — that's intentional.

**B3. Abandoned narrative threads** — the speaker sets up an expectation ("we're going to try X strategy"), then NEVER follows through later in the transcript. Cut the setup so the viewer isn't waiting for a payoff that never comes.

  Verify abandonment by scanning the rest of the transcript AFTER the setup before deciding. If the thread is picked up even briefly, KEEP.

## What is NOT a cut candidate

Be explicit about avoiding these false positives:

- **Outro / wrap-up speech.** "Thanks for watching", "see you next time", "if you enjoyed", "let me know in the comments", "this was a fun one", "shoutout to my members" — these are intentional and belong on the timeline. They often appear segmented oddly by Whisper but they are scripted content.
- **Mild filler / restatement that flows.** "Yeah, so… we're gonna want to use Tackle here. Tackle does decent damage." — natural emphasis, not a redo.
- **Natural hesitation that resolves.** "I think we're going to… actually let me check the HP first." — the speaker is thinking through gameplay live; this is the video.
- **Recaps and reminders.** "Remember, this Bugsy fight is impossible for us." — even if mentioned earlier, recaps for the viewer are intentional.
- **Reactions to gameplay.** Excited yells, frustration, surprise — these ARE the entertainment.

Bias the call toward KEEP. A false-positive cut (something that should have stayed) is worse than a missed cut (something the editor will catch by ear later).

---

## Output

Respond with ONLY a raw JSON array (no markdown fences, no explanation outside the JSON):

[
  {{"start_sec": 12.3, "end_sec": 13.7, "confidence": "high", "type": "artifact",
    "reason": "Single period transcription, 0.4s duration — Whisper hallucination over throat clear"}},
  {{"start_sec": 187.0, "end_sec": 191.5, "confidence": "medium", "type": "false_start",
    "reason": "Begins describing Onix's HP, audibly cuts off and restarts the same statement at 191.6s"}},
  {{"start_sec": 412.5, "end_sec": 425.0, "confidence": "medium", "type": "abandoned_thread",
    "reason": "Sets up plan to try Defense Curl strategy; never returns to it in the remainder of the transcript"}}
]

`confidence`: `high` only for Category A (clear Whisper hallucination); Category B is almost always `medium`.
`type`: one of `artifact`, `false_start`, `repetition`, `abandoned_thread`.

If you are NOT at least medium-confident the cut would be uncontroversial to an experienced editor, omit it. An empty array `[]` is a valid answer.
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
            print(f'  {color:6s}  [{seg["start_sec"]:.1f}–{seg["end_sec"]:.1f}s]'
                  f'  {conf}  {reason}')
            for clip in hits:
                if not dry_run:
                    clip.SetClipColor(color)
            if color == 'Orange':
                n_orange += len(hits)
            else:
                n_yellow += len(hits)
        else:
            print(f'  NOMATCH [{seg["start_sec"]:.1f}–{seg["end_sec"]:.1f}s]  {reason}')

    return n_orange, n_yellow


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('transcript', nargs='?',
                    help='Transcript JSON path (default: most recent in transcripts/)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show segments without coloring clips in Resolve')
    ap.add_argument('--timeout', type=int, default=TIMEOUT_SEC,
                    help=f'Relay timeout in seconds (default: {TIMEOUT_SEC})')
    args = ap.parse_args()

    if args.transcript:
        t_path = Path(args.transcript)
        stem   = t_path.stem
    else:
        t_path, stem = latest_transcript()

    print(f'Transcript: {t_path}')
    transcript = json.loads(t_path.read_text(encoding='utf-8'))

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / f'cut-analysis-{stem}.in.md'
    out_path = PROMPTS_DIR / f'cut-analysis-{stem}.out.md'

    if out_path.exists():
        out_path.unlink()

    in_path.write_text(build_prompt(transcript), encoding='utf-8')
    print(f'Relay prompt → {in_path}')
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
            print(f'  {color:6s}  [{seg["start_sec"]:.1f}–{seg["end_sec"]:.1f}s]'
                  f'  {seg.get("confidence", "?")}  {seg.get("reason", "")[:70]}')
        return 0

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1

    project  = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))

    n_orange, n_yellow = apply_colors(segments, fps, timeline, dry_run=False)
    print(f'\nColored: {n_orange} orange (high confidence), {n_yellow} yellow (medium confidence)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
