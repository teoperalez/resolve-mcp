"""
Detect end of trainer battles via transcript analysis + frame validation.

For each battle in transcripts/battles.json:
1. Collects the full battle transcript and passes it to Claude for contextual analysis.
2. Extracts frames spread across the battle window (up to MAX_FRAMES per battle).
3. Claude reads the transcript contextually, estimates where the battle ended,
   validates with frames near that estimate, and reassesses if no clear
   battle→non-battle transition is found in that region.
4. Always returns an end_sec — never null.

Places green timeline markers labeled "<Trainer> Battle End (win|loss|gave up)".

Requires: transcripts/battles.json, ffmpeg on PATH, Resolve connected.
"""
import sys
import os
import re
import json
import time
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PROMPTS_DIR     = Path('plans/prompts')
FRAMES_DIR      = Path('plans/frames')
TRANSCRIPTS_DIR = Path('transcripts')
TIMEOUT_SEC     = 600
MAX_BATTLE_SEC  = 1200   # max seconds to search after battle start
LEAD_IN_SEC     = 20     # skip this many seconds after battle start before sampling
MAX_FRAMES      = 10     # max frames per battle
MIN_INTERVAL    = 10     # minimum seconds between frames


def load_battles() -> list[dict]:
    p = TRANSCRIPTS_DIR / 'battles.json'
    if not p.exists():
        raise FileNotFoundError(f'battles.json not found: {p.resolve()}')
    return sorted(json.loads(p.read_text(encoding='utf-8')),
                  key=lambda b: b['timestamp_sec'])


def load_transcript() -> dict:
    for f in sorted(TRANSCRIPTS_DIR.glob('*.json'),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                print(f'Transcript: {f}')
                return data
        except Exception:
            pass
    return {}


def battle_segments(battle: dict, next_start: float | None,
                    segments: list[dict]) -> list[dict]:
    """Return all transcript segments for this battle's time window."""
    b_start = battle['timestamp_sec']
    max_end = b_start + MAX_BATTLE_SEC
    if next_start:
        max_end = min(max_end, next_start - 5)
    return [s for s in segments if b_start <= s['start'] <= max_end]


def extract_frame(source_path: str, ts: float, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['ffmpeg', '-y', '-ss', str(ts), '-i', source_path,
         '-frames:v', '1', '-q:v', '3', str(out)],
        capture_output=True, timeout=30
    )
    return r.returncode == 0 and out.exists()


def extract_battle_frames(battle: dict, next_start: float | None,
                           source_path: str, battle_idx: int
                           ) -> list[tuple[float, Path]]:
    """Extract up to MAX_FRAMES spread evenly across the battle window."""
    b_start   = battle['timestamp_sec']
    win_start = b_start + LEAD_IN_SEC
    win_end   = b_start + MAX_BATTLE_SEC
    if next_start:
        win_end = min(win_end, next_start - 5)

    window   = max(0.0, win_end - win_start)
    interval = max(MIN_INTERVAL, window / MAX_FRAMES)

    frames: list[tuple[float, Path]] = []
    ts = win_start
    while ts <= win_end and len(frames) < MAX_FRAMES:
        out = FRAMES_DIR / f'battle-end-{battle_idx}-{len(frames):02d}.jpg'
        if extract_frame(source_path, ts, out):
            frames.append((ts, out))
        ts += interval
    return frames


def build_prompt(battles: list[dict],
                 ctx_segs: list[list[dict]],
                 frame_sets: list[list[tuple[float, Path]]]) -> str:
    sections = []
    for i, (b, segs, frames) in enumerate(zip(battles, ctx_segs, frame_sets)):
        lines = [f'## Battle {i + 1}: {b["trainer_name"]} '
                 f'(starts at {b["timestamp_sec"]:.1f}s)']

        lines.append('\n### Full battle transcript:')
        if segs:
            for s in segs:
                lines.append(f'[{s["start"]:.1f}s] {s.get("text", "").strip()}')
        else:
            lines.append('(no transcript segments in this window)')

        lines.append('\n### Frames across the battle window (read each with Read tool):')
        if frames:
            for ts, p in frames:
                lines.append(f'- `{p.resolve()}` — {ts:.1f}s')
        else:
            lines.append('(no frames extracted)')

        sections.append('\n'.join(lines))

    return f"""You are identifying the END of Pokémon trainer battles in a YouTube video.

For each battle below, follow this process:

1. **Read the full transcript contextually.** Understand the complete narrative arc of the battle —
   whether it was won, lost, or abandoned as impossible. Do not look for specific phrases; reason
   about the overall flow of commentary.

2. **Form an estimate** of when the battle ended based on that contextual understanding.

3. **Read the frame images** (using the Read tool on each listed path), starting with the frames
   nearest your estimate. Look for the battle→non-battle transition:
   - Trainer defeat screen — trainer sprite/portrait in defeated pose or fade-out
   - Post-battle breakdown overlay the creator uses
   - First frame showing the overworld, town, or any screen without battle UI

4. **If no clear transition is visible near your estimate**, check frames earlier and later in the
   list and reassess. The true end may be somewhat before or after where the transcript suggested.

5. **For impossible / gave-up battles:** the end is when the player clearly moves on — the last
   moment of battle-specific commentary before transitioning to meta-analysis or the next topic.

6. **If the video cuts directly from battle to a non-battle screen**, use that first non-battle frame.

7. **Always return an end_sec.** If frames are ambiguous, use your transcript-based estimate.

{chr(10).join(sections)}

---

Respond with ONLY a raw JSON array (no markdown fences, no explanation):

[
  {{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 381.0, "result": "win", "confidence": "high", "notes": "Frame at 379s shows trainer defeated; transcript confirms easy victory"}},
  {{"battle_index": 4, "trainer_name": "Bugsy", "end_sec": 2380.0, "result": "gave_up", "confidence": "high", "notes": "Transcript shows creator gave up and moved to analysis at 2378s"}}
]

"result" must be one of: "win", "loss", "gave_up"
Never return null for end_sec.
"""


def poll(out_path: Path, timeout_sec: int) -> list:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s')


def build_v1_source_map(v1_clips, fps):
    """For each V1 clip: (tl_start, tl_end, src_start_sec, src_end_sec, clip).

    Mirrors build_a1_map() in insert_battle_gaps.py — works in source seconds so
    matching is robust to cuts and any (small) source/timeline fps drift.
    Assumes source_fps == timeline_fps, consistent with the rest of the codebase.
    """
    entries = []
    for c in v1_clips:
        tl_start  = c.GetStart()
        tl_end    = tl_start + c.GetDuration()
        src_start = c.GetLeftOffset() / fps
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        entries.append((tl_start, tl_end, src_start, src_end, c))
    return entries


def source_sec_to_tl_frame(source_sec: float, fps: float, v1_map,
                            snap_tol_sec: float = 0.5) -> int | None:
    """Convert a source-file second to a timeline frame by finding the V1 clip
    whose source range contains source_sec. Snap-forward/backward by up to
    snap_tol_sec when the timestamp lands just outside an adjacent clip's range
    (e.g., Whisper end times that round slightly past a cut)."""
    # Exact match — source_sec is inside a V1 clip's source range
    for tl_start, _tl_end, src_start, src_end, _ in v1_map:
        if src_start <= source_sec <= src_end:
            return tl_start + round((source_sec - src_start) * fps)

    # Snap-forward — source_sec is just before a clip's source start
    for tl_start, _tl_end, src_start, _src_end, _ in v1_map:
        if src_start - snap_tol_sec <= source_sec < src_start:
            return tl_start

    # Snap-backward — source_sec is just past a clip's source end
    for _tl_start, tl_end, _src_start, src_end, _ in v1_map:
        if src_end < source_sec <= src_end + snap_tol_sec:
            return tl_end - 1

    return None


def place_markers(results: list[dict], timeline, fps: float,
                  v1_map, dry_run: bool) -> int:
    placed = 0
    result_labels = {'win': 'Win', 'loss': 'Loss', 'gave_up': 'Gave Up'}

    # tl.AddMarker takes a frame RELATIVE to timeline start, not an absolute
    # internal frame. v1_map's tl_start/tl_end are absolute (from clip.GetStart),
    # so subtract the timeline's start frame when calling AddMarker.
    tl_start_frame = timeline.GetStartFrame()

    for r in results:
        end_sec = r.get('end_sec')
        if end_sec is None:
            print(f'  SKIP  {r["trainer_name"]}: no end_sec in response')
            continue

        result_str = result_labels.get(r.get('result', ''), r.get('result', ''))
        name       = f'{r["trainer_name"]} Battle End ({result_str})'
        notes      = r.get('notes', '')

        tl_frame = source_sec_to_tl_frame(end_sec, fps, v1_map)
        if tl_frame is None:
            # No V1 clip covers this source second — the editor cut this region.
            # Skip rather than placing a wildly-off marker via the old fallback.
            print(f'  SKIP  [{end_sec:.1f}s]  {name}: source second is in a '
                  f'cut region (no V1 clip covers it)')
            continue

        rel_frame = tl_frame - tl_start_frame
        print(f'  {"DRY " if dry_run else ""}Marker  '
              f'[{end_sec:.1f}s → frame {tl_frame} (rel {rel_frame})]  {name}  {notes}')

        if not dry_run:
            ok = timeline.AddMarker(rel_frame, 'Green', name, notes, 1)
            if ok:
                placed += 1
            else:
                print(f'           AddMarker failed for {name}')
        else:
            placed += 1

    return placed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Show marker preview without placing in Resolve')
    ap.add_argument('--skip-relay', action='store_true',
                    help='Skip frame extraction and relay — read existing .out.md directly and re-place markers')
    ap.add_argument('--timeout', type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

    battles    = load_battles()
    transcript = load_transcript()
    segments   = transcript.get('segments', [])
    print(f'Loaded {len(battles)} battles, {len(segments)} transcript segments')

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

    v1_map = build_v1_source_map(v1_clips, fps)

    # Find gameplay source file by matching first battle timestamp via the
    # source-seconds map (same approach used for marker placement below).
    source_path = None
    if battles:
        target_sec = battles[0]['timestamp_sec']
        for _tl_s, _tl_e, src_start, src_end, clip in v1_map:
            if src_start <= target_sec <= src_end:
                source_path = clip.GetMediaPoolItem().GetClipProperty('File Path')
                if source_path:
                    break
    if not source_path:
        # Last-resort: longest V1 clip's underlying source
        clip = max(v1_clips, key=lambda c: c.GetDuration())
        source_path = clip.GetMediaPoolItem().GetClipProperty('File Path') or ''
    if not source_path:
        print('ERROR: Could not identify gameplay source file.', file=sys.stderr)
        return 1
    print(f'Source: {source_path}')

    stem     = re.sub(r'[^\w\-]', '_', Path(source_path).stem)
    out_path = PROMPTS_DIR / f'battle-ends-{stem}.out.md'
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        print(f'Skip-relay: reading existing {out_path}')
        results = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        ctx_segs:   list[list[dict]]               = []
        frame_sets: list[list[tuple[float, Path]]] = []

        for i, battle in enumerate(battles):
            next_start = battles[i + 1]['timestamp_sec'] if i + 1 < len(battles) else None

            segs = battle_segments(battle, next_start, segments)
            ctx_segs.append(segs)

            frames = extract_battle_frames(battle, next_start, source_path, i)
            frame_sets.append(frames)

            b_start = battle['timestamp_sec']
            win_end = min(b_start + MAX_BATTLE_SEC, next_start - 5 if next_start else b_start + MAX_BATTLE_SEC)
            print(f'  Battle {i + 1} ({battle["trainer_name"]}): '
                  f'{len(segs)} transcript segs, {len(frames)} frames '
                  f'[{b_start + LEAD_IN_SEC:.0f}–{win_end:.0f}s]')

        in_path = PROMPTS_DIR / f'battle-ends-{stem}.in.md'
        if out_path.exists():
            out_path.unlink()

        in_path.write_text(build_prompt(battles, ctx_segs, frame_sets), encoding='utf-8')
        print(f'\nRelay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')

        try:
            results = poll(out_path, timeout_sec=args.timeout)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    print(f'\nReceived {len(results)} result(s).')
    placed = place_markers(results, timeline, fps, v1_map, dry_run=args.dry_run)
    action = 'Would place' if args.dry_run else 'Placed'
    print(f'{action} {placed}/{len(results)} battle end markers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
