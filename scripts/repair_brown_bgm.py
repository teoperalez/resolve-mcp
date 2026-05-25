"""
repair_brown_bgm.py — for each Brown-flagged A2 clip (BGM overlapping a battle):
trim the clip's END to land at the battle start. Re-color Mint on success.

Reads flags from _data/qa-reports/<timeline-stem>.json. If the report is stale,
re-run verify_pipeline.py first.

Usage:
    repair_brown_bgm.py                # repair brown flags from latest report
    repair_brown_bgm.py --dry-run      # show planned trims; no changes
    repair_brown_bgm.py --report PATH  # use a specific QA report
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', default=None,
                    help='Specific QA report JSON (default: auto-detect for current timeline)')
    args = ap.parse_args()

    r    = dvr.scriptapp('Resolve')
    proj = r.GetProjectManager().GetCurrentProject()
    pool = proj.GetMediaPool()
    tl   = proj.GetCurrentTimeline()
    fps  = float(proj.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    # Load report
    if args.report:
        report_path = Path(args.report)
    else:
        report_path = latest_report_for(tl.GetName())
        if report_path is None:
            print('ERROR: no QA report found for this timeline. Run verify_pipeline.py first.',
                  file=sys.stderr)
            return 1
    report = json.loads(report_path.read_text(encoding='utf-8'))
    brown = [f for f in report.get('flags', []) if f.get('color') == 'Brown']
    print(f'Brown flags in report: {len(brown)}')
    if not brown:
        return 0

    # For each brown flag we need: the A2 clip + the battle start TL frame.
    # Battle TL start = source_sec → TL via v1_map.
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())

    def src_sec_to_tl_frame(sec: float) -> int | None:
        for c in v1:
            src_s = c.GetLeftOffset() / fps
            src_e = (c.GetLeftOffset() + c.GetDuration()) / fps
            if src_s <= sec <= src_e:
                return c.GetStart() + int(round((sec - src_s) * fps))
        return None

    # Need battles.json to map trainer_name → source_sec
    battles_path = Path('transcripts/battles.json')
    if not battles_path.exists():
        print('ERROR: transcripts/battles.json not found', file=sys.stderr)
        return 1
    battles = json.loads(battles_path.read_text(encoding='utf-8'))
    battle_by_name = {b['trainer_name'].lower(): b for b in battles}

    a2 = sorted(tl.GetItemListInTrack('audio', 2) or [], key=lambda c: c.GetStart())

    plans = []
    for flag in brown:
        battle_name = flag.get('battle', '').lower()
        b = battle_by_name.get(battle_name)
        if not b:
            print(f'  SKIP brown clip {flag["i"]}: battle {battle_name!r} not in battles.json')
            continue
        battle_tl_frame = src_sec_to_tl_frame(b['timestamp_sec'])
        if battle_tl_frame is None:
            print(f'  SKIP brown clip {flag["i"]}: battle source {b["timestamp_sec"]}s not on V1')
            continue
        # Locate A2 clip by index — but indices can shift if A2 was modified.
        # Match by name + tl_start to be safe.
        target = None
        for ac in a2:
            if ac.GetName() == flag.get('name') and \
               abs((ac.GetStart() - tl_start) / fps - flag['tl_start_s']) < 0.5:
                target = ac
                break
        if target is None:
            print(f'  SKIP brown clip: {flag.get("name")!r} not found at TL {flag["tl_start_s"]}s')
            continue
        # Plan: trim end to battle_tl_frame
        if battle_tl_frame >= target.GetEnd():
            print(f'  SKIP {target.GetName()!r}: already ends before battle start')
            continue
        new_dur = battle_tl_frame - target.GetStart()
        if new_dur < 30:  # less than 0.5s left → just delete
            plans.append({'clip': target, 'op': 'delete', 'reason': flag['reason']})
        else:
            plans.append({'clip': target, 'op': 'trim_end',
                          'new_end_tl_frame': battle_tl_frame,
                          'new_duration': new_dur,
                          'reason': flag['reason']})

    print(f'\nPlanned operations: {len(plans)}')
    for p in plans:
        c = p['clip']
        if p['op'] == 'delete':
            print(f'  DELETE  {c.GetName()!r}  '
                  f'(TL {(c.GetStart()-tl_start)/fps:.2f}..{(c.GetEnd()-tl_start)/fps:.2f}s)')
        else:
            print(f'  TRIM    {c.GetName()!r}  '
                  f'(TL {(c.GetStart()-tl_start)/fps:.2f}..{(c.GetEnd()-tl_start)/fps:.2f}s)  '
                  f'→ end at TL {(p["new_end_tl_frame"]-tl_start)/fps:.2f}s')

    if args.dry_run:
        print('\nDRY RUN — no changes')
        return 0

    # Execute: trim = delete + re-insert with shorter endFrame.
    to_delete = [p['clip'] for p in plans]
    if not to_delete:
        return 0
    # Capture per-clip state before delete (object refs become stale post-delete)
    refs = []
    for p in plans:
        c = p['clip']
        mpi = c.GetMediaPoolItem()
        if mpi is None:
            continue
        src_start = c.GetLeftOffset()
        cur_end_src = src_start + c.GetDuration()
        record = c.GetStart()
        if p['op'] == 'trim_end':
            new_src_end = src_start + p['new_duration']
        else:
            new_src_end = None
        refs.append({
            'p': p, 'mpi': mpi, 'src_start': src_start,
            'cur_end_src': cur_end_src,
            'record': record, 'new_src_end': new_src_end,
        })

    # Make sure A2 is unlocked
    try:
        tl.SetTrackLock('audio', 2, False)
    except Exception:
        pass

    ok = tl.DeleteClips(to_delete, False)  # non-ripple
    print(f'DeleteClips returned: {ok}')

    # Re-insert the trim survivors
    clip_infos = []
    for ref in refs:
        if ref['p']['op'] == 'delete':
            continue
        clip_infos.append({
            'mediaPoolItem': ref['mpi'],
            'startFrame':   ref['src_start'],
            'endFrame':     ref['new_src_end'],  # exclusive
            'recordFrame':  ref['record'],
            'trackIndex':   2,
            'mediaType':    2,
        })
    placed = pool.AppendToTimeline(clip_infos) or []
    print(f'Re-placed {len(placed)}/{len(clip_infos)} trimmed clips')

    # Re-color survivors Mint
    a2_after = sorted(tl.GetItemListInTrack('audio', 2) or [], key=lambda c: c.GetStart())
    repaired = 0
    for ref in refs:
        if ref['p']['op'] == 'delete':
            continue
        for nc in a2_after:
            if nc.GetStart() == ref['record']:
                nc.SetClipColor('Mint')
                repaired += 1
                break
    print(f'Re-colored {repaired} clips Mint (repaired)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
