"""
repair_teal_extra_gap.py — for each Teal-flagged V1 clip (unwanted pre-roll):
trim 60 frames from the clip's START (advance LeftOffset). Mirror the trim
on the parallel A1 clip. Re-color Mint on success.

Reads flags from _data/qa-reports/<timeline-stem>.json.

Usage:
    repair_teal_extra_gap.py
    repair_teal_extra_gap.py --dry-run
    repair_teal_extra_gap.py --trim-frames 60  # default 60 = 1s @ 60fps
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

QA_REPORTS_DIR = Path('_data/qa-reports')


def latest_report_for(timeline_name: str) -> Path | None:
    stem = re.sub(r'[^\w\-]', '_', timeline_name or 'timeline')
    p = QA_REPORTS_DIR / f'{stem}.json'
    return p if p.exists() else None


def find_v1_a1_pair(tl, v1_clip):
    """Return (v1_clip, a1_clip_at_same_tl_position) — a1 may be None."""
    a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
    tl_start = v1_clip.GetStart()
    for ac in a1:
        if ac.GetStart() == tl_start:
            return v1_clip, ac
    return v1_clip, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', default=None)
    ap.add_argument('--trim-frames', type=int, default=60,
                    help='Frames to trim from clip start (default 60 = 1s @60fps)')
    args = ap.parse_args()

    r    = dvr.scriptapp('Resolve')
    proj = r.GetProjectManager().GetCurrentProject()
    pool = proj.GetMediaPool()
    tl   = proj.GetCurrentTimeline()
    fps  = float(proj.GetSetting('timelineFrameRate'))
    tl_start_abs = tl.GetStartFrame()

    if args.report:
        report_path = Path(args.report)
    else:
        report_path = latest_report_for(tl.GetName())
        if report_path is None:
            print('ERROR: no QA report. Run verify_pipeline.py first.', file=sys.stderr)
            return 1
    report = json.loads(report_path.read_text(encoding='utf-8'))
    teal = [f for f in report.get('flags', []) if f.get('color') == 'Teal']
    print(f'Teal flags in report: {len(teal)}')
    if not teal:
        return 0

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())

    plans = []
    for flag in teal:
        # Locate the flagged clip by src_start (most stable identifier)
        target_v1 = None
        for c in v1:
            if c.GetLeftOffset() == flag['src_start'] and \
               c.GetDuration() == (flag['src_end'] - flag['src_start']):
                target_v1 = c
                break
        if target_v1 is None:
            # Fallback: match by TL position
            for c in v1:
                if abs(c.GetStart() - tl_start_abs - flag['tl_start_s'] * fps) < 5:
                    target_v1 = c
                    break
        if target_v1 is None:
            print(f'  SKIP flag at TL {flag["tl_start_s"]}s: clip not found')
            continue
        if target_v1.GetDuration() <= args.trim_frames + 30:
            print(f'  SKIP {flag["tl_start_s"]}s: clip too short to trim {args.trim_frames}f')
            continue
        _, a1c = find_v1_a1_pair(tl, target_v1)
        plans.append({
            'v1': target_v1, 'a1': a1c,
            'new_src_start': target_v1.GetLeftOffset() + args.trim_frames,
            'new_duration': target_v1.GetDuration() - args.trim_frames,
        })

    print(f'\nPlanned trims: {len(plans)}')
    for p in plans:
        c = p['v1']
        print(f'  TRIM_START  V1 @ TL {(c.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'src {c.GetLeftOffset()} → {p["new_src_start"]}  '
              f'(A1 paired: {bool(p["a1"])})')

    if args.dry_run:
        print('\nDRY RUN — no changes')
        return 0

    # Execute: for each plan, delete v1+a1 (no ripple), re-insert with new src_start.
    refs = []
    to_delete = []
    for p in plans:
        v1c = p['v1']
        a1c = p['a1']
        record = v1c.GetStart()
        ref = {
            'record': record,
            'v1_mpi': v1c.GetMediaPoolItem(),
            'v1_src_start': p['new_src_start'],
            'v1_src_end':   p['new_src_start'] + p['new_duration'],
        }
        if a1c is not None:
            ref['a1_mpi'] = a1c.GetMediaPoolItem()
            a1_offset_inside = a1c.GetLeftOffset() + args.trim_frames
            ref['a1_src_start'] = a1_offset_inside
            ref['a1_src_end']   = a1_offset_inside + p['new_duration']
        refs.append(ref)
        to_delete.append(v1c)
        if a1c is not None:
            to_delete.append(a1c)

    if not to_delete:
        return 0
    ok = tl.DeleteClips(to_delete, False)
    print(f'DeleteClips returned: {ok}')

    clip_infos = []
    for ref in refs:
        if ref.get('v1_mpi'):
            clip_infos.append({
                'mediaPoolItem': ref['v1_mpi'],
                'startFrame':   ref['v1_src_start'],
                'endFrame':     ref['v1_src_end'],
                'recordFrame':  ref['record'],
                'trackIndex':   1, 'mediaType': 1,
            })
        if ref.get('a1_mpi'):
            clip_infos.append({
                'mediaPoolItem': ref['a1_mpi'],
                'startFrame':   ref['a1_src_start'],
                'endFrame':     ref['a1_src_end'],
                'recordFrame':  ref['record'],
                'trackIndex':   1, 'mediaType': 2,
            })

    placed = pool.AppendToTimeline(clip_infos) or []
    print(f'Re-placed {len(placed)}/{len(clip_infos)} (v1+a1)')

    # Re-color V1 survivors Mint
    v1_after = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    repaired = 0
    for ref in refs:
        for nc in v1_after:
            if nc.GetStart() == ref['record']:
                nc.SetClipColor('Mint')
                repaired += 1
                break
    print(f'Re-colored {repaired} V1 clips Mint')

    return 0


if __name__ == '__main__':
    sys.exit(main())
