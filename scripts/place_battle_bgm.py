"""
Chain random BGM tracks on A2 from the end of the existing Dual Screen
Lovelife clip up to the start of the outro, pausing during battles.

Rules:
  - Random pick from the bgm bin, EXCLUDING "Dual Screen Lovelife" and
    "Golden Goose". The previous track is also excluded each round to avoid
    back-to-back repeats.
  - If the placed BGM would overlap the next battle start, truncate it at
    the battle start frame.
  - Between battle start and battle end → silence on A2 (no BGM).
  - At each battle end → pick a new random BGM.
  - Continue chaining BGMs within each non-battle segment until the segment
    ends (next battle, or start of outro).

Battle start positions come from `transcripts/battles.json` (mapped through
the V1 source-seconds map). Battle end positions come from the green
markers on the current timeline.

Usage:
    python place_battle_bgm.py [--seed N] [--track-index 2] [--dry-run]
"""
import sys
import os
import json
import random
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

EXCLUDED_TRACKS  = {'dual screen lovelife', 'golden goose'}
BATTLES_JSON     = Path('transcripts/battles.json')
TAGS_PATH        = Path.home() / '.resolve-mcp' / 'bgm-tags.json'
MIN_BGM_FRAMES   = 12   # ~0.2s — skip placements shorter than this


# ── Bin / clip lookup ──────────────────────────────────────────────────────

def find_subfolder(parent, name: str):
    for sub in (parent.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub
    return None


def collect_clips_recursive(bin_):
    out = list(bin_.GetClipList() or [])
    for sub in (bin_.GetSubFolderList() or []):
        out.extend(collect_clips_recursive(sub))
    return out


# ── Duration / fps helpers (mirrors insert_intro_outro & place_bgm) ────────

def _mpi_clip_fps(mpi):
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            v = float(props.get(key) or 0)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return None


def mpi_duration_frames(mpi, timeline_fps: float):
    props = mpi.GetClipProperty() or {}
    clip_fps = _mpi_clip_fps(mpi) or timeline_fps
    for key in ('Audio Duration', 'Video Duration', 'Duration'):
        raw = (props.get(key) or '').strip()
        if not raw:
            continue
        parts = raw.replace(';', ':').split(':')
        if len(parts) == 4:
            h, m, s, f = (int(x) for x in parts)
            total_sec = h * 3600 + m * 60 + s + f / clip_fps
            frames = round(total_sec * timeline_fps)
            if frames > 0:
                return frames
        try:
            n = int(raw)
            if n > 0:
                return round(n * timeline_fps / clip_fps) if clip_fps != timeline_fps else n
        except ValueError:
            pass
    try:
        n = int(props.get('Frames') or 0)
        if n > 0:
            return round(n * timeline_fps / clip_fps) if clip_fps != timeline_fps else n
    except (ValueError, TypeError):
        pass
    return None


# ── V1 source-seconds mapping ──────────────────────────────────────────────

def build_v1_source_map(v1_clips, fps):
    entries = []
    for c in v1_clips:
        tl_start  = c.GetStart()
        tl_end    = tl_start + c.GetDuration()
        src_start = c.GetLeftOffset() / fps
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        entries.append((tl_start, tl_end, src_start, src_end, c))
    return entries


def source_sec_to_tl_abs(source_sec, fps, v1_map, snap_tol_sec=0.5):
    for tl_start, _te, src_start, src_end, _c in v1_map:
        if src_start <= source_sec <= src_end:
            return tl_start + round((source_sec - src_start) * fps)
    for tl_start, _te, src_start, _se, _c in v1_map:
        if src_start - snap_tol_sec <= source_sec < src_start:
            return tl_start
    for _ts, tl_end, _ss, src_end, _c in v1_map:
        if src_end < source_sec <= src_end + snap_tol_sec:
            return tl_end - 1
    return None


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seed', type=int, default=None,
                    help='Random seed for reproducible BGM selection')
    ap.add_argument('--track-index', type=int, default=2,
                    help='Audio track to place on (default: 2 = A2)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    import DaVinciResolveScript as dvr
    resolve  = dvr.scriptapp('Resolve')
    project  = resolve.GetProjectManager().GetCurrentProject()
    pool     = project.GetMediaPool()
    tl       = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    print(f'Timeline: "{tl.GetName()}"  fps={fps}  start={tl_start}')

    # ── BGM bin + eligible tracks ───────────────────────────────────────────
    root      = pool.GetRootFolder()
    assets    = find_subfolder(root, 'assets')
    bgm_bin   = find_subfolder(assets, 'bgm') if assets else None
    if bgm_bin is None:
        print('ERROR: bgm bin not found.', file=sys.stderr)
        return 1

    # Load bgm-tags.json if it exists — we filter the random pool to ONLY
    # tracks tagged "general" so battle-tagged tracks aren't picked for the
    # between-battle BGM segments.
    tags: dict = {}
    if TAGS_PATH.exists():
        try:
            tags = json.loads(TAGS_PATH.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'WARN: could not parse {TAGS_PATH}: {e} — using all tracks',
                  file=sys.stderr)

    all_bgm  = collect_clips_recursive(bgm_bin)
    eligible = []
    for mpi in all_bgm:
        full_name = (mpi.GetName() or '').strip()
        stem      = Path(full_name).stem
        if stem.lower() in EXCLUDED_TRACKS:
            continue
        # If tags exist, restrict to "general"
        if tags:
            t = (tags.get(full_name) or {}).get('tag', 'general')
            if t != 'general':
                continue
        dur = mpi_duration_frames(mpi, fps)
        if dur and dur >= MIN_BGM_FRAMES:
            eligible.append((mpi, dur, stem))

    print(f'Eligible BGM tracks: {len(eligible)}')
    if not eligible:
        print('ERROR: no eligible BGM tracks after exclusions.', file=sys.stderr)
        return 1
    for _m, d, n in sorted(eligible, key=lambda x: x[2].lower()):
        print(f'  {n:35s}  {d}f  ({d/fps:.1f}s)')

    # ── V1: identify gameplay clips, outro start, DSL end ──────────────────
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    if len(v1) < 3:
        print('ERROR: V1 needs intro + gameplay + outro.', file=sys.stderr)
        return 1
    outro_tl_start = v1[-1].GetStart()
    print(f'Outro starts: abs={outro_tl_start}  rel={(outro_tl_start - tl_start)/fps:.2f}s')

    a2 = sorted(tl.GetItemListInTrack('audio', args.track_index) or [],
                key=lambda c: c.GetStart())
    if not a2:
        print(f'ERROR: A{args.track_index} is empty. Run place_bgm.py first.',
              file=sys.stderr)
        return 1
    dsl_end_abs = a2[-1].GetStart() + a2[-1].GetDuration()
    print(f'A{args.track_index} current end (DSL end): abs={dsl_end_abs}  '
          f'rel={(dsl_end_abs - tl_start)/fps:.2f}s')

    if dsl_end_abs >= outro_tl_start:
        print('A2 already extends to or past outro — nothing to do.')
        return 0

    # Gameplay V1 = exclude intro (v1[0]) and outro (v1[-1])
    v1_map = build_v1_source_map(v1[1:-1], fps)

    # ── Read battles.json ──────────────────────────────────────────────────
    if not BATTLES_JSON.exists():
        print(f'ERROR: {BATTLES_JSON} not found.', file=sys.stderr)
        return 1
    battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))
    print(f'Battles loaded: {len(battles)}')

    # ── Green markers (battle ends) ────────────────────────────────────────
    markers = tl.GetMarkers() or {}
    greens  = sorted(((f, m.get('name', '')) for f, m in markers.items()
                      if m.get('color') == 'Green'))
    print(f'Green markers: {len(greens)}')

    # ── Build battle pairs: (start_abs, end_abs, name) ─────────────────────
    used_greens = set()
    pairs = []
    for b in battles:
        start_abs = source_sec_to_tl_abs(b['timestamp_sec'], fps, v1_map)
        if start_abs is None:
            print(f'  WARN: could not map start {b["timestamp_sec"]:.1f}s '
                  f'({b["trainer_name"]!r})')
            continue
        # match green marker by trainer name (case-insensitive substring)
        end_abs   = None
        end_rel   = None
        for f, name in greens:
            if f in used_greens:
                continue
            if b['trainer_name'].lower() in (name or '').lower():
                end_rel = f
                end_abs = tl_start + f
                used_greens.add(f)
                break
        if end_abs is None:
            print(f'  WARN: no green marker for {b["trainer_name"]!r}')
            continue
        pairs.append((start_abs, end_abs, b['trainer_name']))

    pairs.sort()
    print(f'\nBattle pairs (abs frames):')
    for s, e, n in pairs:
        print(f'  {n:14s}  [{s:8d} → {e:8d}]   '
              f'rel [{(s-tl_start)/fps:7.1f}s → {(e-tl_start)/fps:7.1f}s]')

    # ── Build BGM segments (non-battle gameplay regions on A2) ─────────────
    segments = []
    cur = dsl_end_abs
    for start_abs, end_abs, _n in pairs:
        if start_abs > cur:
            segments.append((cur, start_abs))
        if end_abs > cur:
            cur = end_abs
    if cur < outro_tl_start:
        segments.append((cur, outro_tl_start))

    print(f'\nBGM segments to fill: {len(segments)}')
    for s, e in segments:
        print(f'  [{s:8d} → {e:8d}]   rel [{(s-tl_start)/fps:7.1f}s → '
              f'{(e-tl_start)/fps:7.1f}s]   {(e-s)/fps:6.1f}s')

    # ── Fill each segment with chained random BGMs ─────────────────────────
    placements = []
    last_name  = 'Dual Screen Lovelife'  # so we don't immediately re-pick DSL-adjacent

    for seg_start, seg_end in segments:
        cur = seg_start
        while cur < seg_end:
            # Random track excluding last
            pickable = [(m, d, n) for m, d, n in eligible if n != last_name]
            if not pickable:
                pickable = eligible
            track_mpi, track_dur, track_name = random.choice(pickable)

            available = seg_end - cur
            place_dur = min(track_dur, available)
            if place_dur < MIN_BGM_FRAMES:
                break

            placements.append({
                'mediaPoolItem': track_mpi,
                'startFrame':    0,
                'endFrame':      place_dur,
                'recordFrame':   cur,
                'trackIndex':    args.track_index,
                'mediaType':     2,
                '_name':         track_name,
            })
            cur       += place_dur
            last_name  = track_name

    print(f'\nPlanned BGM placements: {len(placements)}')
    for p in placements:
        print(f"  A{p['trackIndex']}  rel={(p['recordFrame']-tl_start)/fps:7.1f}s  "
              f"dur={p['endFrame']/fps:6.1f}s  {p['_name']!r}")

    if args.dry_run:
        print('\nDRY RUN — no changes made.')
        return 0

    # Ensure target track exists
    while tl.GetTrackCount('audio') < args.track_index:
        tl.AddTrack('audio', 'stereo')

    specs = [{k: v for k, v in p.items() if not k.startswith('_')} for p in placements]
    placed = pool.AppendToTimeline(specs) or []
    print(f'\nPlaced: {len(placed)}/{len(specs)} BGM clips on A{args.track_index}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
