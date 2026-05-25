"""
repair_lime_battle_gaps.py — for each Lime-flagged V1 clip (missing battle
pre-roll): steal 60 frames from the PREVIOUS V1 clip's right-handle so the
lime clip can pull its LeftOffset back by 60 frames. Mirror on A1.

Algorithm per flag:
1. Find the previous V1 clip on the timeline.
2. Trim 60 frames off the previous clip's end (shorten duration).
3. Pull the lime clip's LeftOffset back by 60 frames (extend backward into the
   newly-freed source range — note: this requires the lime clip's source to
   have left-handle available; if it doesn't, we trim previous clip but
   shift TL position of lime instead).
4. Mirror on A1.

If previous clip can't surrender 60 frames (too short), warn and skip.

Usage:
    repair_lime_battle_gaps.py
    repair_lime_battle_gaps.py --dry-run
    repair_lime_battle_gaps.py --gap-frames 60
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
MIN_PREV_DURATION_AFTER_TRIM = 30  # leave at least 0.5s of prev clip


def latest_report_for(timeline_name: str) -> Path | None:
    stem = re.sub(r'[^\w\-]', '_', timeline_name or 'timeline')
    p = QA_REPORTS_DIR / f'{stem}.json'
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', default=None)
    ap.add_argument('--gap-frames', type=int, default=60)
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
    lime = [f for f in report.get('flags', []) if f.get('color') == 'Lime']
    print(f'Lime flags in report: {len(lime)}')
    if not lime:
        return 0

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())

    def a1_at(tl_pos: int):
        for ac in a1:
            if ac.GetStart() == tl_pos:
                return ac
        return None

    plans = []
    for flag in lime:
        # Locate flagged clip
        target_idx = None
        for i, c in enumerate(v1):
            if c.GetLeftOffset() == flag['src_start'] and \
               c.GetDuration() == (flag['src_end'] - flag['src_start']):
                target_idx = i
                break
        if target_idx is None:
            print(f'  SKIP lime at TL {flag["tl_start_s"]}s: clip not found')
            continue
        if target_idx == 0:
            print(f'  SKIP lime at TL {flag["tl_start_s"]}s: no previous V1 clip')
            continue
        lime_v1 = v1[target_idx]
        prev_v1 = v1[target_idx - 1]
        prev_dur = prev_v1.GetDuration()
        if prev_dur < args.gap_frames + MIN_PREV_DURATION_AFTER_TRIM:
            print(f'  SKIP lime at TL {flag["tl_start_s"]}s: prev clip too short '
                  f'({prev_dur}f < {args.gap_frames + MIN_PREV_DURATION_AFTER_TRIM}f)')
            continue

        # Check whether lime clip has left-handle to extend backward.
        lime_left_off = lime_v1.GetLeftOffset()
        can_extend_back = lime_left_off >= args.gap_frames

        plan = {
            'prev_v1': prev_v1, 'prev_a1': a1_at(prev_v1.GetStart()),
            'lime_v1': lime_v1, 'lime_a1': a1_at(lime_v1.GetStart()),
            'gap_frames': args.gap_frames,
            'can_extend_back': can_extend_back,
            'battle': flag.get('battle'),
        }
        plans.append(plan)

    print(f'\nPlanned repairs: {len(plans)}')
    for p in plans:
        prev = p['prev_v1']
        lime = p['lime_v1']
        action = 'extend lime back' if p['can_extend_back'] else 'shift lime TL pos'
        print(f'  LIME {p["battle"]!r}  '
              f'TL {(lime.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'(prev TL {(prev.GetStart()-tl_start_abs)/fps:.2f}s, '
              f'dur {prev.GetDuration()}f → {prev.GetDuration()-p["gap_frames"]}f) '
              f'[{action}]')

    if args.dry_run:
        print('\nDRY RUN — no changes')
        return 0

    # Execute: for each plan, modify the PAIR (prev + lime) on both V1 and A1.
    # Strategy: delete and re-insert the 2 clips per plan (prev shortened, lime
    # extended-back-into-handle OR shifted-left-on-TL).
    for p in plans:
        prev_v1 = p['prev_v1']; prev_a1 = p['prev_a1']
        lime_v1 = p['lime_v1']; lime_a1 = p['lime_a1']
        gap = p['gap_frames']

        # Snapshot state before delete
        prev_state = {
            'mpi_v': prev_v1.GetMediaPoolItem(),
            'mpi_a': prev_a1.GetMediaPoolItem() if prev_a1 else None,
            'record': prev_v1.GetStart(),
            'src_start_v': prev_v1.GetLeftOffset(),
            'src_end_v_new': prev_v1.GetLeftOffset() + prev_v1.GetDuration() - gap,
            'src_start_a': prev_a1.GetLeftOffset() if prev_a1 else None,
            'src_end_a_new': (prev_a1.GetLeftOffset() + prev_a1.GetDuration() - gap)
                              if prev_a1 else None,
        }
        # Lime: if can_extend_back, src_start - gap (offset reduces by gap),
        #       record stays the same; duration grows by gap.
        # Else: src_start unchanged, record shifts LEFT by gap (uses freed slot),
        #       duration grows by gap.
        if p['can_extend_back']:
            lime_state = {
                'mpi_v': lime_v1.GetMediaPoolItem(),
                'mpi_a': lime_a1.GetMediaPoolItem() if lime_a1 else None,
                'record': lime_v1.GetStart() - gap,
                'src_start_v': lime_v1.GetLeftOffset() - gap,
                'src_end_v':   lime_v1.GetLeftOffset() - gap + lime_v1.GetDuration() + gap,
                'src_start_a': (lime_a1.GetLeftOffset() - gap) if lime_a1 else None,
                'src_end_a':   ((lime_a1.GetLeftOffset() - gap)
                                 + lime_a1.GetDuration() + gap) if lime_a1 else None,
            }
        else:
            # No left-handle — just shift TL position so the freed slot from prev's
            # shortened tail is used; clip itself is unchanged.
            lime_state = {
                'mpi_v': lime_v1.GetMediaPoolItem(),
                'mpi_a': lime_a1.GetMediaPoolItem() if lime_a1 else None,
                'record': lime_v1.GetStart() - gap,
                'src_start_v': lime_v1.GetLeftOffset(),
                'src_end_v':   lime_v1.GetLeftOffset() + lime_v1.GetDuration(),
                'src_start_a': lime_a1.GetLeftOffset() if lime_a1 else None,
                'src_end_a':   (lime_a1.GetLeftOffset() + lime_a1.GetDuration())
                                if lime_a1 else None,
            }

        # Delete the 2 clips (4 if A1 present)
        to_delete = [prev_v1, lime_v1]
        if prev_a1: to_delete.append(prev_a1)
        if lime_a1: to_delete.append(lime_a1)
        ok = tl.DeleteClips(to_delete, False)
        if not ok:
            print(f'  WARN: DeleteClips failed for battle {p["battle"]!r}, skipping')
            continue

        # Re-insert
        infos = [
            {'mediaPoolItem': prev_state['mpi_v'],
             'startFrame':   prev_state['src_start_v'],
             'endFrame':     prev_state['src_end_v_new'],
             'recordFrame':  prev_state['record'],
             'trackIndex':   1, 'mediaType': 1},
            {'mediaPoolItem': lime_state['mpi_v'],
             'startFrame':   lime_state['src_start_v'],
             'endFrame':     lime_state['src_end_v'],
             'recordFrame':  lime_state['record'],
             'trackIndex':   1, 'mediaType': 1},
        ]
        if prev_state['mpi_a']:
            infos.append({'mediaPoolItem': prev_state['mpi_a'],
                          'startFrame':   prev_state['src_start_a'],
                          'endFrame':     prev_state['src_end_a_new'],
                          'recordFrame':  prev_state['record'],
                          'trackIndex':   1, 'mediaType': 2})
        if lime_state['mpi_a']:
            infos.append({'mediaPoolItem': lime_state['mpi_a'],
                          'startFrame':   lime_state['src_start_a'],
                          'endFrame':     lime_state['src_end_a'],
                          'recordFrame':  lime_state['record'],
                          'trackIndex':   1, 'mediaType': 2})
        placed = pool.AppendToTimeline(infos) or []
        print(f'  Battle {p["battle"]!r}: re-placed {len(placed)}/{len(infos)}')

        # Refresh V1/A1 listings for next iteration
        v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
        a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
        # Re-color the now-prepended lime clip Mint
        for nc in v1:
            if nc.GetStart() == lime_state['record']:
                nc.SetClipColor('Mint')
                break

    return 0


if __name__ == '__main__':
    sys.exit(main())
