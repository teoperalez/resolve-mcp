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
    files = sorted(TRANSCRIPTS_DIR.glob('*.json'),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f'No transcript JSON in {TRANSCRIPTS_DIR.resolve()}')
    return files[0], files[0].stem


def build_prompt(transcript: dict) -> str:
    segs = transcript.get('segments', [])
    lines = [f'[{s["start"]:.2f}–{s["end"]:.2f}] {s.get("text", "").strip()}'
             for s in segs]
    body = '\n'.join(lines)
    return f"""Analyze this Pokémon gameplay commentary transcript to identify segments that should be cut.

## Transcript (timestamps in seconds)

{body}

---

## Task

Identify two types of cut candidates:

### 1. Non-dialogue / artifacts
Segments with NO genuine spoken commentary:
- Very short segments (< 2 s) where the transcribed text is impossibly long for the duration —
  Whisper hallucinating over silence, a mic bump, or background noise
- Garbled or nonsensical text with no connection to Pokémon gameplay
KEEP: laughter, reactions ("oh no!", "yes!", "let's go"), brief genuine utterances

### 2. False starts, repetitions, topic changes
- Speaker begins a thought but abandons and restarts it moments later
- Substantially the same content repeated within ~30 seconds
- Speaker starts discussing one Pokémon/strategy/move but significantly pivots mid-sentence
Use the full context (game being played, current challenge rules, battle situation) to judge.

---

## Output

Respond with ONLY a raw JSON array (no markdown fences, no explanation):

[
  {{"start_sec": 12.3, "end_sec": 14.1, "confidence": "high", "type": "non_dialogue", "reason": "0.5 s segment — 15-word transcription impossible for that duration"}},
  {{"start_sec": 45.0, "end_sec": 52.3, "confidence": "medium", "type": "false_start", "reason": "Starts describing Leech Seed strategy then pivots to Tackle approach"}}
]

"confidence": "high"   — cut is almost certain
"confidence": "medium" — cut is likely but context is ambiguous
Only include segments you are at least medium-confident about.
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
