"""
Local audio transcription using faster-whisper (CPU/GPU, cross-platform).

Long files are split into chunks with ffmpeg so each transcription call
completes well within any MCP timeout.
"""

import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional, List, Dict, Any

logger = logging.getLogger("ResolveMCP")

# ── Models ──────────────────────────────────────────────────────────

WHISPER_MODELS = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large": "large-v3",
    "turbo": "large-v3-turbo",
}

DEFAULT_MODEL = "turbo"

CHUNK_SECONDS = 300  # 5 minutes per chunk


def _get_model_name(model: str) -> str:
    if model in WHISPER_MODELS.values():
        return model
    name = WHISPER_MODELS.get(model)
    if name is None:
        raise ValueError(
            f"Unknown model '{model}'. Choose from: {', '.join(WHISPER_MODELS.keys())} "
            f"or pass a valid faster-whisper model name directly."
        )
    return name


def _register_nvidia_dlls() -> None:
    """Add bundled NVIDIA pip-package DLL dirs to the Windows DLL search path."""
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


# ── ffmpeg helpers ──────────────────────────────────────────────────

def _get_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)


def _extract_chunk(src: str, start: float, duration: float, dst: str):
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", src,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        dst,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def _split_audio(path: str, chunk_sec: int, tmp_dir: str) -> List[Dict[str, Any]]:
    total = _get_duration(path)
    chunks = []
    offset = 0.0
    idx = 0
    while offset < total:
        chunk_path = os.path.join(tmp_dir, f"chunk_{idx:04d}.wav")
        _extract_chunk(path, offset, chunk_sec, chunk_path)
        chunks.append({"path": chunk_path, "offset": offset})
        offset += chunk_sec
        idx += 1
    return chunks


# ── Core transcription ─────────────────────────────────────────────

def _load_model(model_name: str):
    """Load faster-whisper model with GPU preference, CPU fallback."""
    _register_nvidia_dlls()
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        raise ImportError(
            "faster-whisper is not installed. Install with: "
            "pip install faster-whisper"
        )
    logger.info("Loading faster-whisper model: %s (GPU)…", model_name)
    try:
        return WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception as e:
        logger.warning("GPU init failed (%s), falling back to CPU int8", e)
        return WhisperModel(model_name, device="cpu", compute_type="int8")


def _transcribe_path(model, audio_path: str, language: Optional[str], word_timestamps: bool,
                     initial_prompt: Optional[str]) -> Dict[str, Any]:
    """Run faster-whisper on a single file and return mlx-whisper-compatible dict."""
    kwargs: Dict[str, Any] = {
        "beam_size": 5,
        "word_timestamps": word_timestamps,
        "vad_filter": False,
    }
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    segments_iter, info = model.transcribe(audio_path, **kwargs)
    segments = []
    text_parts = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        segments.append({"start": round(float(seg.start), 2),
                         "end": round(float(seg.end), 2),
                         "text": text})
        text_parts.append(text)

    return {
        "language": info.language,
        "text": " ".join(text_parts),
        "segments": segments,
    }


def transcribe(
    audio_path: str,
    model: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    word_timestamps: bool = False,
    initial_prompt: Optional[str] = None,
    chunk_seconds: int = CHUNK_SECONDS,
) -> Dict[str, Any]:
    """
    Transcribe an audio/video file using faster-whisper.

    Files longer than *chunk_seconds* are automatically split with ffmpeg.
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model_name = _get_model_name(model)
    whisper_model = _load_model(model_name)
    duration = _get_duration(audio_path)

    if duration <= chunk_seconds:
        logger.info("Transcribing '%s' (%.0fs) with %s", audio_path, duration, model_name)
        return _transcribe_path(whisper_model, audio_path, language, word_timestamps, initial_prompt)

    logger.info("Splitting '%s' (%.0fs) into %d-second chunks", audio_path, duration, chunk_seconds)
    tmp_dir = tempfile.mkdtemp(prefix="resolve_whisper_")
    try:
        chunks = _split_audio(audio_path, chunk_seconds, tmp_dir)
        logger.info("Created %d chunks", len(chunks))

        all_segments: List[Dict[str, Any]] = []
        all_text_parts: List[str] = []
        detected_language = None
        prompt = initial_prompt

        for i, chunk in enumerate(chunks):
            logger.info("Transcribing chunk %d/%d (offset %.0fs)…", i + 1, len(chunks), chunk["offset"])
            result = _transcribe_path(whisper_model, chunk["path"], language, word_timestamps, prompt)

            if detected_language is None:
                detected_language = result.get("language")

            offset = chunk["offset"]
            for seg in result.get("segments", []):
                all_segments.append({
                    "start": seg["start"] + offset,
                    "end": seg["end"] + offset,
                    "text": seg["text"],
                })

            text = result.get("text", "")
            if text:
                all_text_parts.append(text.strip())
                prompt = text.strip()[-200:]

        return {
            "language": detected_language or "unknown",
            "text": " ".join(all_text_parts),
            "segments": all_segments,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── SRT helpers ────────────────────────────────────────────────────

def segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _seconds_to_srt_time(seg["start"])
        end = _seconds_to_srt_time(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _seconds_to_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
