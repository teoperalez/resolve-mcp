"""
Transcribe the audio source file used on A1 in the current Resolve timeline.
Outputs a JSON file with word-level timestamps compatible with detect_battles.py.

Copies the faster-whisper approach from IRLPC Hyperframes/scripts/transcribe_fw.py
with GPU/CPU fallback and Windows CUDA DLL path registration.

Usage:
    python transcribe_audio.py [--model medium.en] [--out transcripts]

Output:
    transcripts/<stem>.json  — segments with word timestamps
"""
import sys
import os
import argparse
import glob
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr


def _register_nvidia_dlls() -> None:
    """Register CUDA DLL dirs so CTranslate2 can find cublas/cudnn on Windows."""
    if os.name != "nt":
        return
    for base in sys.path:
        if "site-packages" not in base:
            continue
        for bin_dir in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(bin_dir)
            except OSError:
                pass
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def get_audio_source_path() -> Path:
    """Find the source file path for the first media pool item used on A1."""
    resolve  = dvr.scriptapp('Resolve')
    tl       = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
    a1       = tl.GetItemListInTrack('audio', 1) or []
    if not a1:
        raise RuntimeError('No clips on Audio 1')

    mpi  = a1[0].GetMediaPoolItem()
    if mpi is None:
        raise RuntimeError('Could not get MediaPoolItem for A1 clip')

    path = mpi.GetClipProperty('File Path')
    if not path:
        raise RuntimeError('MediaPoolItem has no File Path property')
    return Path(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model',        default='large-v3-turbo')
    parser.add_argument('--out',          default='transcripts', type=Path)
    parser.add_argument('--device',       default='cuda')
    parser.add_argument('--compute-type', default='float16')
    parser.add_argument('--language',     default='en')
    parser.add_argument('--audio',        default=None, type=Path,
                        help='Override audio file path (default: auto-detect from Resolve A1)')
    parser.add_argument('--vad', action='store_true', default=True,
                        help='Enable VAD filter to skip non-speech (default: on)')
    parser.add_argument('--no-vad', dest='vad', action='store_false',
                        help='Disable VAD filter')
    args = parser.parse_args()

    audio_path = args.audio if args.audio else get_audio_source_path()
    if not audio_path.exists():
        print(f'Audio file not found: {audio_path}', file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    print(f'Audio source: {audio_path}')

    _register_nvidia_dlls()

    from faster_whisper import WhisperModel

    print(f'Loading model {args.model} on {args.device} ({args.compute_type})...', flush=True)
    t0 = time.time()
    try:
        model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    except Exception as e:
        print(f'GPU init failed: {e}\nFalling back to CPU int8.', flush=True)
        args.device       = 'cpu'
        args.compute_type = 'int8'
        model = WhisperModel(args.model, device='cpu', compute_type='int8')
    print(f'Loaded in {time.time() - t0:.1f}s', flush=True)

    def _transcribe(m):
        return m.transcribe(
            str(audio_path),
            language=args.language,
            word_timestamps=True,
            vad_filter=args.vad,
            beam_size=5,
            condition_on_previous_text=False,  # prevents "." repetition loop on game audio
        )

    print(f'Transcribing...', flush=True)
    t0 = time.time()
    segments_iter, info = _transcribe(model)
    duration = info.duration

    collected = []
    try:
        for i, seg in enumerate(segments_iter):
            collected.append((i, seg))
            pct = seg.end / duration * 100 if duration else 0
            print(f'  [{seg.start:7.2f} -> {seg.end:7.2f}] ({pct:5.1f}%) {seg.text.strip()[:80]}', flush=True)
    except RuntimeError as e:
        msg = str(e)
        if args.device == 'cuda' and any(k in msg.lower() for k in ('cublas', 'cudnn', 'cuda')):
            print(f'\nGPU runtime failure, retrying on CPU...\n', flush=True)
            del model
            model = WhisperModel(args.model, device='cpu', compute_type='int8')
            segments_iter, info = _transcribe(model)
            duration = info.duration
            collected = [(i, seg) for i, seg in enumerate(segments_iter)]
        else:
            raise

    segments_out = []
    for i, seg in collected:
        words_out = []
        for w in (seg.words or []):
            words_out.append({
                'word':        w.word,
                'start':       round(float(w.start), 3),
                'end':         round(float(w.end), 3),
                'probability': round(float(w.probability), 4),
            })
        segments_out.append({
            'id':    i,
            'start': round(float(seg.start), 3),
            'end':   round(float(seg.end), 3),
            'text':  seg.text,
            'words': words_out,
        })

    elapsed = time.time() - t0
    print(f'Done in {elapsed:.1f}s (RTF={elapsed/duration:.2f}x)', flush=True)

    payload = {
        'text':     ''.join(s['text'] for s in segments_out),
        'language': info.language,
        'duration': duration,
        'audio':    str(audio_path),
        'segments': segments_out,
    }
    out_path = args.out / (audio_path.stem + '.json')
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
