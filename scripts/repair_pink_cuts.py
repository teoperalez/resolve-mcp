"""
repair_pink_cuts.py — for each Pink-flagged V1 clip:

(a) Tiny remnants (clip duration < 0.3s by default) → ripple-delete from V1+A1
    (these are speech-fragment debris with no semantic value).
(b) Larger clips where a cut endpoint sits in active speech → snap the cut
    endpoint to the nearest silence (within ±0.5s) by extending the clip
    forward or backward into the source. Mirror on A1.

If no silence is found within max_drift, the cut is left as-is and the clip
is re-colored Purple to flag it as "needs manual review".

Usage:
    repair_pink_cuts.py
    repair_pink_cuts.py --dry-run
    repair_pink_cuts.py --tiny-thresh 0.3
    repair_pink_cuts.py --max-drift 0.5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr
import _audio_tools as A

QA_REPORTS_DIR = Path('_data/qa-reports')
SR = 48000


def latest_report_for(timeline_name: str) -> Path | None:
    stem = re.sub(r'[^\w\-]', '_', timeline_name or 'timeline')
    p = QA_REPORTS_DIR / f'{stem}.json'
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', default=None)
    ap.add_argument('--tiny-thresh', type=float, default=0.30,
                    help='Clips shorter than this (sec) get deleted as remnants (default 0.3)')
    ap.add_argument('--max-drift', type=float, default=0.50,
                    help='Max ±seconds to extend a cut to reach silence (default 0.5)')
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
    pink = [f for f in report.get('flags', []) if f.get('color') == 'Pink']
    source_path = report.get('source_path')
    print(f'Pink flags in report: {len(pink)}')
    print(f'Source: {source_path}')
    if not pink:
        return 0
    if not source_path:
        print('ERROR: source path missing from report; rerun verify_pipeline.py', file=sys.stderr)
        return 1

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
    def a1_at(tl_pos: int):
        for ac in a1:
            if ac.GetStart() == tl_pos:
                return ac
        return None

    # Classify each flag
    deletes = []   # tiny remnants
    extends = []   # (clip, new_src_start, new_src_end, drift_sec, edge)
    skips   = []   # unrecoverable (no silence within max_drift)

    for flag in pink:
        # Locate flagged clip
        target_v1 = None
        for c in v1:
            if c.GetLeftOffset() == flag['src_start'] and \
               c.GetDuration() == (flag['src_end'] - flag['src_start']):
                target_v1 = c
                break
        if target_v1 is None:
            print(f'  WARN: clip not found for flag at TL {flag["tl_start_s"]}s')
            continue

        dur_s = target_v1.GetDuration() / fps
        if dur_s < args.tiny_thresh:
            deletes.append({'v1': target_v1, 'a1': a1_at(target_v1.GetStart()),
                            'reason': flag['reason']})
            continue

        # For larger clips: snap whichever edge the reason mentions.
        # Reasons:
        #   "cut-in truncated speech ..." → fix LeftOffset (extend backward into silence
        #     or pull forward past speech). We extend backward toward silence.
        #   "cut-out truncated speech ..."→ fix RightOffset (extend forward).
        src_start = target_v1.GetLeftOffset()
        src_end   = src_start + target_v1.GetDuration()
        src_start_s = src_start / fps
        src_end_s   = src_end / fps

        edge = 'unknown'
        reason = flag.get('reason', '')
        if 'cut-in' in reason:
            edge = 'in'
        elif 'cut-out' in reason:
            edge = 'out'
        elif 'user-flagged' in reason:
            # User-flagged with no direction hint: probe both edges, snap the
            # one with smaller drift (better silence found).
            edge = 'auto'

        if edge == 'in':
            # Probe a window around the cut-in: [src_start_s - max_drift, src_start_s + 0.1]
            win_start = max(0, src_start_s - args.max_drift)
            win_dur   = (src_start_s + 0.1) - win_start
            audio = A.extract_audio_window(source_path, win_start, win_dur)
            target_in_win = src_start_s - win_start  # target_sec inside the window
            res = A.snap_to_nearest_silence(audio, SR, target_in_win,
                                            max_drift_sec=args.max_drift)
            if res is None:
                skips.append({'v1': target_v1, 'edge': 'in', 'reason': flag['reason']})
                continue
            snapped_sec, drift = res
            # snapped_sec is inside the window; convert back to source-sec
            new_src_start_s = win_start + snapped_sec
            new_src_start_f = int(round(new_src_start_s * fps))
            # Only accept if it extends BACKWARD (was the speech-truncation case)
            if new_src_start_f >= src_start:
                skips.append({'v1': target_v1, 'edge': 'in',
                              'reason': flag['reason'] + ' (snap moved forward; declined)'})
                continue
            extends.append({'v1': target_v1, 'a1': a1_at(target_v1.GetStart()),
                            'new_src_start': new_src_start_f,
                            'new_src_end':   src_end,
                            'drift': drift, 'edge': 'in'})
        elif edge == 'out':
            # Probe [src_end_s - 0.1, src_end_s + max_drift]
            win_start = max(0, src_end_s - 0.1)
            win_dur   = (src_end_s + args.max_drift) - win_start
            audio = A.extract_audio_window(source_path, win_start, win_dur)
            target_in_win = src_end_s - win_start
            res = A.snap_to_nearest_silence(audio, SR, target_in_win,
                                            max_drift_sec=args.max_drift)
            if res is None:
                skips.append({'v1': target_v1, 'edge': 'out', 'reason': flag['reason']})
                continue
            snapped_sec, drift = res
            new_src_end_s = win_start + snapped_sec
            new_src_end_f = int(round(new_src_end_s * fps))
            if new_src_end_f <= src_end:
                skips.append({'v1': target_v1, 'edge': 'out',
                              'reason': flag['reason'] + ' (snap moved backward; declined)'})
                continue
            extends.append({'v1': target_v1, 'a1': a1_at(target_v1.GetStart()),
                            'new_src_start': src_start,
                            'new_src_end':   new_src_end_f,
                            'drift': drift, 'edge': 'out'})
        elif edge == 'auto':
            # User-flagged with no direction hint: probe both edges; only consider
            # edges where the CURRENT endpoint is in active speech (= needs repair).
            res_in  = None
            res_out = None
            try:
                win_start = max(0, src_start_s - args.max_drift)
                win_dur   = (src_start_s + 0.1) - win_start
                a = A.extract_audio_window(source_path, win_start, win_dur)
                # Speech check at current in-edge: 0.1s probe straddling src_start
                edge_probe = A.extract_audio_window(source_path,
                                                    max(0, src_start_s - 0.05), 0.1)
                if A.is_speech_active(edge_probe, SR, threshold_db=-30):
                    res_in = A.snap_to_nearest_silence(a, SR, src_start_s - win_start,
                                                       max_drift_sec=args.max_drift)
            except Exception:
                pass
            try:
                win_start_o = max(0, src_end_s - 0.1)
                win_dur_o   = (src_end_s + args.max_drift) - win_start_o
                a = A.extract_audio_window(source_path, win_start_o, win_dur_o)
                edge_probe = A.extract_audio_window(source_path,
                                                    max(0, src_end_s - 0.05), 0.1)
                if A.is_speech_active(edge_probe, SR, threshold_db=-30):
                    res_out = A.snap_to_nearest_silence(a, SR, src_end_s - win_start_o,
                                                        max_drift_sec=args.max_drift)
            except Exception:
                pass
            picks = []
            if res_in and abs(res_in[1]) > 0.001:
                picks.append(('in', res_in, win_start))
            if res_out and abs(res_out[1]) > 0.001:
                picks.append(('out', res_out, win_start_o))
            if not picks:
                skips.append({'v1': target_v1, 'edge': 'auto', 'reason': flag['reason']})
                continue
            picks.sort(key=lambda x: abs(x[1][1]))
            best_edge, (snapped_sec, drift), w0 = picks[0]
            if best_edge == 'in':
                new_src_start_s = w0 + snapped_sec
                new_src_start_f = int(round(new_src_start_s * fps))
                # Accept any direction — extension OR contraction.
                if new_src_start_f == src_start:
                    skips.append({'v1': target_v1, 'edge': 'auto',
                                  'reason': flag['reason'] + ' (snap = current pos)'})
                    continue
                extends.append({'v1': target_v1, 'a1': a1_at(target_v1.GetStart()),
                                'new_src_start': new_src_start_f,
                                'new_src_end':   src_end,
                                'drift': drift, 'edge': 'in'})
            else:
                new_src_end_s = w0 + snapped_sec
                new_src_end_f = int(round(new_src_end_s * fps))
                if new_src_end_f == src_end:
                    skips.append({'v1': target_v1, 'edge': 'auto',
                                  'reason': flag['reason'] + ' (snap = current pos)'})
                    continue
                extends.append({'v1': target_v1, 'a1': a1_at(target_v1.GetStart()),
                                'new_src_start': src_start,
                                'new_src_end':   new_src_end_f,
                                'drift': drift, 'edge': 'out'})
        else:
            skips.append({'v1': target_v1, 'edge': 'unknown', 'reason': flag['reason']})

    print(f'\nPlanned: delete {len(deletes)} tiny, extend {len(extends)} cuts, '
          f'skip {len(skips)} (no silence in ±{args.max_drift}s)')
    for d in deletes:
        c = d['v1']
        print(f'  DELETE  TL {(c.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'dur {c.GetDuration()/fps:.3f}s')
    for e in extends:
        c = e['v1']
        delta_s = (e['new_src_end'] - e['new_src_start'] - c.GetDuration()) / fps
        print(f'  EXTEND  TL {(c.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'edge={e["edge"]}  drift {e["drift"]*1000:+.0f}ms  Δdur {delta_s:+.3f}s')
    for s in skips:
        c = s['v1']
        print(f'  SKIP    TL {(c.GetStart()-tl_start_abs)/fps:.2f}s  '
              f'edge={s["edge"]}  → Purple (manual review)')

    if args.dry_run:
        print('\nDRY RUN — no changes')
        return 0

    # Execute deletes (ripple)
    if deletes:
        del_items = []
        for d in deletes:
            del_items.append(d['v1'])
            if d['a1']:
                del_items.append(d['a1'])
        ok = tl.DeleteClips(del_items, True)  # ripple
        print(f'Ripple-deleted {len(del_items)} clips (V1+A1): {ok}')

    # Re-fetch lists after delete (timeline shifted)
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())

    # Execute extends: delete + re-insert with adjusted src range
    repaired = 0
    for e in extends:
        # Re-find the V1 clip in the post-ripple list by source-frame fingerprint
        target_v1 = None
        for c in v1:
            if c.GetLeftOffset() == e['v1'].GetLeftOffset() and \
               c.GetDuration() == e['v1'].GetDuration():
                target_v1 = c
                break
        if target_v1 is None:
            print(f'  WARN: extend clip not found after ripple; skipping')
            continue
        target_a1 = None
        for ac in a1:
            if ac.GetStart() == target_v1.GetStart():
                target_a1 = ac
                break

        # Snapshot
        mpi_v = target_v1.GetMediaPoolItem()
        mpi_a = target_a1.GetMediaPoolItem() if target_a1 else None
        record = target_v1.GetStart()
        delta_back  = max(0, target_v1.GetLeftOffset() - e['new_src_start'])
        delta_front = max(0, e['new_src_end'] - (target_v1.GetLeftOffset() + target_v1.GetDuration()))
        # The new record position needs to shift LEFT by delta_back so the new
        # backward-extended portion sits where the original cut was.
        # BUT extending forward only grows duration — no record shift.
        new_record = record - delta_back

        # A1 mirror — assume same offset pattern as V1
        a1_off_orig = target_a1.GetLeftOffset() if target_a1 else None
        a1_new_start = (a1_off_orig - delta_back) if target_a1 else None
        a1_new_end   = (a1_off_orig + target_a1.GetDuration() + delta_front) if target_a1 else None

        to_delete = [target_v1]
        if target_a1: to_delete.append(target_a1)
        ok = tl.DeleteClips(to_delete, False)
        if not ok:
            print(f'  WARN: extend delete failed at TL {(record-tl_start_abs)/fps:.2f}s')
            continue
        infos = [{
            'mediaPoolItem': mpi_v,
            'startFrame':   e['new_src_start'],
            'endFrame':     e['new_src_end'],
            'recordFrame':  new_record,
            'trackIndex':   1, 'mediaType': 1,
        }]
        if mpi_a:
            infos.append({
                'mediaPoolItem': mpi_a,
                'startFrame':   a1_new_start,
                'endFrame':     a1_new_end,
                'recordFrame':  new_record,
                'trackIndex':   1, 'mediaType': 2,
            })
        placed = pool.AppendToTimeline(infos) or []
        if placed:
            repaired += 1
            # Refresh listings & re-color
            v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
            a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
            for nc in v1:
                if nc.GetStart() == new_record:
                    nc.SetClipColor('Navy')
                    break

    # Mark skips as Purple for manual review
    purpled = 0
    for s in skips:
        # Re-find in current v1 list
        for c in v1:
            if c.GetLeftOffset() == s['v1'].GetLeftOffset() and \
               c.GetDuration() == s['v1'].GetDuration():
                c.SetClipColor('Purple')
                purpled += 1
                break

    print(f'\nSummary: deleted {len(deletes)} tiny, extended {repaired} cuts, '
          f'{purpled} marked Purple for manual review')
    return 0


if __name__ == '__main__':
    sys.exit(main())
