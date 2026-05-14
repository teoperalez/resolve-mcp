"""
Place battle-intro graphics on V2 over the 5 seconds leading into each
major-boss battle on the current Resolve timeline.

For each battle in `transcripts/battles.json` classified as `rival` or `gym`
(in `transcripts/battle-types.json`):

  - Map the battle's source-time timestamp to a timeline frame via the
    current V1 clip layout.
  - Pick the matching intro media-pool item:
      * gym / elite4 / champion: `{trainer_lowercase}-battle-intro.mov`
        from the `battle-intros` bin (e.g. `falkner-battle-intro.mov`).
      * rival: `silver-<location>-<starter_type>-battle-intro.mov`
        from the `silver-battle-intros` bin. The location comes from
        `transcripts/rival-starter.json` (per-battle), the starter type
        from the same file (single value for the video).
  - Place the intro on V2, ending exactly at the battle's timeline frame.
    The intro's tail aligns with the battle start; its head sits at
    `battle_frame - min(5s, intro_duration)`. This puts the graphic over
    the LAST 5 seconds of the V1 clip that comes immediately before the
    battle, per the IRLPC workflow spec.

The script only places VIDEO on V2 (mediaType=1) — the intro file's audio
is dropped so it doesn't conflict with the A2 BGM / battle-audio pipeline.

Usage:
    python place_battle_intros.py [--overlap-sec 5] [--include-other]
                                  [--track-index 2] [--dry-run]

`--include-other` also places intros for battle-types classified as
`other` (route trainers, Rocket grunts) using the trainer-name slug; useful
when the user has custom intro files for named overworld trainers.
"""
import sys
import os
import json
import re
import argparse
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr

TRANSCRIPTS_DIR  = Path('transcripts')
BATTLES_JSON     = TRANSCRIPTS_DIR / 'battles.json'
BATTLE_TYPES     = TRANSCRIPTS_DIR / 'battle-types.json'
RIVAL_STARTER    = TRANSCRIPTS_DIR / 'rival-starter.json'

BATTLE_INTROS_BIN        = 'battle-intros'
SILVER_BATTLE_INTROS_BIN = 'silver-battle-intros'

# Canonical Crystal/HGSS rival encounter order, used as a fallback when
# rival-starter.json doesn't supply a location for a given battle index.
FALLBACK_CANONICAL_LOCATIONS = [
    'cherrygrove', 'azalea', 'burnedtower', 'goldenrod',
    'victoryroad', 'indigoplateau', 'mtmoon',
]


def slugify_trainer(name: str) -> str:
    """Normalize a trainer name to the form used in filenames:
    lowercased, dots/whitespace stripped, hyphens preserved. e.g.
    'Lt. Surge' -> 'ltsurge', 'Whitney' -> 'whitney'."""
    s = name.lower()
    s = re.sub(r'[^a-z0-9-]', '', s)
    return s


def build_a1_or_v1_map(timeline, fps):
    """Return a list of (tl_start_frame, tl_end_frame, src_start_frame,
    src_end_frame, name) for V1 clips. Used to map source-time to timeline."""
    v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    out = []
    for c in v1:
        tl_s = c.GetStart()
        tl_e = tl_s + c.GetDuration()
        src_s = c.GetLeftOffset()
        src_e = src_s + c.GetDuration()
        out.append((tl_s, tl_e, src_s, src_e, c.GetName()))
    return out


def source_sec_to_tl_frame(source_sec, v1_map, fps, snap_tol_sec=1.0):
    """Map a source-time second to an absolute timeline frame. Snaps to the
    nearest V1 clip boundary if the timestamp lands in a silence-stripped gap."""
    src_frame = source_sec * fps
    # Identify the dominant (gameplay) source by name; only those clips count.
    name_counts = Counter(name for _, _, _, _, name in v1_map)
    if not name_counts:
        return None
    dominant = name_counts.most_common(1)[0][0]
    candidates = [e for e in v1_map if e[4] == dominant]

    for tl_s, tl_e, src_s, src_e, _ in candidates:
        if src_s <= src_frame <= src_e:
            return tl_s + round(src_frame - src_s)

    snap_tol_frames = snap_tol_sec * fps
    for tl_s, _, src_s, _, _ in candidates:
        if src_s - snap_tol_frames <= src_frame < src_s:
            return tl_s
    for _, tl_e, _, src_e, _ in candidates:
        if src_e < src_frame <= src_e + snap_tol_frames:
            return tl_e - 1
    return None


def find_bin_by_name(folder, name):
    """Search media pool folder tree for a sub-bin with given name."""
    if folder is None:
        return None
    if folder.GetName() == name:
        return folder
    for sub in folder.GetSubFolderList() or []:
        hit = find_bin_by_name(sub, name)
        if hit is not None:
            return hit
    return None


def collect_mpi_by_name(folder):
    """Return {item_name: MediaPoolItem} for every clip directly in folder."""
    out = {}
    for item in folder.GetClipList() or []:
        out[item.GetName()] = item
    return out


def pick_intro_filename(battle_index: int,
                        battle: dict,
                        battle_type: str,
                        rival_starter_data: dict | None) -> tuple[str | None, str]:
    """Return (filename_with_extension, debug_explanation).

    For gym/other: f'{slug}-battle-intro.mov' in battle-intros bin.
    For rival:     f'silver-{location}-{type}-battle-intro.mov' in silver-battle-intros.
    Returns (None, reason) when the intro can't be determined."""
    if battle_type == 'rival':
        if not rival_starter_data:
            return None, 'rival battle but no rival-starter.json data'
        starter = rival_starter_data.get('rival_starter_type')
        if starter not in ('fire', 'water', 'grass'):
            return None, f'rival_starter_type={starter!r} — need fire/water/grass'
        # Per-battle location lookup
        rivals_by_idx = rival_starter_data.get('rivals_by_battle_index') or {}
        loc = rivals_by_idx.get(str(battle_index)) or rivals_by_idx.get(battle_index)
        if not loc:
            # Fallback: canonical encounter order. Count rival ordinal.
            return None, (f'no location for battle_index={battle_index} in '
                          f'rival-starter.json, and fallback would need ordinal info')
        return (f'silver-{loc}-{starter}-battle-intro.mov',
                f'rival @ {loc!r} with {starter!r} starter')

    # gym (or other if --include-other is enabled)
    slug = slugify_trainer(battle.get('trainer_name', ''))
    if not slug:
        return None, f'cannot slugify trainer_name {battle.get("trainer_name")!r}'
    return f'{slug}-battle-intro.mov', f'{battle_type} → {slug!r}'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--overlap-sec', type=float, default=5.0,
                    help='Target overlap on the previous V1 clip (default: 5s). '
                         'Intros shorter than this are placed at their natural length.')
    ap.add_argument('--include-other', action='store_true',
                    help='Also place intros for battles classified as `other` '
                         '(route trainers, Rocket grunts) if a matching '
                         '<slug>-battle-intro.mov is available.')
    ap.add_argument('--track-index', type=int, default=2,
                    help='V-track to place intros on (default: 2 = V2)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Report what would be placed without modifying Resolve')
    args = ap.parse_args()

    if not BATTLES_JSON.exists():
        print(f'ERROR: {BATTLES_JSON} not found', file=sys.stderr)
        return 1
    if not BATTLE_TYPES.exists():
        print(f'ERROR: {BATTLE_TYPES} not found — run classify_battles.py first',
              file=sys.stderr)
        return 1

    battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))
    types   = json.loads(BATTLE_TYPES.read_text(encoding='utf-8'))
    rival_data = None
    if RIVAL_STARTER.exists():
        rival_data = json.loads(RIVAL_STARTER.read_text(encoding='utf-8'))

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    tl      = project.GetCurrentTimeline()
    pool    = project.GetMediaPool()
    fps     = float(project.GetSetting('timelineFrameRate'))
    print(f'Timeline: {tl.GetName()!r}  fps={fps:.2f}')

    # Locate the two intro bins
    root = pool.GetRootFolder()
    gym_bin    = find_bin_by_name(root, BATTLE_INTROS_BIN)
    silver_bin = find_bin_by_name(root, SILVER_BATTLE_INTROS_BIN)
    if gym_bin is None:
        print(f'WARN: bin {BATTLE_INTROS_BIN!r} not found — gym intros will be skipped')
    if silver_bin is None:
        print(f'WARN: bin {SILVER_BATTLE_INTROS_BIN!r} not found — rival intros will be skipped')
    gym_items    = collect_mpi_by_name(gym_bin) if gym_bin else {}
    silver_items = collect_mpi_by_name(silver_bin) if silver_bin else {}
    print(f'  battle-intros bin: {len(gym_items)} files')
    print(f'  silver-battle-intros bin: {len(silver_items)} files')

    v1_map = build_a1_or_v1_map(tl, fps)
    overlap_frames_target = int(round(args.overlap_sec * fps))

    placements = []
    skipped    = []

    for battle_index, b in enumerate(battles):
        t_entry = types.get(str(battle_index)) or types.get(battle_index)
        if not t_entry:
            skipped.append((b, 'no battle-type classification'))
            continue
        btype = t_entry.get('type')
        if btype not in ('rival', 'gym') and not (args.include_other and btype == 'other'):
            continue  # silently skip; only major-boss types get intros by default

        fname, why = pick_intro_filename(battle_index, b, btype, rival_data)
        if fname is None:
            skipped.append((b, f'[{btype}] {why}'))
            continue

        # Look up media-pool item
        if btype == 'rival':
            mpi = silver_items.get(fname)
        else:
            mpi = gym_items.get(fname)
        if mpi is None:
            skipped.append((b, f'[{btype}] media-pool item {fname!r} not found ({why})'))
            continue

        # Map source-time to timeline frame
        tl_frame = source_sec_to_tl_frame(b['timestamp_sec'], v1_map, fps)
        if tl_frame is None:
            skipped.append((b, f'cannot map source_sec={b["timestamp_sec"]} to timeline'))
            continue

        # Intro duration in TIMELINE frames (Resolve handles fps conversion via
        # GetClipProperty 'Frames' — but for the simple "use last N seconds"
        # approach we just place a fixed `overlap_frames_target` slice). To
        # support intros shorter than 5s, we read the property and clamp.
        try:
            intro_frames_native = int(mpi.GetClipProperty('Frames') or 0)
        except Exception:
            intro_frames_native = 0
        try:
            intro_fps_native = float(mpi.GetClipProperty('FPS') or fps)
        except Exception:
            intro_fps_native = fps
        # Native frames * (timeline_fps / native_fps) → timeline-frame count
        intro_frames_tl = int(round(intro_frames_native * fps / intro_fps_native)) \
                          if intro_frames_native else overlap_frames_target

        clip_dur_tl = min(intro_frames_tl, overlap_frames_target)
        record_frame = tl_frame - clip_dur_tl

        # Source startFrame/endFrame are in NATIVE frames. We want the LAST
        # clip_dur_tl timeline-frames of the intro, i.e. native_end - native_dur_of_clip.
        native_clip_dur = int(round(clip_dur_tl * intro_fps_native / fps)) \
                           if intro_frames_native else 0
        if intro_frames_native:
            src_end_native   = intro_frames_native - 1
            src_start_native = max(0, src_end_native - native_clip_dur + 1)
        else:
            src_start_native = 0
            src_end_native   = max(0, clip_dur_tl - 1)

        placements.append({
            'battle':        b,
            'battle_index':  battle_index,
            'type':          btype,
            'reason':        why,
            'filename':      fname,
            'mpi':           mpi,
            'tl_frame':      tl_frame,
            'record_frame':  record_frame,
            'clip_dur_tl':   clip_dur_tl,
            'src_start':     src_start_native,
            'src_end':       src_end_native,
        })

    # Report
    print(f'\nPlanned placements: {len(placements)}')
    for p in placements:
        rel_record = (p['record_frame'] - tl.GetStartFrame()) / fps
        print(f'  battle[{p["battle_index"]}] {p["type"]:5s}  '
              f'tl={rel_record:7.1f}s  dur={p["clip_dur_tl"]/fps:4.1f}s  '
              f'{p["filename"]}  ({p["reason"]})')
    if skipped:
        print(f'\nSkipped ({len(skipped)}):')
        for b, why in skipped:
            print(f'  {b.get("trainer_name", "?")!r} @ {b.get("timestamp_sec", 0):.1f}s — {why}')

    if args.dry_run:
        print('\nDRY RUN — no clips placed.')
        return 0

    if not placements:
        print('\nNothing to place.')
        return 0

    # Build the AppendToTimeline payload — video only, V<track_index>
    payload = []
    for p in placements:
        payload.append({
            'mediaPoolItem': p['mpi'],
            'startFrame':    p['src_start'],
            'endFrame':      p['src_end'],
            'recordFrame':   p['record_frame'],
            'trackIndex':    args.track_index,
            'mediaType':     1,  # video only
        })

    placed = pool.AppendToTimeline(payload) or []
    print(f'\nPlaced: {len(placed)}/{len(payload)} clips on V{args.track_index}')
    if len(placed) < len(payload):
        print(f'  WARN: {len(payload) - len(placed)} placement(s) failed — likely '
              f'V{args.track_index} is occupied at one of the record positions, '
              f'or the source range was outside the media. Review with --dry-run.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
