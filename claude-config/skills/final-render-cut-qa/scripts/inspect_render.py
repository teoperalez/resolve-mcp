"""Wrap ffprobe to inspect a rendered video and emit structured JSON.

Usage:
    python inspect_render.py <video-path>
    # Prints JSON to stdout, exit 0 on valid, 1 on fail

Output schema:
    {
        "path": "<abs>",
        "duration_sec": float,
        "video_streams": [{codec, width, height, fps}],
        "audio_streams": [{codec, channels, sample_rate}],
        "ok": bool,
        "errors": [str]
    }
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def inspect(video_path: str) -> dict:
    out = {
        'path': str(Path(video_path).resolve()),
        'duration_sec': None,
        'video_streams': [],
        'audio_streams': [],
        'ok': False,
        'errors': [],
    }
    if not Path(video_path).exists():
        out['errors'].append(f'File not found: {video_path}')
        return out

    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries',
        'format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate',
        '-of', 'json',
        video_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        out['errors'].append('ffprobe not on PATH — install ffmpeg first')
        return out
    if r.returncode != 0:
        out['errors'].append(f'ffprobe failed: {r.stderr.strip()}')
        return out

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        out['errors'].append(f'ffprobe output not JSON: {e}')
        return out

    out['duration_sec'] = float(data.get('format', {}).get('duration', 0))

    for s in data.get('streams', []):
        kind = s.get('codec_type')
        if kind == 'video':
            fps_str = s.get('r_frame_rate', '0/1')
            num, den = fps_str.split('/')
            fps = float(num) / float(den) if float(den) else 0
            out['video_streams'].append({
                'codec': s.get('codec_name'),
                'width': s.get('width'),
                'height': s.get('height'),
                'fps': fps,
            })
        elif kind == 'audio':
            out['audio_streams'].append({
                'codec': s.get('codec_name'),
                'channels': s.get('channels'),
                'sample_rate': s.get('sample_rate'),
            })

    if out['duration_sec'] <= 0:
        out['errors'].append('Duration is zero or missing')
    if not out['video_streams']:
        out['errors'].append('No video stream')
    if not out['audio_streams']:
        out['errors'].append('No audio stream')

    out['ok'] = len(out['errors']) == 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video_path')
    args = ap.parse_args()

    result = inspect(args.video_path)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
