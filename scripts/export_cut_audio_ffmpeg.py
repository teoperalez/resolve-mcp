"""
Extract the post-cut audio of the current Resolve timeline directly from
the source video via ffmpeg, bypassing Resolve's render pipeline.

The keep-segments come from the CURRENT TIMELINE'S V1 layout (filtered to
the dominant gameplay source). Each V1 clip's source range is one keep
segment. This matches exactly what re-rendering the cut timeline's A1
would produce — but in seconds instead of hours.

Usage:
    python export_cut_audio_ffmpeg.py [--source-video PATH]
                                      [--output PATH]
                                      [--iter N]
"""
import sys
import os
import json
import subprocess
import argparse
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


def _ffmpeg_cmd():
    if shutil.which('ffmpeg'):
        return 'ffmpeg'
    raise FileNotFoundError('ffmpeg not on PATH')


def find_source_video() -> Path | None:
    """Locate the source video by walking from a transcript's `audio` field."""
    tdir = Path('transcripts')
    if not tdir.exists():
        return None
    for f in sorted(tdir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        audio = data.get('audio') if isinstance(data, dict) else None
        if not audio:
            continue
        p = Path(audio)
        # Walk up from .../<name>_tracks/N.wav to .../<name>.mp4
        parent = p.parent
        if parent.name.endswith('_tracks'):
            stem = parent.name[:-len('_tracks')]
            candidate = parent.parent / f'{stem}.mp4'
            if candidate.exists():
                return candidate
        # Same dir, try .mp4 with same stem
        for ext in ('.mp4', '.mov', '.mkv'):
            cand = parent / f'{p.stem}{ext}'
            if cand.exists():
                return cand
    return None


def find_default_cuts_replay() -> Path | None:
    """Look next to the source video for *_cuts_replay.json."""
    src = find_source_video()
    if not src:
        return None
    for p in src.parent.glob('*_cuts_replay.json'):
        return p
    return None


def compute_keep_segments(cuts_frames: list[dict], source_duration_frames: int):
    """Given sorted source-frame cut ranges and the source duration,
    return the list of (start_frame, end_frame) keep ranges."""
    cuts = sorted(((c['start'], c['end']) for c in cuts_frames), key=lambda x: x[0])
    keep = []
    cur = 0
    for cs, ce in cuts:
        if cs > cur:
            keep.append((cur, cs))
        cur = max(cur, ce)
    if cur < source_duration_frames:
        keep.append((cur, source_duration_frames))
    return keep


def keep_segments_from_timeline(args_fps_hint=60.0):
    """Read V1 clips from current Resolve timeline, return a list of
    (src_start_frame, src_end_frame) keep ranges (filtered to the dominant
    source name). Sorted by timeline position."""
    import DaVinciResolveScript as dvr
    from collections import Counter
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    tl = project.GetCurrentTimeline()
    fps = float(project.GetSetting('timelineFrameRate') or args_fps_hint)
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    if not v1:
        return [], fps
    names = [c.GetName() for c in v1]
    dominant = Counter(names).most_common(1)[0][0]
    print(f'Timeline: {tl.GetName()!r}  dominant source: {dominant!r}  fps={fps}')
    keep = []
    for c in v1:
        if c.GetName() != dominant:
            continue
        keep.append((c.GetLeftOffset(), c.GetLeftOffset() + c.GetDuration()))
    return keep, fps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source-video', default=None,
                    help='Source video path (default: auto-detect)')
    ap.add_argument('--output', default=None,
                    help='Output WAV (default: transcripts/audio-cut-iter<N>.wav)')
    ap.add_argument('--iter', type=int, default=2,
                    help='Iteration number (controls default filename only)')
    ap.add_argument('--fps', type=float, default=60.0,
                    help='Source frames per second hint (default: 60)')
    args = ap.parse_args()

    src = Path(args.source_video).resolve() if args.source_video \
          else find_source_video()
    if not src or not src.exists():
        print('ERROR: could not find source video', file=sys.stderr)
        return 1
    print(f'Source: {src}')

    out_path = Path(args.output).resolve() if args.output \
               else Path('transcripts').resolve() / f'audio-cut-iter{args.iter}.wav'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    keep, fps = keep_segments_from_timeline(args.fps)
    if not keep:
        print('ERROR: no V1 keep segments from current timeline', file=sys.stderr)
        return 1
    args.fps = fps
    total_kept_sec = sum((e - s) for s, e in keep) / fps
    print(f'Keep segments: {len(keep)}  total kept: {total_kept_sec:.2f}s')

    # Per-segment extract + concat-demuxer stitch. The aselect-filter approach
    # blows up at ~100 segments due to filter-graph memory limits, so we take
    # the segment-extract path which scales cleanly.
    ff = _ffmpeg_cmd()
    with tempfile.TemporaryDirectory(prefix='cut_audio_') as tmpdir:
        tmp = Path(tmpdir)
        seg_paths = []
        print(f'\nExtracting {len(keep)} keep segments to {tmp} ...')
        for i, (s, e) in enumerate(keep):
            s_sec = s / args.fps
            dur_sec = (e - s) / args.fps
            seg_path = tmp / f'seg_{i:05d}.wav'
            cmd = [
                ff, '-y', '-loglevel', 'error',
                '-ss', f'{s_sec:.5f}',
                '-t',  f'{dur_sec:.5f}',
                '-i', str(src),
                '-vn',
                '-c:a', 'pcm_s16le',
                '-ar', '48000',
                '-ac', '2',
                str(seg_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f'ffmpeg failed on segment {i}:', file=sys.stderr)
                print(res.stderr[-1500:], file=sys.stderr)
                return 1
            seg_paths.append(seg_path)

        # Build concat list
        list_path = tmp / 'concat.txt'
        list_path.write_text(
            '\n'.join(f"file '{p.as_posix()}'" for p in seg_paths),
            encoding='utf-8',
        )
        print(f'Concatenating ...')
        cmd = [
            ff, '-y', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0',
            '-i', str(list_path),
            '-c', 'copy',
            str(out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print('ffmpeg concat failed:', file=sys.stderr)
            print(res.stderr[-1500:], file=sys.stderr)
            return 1

    sz_mb = out_path.stat().st_size / (1024 * 1024)
    print(f'\nWrote: {out_path}  ({sz_mb:.1f} MB)')
    print(f'\nReady for transcription:\n  '
          f'.venv\\Scripts\\python scripts\\transcribe_audio.py "{out_path}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
