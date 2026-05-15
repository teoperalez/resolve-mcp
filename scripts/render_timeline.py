"""
Render the current Resolve timeline using one of two built-in presets:

  --preset qa  → YouTube - 720p  (fast QA render for review)
  --preset 4k  → YouTube - 2160p (production-quality 4K render)

Both presets are Resolve's built-in YouTube presets, which produce
H.264-encoded MP4 files with sensible bitrates for delivery.

Output filename: <timeline-name>_<preset-tag>.mp4
Default output dir: alongside the source video (read from the most-recent
transcripts/*.json's `audio` field), or override with --output-dir.

Process:
  1. Load the chosen built-in preset
  2. Override TargetDir + CustomName so output goes where we want
  3. Add job to render queue (skipping any prior queued/completed jobs)
  4. Start rendering; poll until Resolve reports IsRenderingInProgress=False
  5. Print final job status + output file path

Usage:
    python render_timeline.py --preset {qa|4k} [--output-dir PATH]
                              [--filename-tag TAG]
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PRESET_MAP = {
    'qa':    'YouTube - 720p',
    '4k':    'YouTube - 2160p',
    'audio': None,                # special — manual settings, no preset
}
DEFAULT_FILENAME_TAGS = {
    'qa':    'QA_720p',
    '4k':    'FINAL_4K',
    'audio': 'AUDIO_MIX',
}


def default_output_dir(project_name_hint: str | None = None) -> Path:
    """Find the source-video directory by walking up from the transcript's
    `audio` field. Auto-editor convention: source video is at
    `<dir>/<name>.mp4` and split audio is at `<dir>/<name>_tracks/1.wav` —
    so if the audio's parent ends with `_tracks`, the video's parent is the
    grandparent. Falls back to ./renders if no transcript is available."""
    tdir = Path('transcripts')
    if tdir.exists():
        candidates = sorted(tdir.glob('*.json'),
                            key=lambda f: f.stat().st_mtime, reverse=True)
        for f in candidates:
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
            except Exception:
                continue
            audio = data.get('audio') if isinstance(data, dict) else None
            if not audio:
                continue
            p = Path(audio)
            # Walk up if we're inside an auto-editor `<name>_tracks` folder
            parent = p.parent
            if parent.name.endswith('_tracks') and parent.parent.exists():
                return parent.parent
            if parent.exists():
                return parent
    return Path('renders').resolve()


def safe_filename(s: str) -> str:
    """Strip characters that don't belong in a Windows filename."""
    bad = set('<>:"|?*\\/')
    return ''.join('_' if c in bad else c for c in s).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--preset', required=True, choices=list(PRESET_MAP),
                    help='qa = YouTube 720p (QA review); 4k = YouTube 2160p (final)')
    ap.add_argument('--output-dir', default=None,
                    help='Output directory (default: next to the source video, '
                         'else ./renders/)')
    ap.add_argument('--filename-tag', default=None,
                    help=f'Suffix added to the output filename. Defaults: '
                         f'qa→{DEFAULT_FILENAME_TAGS["qa"]}, '
                         f'4k→{DEFAULT_FILENAME_TAGS["4k"]}')
    ap.add_argument('--poll-sec', type=float, default=10.0,
                    help='Polling interval for render progress (default: 10s)')
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print('ERROR: No active timeline.', file=sys.stderr)
        return 1

    preset_name = PRESET_MAP[args.preset]
    tag         = args.filename_tag or DEFAULT_FILENAME_TAGS[args.preset]
    out_dir     = Path(args.output_dir).resolve() if args.output_dir \
                   else default_output_dir(project.GetName())
    out_dir.mkdir(parents=True, exist_ok=True)
    output_name = safe_filename(f'{timeline.GetName()}_{tag}')

    print(f'Project:        {project.GetName()!r}')
    print(f'Timeline:       {timeline.GetName()!r}')
    print(f'Preset:         {preset_name!r}  ({args.preset})')
    print(f'Output dir:     {out_dir}')
    print(f'Output name:    {output_name}.mp4')

    # ── Switch to Deliver page so render runs reliably ──
    if not resolve.OpenPage('deliver'):
        print('WARN: OpenPage("deliver") returned False — continuing anyway')

    if args.preset == 'audio':
        # Audio-only render: no Resolve preset, configure settings manually
        ok = project.SetRenderSettings({
            'TargetDir':       str(out_dir),
            'CustomName':      output_name,
            'ExportVideo':     False,
            'ExportAudio':     True,
            'VideoFormat':     'mp4',     # container; video stream disabled
            'AudioCodec':      'aac',     # widely-playable; high enough for review
            'AudioBitDepth':   '16',
            'AudioSampleRate': '48000',
            'FormatWidth':     1280,      # required even when video disabled
            'FormatHeight':    720,
        })
        if not ok:
            print('WARN: SetRenderSettings returned False — trying H.264 Master',
                  'with audio-only override', file=sys.stderr)
            project.LoadRenderPreset('H.264 Master')
            project.SetRenderSettings({
                'TargetDir':     str(out_dir),
                'CustomName':    output_name,
                'ExportVideo':   False,
                'ExportAudio':   True,
            })
        print(f'Audio-only mode: AAC into MP4 container')
    else:
        # ── Load the chosen preset (video render) ──
        if not project.LoadRenderPreset(preset_name):
            print(f'ERROR: LoadRenderPreset({preset_name!r}) returned False — '
                  f'preset may not exist in this Resolve install.', file=sys.stderr)
            return 1
        print(f'Loaded preset: {preset_name!r}')

        # ── Override output path + filename ──
        ok = project.SetRenderSettings({
            'TargetDir':   str(out_dir),
            'CustomName':  output_name,
        })
        if not ok:
            print('WARN: SetRenderSettings returned False — render path overrides '
                  'may not have applied', file=sys.stderr)

    # ── Track existing render jobs so we can identify ours ──
    pre_existing = {j.get('JobId') for j in (project.GetRenderJobs() or [])
                    if isinstance(j, dict)}

    # ── Add to queue ──
    job_id = project.AddRenderJob()
    if not job_id:
        print('ERROR: AddRenderJob returned no id. Is the timeline rendererable?',
              file=sys.stderr)
        return 1
    print(f'Render job queued: id={job_id!r}')

    # ── Start rendering this specific job ──
    start_ok = project.StartRendering([job_id])
    if not start_ok:
        # Older Resolve API accepts a single id, not a list:
        start_ok = project.StartRendering(job_id)
    print(f'StartRendering: {start_ok!r}')

    # ── Poll until complete ──
    started_ts = time.time()
    last_pct = -1
    while True:
        in_prog = project.IsRenderingInProgress()
        status = project.GetRenderJobStatus(job_id) or {}
        pct = status.get('CompletionPercentage', status.get('Progress', 0))
        if pct != last_pct:
            elapsed = int(time.time() - started_ts)
            print(f'  [{elapsed:5d}s] in_progress={in_prog}  pct={pct}  '
                  f'status={status.get("JobStatus") or status.get("Status") or "?"}')
            last_pct = pct
        if not in_prog:
            break
        time.sleep(args.poll_sec)

    final = project.GetRenderJobStatus(job_id) or {}
    print(f'\nFinal status: {final}')

    # ── Resolve final output path ──
    # Try common extensions Resolve might use; mp4 covers both video and
    # audio-only AAC; m4a sometimes used for audio-only.
    candidates = []
    for ext in ('.mp4', '.m4a', '.wav'):
        p = out_dir / f'{output_name}{ext}'
        if p.exists():
            candidates.append(p)
    if not candidates:
        # Resolve sometimes appends a trailing _ or frame-range before ext
        for ext in ('.mp4', '.m4a', '.wav'):
            candidates.extend(out_dir.glob(f'{output_name}*{ext}'))
    if candidates:
        for c in candidates:
            sz_mb = c.stat().st_size / (1024 * 1024)
            print(f'Output:        {c}  ({sz_mb:.1f} MB)')
    else:
        print(f'WARN: expected output not found in {out_dir}.', file=sys.stderr)

    job_status = (final.get('JobStatus') or final.get('Status') or '').lower()
    if 'fail' in job_status or 'cancel' in job_status:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
