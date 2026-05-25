"""
Shared audio-analysis utilities for the resolve-mcp QA pipeline.

Used by:
- repair_*.py scripts (Phase A)
- verify_pipeline.py (Phase D)
- mark_cut_candidates / apply_cuts_to_fcpxml / place_battle_* (Phase C patches)

All public functions accept either a pre-loaded numpy array (preferred for
repeated calls on overlapping windows) or a source-video path + window range
(triggers ffmpeg extraction with on-disk caching).

Caching: extracted PCM windows live at
  ~/.resolve-mcp/cache/audio-windows/<sha1(path|start|dur|sr)>.npy
so repeated calls during a single verify/repair pass are ~free after the first
extraction. Cache is durable across sessions.

Requires: librosa (pip), numpy, ffmpeg on PATH.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

# ── ffmpeg discovery ──────────────────────────────────────────────────────────

def _ffmpeg_cmd() -> str:
    ff = shutil.which('ffmpeg')
    if ff:
        return ff
    raise RuntimeError(
        'ffmpeg not found on PATH. Install: winget install Gyan.FFmpeg, '
        'then restart your terminal.'
    )


# ── cache management ──────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / '.resolve-mcp' / 'cache' / 'audio-windows'

def _cache_key(source_path: str, start_sec: float, dur_sec: float, sr: int) -> Path:
    h = hashlib.sha1(
        f'{source_path}|{start_sec:.5f}|{dur_sec:.5f}|{sr}'.encode('utf-8')
    ).hexdigest()
    return CACHE_DIR / f'{h}.npy'


def clear_cache() -> int:
    """Wipe the cache. Returns count of removed files."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for f in CACHE_DIR.glob('*.npy'):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


# ── whole-track extraction (fast batch probe via in-memory slicing) ───────────

_FULL_TRACK_CACHE: dict[tuple[str, int], np.ndarray] = {}

def load_full_audio_track(
    source_path: str | os.PathLike,
    sr: int = 48000,
    mono: bool = True,
    use_cache: bool = True,
) -> np.ndarray:
    """Load the ENTIRE audio track of a source video into memory.

    For a typical 30-50min gameplay MP4 at 48kHz mono float32 this is ~270MB;
    well worth the RAM trade for the ~1000x speedup vs per-probe ffmpeg seeks.

    Two cache layers:
    - in-process dict for repeat calls within a single Python run
    - on-disk .npy at ~/.resolve-mcp/cache/audio-windows/full_<sha1>.npy
    """
    source_path = str(source_path)
    key = (source_path, sr)
    if key in _FULL_TRACK_CACHE:
        return _FULL_TRACK_CACHE[key]

    h = hashlib.sha1(f'FULL|{source_path}|{sr}'.encode('utf-8')).hexdigest()
    disk_cache = CACHE_DIR / f'full_{h}.npy'
    if use_cache and disk_cache.exists():
        try:
            arr = np.load(disk_cache)
            _FULL_TRACK_CACHE[key] = arr
            return arr
        except Exception:
            pass

    ff = _ffmpeg_cmd()
    with tempfile.TemporaryDirectory(prefix='_audio_tools_full_') as tmpdir:
        wav_path = Path(tmpdir) / 'full.wav'
        cmd = [
            ff, '-y', '-loglevel', 'error',
            '-i', source_path,
            '-vn',
            '-c:a', 'pcm_s16le',
            '-ar', str(sr),
            '-ac', '1' if mono else '2',
            str(wav_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f'ffmpeg full-track extract failed:\n'
                f'  cmd: {" ".join(cmd)}\n'
                f'  stderr: {res.stderr[-1500:]}'
            )
        import wave
        with wave.open(str(wav_path), 'rb') as w:
            n = w.getnframes()
            raw = w.readframes(n)
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    _FULL_TRACK_CACHE[key] = arr
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            np.save(disk_cache, arr)
        except OSError:
            pass
    return arr


def slice_window(full: np.ndarray, sr: int, start_sec: float, dur_sec: float) -> np.ndarray:
    """Slice [start_sec, start_sec+dur_sec) from a preloaded mono track."""
    if full.size == 0 or dur_sec <= 0:
        return np.zeros(0, dtype=np.float32)
    s = max(0, int(round(start_sec * sr)))
    e = min(len(full), s + max(1, int(round(dur_sec * sr))))
    if s >= e:
        return np.zeros(0, dtype=np.float32)
    return full[s:e]


# ── per-window extraction (one-off probes) ────────────────────────────────────

def extract_audio_window(
    source_path: str | os.PathLike,
    start_sec: float,
    dur_sec: float,
    sr: int = 48000,
    mono: bool = True,
    use_cache: bool = True,
) -> np.ndarray:
    """Extract a PCM audio window from a media file via ffmpeg.

    Returns a 1-D float32 ndarray in range [-1, 1] (mono) or 2-D (sr, channels)
    if mono=False. Cached on disk by content hash unless use_cache=False.
    """
    source_path = str(source_path)
    if dur_sec <= 0:
        return np.zeros(0, dtype=np.float32)

    cache_path = _cache_key(source_path, start_sec, dur_sec, sr) if use_cache else None
    if cache_path and cache_path.exists():
        try:
            return np.load(cache_path)
        except Exception:
            pass  # cache corrupt, re-extract

    ff = _ffmpeg_cmd()
    with tempfile.TemporaryDirectory(prefix='_audio_tools_') as tmpdir:
        wav_path = Path(tmpdir) / 'window.wav'
        cmd = [
            ff, '-y', '-loglevel', 'error',
            '-ss', f'{start_sec:.5f}',
            '-t',  f'{dur_sec:.5f}',
            '-i', source_path,
            '-vn',
            '-c:a', 'pcm_s16le',
            '-ar', str(sr),
            '-ac', '1' if mono else '2',
            str(wav_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f'ffmpeg extract failed (rc={res.returncode}):\n'
                f'  cmd: {" ".join(cmd)}\n'
                f'  stderr: {res.stderr[-1500:]}'
            )

        # Read WAV → np
        import wave
        with wave.open(str(wav_path), 'rb') as w:
            n = w.getnframes()
            raw = w.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if not mono and w.getnchannels() == 2:
            samples = samples.reshape(-1, 2)

    if cache_path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            np.save(cache_path, samples)
        except OSError:
            pass

    return samples


# ── RMS / silence detection ───────────────────────────────────────────────────

def compute_rms_envelope(
    audio: np.ndarray,
    sr: int,
    hop_ms: float = 10.0,
    frame_ms: float = 25.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute RMS envelope. Returns (times_sec, rms_linear)."""
    import librosa
    hop  = max(1, int(sr * hop_ms / 1000.0))
    fram = max(hop * 2, int(sr * frame_ms / 1000.0))
    rms  = librosa.feature.rms(y=audio, frame_length=fram, hop_length=hop)[0]
    times = np.arange(len(rms)) * hop / sr
    return times, rms


def _db(linear: np.ndarray, ref: float = 1.0) -> np.ndarray:
    """Convert linear amplitude to dBFS. Floors very-small values at -120 dB."""
    return 20.0 * np.log10(np.maximum(linear / ref, 1e-6))


def find_silence_in_window(
    audio: np.ndarray,
    sr: int,
    threshold_db: float = -40.0,
    min_silence_ms: float = 80.0,
    hop_ms: float = 10.0,
) -> list[tuple[float, float]]:
    """Find silence stretches in an audio window.

    Returns list of (start_sec, end_sec) tuples where RMS stayed below
    threshold_db for at least min_silence_ms.
    """
    if audio.size == 0:
        return []
    times, rms = compute_rms_envelope(audio, sr, hop_ms=hop_ms)
    db = _db(rms)
    is_silent = db < threshold_db

    out: list[tuple[float, float]] = []
    min_frames = max(1, int(min_silence_ms / hop_ms))
    i = 0
    n = len(is_silent)
    while i < n:
        if is_silent[i]:
            j = i
            while j < n and is_silent[j]:
                j += 1
            if (j - i) >= min_frames:
                out.append((float(times[i]), float(times[min(j, n - 1)])))
            i = j
        else:
            i += 1
    return out


def snap_to_nearest_silence(
    audio: np.ndarray,
    sr: int,
    target_sec: float,
    max_drift_sec: float = 0.5,
    threshold_db: float = -40.0,
    min_silence_ms: float = 80.0,
) -> Optional[tuple[float, float]]:
    """Snap target_sec to the center of the nearest silence stretch.

    Returns (snapped_sec, drift_sec) or None if no qualifying silence is
    within max_drift_sec.
    """
    silences = find_silence_in_window(
        audio, sr, threshold_db=threshold_db, min_silence_ms=min_silence_ms
    )
    if not silences:
        return None

    best: Optional[tuple[float, float]] = None
    best_drift = float('inf')
    for s, e in silences:
        # Anywhere inside the silence is fine — pick the closest edge to target
        if s <= target_sec <= e:
            return (target_sec, 0.0)
        candidate = s if abs(target_sec - s) < abs(target_sec - e) else e
        drift = abs(target_sec - candidate)
        if drift < best_drift:
            best = (candidate, candidate - target_sec)
            best_drift = drift

    if best is None or best_drift > max_drift_sec:
        return None
    return best


def is_speech_active(
    audio: np.ndarray,
    sr: int,
    threshold_db: float = -30.0,
    window_ms: float = 100.0,
) -> bool:
    """True if the centred window contains active (non-silent) audio."""
    if audio.size == 0:
        return False
    _, rms = compute_rms_envelope(audio, sr, hop_ms=10.0, frame_ms=window_ms)
    if rms.size == 0:
        return False
    peak_db = float(_db(rms).max())
    return peak_db >= threshold_db


# ── transient detection (for battle music kick-in sync) ───────────────────────

def detect_loud_transient(
    audio: np.ndarray,
    sr: int,
    baseline_db: Optional[float] = None,
    threshold_db: float = 6.0,
    min_duration_ms: float = 200.0,
    hop_ms: float = 10.0,
) -> Optional[float]:
    """Find the time (sec) of the first sustained loud transient.

    Looks for a region where RMS exceeds baseline_db + threshold_db for at
    least min_duration_ms. If baseline_db is None, the 25th percentile of the
    window's dB envelope is used as baseline.
    """
    if audio.size == 0:
        return None
    times, rms = compute_rms_envelope(audio, sr, hop_ms=hop_ms)
    db = _db(rms)
    if baseline_db is None:
        baseline_db = float(np.percentile(db, 25))
    target = baseline_db + threshold_db
    is_loud = db >= target

    min_frames = max(1, int(min_duration_ms / hop_ms))
    run = 0
    for i, v in enumerate(is_loud):
        run = run + 1 if v else 0
        if run >= min_frames:
            return float(times[i - min_frames + 1])
    return None


# ── MFCC similarity (for repetition detection) ────────────────────────────────

def mfcc_similarity(
    audio_a: np.ndarray,
    audio_b: np.ndarray,
    sr: int,
    n_mfcc: int = 13,
) -> float:
    """Cosine similarity between two audio windows' mean MFCC vectors.

    Returns a float in [-1, 1]; values >0.85 typically indicate same speech.
    Mirrors the approach in scripts/find_audio_repetitions.py.
    """
    import librosa
    if audio_a.size == 0 or audio_b.size == 0:
        return 0.0
    mfcc_a = librosa.feature.mfcc(y=audio_a, sr=sr, n_mfcc=n_mfcc)
    mfcc_b = librosa.feature.mfcc(y=audio_b, sr=sr, n_mfcc=n_mfcc)
    va = mfcc_a.mean(axis=1)
    vb = mfcc_b.mean(axis=1)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='_audio_tools smoke test')
    ap.add_argument('source', help='Source media file')
    ap.add_argument('--start', type=float, default=10.0)
    ap.add_argument('--dur',   type=float, default=5.0)
    args = ap.parse_args()

    audio = extract_audio_window(args.source, args.start, args.dur)
    print(f'Extracted {len(audio)} samples ({len(audio)/48000:.2f}s @ 48000Hz)')
    silences = find_silence_in_window(audio, 48000)
    print(f'Silence stretches: {len(silences)}')
    for s, e in silences:
        print(f'  {args.start + s:.3f} → {args.start + e:.3f}  ({e-s:.3f}s)')
    print(f'is_speech_active: {is_speech_active(audio, 48000)}')
    transient = detect_loud_transient(audio, 48000)
    if transient is not None:
        print(f'First loud transient: {args.start + transient:.3f}s')
