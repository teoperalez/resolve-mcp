"""
Extract the post-cut audio of a cut FCPXML directly from the source video
via ffmpeg, bypassing Resolve's render pipeline.

Reads the cut variant's `_cuts_replay.json` (produced by
apply_cuts_to_fcpxml.py) — its `src_cuts_frames` field tells us which
source-frame intervals were removed. The complement = keep-segments. We
extract each keep-segment's audio as a temp WAV and concat into the output.

Output: a 48kHz/16-bit mono (or stereo) WAV that matches what re-rendering
the cut timeline's A1 would produce — but in seconds instead of hours.

Usage:
    python export_cut_audio_ffmpeg.py [--source-video PATH]
                                      [--cuts-replay PATH]
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source-video', default=None,
                    help='Source video path (default: auto-detect)')
    ap.add_argument('--cuts-replay', default=None,
                    help='Cut replay JSON (default: auto-detect next to source)')
    ap.add_argument('--output', default=None,
                    help='Output WAV (default: transcripts/audio-cut-iter<N>.wav)')
    ap.add_argument('--iter', type=int, default=2,
                    help='Iteration number (controls default filename only)')
    ap.add_argument('--variant', default='all_cuts',
                    choices=['all_cuts', 'high_only'],
                    help='Which cut variant from the replay JSON to use')
    ap.add_argument('--fps', type=float, default=60.0,
                    help='Source frames per second (default: 60)')
    args = ap.parse_args()

    src = Path(args.source_video).resolve() if args.source_video \
          else find_source_video()
    if not src or not src.exists():
        print('ERROR: could not find source video', file=sys.stderr)
        return 1
    print(f'Source: {src}')

    replay_path = Path(args.cuts_replay).resolve() if args.cuts_replay \
                  else find_default_cuts_replay()
    if not replay_path or not replay_path.exists():
        print('ERROR: could not find cuts_replay.json', file=sys.stderr)
        return 1
    print(f'Cuts:   {replay_path}')
    replay = json.loads(replay_path.read_text(encoding='utf-8'))
    variant = replay.get(args.variant, {})
    cuts_frames = variant.get('src_cuts_frames', [])
    if not cuts_frames:
        print('No cuts found in replay file (variant=%s)' % args.variant,
              file=sys.stderr)
        return 1

    out_path = Path(args.output).resolve() if args.output \
               else Path('transcripts').resolve() / f'audio-cut-iter{args.iter}.wav'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Get source duration in frames via ffprobe
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=duration', '-of', 'default=nw=1:nk=1', str(src)],
        capture_output=True, text=True, check=True,
    )
    src_dur_sec = float(probe.stdout.strip())
    src_dur_frames = int(round(src_dur_sec * args.fps))
    print(f'Source duration: {src_dur_sec:.2f}s ({src_dur_frames} frames @ {args.fps}fps)')

    keep = compute_keep_segments(cuts_frames, src_dur_frames)
    total_kept_sec = sum((e - s) for s, e in keep) / args.fps
    print(f'Keep segments: {len(keep)}  total kept: {total_kept_sec:.2f}s')

    # Build a single ffmpeg command that uses concat-filter to stitch keep ranges
    # in one pass — much faster than per-segment extract + concat.
    ff = _ffmpeg_cmd()
    inputs = ['-y', '-i', str(src)]
    # filter_complex: aselect=between(t,a0,b0)+between(t,a1,b1)+...,asetpts
    parts = []
    for s, e in keep:
        s_sec = s / args.fps
        e_sec = e / args.fps
        parts.append(f'between(t,{s_sec:.5f},{e_sec:.5f})')
    select_expr = '+'.join(parts)
    fc = f'[0:a]aselect=\'{select_expr}\',asetpts=N/SR/TB[a]'
    cmd = [ff] + inputs + [
        '-filter_complex', fc,
        '-map', '[a]',
        '-c:a', 'pcm_s16le',
        '-ar', '48000',
        '-ac', '2',
        str(out_path),
    ]
    print(f'\nRunning ffmpeg ({len(parts)} keep segments)...')
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print('ffmpeg failed:', file=sys.stderr)
        print(res.stderr[-3000:], file=sys.stderr)
        return 1

    sz_mb = out_path.stat().st_size / (1024 * 1024)
    print(f'\nWrote: {out_path}  ({sz_mb:.1f} MB)')
    print(f'\nReady for transcription:\n  '
          f'.venv\\Scripts\\python scripts\\transcribe_audio.py "{out_path}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
