"""
Refine each Battle End marker to the precise transition frame via dense sampling.

Pipeline:
1. Reads battle-ends-<stem>.out.md (initial estimates from mark_battle_ends.py).
2. For each battle, extracts ~41 frames at REFINE_STEP_SEC intervals across a
   ±REFINE_WINDOW_SEC window around the existing estimate.
3. Writes battle-ends-refine-<stem>.in.md and polls for the .out.md response.
4. The relay (Claude in the active chat) should spawn one Haiku subagent per
   battle, each Reading its dense frame list and returning the precise end_sec.
5. On valid response: deletes existing green markers and replaces them with
   precise ones at the new timestamps.

Run AFTER mark_battle_ends.py has placed initial markers.
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
FRAMES_DIR      = Path('plans/frames/refine')
TRANSCRIPTS_DIR = Path('transcripts')
TIMEOUT_SEC     = 900

REFINE_WINDOW_SEC = 5.0   # search ±5s around each existing estimate
REFINE_STEP_SEC   = 0.25  # ~41 frames per battle


def load_initial_results(stem: str) -> list[dict]:
    out_path = PROMPTS_DIR / f'battle-ends-{stem}.out.md'
    if not out_path.exists():
        raise FileNotFoundError(
            f'Initial estimates not found: {out_path}\n'
            f'Run mark_battle_ends.py first.'
        )
    return json.loads(out_path.read_text(encoding='utf-8').strip())


def extract_frame(source_path: str, ts: float, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['ffmpeg', '-y', '-ss', f'{ts:.3f}', '-i', source_path,
         '-frames:v', '1', '-q:v', '2', str(out)],
        capture_output=True, timeout=30
    )
    return r.returncode == 0 and out.exists()


def extract_dense_frames(estimate_sec: float, source_path: str,
                         battle_idx: int) -> list[tuple[float, Path]]:
    frames = []
    n_steps = int((2 * REFINE_WINDOW_SEC) / REFINE_STEP_SEC) + 1
    for i in range(n_steps):
        ts = estimate_sec - REFINE_WINDOW_SEC + i * REFINE_STEP_SEC
        if ts < 0:
            continue
        out = FRAMES_DIR / f'b{battle_idx:02d}-{i:03d}.jpg'
        if extract_frame(source_path, ts, out):
            frames.append((round(ts, 3), out))
    return frames


def build_prompt(results: list[dict],
                 frame_sets: list[list[tuple[float, Path]]]) -> str:
    sections = []
    for i, (r, frames) in enumerate(zip(results, frame_sets)):
        result_str = r.get('result', '?')
        lines = [
            f'## Battle {i}: {r["trainer_name"]} '
            f'(initial estimate {r["end_sec"]:.2f}s, result: {result_str})',
            '',
            f'Dense frames (±{REFINE_WINDOW_SEC}s window @ {REFINE_STEP_SEC}s steps):',
        ]
        for ts, p in frames:
            lines.append(f'- `{p.resolve()}` — {ts:.2f}s')
        sections.append('\n'.join(lines))

    return f"""You are refining the PRECISE end-of-battle frame for Pokémon trainer battles.

Each battle below has a rough initial estimate and a dense set of frames (every {REFINE_STEP_SEC}s across ±{REFINE_WINDOW_SEC}s). Identify the EXACT frame where the battle ends.

## Visual pattern — WIN battles

The composition has gameplay (Game Boy emulator on the left) and a "Crystal score overlay" panel (right side, gym-themed background). The battle is WON when the post-battle screen displays:
- The defeated trainer's full character portrait (revealed art, NOT the in-battle sprite)
- A finalized `SCORE: XX.XX` line on the right overlay
- The trainer's stat panel filled in (EXP, HP, ATK, DEF, etc.)

The battle end is the **first frame** where this post-battle overlay fully replaces the in-battle UI. Look for the moment HP bars / move menu / attack animations DISAPPEAR and the trainer portrait + final score APPEAR.

## Visual pattern — GAVE_UP / LOSS battles

No defeat flourish. Identify the first frame where the in-battle UI clearly ends and the player transitions to overworld / menu / next topic.

## How to analyze

**Delegate one battle per parallel Haiku subagent.** Each subagent should:
1. Read every listed frame in order (Read tool on each `.jpg` path).
2. Find the precise transition frame — the first frame matching the pattern above.
3. Return that frame's timestamp.

Aim for within ±0.25s of the true transition (the sampling step). Always return a number for `end_sec`.

{chr(10).join(sections)}

---

Respond with ONLY a raw JSON array (no markdown fences, no explanation):

[
  {{"battle_index": 0, "trainer_name": "Rival 1", "end_sec": 379.50, "frame_picked": "b00-019.jpg", "confidence": "high", "notes": "First frame with trainer portrait visible + SCORE: 99.9 finalized"}}
]

`end_sec` must be a number drawn from the timestamps listed in this battle's dense frame list.
"""


def poll(out_path: Path, timeout_sec: int) -> list:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s')


def build_v1_source_map(v1_clips, fps):
    """Same as mark_battle_ends.py — source-seconds map for V1 clips."""
    entries = []
    for c in v1_clips:
        tl_start  = c.GetStart()
        tl_end    = tl_start + c.GetDuration()
        src_start = c.GetLeftOffset() / fps
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        entries.append((tl_start, tl_end, src_start, src_end, c))
    return entries


def source_sec_to_tl_frame(source_sec, fps, v1_map, snap_tol_sec=0.5):
    for tl_start, _tl_end, src_start, src_end, _ in v1_map:
        if src_start <= source_sec <= src_end:
            return tl_start + round((source_sec - src_start) * fps)
    for tl_start, _tl_end, src_start, _src_end, _ in v1_map:
        if src_start - snap_tol_sec <= source_sec < src_start:
            return tl_start
    for _tl_start, tl_end, _src_start, src_end, _ in v1_map:
        if src_end < source_sec <= src_end + snap_tol_sec:
            return tl_end - 1
    return None


def clear_existing_green_markers(timeline) -> int:
    markers = timeline.GetMarkers() or {}
    green = [f for f, m in markers.items() if m.get('color') == 'Green']
    for f in green:
        timeline.DeleteMarkerAtFrame(f)
    return len(green)


def place_refined_markers(refined: list[dict], timeline, fps, v1_map,
                          dry_run: bool) -> int:
    """Mirror of mark_battle_ends.place_markers but uses refined estimates."""
    placed = 0
    result_labels = {'win': 'Win', 'loss': 'Loss', 'gave_up': 'Gave Up'}
    tl_start_frame = timeline.GetStartFrame()

    for r in refined:
        end_sec = r.get('end_sec')
        if end_sec is None:
            print(f'  SKIP  {r["trainer_name"]}: no end_sec')
            continue

        result_str = result_labels.get(r.get('result', ''), r.get('result', ''))
        name = (f'{r["trainer_name"]} Battle End ({result_str})' if result_str
                else f'{r["trainer_name"]} Battle End')
        notes = r.get('notes', '')

        tl_frame = source_sec_to_tl_frame(end_sec, fps, v1_map)
        if tl_frame is None:
            print(f'  SKIP  [{end_sec:.2f}s]  {name}: source second in a cut region')
            continue

        rel_frame = tl_frame - tl_start_frame
        print(f'  {"DRY " if dry_run else ""}Marker  '
              f'[{end_sec:.2f}s → frame {tl_frame} (rel {rel_frame})]  {name}')

        if not dry_run:
            ok = timeline.AddMarker(rel_frame, 'Green', name, notes, 1)
            placed += int(bool(ok))
        else:
            placed += 1
    return placed


def find_source_path(v1_map, first_battle_sec: float) -> str | None:
    """Locate the gameplay source via the V1 clip that contains the first
    battle's source second."""
    for _ts, _te, src_start, src_end, clip in v1_map:
        if src_start <= first_battle_sec <= src_end:
            p = clip.GetMediaPoolItem().GetClipProperty('File Path')
            if p:
                return p
    # Fallback: longest clip's source
    longest = max(v1_map, key=lambda e: e[1] - e[0])
    return longest[4].GetMediaPoolItem().GetClipProperty('File Path') or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Show refined markers without modifying Resolve')
    ap.add_argument('--skip-relay', action='store_true',
                    help='Reuse existing refine .out.md without re-extracting frames')
    ap.add_argument('--timeout', type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

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

    # Determine which stem we're refining via the most recent battle-ends-*.in.md
    in_files = sorted(PROMPTS_DIR.glob('battle-ends-*.in.md'),
                      key=lambda f: f.stat().st_mtime, reverse=True)
    in_files = [f for f in in_files if 'refine' not in f.name]
    if not in_files:
        print('ERROR: No battle-ends-*.in.md found. Run mark_battle_ends.py first.',
              file=sys.stderr)
        return 1
    # Name like "battle-ends-Brock_Red_Blue_versus_Crystl.in.md" — strip both
    # the leading "battle-ends-" and trailing ".in.md".
    stem = in_files[0].name[len('battle-ends-'):-len('.in.md')]
    print(f'Stem: {stem}')

    initial = load_initial_results(stem)
    print(f'Loaded {len(initial)} initial battle ends.')

    refine_in  = PROMPTS_DIR / f'battle-ends-refine-{stem}.in.md'
    refine_out = PROMPTS_DIR / f'battle-ends-refine-{stem}.out.md'

    if args.skip_relay:
        if not refine_out.exists():
            print(f'ERROR: --skip-relay requires existing {refine_out}', file=sys.stderr)
            return 1
        refined = json.loads(refine_out.read_text(encoding='utf-8').strip())
        print(f'Skip-relay: loaded {len(refined)} refined results from {refine_out}')
    else:
        first_sec = initial[0]['end_sec']
        source_path = find_source_path(v1_map, first_sec)
        if not source_path:
            print('ERROR: Could not identify gameplay source file.', file=sys.stderr)
            return 1
        print(f'Source: {source_path}')

        frame_sets: list[list[tuple[float, Path]]] = []
        for i, r in enumerate(initial):
            frames = extract_dense_frames(r['end_sec'], source_path, i)
            print(f'  Battle {i} ({r["trainer_name"]}): {len(frames)} frames '
                  f'around {r["end_sec"]:.2f}s')
            frame_sets.append(frames)

        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        if refine_out.exists():
            refine_out.unlink()
        refine_in.write_text(build_prompt(initial, frame_sets), encoding='utf-8')
        print(f'\nRelay prompt → {refine_in}')
        print(f'Waiting for {refine_out} ...')

        try:
            refined = poll(refine_out, timeout_sec=args.timeout)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    # Merge refined end_sec into the initial records (so result/notes carry over)
    by_idx = {r.get('battle_index', i): r for i, r in enumerate(refined)}
    merged = []
    for i, base in enumerate(initial):
        upd = by_idx.get(i)
        if upd and upd.get('end_sec') is not None:
            base = {**base, **upd}
        merged.append(base)

    # Re-fetch live Resolve handles — long polls can stale the previous refs.
    project  = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    v1_clips = timeline.GetItemListInTrack('video', 1) or []
    v1_map   = build_v1_source_map(v1_clips, fps)

    if not args.dry_run:
        n = clear_existing_green_markers(timeline)
        print(f'\nCleared {n} existing green marker(s).')

    print(f'\nPlacing refined markers:')
    placed = place_refined_markers(merged, timeline, fps, v1_map, args.dry_run)
    action = 'Would place' if args.dry_run else 'Placed'
    print(f'\n{action} {placed}/{len(merged)} refined battle end markers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
