"""
Export the audio of the current Resolve timeline to a WAV file for
re-transcription. Used by the iterative cut-candidates workflow:

  apply_cuts → export_cut_audio → transcribe (Whisper) → remap_transcript
  → mark_cut_candidates → apply_cuts → ...

Renders A1 only (or all audio, depending on the timeline) as 48 kHz 16-bit
WAV via Resolve's render API. The output filename includes an iteration
counter so successive iterations don't overwrite each other.

Usage:
    python export_cut_audio.py [--output PATH] [--iter N]
                               [--audio-tracks 1] [--poll-sec 10]
"""
import sys
import os
import time
import argparse
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


def safe_filename(s: str) -> str:
    bad = set('<>:"|?*\\/')
    return ''.join('_' if c in bad else c for c in s).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', default=None,
                    help='Output WAV path. Default: '
                         '<repo>/transcripts/audio-cut-iter<N>.wav')
    ap.add_argument('--iter', type=int, default=1,
                    help='Iteration number (controls default filename only)')
    ap.add_argument('--poll-sec', type=float, default=10.0)
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

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_dir = Path('transcripts').resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'audio-cut-iter{args.iter}.wav'
    out_dir = out_path.parent
    out_name = out_path.stem  # without .wav

    print(f'Timeline: {timeline.GetName()!r}')
    print(f'Output:   {out_path}')

    # Switch to Deliver page
    resolve.OpenPage('deliver')

    # ── Configure render settings: audio-only WAV ──
    settings = {
        'TargetDir':            str(out_dir),
        'CustomName':           out_name,
        'ExportVideo':          False,
        'ExportAudio':          True,
        'AudioCodec':           'LinearPCM',
        'AudioBitDepth':        16,
        'AudioSampleRate':      48000,
        'FormatWidth':          1280,    # Resolve requires these even for audio-only
        'FormatHeight':         720,
        'VideoFormat':          'wav',   # wav as container
    }
    ok = project.SetRenderSettings(settings)
    print(f'SetRenderSettings: {ok}')
    if not ok:
        # Some versions need 'AudioFormat' rather than 'VideoFormat' for WAV.
        # Try a fallback that loads a known preset then overrides audio-only.
        print('Falling back to YouTube preset + audio-only override')
        project.LoadRenderPreset('YouTube - 720p')
        project.SetRenderSettings({
            'TargetDir':       str(out_dir),
            'CustomName':      out_name,
            'ExportVideo':     False,
            'ExportAudio':     True,
        })

    job_id = project.AddRenderJob()
    if not job_id:
        print('ERROR: AddRenderJob returned no id', file=sys.stderr)
        return 1
    print(f'Render job queued: id={job_id!r}')

    start_ok = project.StartRendering([job_id])
    if not start_ok:
        start_ok = project.StartRendering(job_id)
    print(f'StartRendering: {start_ok!r}')

    # Poll
    started = time.time()
    last_pct = -1
    while True:
        in_prog = project.IsRenderingInProgress()
        st = project.GetRenderJobStatus(job_id) or {}
        pct = st.get('CompletionPercentage', 0)
        if pct != last_pct:
            elapsed = int(time.time() - started)
            print(f'  [{elapsed:5d}s] in_progress={in_prog}  pct={pct}  '
                  f'status={st.get("JobStatus") or "?"}')
            last_pct = pct
        if not in_prog:
            break
        time.sleep(args.poll_sec)

    final = project.GetRenderJobStatus(job_id) or {}
    print(f'\nFinal status: {final}')

    # Resolve sometimes writes <name>.wav and sometimes <name>_track<N>.wav
    # depending on multi-track output. Scan and report.
    cands = sorted(out_dir.glob(f'{out_name}*.wav'))
    if cands:
        for c in cands:
            sz = c.stat().st_size / (1024 * 1024)
            print(f'Output file: {c}  ({sz:.1f} MB)')
        # If we got exactly one, that's the file. Otherwise warn.
        if len(cands) == 1:
            print(f'\nReady for transcription:\n  python scripts/transcribe_audio.py "{cands[0]}"')
    else:
        print(f'WARN: no output file found at {out_path}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
