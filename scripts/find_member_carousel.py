"""
Find the first V1 clip after the last battle end that displays the "Member
Carousel" style overlay (Pokémon at bottom-left, member name centered in
yellow text, badge at bottom-right). Places a "Member Carousel Start" marker.

Algorithm:
  1. Find the LAST green marker on the current timeline (= final battle end).
  2. Collect V1 clips starting at or after that marker (up to MAX_CANDIDATES).
  3. For each candidate clip i, extract:
       - first frame  (clip[i].first)
       - last frame of the clip immediately before it (clip[i-1].last)
  4. Write relay prompt to plans/prompts/member-carousel-<stem>.in.md.
  5. Claude classifies each pair and identifies the start clip:
       - first clip i where first[i] has the style AND last[i-1] doesn't
       - (if last[i-1] also has it, the carousel started in the previous
         clip — answer with clip i-1 instead)
  6. Script reads .out.md and places "Member Carousel Start" marker at the
     start of the chosen clip.

Usage:
    python find_member_carousel.py [--max-candidates N] [--dry-run]
                                   [--skip-relay] [--timeout-sec 600]
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

PROMPTS_DIR    = Path('plans/prompts')
FRAMES_DIR     = Path('plans/frames/member-carousel')
MAX_CANDIDATES = 30
TIMEOUT_SEC    = 600


def extract_frame(source_path: str, src_frame: int, fps: float, out: Path) -> bool:
    """Extract a single frame at the given source-frame using ffmpeg."""
    out.parent.mkdir(parents=True, exist_ok=True)
    ts = src_frame / fps
    r = subprocess.run(
        ['ffmpeg', '-y', '-ss', f'{ts:.3f}', '-i', source_path,
         '-frames:v', '1', '-q:v', '2', str(out)],
        capture_output=True, timeout=30
    )
    return r.returncode == 0 and out.exists()


def file_for_clip(clip):
    mpi = clip.GetMediaPoolItem()
    return mpi.GetClipProperty('File Path') if mpi else ''


def collect_candidates(v1_clips, after_tl_frame: int, max_n: int):
    """Return list of (idx_in_v1, clip) for clips starting at or after the
    given timeline frame. idx_in_v1 is the original index in v1_clips so we
    can find the previous clip later."""
    out = []
    for i, c in enumerate(v1_clips):
        if c.GetStart() >= after_tl_frame:
            out.append((i, c))
            if len(out) >= max_n:
                break
    return out


def build_prompt(candidates, prev_clips, fps, last_battle_tl_frame, tl_start_frame):
    """Each candidate has its first-frame jpg and the previous clip's last-frame
    jpg side by side."""
    lines = ["""You are looking for the moment a "Member Carousel" / "Member Thank You" overlay STARTS in a Pokémon gameplay video.

## What the carousel looks like

When the carousel is active, the **bottom strip** of the frame shows:
- A Pokémon sprite/artwork on the **bottom-LEFT**
- A member NAME centered in the bottom-middle (usually in bright yellow text, sometimes with an "OPHELIA" / "LAVENDAR REGARDS" / etc style)
- A gym BADGE icon on the **bottom-RIGHT** (typically a small geometric/octagonal colored badge)

The rest of the frame (top portion) still shows the regular gameplay video composition (Game Boy emulator + Crystal score overlay). The carousel is an OVERLAY added in post — it does not replace the underlying frame.

## Frames

For each candidate clip i, you have TWO frames:
- `first[i]` — the first frame of clip i
- `prev_last[i]` — the last frame of the clip immediately before i (i.e., clip i-1's final frame)

Classify each as "carousel" (style present) or "no carousel" (no overlay at bottom).

## Decision rule

Find the smallest i such that `first[i]` is "carousel":
- If `prev_last[i]` is ALSO "carousel" → the carousel actually started in the previous clip. Answer with clip i-1.
- If `prev_last[i]` is "no carousel" → the carousel started exactly at clip i. Answer with clip i.

If no candidate clip has a "carousel" first frame, answer with `chosen_v1_index: null`.

## How to analyze

Spawn ONE Haiku subagent. It should:
1. Read each listed frame in order.
2. For each clip, decide: is the carousel style present at first[i]? At prev_last[i]?
3. Apply the decision rule above.
4. Return the JSON below.

"""]

    for cand_idx, (v1_idx, c) in enumerate(candidates):
        tl_start_rel = (c.GetStart() - tl_start_frame) / fps
        first_path  = FRAMES_DIR / f'cand-{cand_idx:02d}-first.jpg'
        prev_path   = FRAMES_DIR / f'cand-{cand_idx:02d}-prev-last.jpg'
        prev_clip   = prev_clips[cand_idx]
        prev_v1_idx = v1_idx - 1
        lines.append(f"### Candidate clip {cand_idx}  "
                     f"(v1_idx={v1_idx}, tl_start={tl_start_rel:.2f}s rel)")
        lines.append(f"- `first[{cand_idx}]`  →  `{first_path.resolve()}`")
        prev_info = f"(v1_idx={prev_v1_idx})" if prev_clip is not None else "(none — first V1 clip)"
        lines.append(f"- `prev_last[{cand_idx}]` →  `{prev_path.resolve()}`  {prev_info}")

    lines.append("""
## Output

Reply with ONLY a single JSON object (no markdown fences, no extra text):

{"chosen_v1_index": <int or null>, "chosen_cand_index": <int or null>, "first_carousel_cand": <int or null>, "previous_also_carousel": <bool>, "reasoning": "1-2 sentences"}

- `chosen_v1_index` = the v1_idx of the clip that starts the carousel (see decision rule).
- `chosen_cand_index` = the candidate index in this prompt of the chosen clip (or null if it's the clip immediately before candidate 0 — i.e., prev_last[0] already had the style — in which case set chosen_cand_index=-1).
- `first_carousel_cand` = the smallest candidate index whose first frame shows the carousel.
- `previous_also_carousel` = whether prev_last[first_carousel_cand] also showed the carousel.
""")
    return '\n'.join(lines)


def poll(out_path: Path, timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--max-candidates', type=int, default=MAX_CANDIDATES)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--skip-relay', action='store_true')
    ap.add_argument('--timeout-sec', type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    tl      = project.GetCurrentTimeline()
    fps     = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()
    print(f'Timeline: "{tl.GetName()}"  fps={fps}  start={tl_start}')

    # ── Find the last green (Battle End) marker ─────────────────────────────
    markers = tl.GetMarkers() or {}
    greens  = [f for f, m in markers.items() if m.get('color') == 'Green']
    if not greens:
        print('ERROR: no green markers on this timeline.', file=sys.stderr)
        return 1
    last_rel = max(greens)
    last_abs = tl_start + last_rel
    print(f'Last green marker: rel={last_rel}  abs={last_abs}  '
          f'tl={last_rel/fps:.2f}s  '
          f'name={markers[last_rel].get("name", "")!r}')

    # ── Get V1 clips ─────────────────────────────────────────────────────────
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    print(f'V1 clips: {len(v1)}')

    # Candidates: clips starting at or after the last battle marker
    candidates = collect_candidates(v1, last_abs, args.max_candidates)
    print(f'Candidates (clips starting ≥ last battle marker): {len(candidates)}')
    if not candidates:
        print('ERROR: no V1 clips after the last battle marker.', file=sys.stderr)
        return 1

    # For each candidate, look up the immediately-previous V1 clip
    prev_clips = []
    for v1_idx, _c in candidates:
        prev_clips.append(v1[v1_idx - 1] if v1_idx > 0 else None)

    stem = re.sub(r'[^\w\-]', '_', tl.GetName())
    in_path  = PROMPTS_DIR / f'member-carousel-{stem}.in.md'
    out_path = PROMPTS_DIR / f'member-carousel-{stem}.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        result = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        # ── Extract frames for each candidate ────────────────────────────────
        print(f'\nExtracting frames...')
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        for cand_idx, (v1_idx, c) in enumerate(candidates):
            mpi_path = file_for_clip(c)
            first_src_frame = c.GetLeftOffset()
            extract_frame(mpi_path, first_src_frame, fps,
                          FRAMES_DIR / f'cand-{cand_idx:02d}-first.jpg')

            prev = prev_clips[cand_idx]
            if prev is not None:
                prev_mpi = file_for_clip(prev)
                prev_last_src_frame = prev.GetLeftOffset() + prev.GetDuration() - 1
                extract_frame(prev_mpi, prev_last_src_frame, fps,
                              FRAMES_DIR / f'cand-{cand_idx:02d}-prev-last.jpg')
        print(f'  Done. Wrote {len(candidates)*2} frames to {FRAMES_DIR}/')

        # ── Write relay prompt ───────────────────────────────────────────────
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        in_path.write_text(
            build_prompt(candidates, prev_clips, fps, last_abs, tl_start),
            encoding='utf-8'
        )
        print(f'\nRelay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')

        try:
            result = poll(out_path, timeout_sec=args.timeout_sec)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    print(f'\nResult: {json.dumps(result, indent=2)}')

    chosen_v1 = result.get('chosen_v1_index')
    if chosen_v1 is None:
        print('No carousel start identified (chosen_v1_index is null).')
        return 0

    if chosen_v1 < 0 or chosen_v1 >= len(v1):
        print(f'ERROR: chosen_v1_index={chosen_v1} out of range [0, {len(v1)})',
              file=sys.stderr)
        return 1

    chosen_clip   = v1[chosen_v1]
    marker_abs    = chosen_clip.GetStart()
    marker_rel    = marker_abs - tl_start
    print(f'\nPlacing marker at v1[{chosen_v1}].start: '
          f'abs={marker_abs} rel={marker_rel} '
          f'({marker_rel/fps:.2f}s into timeline)')

    if not args.dry_run:
        ok = tl.AddMarker(marker_rel, 'Yellow', 'Member Carousel Start',
                          result.get('reasoning', ''), 1)
        print(f'AddMarker returned: {ok}')
    else:
        print('  (--dry-run: skipping AddMarker call)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
