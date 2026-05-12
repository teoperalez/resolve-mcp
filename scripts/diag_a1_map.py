"""
Diagnostic: dump A1 clip source ranges and check battle timestamp coverage.
Usage: python diag_a1_map.py [battles_json]
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

BATTLES_DEFAULT = Path('transcripts/battles.json')

def main():
    battles_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BATTLES_DEFAULT
    battles = json.loads(battles_path.read_text(encoding='utf-8')) if battles_path.exists() else []

    resolve = dvr.scriptapp('Resolve')
    tl  = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
    fps = float(tl.GetSetting('timelineFrameRate'))
    print(f'Timeline FPS: {fps}')
    print(f'Timeline start frame: {tl.GetStartFrame()}')
    print()

    clips = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
    print(f'A1 clips ({len(clips)} total):')
    print(f'  {"#":>3}  {"tl_start":>10}  {"tl_end":>10}  {"tl_dur":>8}  {"src_start_s":>12}  {"src_end_s":>10}  {"left_off_f":>10}  name')
    entries = []
    for i, c in enumerate(clips):
        tl_start  = c.GetStart()
        tl_dur    = c.GetDuration()
        tl_end    = tl_start + tl_dur
        left_off  = c.GetLeftOffset()
        src_start = left_off / fps
        src_end   = (left_off + tl_dur) / fps
        name      = c.GetName() if hasattr(c, 'GetName') else '?'
        entries.append((tl_start, tl_end, src_start, src_end, c))
        print(f'  {i:>3}  {tl_start:>10}  {tl_end:>10}  {tl_dur:>8}  {src_start:>12.3f}  {src_end:>10.3f}  {left_off:>10}  {name}')

    print()
    print('Battle timestamp coverage:')
    for b in battles:
        ts   = b['timestamp_sec']
        name = b.get('trainer_name', '?')
        found = None
        for tl_start, tl_end, src_start, src_end, c in entries:
            if src_start <= ts <= src_end:
                offset = round((ts - src_start) * fps)
                tl_frame = tl_start + offset
                found = (tl_frame, src_start, src_end, tl_start, tl_end)
                break
        if found:
            tl_frame, ss, se, tls, tle = found
            print(f'  OK    {ts:8.2f}s  {name:<20}  -> frame {tl_frame}  (clip src {ss:.2f}–{se:.2f}s, tl {tls}–{tle})')
        else:
            # Find nearest clip
            nearest = min(entries, key=lambda e: min(abs(ts - e[2]), abs(ts - e[3])))
            tls, tle, ss, se, _ = nearest
            gap_before = ts - se if ts > se else None
            gap_after  = ss - ts if ts < ss else None
            gap_str = f'nearest clip src {ss:.2f}–{se:.2f}s'
            if gap_before: gap_str += f'  ({gap_before:.2f}s AFTER clip end)'
            if gap_after:  gap_str += f'  ({gap_after:.2f}s BEFORE clip start)'
            print(f'  MISS  {ts:8.2f}s  {name:<20}  {gap_str}')

if __name__ == '__main__':
    main()
