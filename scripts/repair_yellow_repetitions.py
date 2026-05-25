"""
repair_yellow_repetitions.py — for each Yellow-flagged V1 clip (missed
repetition / stutter): ripple-delete the clip from V1+A1.

The verifier already validated each yellow flag (either by micro-cluster
heuristic or MFCC similarity ≥ threshold). User flags are also trusted —
yellow means "should have been cut, was not". So this script just executes
the delete.

Usage:
    repair_yellow_repetitions.py
    repair_yellow_repetitions.py --dry-run
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
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    r    = dvr.scriptapp('Resolve')
    proj = r.GetProjectManager().GetCurrentProject()
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
    yellow = [f for f in report.get('flags', []) if f.get('color') == 'Yellow']
    print(f'Yellow flags in report: {len(yellow)}')
    if not yellow:
        return 0

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
    def a1_at(tl_pos: int):
        for ac in a1:
            if ac.GetStart() == tl_pos:
                return ac
        return None

    targets = []
    for flag in yellow:
        target = None
        for c in v1:
            if c.GetLeftOffset() == flag['src_start'] and \
               c.GetDuration() == (flag['src_end'] - flag['src_start']):
                target = c
                break
        if target is None:
            print(f'  WARN: yellow clip not found at TL {flag["tl_start_s"]}s')
            continue
        targets.append({'v1': target, 'a1': a1_at(target.GetStart()),
                        'reason': flag['reason']})

    print(f'\nPlanned ripple-deletes: {len(targets)}')
    for t in targets:
        c = t['v1']
        print(f'  DELETE  TL {(c.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'dur {c.GetDuration()/fps:.3f}s  ({t["reason"]})')

    if args.dry_run:
        print('\nDRY RUN — no changes')
        return 0

    del_items = []
    for t in targets:
        del_items.append(t['v1'])
        if t['a1']:
            del_items.append(t['a1'])
    if not del_items:
        return 0
    ok = tl.DeleteClips(del_items, True)  # ripple
    print(f'Ripple-deleted {len(del_items)} V1+A1 items: {ok}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
