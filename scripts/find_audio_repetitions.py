"""
Detect duplicate / near-duplicate audio passages within a single WAV file.

Whisper's decoder applies repetition penalties that hide duplicate phrases in
the transcript — so a transcript-only QA pass will miss audio duplicates that
came from upstream tooling (SRC_OVERLAP, double-recorded takes, etc.). This
script ignores the transcript and operates on the waveform directly:

  1. Compute MFCC features at a fine frame rate (10ms hop, 25ms window).
  2. For each candidate window, compare it to subsequent windows within a
     bounded time-lag (default 0.4s..3s) using cosine similarity in the
     flattened MFCC feature space.
  3. Group adjacent high-similarity matches into "candidate" repetition
     events.
  4. For each candidate, optionally re-transcribe the surrounding window
     with `large-v3` + repetition penalties DISABLED — the decoder settings
     that default-Whisper uses to hide repeats. If the re-transcription
     contains an obvious repeated n-gram, the candidate is confirmed.

Output: JSON list of {start_sec, end_sec, lag_sec, similarity, transcript}.

Typical use:
    .venv\\Scripts\\python scripts\\find_audio_repetitions.py \\
        "E:\\Misty Red\\Misty Red - DIALOGUE_REVIEW_v6.wav" \\
        --window-ms 500 --min-lag-ms 400 --max-lag-ms 3000 \\
        --sim-threshold 0.85 --min-duration-ms 250 \\
        --transcribe-candidates --out repetitions-v6.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class Candidate:
    start_sec: float       # start of the FIRST occurrence
    end_sec: float         # end of the FIRST occurrence (= start of the second)
    second_start_sec: float
    second_end_sec: float
    lag_sec: float
    similarity_peak: float
    similarity_mean: float
    transcript: str | None = None
    repeated_ngram: str | None = None


def _load_audio(path: Path, sr: int) -> tuple[np.ndarray, int]:
    import librosa
    y, file_sr = librosa.load(str(path), sr=sr, mono=True)
    return y, file_sr


def _compute_mfcc(y: np.ndarray, sr: int, n_mfcc: int,
                   hop_length: int, n_fft: int) -> np.ndarray:
    import librosa
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc,
                                 hop_length=hop_length, n_fft=n_fft)
    # Per-frame z-score so cosine similarity reflects shape, not absolute level
    mu = mfcc.mean(axis=0, keepdims=True)
    sd = mfcc.std(axis=0, keepdims=True) + 1e-6
    return ((mfcc - mu) / sd).astype(np.float32)


def _scan_for_repetitions(mfcc: np.ndarray, frame_sec: float,
                            window_frames: int, hop_frames: int,
                            min_lag_frames: int, max_lag_frames: int,
                            sim_threshold: float, min_duration_frames: int,
                            verbose: bool = False) -> list[Candidate]:
    """Sliding self-similarity: for each starting position i, check how
    similar the window [i, i+W) is to the windows [i+L, i+L+W) for L in
    [min_lag, max_lag]. Record positions where similarity >= threshold
    persists across consecutive starting positions."""
    n_frames = mfcc.shape[1]
    n_starts = (n_frames - window_frames - max_lag_frames) // hop_frames
    if n_starts <= 0:
        return []

    if verbose:
        print(f'  frames: {n_frames}, starts: {n_starts}, '
              f'lag range: {min_lag_frames*frame_sec:.2f}..{max_lag_frames*frame_sec:.2f}s, '
              f'window: {window_frames*frame_sec:.2f}s', file=sys.stderr)

    # For every starting position i, compute the BEST similarity over the
    # whole lag range and record (best_lag, best_sim).
    best_sim = np.full(n_starts, -1.0, dtype=np.float32)
    best_lag = np.zeros(n_starts, dtype=np.int32)

    # Pre-flatten + L2-normalize windows so we can use simple dot products.
    feat_dim = mfcc.shape[0] * window_frames
    starts = np.arange(n_starts) * hop_frames
    # We'll compute similarities in chunks of `chunk` starts at a time to
    # keep memory bounded.
    chunk = 256
    for c0 in range(0, n_starts, chunk):
        c1 = min(c0 + chunk, n_starts)
        idx = starts[c0:c1]
        # Flatten anchor windows: shape (c, feat_dim)
        anchors = np.stack(
            [mfcc[:, s:s+window_frames].reshape(-1) for s in idx]
        )
        anchors /= (np.linalg.norm(anchors, axis=1, keepdims=True) + 1e-6)

        # For each lag L in [min, max), build a "candidate-windows" matrix
        # and dot against anchors. Doing this per-lag is the simplest way
        # to keep memory linear in n_starts.
        for L in range(min_lag_frames, max_lag_frames + 1, hop_frames):
            cand_starts = idx + L
            cand = np.stack(
                [mfcc[:, s:s+window_frames].reshape(-1) for s in cand_starts]
            )
            cand /= (np.linalg.norm(cand, axis=1, keepdims=True) + 1e-6)
            sims = (anchors * cand).sum(axis=1)
            mask = sims > best_sim[c0:c1]
            best_sim[c0:c1] = np.where(mask, sims, best_sim[c0:c1])
            best_lag[c0:c1] = np.where(mask, L, best_lag[c0:c1])

        if verbose and c0 % (chunk * 10) == 0:
            print(f'    scanned {c1}/{n_starts} starts...', file=sys.stderr)

    # Find runs of consecutive starts whose best_sim >= threshold AND whose
    # best_lag is roughly stable (so we don't merge unrelated repetitions
    # that happen to alias near each other).
    candidates: list[Candidate] = []
    i = 0
    while i < n_starts:
        if best_sim[i] < sim_threshold:
            i += 1
            continue
        run_start = i
        ref_lag = best_lag[i]
        sims = [best_sim[i]]
        lags = [best_lag[i]]
        j = i + 1
        # Allow lag drift of up to ~15% of the running median lag — keeps
        # multi-syllable runs together while rejecting unrelated spikes.
        while j < n_starts and best_sim[j] >= sim_threshold:
            cur = best_lag[j]
            med = int(np.median(lags))
            if abs(cur - med) > max(2, med // 7):
                break
            sims.append(best_sim[j])
            lags.append(cur)
            j += 1
        run_len = j - run_start
        if run_len >= max(1, min_duration_frames // hop_frames):
            s_frame = starts[run_start]
            e_frame = starts[j - 1] + window_frames
            lag_frames = int(np.median(lags))
            second_s = s_frame + lag_frames
            second_e = e_frame + lag_frames
            candidates.append(Candidate(
                start_sec        = float(s_frame * frame_sec),
                end_sec          = float(e_frame * frame_sec),
                second_start_sec = float(second_s * frame_sec),
                second_end_sec   = float(second_e * frame_sec),
                lag_sec          = float(lag_frames * frame_sec),
                similarity_peak  = float(max(sims)),
                similarity_mean  = float(np.mean(sims)),
            ))
        i = j

    return candidates


def _merge_overlapping(cands: list[Candidate]) -> list[Candidate]:
    """If two candidates' first-occurrence ranges overlap, keep the one with
    the higher peak similarity. This dedups multi-frame variants of the
    same underlying duplication."""
    if not cands:
        return cands
    cands = sorted(cands, key=lambda c: c.start_sec)
    out: list[Candidate] = []
    for c in cands:
        if out and c.start_sec < out[-1].end_sec:
            if c.similarity_peak > out[-1].similarity_peak:
                out[-1] = c
            continue
        out.append(c)
    return out


def _transcribe_candidate(model, src_path: Path, c: Candidate,
                            pad_sec: float = 1.0) -> tuple[str, str | None]:
    """Re-extract the candidate window + padding via in-memory ffmpeg call,
    transcribe with repetition penalties DISABLED, return text + the most
    obvious repeated n-gram if any."""
    import subprocess, tempfile
    s = max(0.0, c.start_sec - pad_sec)
    e = c.second_end_sec + pad_sec
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / 'clip.wav'
        subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error',
             '-ss', f'{s:.3f}', '-to', f'{e:.3f}',
             '-i', str(src_path),
             '-ac', '1', '-ar', '16000', str(clip)],
            check=True
        )
        segments, _ = model.transcribe(
            str(clip), language='en', word_timestamps=False,
            beam_size=5, vad_filter=False,
            condition_on_previous_text=False,
            no_repeat_ngram_size=0,
        )
        text = ' '.join(seg.text.strip() for seg in segments).strip()
    # Find the most obvious repeated 2..6-gram in the text.
    repeated = None
    words = text.lower().split()
    for n in (6, 5, 4, 3, 2):
        for i in range(len(words) - 2 * n + 1):
            a = ' '.join(words[i:i+n])
            b = ' '.join(words[i+n:i+2*n])
            if a == b:
                repeated = a
                break
        if repeated:
            break
    return text, repeated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav', help='Input WAV file')
    ap.add_argument('--window-ms', type=float, default=500.0,
                    help='Comparison window length in ms (default: 500)')
    ap.add_argument('--min-lag-ms', type=float, default=400.0,
                    help='Min repetition lag to consider (default: 400)')
    ap.add_argument('--max-lag-ms', type=float, default=3000.0,
                    help='Max repetition lag to consider (default: 3000)')
    ap.add_argument('--sim-threshold', type=float, default=0.85,
                    help='Cosine similarity threshold (default: 0.85)')
    ap.add_argument('--min-duration-ms', type=float, default=250.0,
                    help='Minimum duration of a sustained match (default: 250)')
    ap.add_argument('--hop-ms', type=float, default=100.0,
                    help='Search hop in ms (default: 100)')
    ap.add_argument('--frame-ms', type=float, default=10.0,
                    help='MFCC frame hop in ms (default: 10)')
    ap.add_argument('--n-mfcc', type=int, default=13,
                    help='Number of MFCC coefficients (default: 13)')
    ap.add_argument('--sr', type=int, default=16000,
                    help='Resample rate (default: 16000)')
    ap.add_argument('--transcribe-candidates', action='store_true',
                    help='Re-transcribe each candidate with large-v3 + no_repeat_ngram_size=0')
    ap.add_argument('--whisper-model', default='large-v3',
                    help='Faster-whisper model for re-transcription (default: large-v3)')
    ap.add_argument('--device', default='auto',
                    help='cuda / cpu / auto (default: auto = try cuda then cpu)')
    ap.add_argument('--out', default=None,
                    help='Output JSON path (default: print to stdout)')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    src = Path(args.wav).resolve()
    if not src.exists():
        print(f'ERROR: not found: {src}', file=sys.stderr)
        return 1

    sr = args.sr
    hop_length = int(round(args.frame_ms / 1000.0 * sr))
    n_fft      = max(256, 2 * hop_length)
    frame_sec  = hop_length / sr
    window_frames = max(1, int(round(args.window_ms / 1000.0 / frame_sec)))
    hop_frames    = max(1, int(round(args.hop_ms / 1000.0 / frame_sec)))
    min_lag_frames = max(1, int(round(args.min_lag_ms / 1000.0 / frame_sec)))
    max_lag_frames = max(min_lag_frames + 1,
                          int(round(args.max_lag_ms / 1000.0 / frame_sec)))
    min_duration_frames = max(1, int(round(args.min_duration_ms / 1000.0 / frame_sec)))

    print(f'Loading: {src}', file=sys.stderr)
    t0 = time.time()
    y, _ = _load_audio(src, sr)
    print(f'  {len(y) / sr:.1f}s @ {sr}Hz  ({time.time()-t0:.1f}s)', file=sys.stderr)

    print('Computing MFCC features...', file=sys.stderr)
    t0 = time.time()
    mfcc = _compute_mfcc(y, sr, args.n_mfcc, hop_length, n_fft)
    print(f'  {mfcc.shape[1]} frames  ({time.time()-t0:.1f}s)', file=sys.stderr)

    print(f'Scanning for repetitions '
          f'(window={args.window_ms}ms, lag={args.min_lag_ms}..{args.max_lag_ms}ms, '
          f'sim>={args.sim_threshold}, min_dur={args.min_duration_ms}ms)...',
          file=sys.stderr)
    t0 = time.time()
    cands = _scan_for_repetitions(
        mfcc=mfcc, frame_sec=frame_sec,
        window_frames=window_frames, hop_frames=hop_frames,
        min_lag_frames=min_lag_frames, max_lag_frames=max_lag_frames,
        sim_threshold=args.sim_threshold,
        min_duration_frames=min_duration_frames,
        verbose=args.verbose,
    )
    cands = _merge_overlapping(cands)
    print(f'  {len(cands)} candidate repetitions  ({time.time()-t0:.1f}s)',
          file=sys.stderr)

    if args.transcribe_candidates and cands:
        print(f'Re-transcribing {len(cands)} candidate windows with '
              f'{args.whisper_model} (no-repeat-suppression)...', file=sys.stderr)
        from _cuda_dlls import register_nvidia_dll_dirs
        register_nvidia_dll_dirs()
        from faster_whisper import WhisperModel
        device = args.device
        if device == 'auto':
            device = 'cuda'
        compute_type = 'float16' if device == 'cuda' else 'int8'
        try:
            model = WhisperModel(args.whisper_model, device=device,
                                 compute_type=compute_type)
        except Exception as e:
            if device == 'cuda':
                print(f'  CUDA failed ({e}); using CPU', file=sys.stderr)
                model = WhisperModel(args.whisper_model, device='cpu',
                                     compute_type='int8')
            else:
                raise
        for i, c in enumerate(cands):
            try:
                text, repeated = _transcribe_candidate(model, src, c)
            except Exception as e:
                text, repeated = f'(transcribe error: {e})', None
            c.transcript = text
            c.repeated_ngram = repeated
            mark = ' ★' if repeated else '  '
            print(f'  [{i+1}/{len(cands)}]{mark} {c.start_sec:7.2f}-{c.end_sec:7.2f}'
                  f'  lag={c.lag_sec:.2f}s  sim={c.similarity_peak:.2f}  '
                  f'repeat={repeated!r}',
                  file=sys.stderr)

    out_data = [asdict(c) for c in cands]
    if args.out:
        Path(args.out).write_text(json.dumps(out_data, indent=2), encoding='utf-8')
        print(f'\nWrote: {args.out}', file=sys.stderr)
    else:
        print(json.dumps(out_data, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
