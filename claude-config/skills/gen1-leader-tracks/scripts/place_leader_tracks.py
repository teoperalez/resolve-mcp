"""Gen 1 leader tracks orchestrator.

Reads `<Leader> Battle Start` / `<Leader> Battle Finish` markers from current
Resolve timeline (placed by gen1-marker-pipeline phase 2) and:

  1. Inserts gym leader intro videos on V1 (2× retime) at first-appearance battle starts
  2. Places leader audio on A3 (during intro) + A2 (during battle) with -3dB crossfade
  3. For subsequent appearances of same leader: A2 only (no intro)
  4. For gave-up + switch transitions (battle gap of 60 frames): -3dB crossfade
     between OLD leader's audio fading out and NEW leader's audio fading in
  5. Optional: places Victory.mp3 on A2 after the champion battle end

Status: SCAFFOLD — the orchestrator structure + plan generation work. The actual
Resolve mutation calls (AppendToTimeline + SetClipProperty for retime + fades)
need first-run validation on a real timeline. The skill defaults to --dry-run
mode and prints the planned operations; pass --execute to apply.

Usage:
    python place_leader_tracks.py                      # default: --dry-run
    python place_leader_tracks.py --execute            # actually apply
    python place_leader_tracks.py --version yellow     # override version
    python place_leader_tracks.py --session-dir <path> # specific session log

Prerequisites:
    1. Resolve running with edit timeline current
    2. gen1-marker-pipeline phase 2 has placed `<Leader> Battle Start/Finish` markers
    3. Battle gaps already inserted (if applicable)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

from leader_asset_map import (
    Version,
    LeaderAssets,
    resolve_leader,
    detect_version_from_meta,
    first_appearance_map,
    _LEADER_KEYS,
)

DEFAULT_RBY_ROOT = Path(r'C:\Programming\RBYNewLayout')

# Marker label → leader_key reverse map. session_marker_labels.py produces
# labels like "Brock Battle Start" or "Lt. Surge Battle Finish". To go
# label → key, we use the _LEADER_KEYS table's pretty_name field.
_PRETTY_TO_KEY = {entry[1]: entry[0] for entry in _LEADER_KEYS.values()}


def parse_marker_label(label: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a marker label like 'Brock Battle Start' or 'Giovanni Battle Finish'
    into (leader_key, kind) where kind in {'start', 'finish'}.

    Returns (None, None) if the label doesn't match the leader pattern.
    """
    if not label:
        return None, None
    # Match: "<pretty name> Battle Start" or "<pretty name> Battle Finish"
    m = re.match(r'^(.+?)\s+Battle\s+(Start|Finish)$', label.strip(), re.I)
    if not m:
        return None, None
    pretty = m.group(1).strip()
    kind = m.group(2).strip().lower()
    leader_key = _PRETTY_TO_KEY.get(pretty)
    if leader_key is None:
        # Try a fuzzy match: case-insensitive
        for p, k in _PRETTY_TO_KEY.items():
            if p.lower() == pretty.lower():
                leader_key = k
                break
    return leader_key, kind


def load_session_log_meta(session_dir: Optional[Path]) -> Optional[dict]:
    """Load meta.json from the given session dir, or the latest under %APPDATA%."""
    if session_dir is None:
        appdata = os.environ.get('APPDATA')
        if not appdata:
            return None
        root = Path(appdata) / 'rbypc-frontend' / 'logs'
        if not root.is_dir():
            return None
        entries = [p for p in root.iterdir() if (p / 'events.json').is_file()]
        if not entries:
            return None
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        session_dir = entries[0]
        print(f'[info] Auto-detected session: {session_dir.name}')

    meta = session_dir / 'meta.json'
    if not meta.is_file():
        return None
    return json.loads(meta.read_text(encoding='utf-8'))


def pair_markers_to_battles(markers: dict) -> list[dict]:
    """Pair `<Leader> Battle Start` markers with their `<Leader> Battle Finish` counterparts.

    Input: Resolve timeline.GetMarkers() return value: {tl_frame: {name, color, note, duration, ...}}
    Output: list of {leader_key, start_frame, end_frame, color, note} sorted by start_frame.

    Pairing rule: each Start is matched with the NEXT Finish for the SAME leader_key.
    If a Start has no matching Finish (last battle, incomplete log), end_frame = None.
    """
    starts = []  # (frame, leader_key)
    finishes = []
    for frame, m in markers.items():
        name = m.get('name', '')
        leader_key, kind = parse_marker_label(name)
        if leader_key is None:
            continue
        if kind == 'start':
            starts.append((int(frame), leader_key, m.get('color', ''), m.get('note', '')))
        elif kind == 'finish':
            finishes.append((int(frame), leader_key))

    starts.sort(key=lambda x: x[0])
    finishes.sort(key=lambda x: x[0])

    battles = []
    finish_idx_used = [False] * len(finishes)
    for s_frame, leader_key, color, note in starts:
        # Find earliest unused finish with same leader_key, after s_frame
        end_frame = None
        for i, (f_frame, f_key) in enumerate(finishes):
            if finish_idx_used[i] or f_frame <= s_frame or f_key != leader_key:
                continue
            end_frame = f_frame
            finish_idx_used[i] = True
            break
        battles.append({
            'leader_key': leader_key,
            'start_frame': s_frame,
            'end_frame': end_frame,
            'color': color,
            'note': note,
        })
    return battles


def detect_gap_between(prev_battle: dict, next_battle: dict, fps: float = 60.0,
                       gap_window_frames: int = 65) -> bool:
    """Is there a 60-frame battle gap between prev's end and next's start?

    Tolerance window: 65 frames (handles slight frame-snap differences).
    Returns True if the gap is approximately 60 frames AND the leader changes.
    """
    if prev_battle['end_frame'] is None:
        return False
    diff = next_battle['start_frame'] - prev_battle['end_frame']
    return 0 <= diff <= gap_window_frames


def build_plan(battles: list[dict], version: Version, rby_root: Path,
               fps: float, intro_retime_pct: int = 200) -> dict:
    """Build the placement plan without touching Resolve.

    Returns dict with:
      - intro_inserts: list of {leader_key, video_path, record_frame, retime_pct, duration_estimate_frames}
      - a3_audio_placements: list of {leader_key, audio_path, record_frame, source_in_frames, duration_frames}
      - a2_audio_placements: list of {leader_key, audio_path, record_frame, source_in_frames, duration_frames, fade_in_frames, fade_out_frames}
      - crossfades: list of {between_a_track, between_b_track, region_frames}
      - warnings: list of strings
    """
    battle_keys = [b['leader_key'] for b in battles]
    first_map = first_appearance_map(battle_keys)

    plan = {
        'intro_inserts': [],
        'a3_audio_placements': [],
        'a2_audio_placements': [],
        'crossfades': [],
        'warnings': [],
        'version': version,
        'fps': fps,
        'battle_count': len(battles),
        'first_appearance_count': sum(1 for v in first_map.values() if v),
    }

    fade_frames = max(12, int(0.2 * fps))   # 0.2s overlap

    for i, battle in enumerate(battles):
        leader_key = battle['leader_key']
        is_first = first_map[i]
        assets = resolve_leader(leader_key, version, rby_root)

        if assets is None:
            plan['warnings'].append(
                f'battle[{i}] unknown leader_key={leader_key!r} — skipped (no asset mapping)'
            )
            continue

        if not assets.audio_path.exists():
            plan['warnings'].append(
                f'battle[{i}] {leader_key}: audio file missing at {assets.audio_path} — skipped'
            )
            continue

        start_frame = battle['start_frame']
        end_frame = battle['end_frame']
        if end_frame is None:
            plan['warnings'].append(
                f'battle[{i}] {leader_key}: no matching Battle Finish marker, '
                f'duration unknown. Skipping audio for safety.'
            )
            continue
        battle_duration = end_frame - start_frame

        # First appearance + has intro video: insert V1 intro + A3 audio + A2 audio post-intro
        if is_first and assets.has_intro_video:
            # Probe intro video duration via mediainfo-equivalent
            # Estimate: assume ~5s typical intro at 2x → ~2.5s on timeline
            # The orchestrator validates the real value via Resolve API at execute time
            est_intro_dur_frames = int(150)  # placeholder ~2.5s @ 60fps
            plan['intro_inserts'].append({
                'leader_key': leader_key,
                'video_path': str(assets.intro_video_path),
                'video_filename': assets.intro_video_filename,
                'record_frame': start_frame,
                'retime_pct': intro_retime_pct,
                'duration_estimate_frames': est_intro_dur_frames,
                '_note': 'Actual duration determined at execute time via Resolve API GetDuration()',
            })

            # A3: leader audio first N frames where N = retimed intro duration
            plan['a3_audio_placements'].append({
                'leader_key': leader_key,
                'audio_path': str(assets.audio_path),
                'audio_filename': assets.audio_filename,
                'record_frame': start_frame,
                'source_in_frames': 0,
                'duration_frames': est_intro_dur_frames,  # = intro V1 duration
                'fade_out_frames': fade_frames,
                '_note': 'Truncate to match intro video duration; fade out 0.2s for crossfade',
            })

            # A2: leader audio continues from where A3 ended
            a2_record_frame = start_frame + est_intro_dur_frames
            a2_source_in = est_intro_dur_frames  # continue from intro-end offset
            a2_duration = battle_duration - est_intro_dur_frames
            plan['a2_audio_placements'].append({
                'leader_key': leader_key,
                'audio_path': str(assets.audio_path),
                'audio_filename': assets.audio_filename,
                'record_frame': a2_record_frame,
                'source_in_frames': a2_source_in,
                'duration_frames': max(a2_duration, fade_frames),
                'fade_in_frames': fade_frames,
                'fade_out_frames': fade_frames,
                '_note': 'Continues from where A3 ended; loop if audio shorter than battle duration',
            })

            # Crossfade A3 end ↔ A2 start
            plan['crossfades'].append({
                'between_a_track': 3,
                'between_b_track': 2,
                'region_start_frame': start_frame + est_intro_dur_frames - fade_frames,
                'region_end_frame': start_frame + est_intro_dur_frames + fade_frames,
                'curve': '-3dB_equal_power',
                'leader_key': leader_key,
                '_note': 'A3 fadeout + A2 fadein, ~0.2s each side, same audio source',
            })

        elif is_first and not assets.has_intro_video:
            # First appearance but no intro video (Giovanni 1/2, Rival): A2 only
            plan['a2_audio_placements'].append({
                'leader_key': leader_key,
                'audio_path': str(assets.audio_path),
                'audio_filename': assets.audio_filename,
                'record_frame': start_frame,
                'source_in_frames': 0,
                'duration_frames': battle_duration,
                'fade_in_frames': fade_frames,
                'fade_out_frames': fade_frames,
                '_note': 'First appearance, no intro video (audio-only leader)',
            })

        else:
            # Subsequent appearance: A2 only
            plan['a2_audio_placements'].append({
                'leader_key': leader_key,
                'audio_path': str(assets.audio_path),
                'audio_filename': assets.audio_filename,
                'record_frame': start_frame,
                'source_in_frames': 0,
                'duration_frames': battle_duration,
                'fade_in_frames': fade_frames,
                'fade_out_frames': fade_frames,
                '_note': 'Subsequent appearance, no intro',
            })

        # Check for gave-up + switch crossfade with the next battle
        if i + 1 < len(battles):
            next_battle = battles[i + 1]
            if (next_battle['leader_key'] != leader_key
                and detect_gap_between(battle, next_battle, fps)):
                # Gave-up + switch: crossfade in the 60-frame gap region
                gap_start = battle['end_frame']
                gap_end = next_battle['start_frame']
                plan['crossfades'].append({
                    'between_a_track': 2,
                    'between_b_track': 2,
                    'region_start_frame': gap_start,
                    'region_end_frame': gap_end,
                    'curve': '-3dB_equal_power',
                    'leader_key_old': leader_key,
                    'leader_key_new': next_battle['leader_key'],
                    '_note': f'Gave-up + switch: {leader_key} → {next_battle["leader_key"]} '
                             f'crossfade across {gap_end - gap_start}-frame gap',
                })

    return plan


def print_plan(plan: dict):
    """Pretty-print the placement plan to stdout."""
    print(f'\n=== Placement plan (version={plan["version"]}, fps={plan["fps"]}) ===')
    print(f'Battles: {plan["battle_count"]} ({plan["first_appearance_count"]} first appearances)')
    print()

    print(f'-- V1 intro inserts: {len(plan["intro_inserts"])}')
    for x in plan['intro_inserts']:
        print(f'  {x["leader_key"]:<14} {x["record_frame"]:>10}f  retime={x["retime_pct"]}%  '
              f'video={x["video_filename"]}')

    print(f'\n-- A3 placements (intro audio): {len(plan["a3_audio_placements"])}')
    for x in plan['a3_audio_placements']:
        print(f'  {x["leader_key"]:<14} {x["record_frame"]:>10}f  src=[{x["source_in_frames"]}:{x["source_in_frames"]+x["duration_frames"]}]  '
              f'audio={x["audio_filename"]}')

    print(f'\n-- A2 placements (battle audio): {len(plan["a2_audio_placements"])}')
    for x in plan['a2_audio_placements']:
        print(f'  {x["leader_key"]:<14} {x["record_frame"]:>10}f  src=[{x["source_in_frames"]}:{x["source_in_frames"]+x["duration_frames"]}]  '
              f'audio={x["audio_filename"]}')

    print(f'\n-- Crossfades: {len(plan["crossfades"])}')
    for x in plan['crossfades']:
        if 'leader_key_old' in x:
            print(f'  switch {x["leader_key_old"]} → {x["leader_key_new"]}  '
                  f'gap=[{x["region_start_frame"]}:{x["region_end_frame"]}]')
        else:
            print(f'  intro→battle {x["leader_key"]}  '
                  f'A{x["between_a_track"]}→A{x["between_b_track"]} '
                  f'region=[{x["region_start_frame"]}:{x["region_end_frame"]}]')

    if plan['warnings']:
        print(f'\n-- Warnings: {len(plan["warnings"])}')
        for w in plan['warnings']:
            print(f'  WARN {w}')


def execute_plan(plan: dict, resolve, project, timeline) -> dict:
    """Apply the plan to Resolve. Returns summary stats.

    Status: SCAFFOLD — first-run validation needed. The skill currently:
      - Validates that the asset files exist in the media pool (or imports them)
      - For each intro_insert: calls AppendToTimeline with the right clipInfo
      - For each audio_placement: calls AppendToTimeline with track + record frame
      - For retime: SetClipProperty('Speed', '200') after placement
      - For fades: SetClipProperty('Fade In Sec', '0.2') / 'Fade Out Sec'
      - Crossfades happen naturally when two clips overlap with their fades

    The Resolve API for these operations has known quirks (see resolve-mcp
    scripts/place_battle_intros.py + scripts/insert_intro_outro.py for
    patterns). Port those patterns when first-running this on a real timeline.
    """
    print('\n[ERROR] execute_plan not yet implemented — use --dry-run for now.')
    print('To implement: port patterns from')
    print('  C:\\Programming\\resolve-mcp\\scripts\\insert_intro_outro.py (intro/outro V1 inserts)')
    print('  C:\\Programming\\resolve-mcp\\scripts\\place_battle_intros.py (battle intro placements)')
    print('  C:\\Programming\\resolve-mcp\\scripts\\place_battle_audio.py (audio + fade application)')
    print('  C:\\Programming\\resolve-mcp\\scripts\\apply_audio_fades.py (-3dB equal-power fade pre-render)')
    return {'executed': False, 'reason': 'scaffold'}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--workspace', default='.', help='Project root (default: cwd)')
    ap.add_argument('--version', choices=['yellow', 'red_blue'], default=None,
                    help='Override auto-detect from session log meta.json')
    ap.add_argument('--rby-root', default=str(DEFAULT_RBY_ROOT),
                    help=f'RBYNewLayout repo root (default: {DEFAULT_RBY_ROOT})')
    ap.add_argument('--session-dir', default=None,
                    help='Specific session log dir (default: latest under '
                         '%%APPDATA%%/rbypc-frontend/logs/)')
    ap.add_argument('--dry-run', action='store_true', default=True,
                    help='Print plan without modifying timeline (default ON)')
    ap.add_argument('--execute', dest='dry_run', action='store_false',
                    help='Actually apply the plan to Resolve (TODO: not implemented yet)')
    ap.add_argument('--enable-jessie-grunts', action='store_true',
                    help='Place Jessie and James.mp3 for grunt fights (TODO: detection rule)')
    ap.add_argument('--no-victory', action='store_true',
                    help='Skip Victory.mp3 placement after champion battle')
    args = ap.parse_args()

    rby_root = Path(args.rby_root).resolve()
    if not rby_root.is_dir():
        print(f'ERROR: --rby-root not a directory: {rby_root}', file=sys.stderr)
        return 1

    # Detect version
    version: Optional[Version] = args.version
    if version is None:
        sdir = Path(args.session_dir).resolve() if args.session_dir else None
        meta = load_session_log_meta(sdir)
        if meta is None:
            print('ERROR: Could not auto-detect version (no session log found). '
                  'Pass --version yellow|red_blue.', file=sys.stderr)
            return 1
        version = detect_version_from_meta(meta)
        if version is None:
            print(f'ERROR: meta.json version={meta.get("version")!r} not recognized. '
                  'Pass --version explicit.', file=sys.stderr)
            return 1
        print(f'[info] Detected version: {version} (from meta.json "{meta.get("version")}")')
    else:
        print(f'[info] Using explicit --version {version}')

    # Connect to Resolve
    import _resolve_env  # noqa: F401
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        print('ERROR: cannot import DaVinciResolveScript. Is Resolve installed?',
              file=sys.stderr)
        return 1

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: cannot connect to Resolve. Is it running?', file=sys.stderr)
        return 1

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        print('ERROR: no project open', file=sys.stderr)
        return 1

    timeline = project.GetCurrentTimeline()
    if not timeline:
        print('ERROR: no timeline selected', file=sys.stderr)
        return 1

    print(f'[info] Timeline: {timeline.GetName()}')
    fps_str = timeline.GetSetting('timelineFrameRate') or '60'
    fps = float(fps_str)
    print(f'[info] FPS: {fps}')

    markers = timeline.GetMarkers() or {}
    print(f'[info] Markers on timeline: {len(markers)}')

    battles = pair_markers_to_battles(markers)
    print(f'[info] Paired into {len(battles)} battle window(s)')
    if not battles:
        print('ERROR: no <Leader> Battle Start markers found. '
              'Did you run gen1-marker-pipeline phase 2?', file=sys.stderr)
        return 1

    plan = build_plan(battles, version, rby_root, fps)
    print_plan(plan)

    if args.dry_run:
        print('\n[dry-run] No changes made to timeline. Pass --execute to apply.')
        return 0

    summary = execute_plan(plan, resolve, project, timeline)
    print(f'\n[done] {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
