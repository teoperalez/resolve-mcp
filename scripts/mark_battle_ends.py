"""
Detect end of trainer battles via frame extraction + LLM relay.
Places green markers on the timeline ruler labeled "<Trainer> Battle End".

For each battle in transcripts/battles.json, extracts frames from the source
video (ffmpeg) around the estimated battle end, then relays to Claude Code for
visual identification. Claude reads the image files and returns the end timestamp.

Requires: transcripts/battles.json, ffmpeg on PATH, Resolve connected.
"""
import sys
import os
import json
import time
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PROMPTS_DIR        = Path('plans/prompts')
FRAMES_DIR         = Path('plans/frames')
TRANSCRIPTS_DIR    = Path('transcripts')
TIMEOUT_SEC        = 600
FRAME_INTERVAL_SEC = 30   # seconds between extracted frames
MAX_BATTLE_SEC     = 600  # max battle duration to search
LEAD_IN_SEC        = 30   # seconds after battle start before first frame sample
MAX_FRAMES         = 20   # safety cap per battle


def load_battles() -> list[dict]:
    p = TRANSCRIPTS_DIR / 'battles.json'
    if not p.exists():
        raise FileNotFoundError(f'battles.json not found: {p.resolve()}')
    data = json.loads(p.read_text(encoding='utf-8'))
    return sorted(data, key=lambda b: b['timestamp_sec'])


def load_transcript_segments() -> list[dict]:
    for f in sorted(TRANSCRIPTS_DIR.glob('*.json'),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                print(f'Transcript: {f}')
                return data['segments']
        except Exception:
            pass
    return []


def estimate_end_window(battle: dict, next_start: float | None,
                        segments: list[dict]) -> tuple[float, float]:
    """Use transcript keywords to narrow the search window for battle end."""
    b_start   = battle['timestamp_sec']
    win_start = b_start + LEAD_IN_SEC
    win_end   = b_start + MAX_BATTLE_SEC
    if next_start:
        win_end = min(win_end, next_start - 10)

    cue_keywords = [
        'knocked out', 'fainted', 'defeated', 'we win', 'we won', 'beat',
        'that was', 'we did it', 'victory', 'we lose', 'we lost',
        'got through', 'get through', 'manage to', 'that brings out',
    ]
    earliest_cue = None
    for seg in segments:
        if seg['start'] < win_start or seg['start'] > win_end:
            continue
        if any(kw in seg.get('text', '').lower() for kw in cue_keywords):
            if earliest_cue is None:
                earliest_cue = seg['start']

    if earliest_cue is not None:
        # Narrow: 60s before the cue to 30s after
        return max(win_start, earliest_cue - 60), min(win_end, earliest_cue + 30)
    return win_start, win_end


def extract_frame(source_path: str, ts: float, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['ffmpeg', '-y', '-ss', str(ts), '-i', source_path,
         '-frames:v', '1', '-q:v', '3', str(out)],
        capture_output=True, timeout=30
    )
    return r.returncode == 0 and out.exists()


def build_prompt(battles: list[dict],
                 frame_sets: list[list[tuple[float, Path]]]) -> str:
    sections = []
    for i, (b, frames) in enumerate(zip(battles, frame_sets)):
        header = (f'## Battle {i + 1}: {b["trainer_name"]} '
                  f'(starts at {b["timestamp_sec"]:.1f}s)')
        if not frames:
            sections.append(f'{header}\n(no frames extracted)')
            continue
        lines = [header, 'Read each image file using the Read tool and analyze:']
        for ts, p in frames:
            lines.append(f'- `{p.resolve()}` — {ts:.1f}s')
        sections.append('\n'.join(lines))

    battles_block = '\n\n'.join(sections)

    return f"""You are identifying the END of Pokémon trainer battles from video frame captures.

For each battle below, read the listed image files (using the Read tool on each path) and
identify the frame that best marks the battle end.

**What to look for (priority order):**
1. **Trainer defeat screen** — the losing trainer's sprite or portrait visible in a defeated pose or
   fade-out animation. This is the ideal marker point.
2. **Post-battle breakdown overlay** — a creator-made results/stats screen that appears after the battle.
3. **First non-battle frame** — the overworld map, town, or any screen without the battle UI.
4. **Experience/level-up screen** — the first post-battle game screen if none of the above are clear.

If none of the frames clearly show a battle end, note the closest candidate or return null.

{battles_block}

---

Respond with ONLY a raw JSON array (no markdown fences, no explanation):

[
  {{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 385.3, "confidence": "high", "notes": "Trainer defeat pose visible"}},
  {{"battle_index": 1, "trainer_name": "Falkner", "end_sec": 741.0, "confidence": "medium", "notes": "First overworld frame after battle UI disappears"}},
  {{"battle_index": 2, "trainer_name": "Bugsy", "end_sec": null, "confidence": "low", "notes": "No clear end frame found in extracted range"}}
]
"""


def poll(out_path: Path, timeout_sec: int) -> list:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s — expected {out_path}')


def source_sec_to_tl_frame(source_sec: float, fps: float,
                            v1_clips: list) -> int | None:
    """Map source timestamp (seconds) to timeline frame, accounting for inserted gaps."""
    sf = int(source_sec * fps)
    for clip in v1_clips:
        src_start = clip.GetLeftOffset()
        src_end   = src_start + clip.GetDuration()
        if src_start <= sf < src_end:
            return clip.GetStart() + (sf - src_start)
    return None


def place_markers(results: list[dict], timeline, fps: float,
                  v1_clips: list, dry_run: bool) -> int:
    placed = 0
    for r in results:
        end_sec = r.get('end_sec')
        name    = f'{r["trainer_name"]} Battle End'

        if end_sec is None:
            print(f'  SKIP    {name}: {r.get("notes", "no end detected")}')
            continue

        tl_frame = source_sec_to_tl_frame(end_sec, fps, v1_clips)
        if tl_frame is None:
            tl_frame = timeline.GetStartFrame() + int(end_sec * fps)
            print(f'  APPROX  {name} at {end_sec:.1f}s (approx — source frame between clips)')
        else:
            print(f'  {"DRY " if dry_run else ""}Marker  '
                  f'[{end_sec:.1f}s → tl frame {tl_frame}]  {name}  {r.get("notes", "")}')

        if not dry_run:
            ok = timeline.AddMarker(tl_frame, 'Green', name, r.get('notes', ''), 1)
            if ok:
                placed += 1
            else:
                print(f'           AddMarker returned False for {name}')
        else:
            placed += 1

    return placed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Extract frames and show marker preview without placing in Resolve')
    ap.add_argument('--interval', type=int, default=FRAME_INTERVAL_SEC,
                    help=f'Seconds between extracted frames (default: {FRAME_INTERVAL_SEC})')
    ap.add_argument('--timeout', type=int, default=TIMEOUT_SEC,
                    help=f'Relay timeout in seconds (default: {TIMEOUT_SEC})')
    args = ap.parse_args()

    battles  = load_battles()
    segments = load_transcript_segments()
    print(f'Loaded {len(battles)} battles')

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1

    project  = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))
    v1_clips = timeline.GetItemListInTrack('video', 1) or []

    if not v1_clips:
        print('ERROR: No clips on V1.', file=sys.stderr)
        return 1

    source_path = v1_clips[0].GetMediaPoolItem().GetClipProperty('File Path')
    if not source_path:
        print('ERROR: Could not get source file path from V1.', file=sys.stderr)
        return 1
    print(f'Source: {source_path}')

    # Extract frames around estimated end window for each battle
    frame_sets: list[list[tuple[float, Path]]] = []
    for i, battle in enumerate(battles):
        next_start = battles[i + 1]['timestamp_sec'] if i + 1 < len(battles) else None
        w_start, w_end = estimate_end_window(battle, next_start, segments)

        frames: list[tuple[float, Path]] = []
        ts = w_start
        while ts <= w_end and len(frames) < MAX_FRAMES:
            out = FRAMES_DIR / f'battle-end-{i}-{len(frames):02d}.jpg'
            if extract_frame(source_path, ts, out):
                frames.append((ts, out))
            ts += args.interval

        frame_sets.append(frames)
        print(f'  Battle {i + 1} ({battle["trainer_name"]}): '
              f'{len(frames)} frames [{w_start:.0f}–{w_end:.0f}s]')

    stem     = Path(source_path).stem
    in_path  = PROMPTS_DIR / f'battle-ends-{stem}.in.md'
    out_path = PROMPTS_DIR / f'battle-ends-{stem}.out.md'
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        out_path.unlink()

    in_path.write_text(build_prompt(battles, frame_sets), encoding='utf-8')
    print(f'\nRelay prompt → {in_path}')
    print(f'Waiting for {out_path} ...')

    try:
        results = poll(out_path, timeout_sec=args.timeout)
    except TimeoutError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    print(f'\nReceived {len(results)} result(s).')
    placed = place_markers(results, timeline, fps, v1_clips, dry_run=args.dry_run)
    action = 'Would place' if args.dry_run else 'Placed'
    print(f'{action} {placed}/{len(results)} battle end markers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
