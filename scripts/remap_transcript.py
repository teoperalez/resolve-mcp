"""
Remap a Whisper transcript whose timestamps are in CUT-AUDIO time back to
ORIGINAL-SOURCE time, using the current Resolve timeline's V1 layout.

The cut audio (produced by `export_cut_audio.py` from the rendered cut
timeline) has timestamps starting at 0. Each second of the cut audio
corresponds to some second of the ORIGINAL gameplay source — but only on
the keep-segments (the parts not cut). This script walks the V1 layout
and produces a new transcript file with timestamps in original-source-time,
which downstream scripts (mark_cut_candidates.py, classify_*, etc.) can
consume as if it were the original transcript.

Strategy:
  1. Enumerate V1 clips on the current timeline (filtered to the dominant
     gameplay source — same logic as mark_cut_candidates).
  2. Build a list of (tl_start_sec, tl_end_sec, src_start_sec) entries.
     Each entry is a "keep segment".
  3. The cut audio is the concatenation of these segments in tl order.
     So cut-audio-second `t_cut` corresponds to:
       - Find the keep-segment whose cumulative duration first exceeds t_cut
       - Within that segment, original-source-second =
         segment.src_start + (t_cut - cumulative_before_segment)

  4. Apply that mapping to every segment/word timestamp.

Usage:
    python remap_transcript.py INPUT_TRANSCRIPT.json
                               [--output OUTPUT.json]
                               [--source-name NAME]
"""
import sys
import os
import json
import argparse
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


def build_keep_segments(timeline, fps: float):
    """Return list of (cut_start_sec, src_start_sec, length_sec) tuples,
    sorted by timeline position. `cut_start_sec` is the cut-audio time
    where this segment starts (cumulative). `src_start_sec` is the
    original-source second the segment starts from. `length_sec` is the
    duration. Only includes clips from the dominant (gameplay) source name."""
    v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    if not v1:
        return []
    names = [c.GetName() for c in v1]
    dominant = Counter(names).most_common(1)[0][0]
    print(f'Dominant source: {dominant!r}')

    keep = []
    cur_cut = 0.0
    for c in v1:
        if c.GetName() != dominant:
            # Skip structural clips. Their tl-time doesn't appear in the cut
            # audio either (we exported audio of the WHOLE timeline though —
            # which would include structural audio if any. The mapping is
            # still correct as long as we skip the same clips Whisper saw
            # as non-gameplay).
            #
            # In practice: if intro/outro have audio, they contribute to the
            # cut audio. We're treating them as "outside the gameplay" and
            # not mapping their content. Their transcript segments will be
            # mapped to invalid src ranges and the downstream cut analyzer
            # will treat them as "outside any clip" and ignore them.
            continue
        src_start_sec = c.GetLeftOffset() / fps
        length_sec    = c.GetDuration() / fps
        keep.append((cur_cut, src_start_sec, length_sec))
        cur_cut += length_sec
    return keep


def cut_time_to_src(t_cut: float, keep_segments):
    """Map cut-audio second to original-source second. Returns None if
    t_cut is past the end of the cut audio."""
    for cut_s, src_s, length in keep_segments:
        if cut_s <= t_cut <= cut_s + length:
            return src_s + (t_cut - cut_s)
    return None


def remap(transcript: dict, keep_segments) -> dict:
    """Build a new transcript with original-source timestamps."""
    out = dict(transcript)  # shallow copy of top-level fields
    new_segments = []
    skipped = 0
    for s in transcript.get('segments', []):
        new_start = cut_time_to_src(s['start'], keep_segments)
        new_end   = cut_time_to_src(s['end'],   keep_segments)
        if new_start is None or new_end is None:
            skipped += 1
            continue
        new_seg = dict(s)
        new_seg['start'] = new_start
        new_seg['end']   = new_end
        new_seg['words'] = []
        for w in s.get('words', []):
            ws = cut_time_to_src(float(w.get('start', 0)), keep_segments)
            we = cut_time_to_src(float(w.get('end',   0)), keep_segments)
            if ws is None or we is None:
                continue
            nw = dict(w)
            nw['start'] = ws
            nw['end']   = we
            new_seg['words'].append(nw)
        new_segments.append(new_seg)
    out['segments'] = new_segments
    if skipped:
        print(f'  WARN: skipped {skipped} segment(s) whose timestamps fell '
              f'outside any keep segment (probably intro/outro audio).')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='Cut-audio transcript (output of transcribe_audio.py)')
    ap.add_argument('--output', default=None,
                    help='Output remapped transcript (default: <input>_remapped.json)')
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f'ERROR: {in_path} not found', file=sys.stderr)
        return 1
    out_path = Path(args.output) if args.output \
               else in_path.with_name(in_path.stem + '_remapped.json')

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps = float(project.GetSetting('timelineFrameRate'))

    print(f'Building keep-segment map from {timeline.GetName()!r} (fps={fps})')
    keep = build_keep_segments(timeline, fps)
    total = sum(L for _, _, L in keep)
    print(f'Keep segments: {len(keep)}  total cut-audio duration: {total:.2f}s')

    transcript = json.loads(in_path.read_text(encoding='utf-8'))
    print(f'Input transcript: {len(transcript.get("segments", []))} segments')

    remapped = remap(transcript, keep)
    print(f'Remapped: {len(remapped["segments"])} segments')

    out_path.write_text(json.dumps(remapped, indent=2, ensure_ascii=False),
                        encoding='utf-8')
    print(f'\nWrote: {out_path}  ({out_path.stat().st_size // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
