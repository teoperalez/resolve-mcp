"""
Chain BGM tracks on A2 from the end of the existing Dual Screen Lovelife
clip up to the start of the outro, pausing during battles.

Between-battle rules:
  - Random pick from the bgm bin's `general`-tagged tracks, EXCLUDING the
    EXCLUDED_TRACKS set ("Dual Screen Lovelife", "Golden Goose"). The
    previous track is excluded each round to avoid back-to-back repeats.
  - Between battle start and battle end → silence on A2 (no BGM).
  - At each battle end → pick a new random BGM.

**Final-segment override** (after the LAST battle, up to the outro):
  - Place a FIXED sequence first: Dual Screen Lovelife → Motivated By
    Clouds → Roll Me in Stardust. Each track plays at its natural length,
    truncated only if it would run past the outro start.
  - After the fixed sequence, fill remaining time by chaining random
    `audio_classification: "energetic"` tracks (the "upbeat" pool) until
    the outro starts. Truncate the final pick to fit.
  - The fixed sequence is configurable via --final-sequence (comma list of
    file stems). Pass --final-sequence "" to disable the override and use
    the random logic for the last segment too.

Battle start positions come from `transcripts/battles.json` (mapped through
the V1 source-seconds map). Battle end positions come from the green
markers on the current timeline.

Usage:
    python place_battle_bgm.py [--seed N] [--track-index 2] [--dry-run]
                               [--final-sequence "Dual Screen Lovelife,Motivated By Clouds,Roll Me in Stardust"]
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

DEFAULT_FINAL_SEQUENCE = ['Dual Screen Lovelife', 'Motivated By Clouds', 'Roll Me in Stardust']


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
    ap.add_argument('--final-sequence', default=','.join(DEFAULT_FINAL_SEQUENCE),
                    help='Comma-separated track stems (filenames without .ext) to '
                         'play in order at the start of the post-last-battle segment. '
                         'After the sequence is exhausted, the remainder is filled '
                         'with chained random energetic tracks. Pass "" to disable.')
    ap.add_argument('--respect-existing-a2', dest='respect_existing_a2',
                    action='store_true', default=True,
                    help='(default) Derive battle ranges from existing A2 clip '
                         'boundaries — assumes place_battle_audio.py has already '
                         'placed battle theme loops on A2. BGM fills only the '
                         'gaps. Use this under the new pipeline order (12d before 12e).')
    ap.add_argument('--no-respect-existing-a2', dest='respect_existing_a2',
                    action='store_false',
                    help='Use the legacy logic: derive battle ranges from '
                         'transcripts/battles.json + Green ruler markers. '
                         'Use this for standalone invocations when A2 only has '
                         'the DSL clip.')
    args = ap.parse_args()
    final_seq = [s.strip() for s in args.final_sequence.split(',') if s.strip()]

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

    all_bgm = collect_clips_recursive(bgm_bin)

    # Full general pool — includes DSL/Golden Goose (used by final-sequence
    # lookup). The random pool below filters them out.
    full_general = []
    for mpi in all_bgm:
        full_name = (mpi.GetName() or '').strip()
        stem      = Path(full_name).stem
        if tags:
            t = (tags.get(full_name) or {}).get('tag', 'general')
            if t != 'general':
                continue
        dur = mpi_duration_frames(mpi, fps)
        if dur and dur >= MIN_BGM_FRAMES:
            full_general.append((mpi, dur, stem, full_name))

    # Random pool for between-battle segments: excludes EXCLUDED_TRACKS
    eligible = [(m, d, n) for m, d, n, _fn in full_general
                if n.lower() not in EXCLUDED_TRACKS]

    # Upbeat pool: filter to audio_classification='energetic'. Used to fill
    # the tail of the final segment after the fixed sequence.
    upbeat = []
    for m, d, n, fn in full_general:
        if n.lower() in EXCLUDED_TRACKS:
            continue
        cls = (tags.get(fn) or {}).get('audio_classification')
        if cls == 'energetic':
            upbeat.append((m, d, n))
    if not upbeat:
        # Fallback: use the random pool if no classifications available
        upbeat = list(eligible)

    print(f'Random pool: {len(eligible)} tracks  |  Upbeat pool: {len(upbeat)} tracks')
    if not eligible:
        print('ERROR: no eligible BGM tracks after exclusions.', file=sys.stderr)
        return 1

    # Helper: lookup MPI by stem (case-insensitive, with or without extension)
    def find_by_stem(stem: str):
        s = stem.lower()
        for m, d, n, _fn in full_general:
            if n.lower() == s:
                return (m, d, n)
        return None

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

    # DSL anchor: the FIRST clip on A2 is the opening BGM (Dual Screen
    # Lovelife). When A2 has just one clip, this is also the last clip —
    # the legacy `a2[-1]` semantics. When A2 already has battle audio +
    # other content from a prior pipeline pass, we still want dsl_end_abs
    # to point to the end of the opening BGM (so gap-filling starts there),
    # NOT to the end of the last A2 clip (which would falsely report "A2
    # already extends to outro" when really we just need to refresh the
    # middle BGM).
    if args.respect_existing_a2 and len(a2) > 1:
        dsl_end_abs = a2[0].GetStart() + a2[0].GetDuration()
        print(f'A{args.track_index} DSL anchor (a2[0]): abs={dsl_end_abs}  '
              f'rel={(dsl_end_abs - tl_start)/fps:.2f}s  '
              f'(--respect-existing-a2)')
    else:
        dsl_end_abs = a2[-1].GetStart() + a2[-1].GetDuration()
        print(f'A{args.track_index} current end (DSL end): abs={dsl_end_abs}  '
              f'rel={(dsl_end_abs - tl_start)/fps:.2f}s')

        if dsl_end_abs >= outro_tl_start:
            print('A2 already extends to or past outro — nothing to do.')
            return 0

    # Gameplay V1 = exclude intro (v1[0]) and outro (v1[-1])
    v1_map = build_v1_source_map(v1[1:-1], fps)

    # ── Decide segment-derivation source ───────────────────────────────────
    #
    # Under the new pipeline order (Step 12d places battle audio on A2 BEFORE
    # this script runs as Step 12e), --respect-existing-a2 is on by default
    # and we read battle ranges straight off A2: any frame range NOT covered
    # by an existing A2 clip (between DSL end and outro start) is a BGM gap.
    #
    # When invoked standalone with --no-respect-existing-a2 we fall back to
    # the legacy logic: derive battle ranges from transcripts/battles.json +
    # Green ruler markers.

    use_a2 = args.respect_existing_a2 and len(a2) > 1
    if args.respect_existing_a2 and not use_a2:
        print('NOTE: --respect-existing-a2 requested but A2 only has the DSL '
              'clip; falling back to battles.json + Green markers')

    pairs = []  # (start_abs, end_abs, label) — used for logging only
    segments = []  # (start_abs, end_abs) — what to fill with BGM

    if use_a2:
        print('\nDeriving battle ranges from existing A2 clips (post-DSL).')
        # Sort A2 clips that lie at or after the DSL end. The DSL clip itself
        # ends at dsl_end_abs, so anything starting >= dsl_end_abs counts.
        later_a2 = sorted([c for c in a2 if c.GetStart() >= dsl_end_abs],
                          key=lambda c: c.GetStart())
        print(f'  Post-DSL A2 clips found: {len(later_a2)}')
        # Group adjacent clips (gap < 1 frame) as a single battle range.
        if later_a2:
            grp_start = later_a2[0].GetStart()
            grp_end   = grp_start + later_a2[0].GetDuration()
            grp_name  = later_a2[0].GetName() or ''
            for c in later_a2[1:]:
                cs = c.GetStart()
                ce = cs + c.GetDuration()
                if cs <= grp_end + 1:
                    grp_end = max(grp_end, ce)
                else:
                    pairs.append((grp_start, grp_end, grp_name))
                    grp_start, grp_end, grp_name = cs, ce, (c.GetName() or '')
            pairs.append((grp_start, grp_end, grp_name))

        # Segments = gaps between [dsl_end, outro_start) not covered by any pair
        cur = dsl_end_abs
        for s, e, _n in pairs:
            if s > cur:
                segments.append((cur, s))
            if e > cur:
                cur = e
        if cur < outro_tl_start:
            segments.append((cur, outro_tl_start))
    else:
        # ── Legacy logic: derive from battles.json + Green ruler markers ───
        if not BATTLES_JSON.exists():
            print(f'ERROR: {BATTLES_JSON} not found.', file=sys.stderr)
            return 1
        battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))
        print(f'Battles loaded: {len(battles)}')

        markers = tl.GetMarkers() or {}
        greens  = sorted(((f, m.get('name', '')) for f, m in markers.items()
                          if m.get('color') == 'Green'))
        print(f'Green markers: {len(greens)}')

        used_greens = set()
        for b in battles:
            start_abs = source_sec_to_tl_abs(b['timestamp_sec'], fps, v1_map)
            if start_abs is None:
                print(f'  WARN: could not map start {b["timestamp_sec"]:.1f}s '
                      f'({b["trainer_name"]!r})')
                continue
            end_abs   = None
            for f, name in greens:
                if f in used_greens:
                    continue
                if b['trainer_name'].lower() in (name or '').lower():
                    end_abs = tl_start + f
                    used_greens.add(f)
                    break
            if end_abs is None:
                print(f'  WARN: no green marker for {b["trainer_name"]!r}')
                continue
            pairs.append((start_abs, end_abs, b['trainer_name']))

        cur = dsl_end_abs
        for start_abs, end_abs, _n in pairs:
            if start_abs > cur:
                segments.append((cur, start_abs))
            if end_abs > cur:
                cur = end_abs
        if cur < outro_tl_start:
            segments.append((cur, outro_tl_start))

    pairs.sort()
    print(f'\nBattle pairs (abs frames):')
    for s, e, n in pairs:
        print(f'  {n[:24]:24s}  [{s:8d} → {e:8d}]   '
              f'rel [{(s-tl_start)/fps:7.1f}s → {(e-tl_start)/fps:7.1f}s]')

    print(f'\nBGM segments to fill: {len(segments)}')
    for s, e in segments:
        print(f'  [{s:8d} → {e:8d}]   rel [{(s-tl_start)/fps:7.1f}s → '
              f'{(e-tl_start)/fps:7.1f}s]   {(e-s)/fps:6.1f}s')

    # ── Fill each segment with chained BGMs ────────────────────────────────
    # The LAST segment (after the final battle, ending at outro) uses the
    # fixed final_seq first, then random upbeat. Other segments use random.
    placements = []
    last_name  = 'Dual Screen Lovelife'  # avoid immediate DSL-adjacent repeat

    def place(track_mpi, track_dur, track_name, cur, seg_end, label):
        """Plan one placement, truncated to remaining segment. Returns advance frames."""
        available = seg_end - cur
        place_dur = min(track_dur, available)
        if place_dur < MIN_BGM_FRAMES:
            return 0
        placements.append({
            'mediaPoolItem': track_mpi,
            'startFrame':    0,
            'endFrame':      place_dur,
            'recordFrame':   cur,
            'trackIndex':    args.track_index,
            'mediaType':     2,
            '_name':         track_name,
            '_label':        label,
        })
        return place_dur

    for i, (seg_start, seg_end) in enumerate(segments):
        is_final = (i == len(segments) - 1)
        cur = seg_start

        if is_final and final_seq:
            print(f'\n── Final segment override (segment {i+1}/{len(segments)}) ──')
            print(f'   Fixed sequence: {final_seq}')
            for stem in final_seq:
                hit = find_by_stem(stem)
                if not hit:
                    print(f'   WARN: {stem!r} not found in general pool — skipping')
                    continue
                mpi, dur, name = hit
                advance = place(mpi, dur, name, cur, seg_end, 'fixed')
                if advance == 0:
                    break
                cur += advance
                last_name = name
            # Fill remaining with chained random UPBEAT picks
            while cur < seg_end:
                pickable = [(m, d, n) for m, d, n in upbeat if n != last_name]
                if not pickable:
                    pickable = upbeat
                track_mpi, track_dur, track_name = random.choice(pickable)
                advance = place(track_mpi, track_dur, track_name, cur, seg_end, 'upbeat-random')
                if advance == 0:
                    break
                cur += advance
                last_name = track_name
            continue

        # Non-final segments: random general
        while cur < seg_end:
            pickable = [(m, d, n) for m, d, n in eligible if n != last_name]
            if not pickable:
                pickable = eligible
            track_mpi, track_dur, track_name = random.choice(pickable)
            advance = place(track_mpi, track_dur, track_name, cur, seg_end, 'random')
            if advance == 0:
                break
            cur += advance
            last_name = track_name

    print(f'\nPlanned BGM placements: {len(placements)}')
    for p in placements:
        print(f"  A{p['trackIndex']}  rel={(p['recordFrame']-tl_start)/fps:7.1f}s  "
              f"dur={p['endFrame']/fps:6.1f}s  [{p['_label']:14s}]  {p['_name']!r}")

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
