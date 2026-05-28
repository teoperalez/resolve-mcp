from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np


DEFAULT_MODEL = "tiny"
DEFAULT_SR = 16000


def ffmpeg_cmd() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    return ff


def uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    raw = unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw):
        raw = raw[1:]
    return Path(raw)


def media_duration_sec(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(proc.stdout.strip())


def extract_probe_wav(path: Path, duration_sec: float, sr: int) -> Path:
    out = Path(tempfile.mkdtemp(prefix="dialogue_probe_")) / "probe.wav"
    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-t",
        f"{duration_sec:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {path}:\n{proc.stderr[-1200:]}")
    return out


def load_wav_float(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def rms_db(audio: np.ndarray, sr: int, frame_ms: float = 100.0, hop_ms: float = 50.0) -> np.ndarray:
    if audio.size == 0:
        return np.zeros(0, dtype=np.float32)
    frame = max(1, int(sr * frame_ms / 1000.0))
    hop = max(1, int(sr * hop_ms / 1000.0))
    if audio.size < frame:
        audio = np.pad(audio, (0, frame - audio.size))
    n = 1 + (len(audio) - frame) // hop
    vals = np.empty(max(0, n), dtype=np.float32)
    for i in range(len(vals)):
        chunk = audio[i * hop:i * hop + frame]
        vals[i] = float(np.sqrt(np.mean(chunk * chunk)))
    return 20.0 * np.log10(np.maximum(vals, 1e-6))


def register_nvidia_dlls() -> None:
    if os.name != "nt":
        return
    for base in sys.path:
        if "site-packages" not in base:
            continue
        for bin_dir in Path(base).glob("nvidia/*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def load_whisper(model_name: str, device: str, compute_type: str):
    register_nvidia_dlls()
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type), device, compute_type
    except Exception:
        return WhisperModel(model_name, device="cpu", compute_type="int8"), "cpu", "int8"


def transcribe_probe(model, wav_path: Path, language: str) -> dict:
    segments_iter, info = model.transcribe(
        str(wav_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
    )
    words = []
    speech_ranges = []
    text_parts = []
    for seg in segments_iter:
        text_parts.append(seg.text)
        speech_ranges.append((float(seg.start), float(seg.end)))
        for w in seg.words or []:
            words.append({
                "word": w.word,
                "start": float(w.start),
                "end": float(w.end),
                "probability": float(w.probability),
            })
    probs = [w["probability"] for w in words]
    speech_sec = sum(max(0.0, e - s) for s, e in speech_ranges)
    return {
        "language": getattr(info, "language", language),
        "word_count": len(words),
        "avg_word_probability": float(np.mean(probs)) if probs else 0.0,
        "min_word_probability": float(np.min(probs)) if probs else 0.0,
        "speech_seconds": speech_sec,
        "text_preview": "".join(text_parts).strip()[:240],
    }


def discover_tracks(tracks_dir: Path | None, video: Path | None) -> list[Path]:
    if tracks_dir is None:
        if video is None:
            raise ValueError("Provide --tracks-dir or --video")
        tracks_dir = video.parent / f"{video.stem}_tracks"
    if not tracks_dir.is_dir():
        raise FileNotFoundError(f"tracks directory not found: {tracks_dir}")
    return sorted(
        [p for p in tracks_dir.iterdir() if p.is_file() and p.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac"}],
        key=lambda p: p.name.lower(),
    )


def fcpxml_primary_audio_path(fcpxml: Path) -> Path | None:
    if not fcpxml or not fcpxml.exists():
        return None
    root = ET.parse(fcpxml).getroot()
    assets = {a.get("id"): a for a in root.findall(".//asset")}
    for ac in root.findall(".//spine/asset-clip"):
        ref = ac.get("ref")
        asset = assets.get(ref)
        if asset is None or asset.get("hasVideo") == "1" or asset.get("hasAudio") != "1":
            continue
        rep = asset.find("media-rep")
        path = uri_to_path(rep.get("src", "")) if rep is not None else None
        if path is not None:
            return path
    return None


def score_candidate(path: Path, probe_duration: float, sr: int, model, language: str) -> dict:
    dur = min(media_duration_sec(path), probe_duration)
    probe = extract_probe_wav(path, dur, sr)
    audio = load_wav_float(probe)
    db = rms_db(audio, sr)
    p10 = float(np.percentile(db, 10)) if db.size else -120.0
    p50 = float(np.percentile(db, 50)) if db.size else -120.0
    p90 = float(np.percentile(db, 90)) if db.size else -120.0
    p95 = float(np.percentile(db, 95)) if db.size else -120.0
    active_threshold = max(-45.0, p10 + 12.0)
    active_ratio = float(np.mean(db >= active_threshold)) if db.size else 0.0
    quiet_ratio = float(np.mean(db < -50.0)) if db.size else 1.0
    dynamic_range = p95 - p10

    speech = transcribe_probe(model, probe, language)
    speech_ratio = speech["speech_seconds"] / dur if dur else 0.0

    # Dialogue track shape: lots of quiet bed, speech recognized with high
    # confidence, and strong contrast between quiet and spoken frames.
    silence_score = min(1.0, max(0.0, (quiet_ratio - 0.25) / 0.55))
    speech_score = min(1.0, speech["avg_word_probability"] * min(1.0, speech["word_count"] / 35.0))
    contrast_score = min(1.0, max(0.0, (dynamic_range - 10.0) / 22.0))
    bgm_penalty = 0.0
    if p50 > -42.0:
        bgm_penalty += min(0.35, (p50 + 42.0) / 24.0)
    if active_ratio > 0.75:
        bgm_penalty += min(0.35, (active_ratio - 0.75) / 0.25)
    score = max(0.0, 0.42 * speech_score + 0.34 * silence_score + 0.24 * contrast_score - bgm_penalty)

    return {
        "path": str(path),
        "probe_duration_sec": dur,
        "rms_db_p10": round(p10, 2),
        "rms_db_p50": round(p50, 2),
        "rms_db_p90": round(p90, 2),
        "rms_db_p95": round(p95, 2),
        "active_threshold_db": round(active_threshold, 2),
        "active_ratio": round(active_ratio, 4),
        "quiet_ratio_below_-50db": round(quiet_ratio, 4),
        "dynamic_range_db": round(dynamic_range, 2),
        "speech_ratio": round(speech_ratio, 4),
        **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in speech.items()},
        "dialogue_score": round(score, 4),
    }


def choose_candidate(scores: list[dict], fcpxml_primary: Path | None, trust_fcpxml: bool) -> tuple[dict | None, str, list[str]]:
    warnings = []
    by_path = {str(Path(s["path"]).resolve()).lower(): s for s in scores}
    if fcpxml_primary is not None and trust_fcpxml:
        key = str(fcpxml_primary.resolve()).lower()
        chosen = by_path.get(key)
        if chosen is not None:
            return chosen, "trusted_fcpxml_primary_for_5_track_layout", warnings
        warnings.append(f"FCPXML primary audio is not among candidates: {fcpxml_primary}")

    if not scores:
        return None, "no_candidates", warnings
    ranked = sorted(scores, key=lambda s: float(s["dialogue_score"]), reverse=True)
    chosen = ranked[0]
    if len(ranked) > 1 and float(chosen["dialogue_score"]) - float(ranked[1]["dialogue_score"]) < 0.08:
        warnings.append("Top two dialogue scores are close; inspect manually before destructive edits.")
    if chosen["avg_word_probability"] < 0.45 or chosen["word_count"] < 8:
        warnings.append("Chosen track has weak speech evidence.")
    if chosen["quiet_ratio_below_-50db"] < 0.25:
        warnings.append("Chosen track is not mostly quiet; it may contain BGM mixed with speech.")
    return chosen, "detected_by_speech_silence_score", warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect the likely dialogue WAV among auto-editor extracted audio tracks.")
    ap.add_argument("--video", type=Path, help="Source video; implies <stem>_tracks and <stem>_ALTERED.fcpxml.")
    ap.add_argument("--tracks-dir", type=Path, help="Explicit auto-editor tracks directory.")
    ap.add_argument("--fcpxml", type=Path, help="Optional FCPXML to identify the primary A1-style audio ref.")
    ap.add_argument("--out", type=Path, help="Write JSON report here.")
    ap.add_argument("--probe-duration", type=float, default=600.0)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--language", default="en")
    ap.add_argument("--force-detect", action="store_true", help="Score and choose even in 5-track layouts.")
    ap.add_argument("--fail-weak", action="store_true", help="Exit nonzero when speech evidence is weak or ambiguous.")
    args = ap.parse_args()

    tracks = discover_tracks(args.tracks_dir, args.video)
    fcpxml = args.fcpxml
    if fcpxml is None and args.video is not None:
        candidate = args.video.parent / f"{args.video.stem}_ALTERED.fcpxml"
        fcpxml = candidate if candidate.exists() else None
    fcpxml_primary = fcpxml_primary_audio_path(fcpxml) if fcpxml else None
    trust_fcpxml = (len(tracks) >= 5 and not args.force_detect)

    model, used_device, used_compute = load_whisper(args.model, args.device, args.compute_type)
    scores = [score_candidate(p, args.probe_duration, DEFAULT_SR, model, args.language) for p in tracks]
    chosen, reason, warnings = choose_candidate(scores, fcpxml_primary, trust_fcpxml)

    report = {
        "tracks_dir": str((args.tracks_dir or (args.video.parent / f"{args.video.stem}_tracks")).resolve()) if (args.tracks_dir or args.video) else None,
        "track_count": len(tracks),
        "mode": "trust_fcpxml_primary_for_5_track_layout" if trust_fcpxml else "detect_dialogue_track",
        "fcpxml": str(fcpxml) if fcpxml else None,
        "fcpxml_primary_audio": str(fcpxml_primary) if fcpxml_primary else None,
        "whisper_model": args.model,
        "whisper_device": used_device,
        "whisper_compute_type": used_compute,
        "chosen_path": chosen["path"] if chosen else None,
        "chosen_reason": reason,
        "warnings": warnings,
        "candidates": sorted(scores, key=lambda s: float(s["dialogue_score"]), reverse=True),
    }

    print(json.dumps({
        "chosen_path": report["chosen_path"],
        "chosen_reason": reason,
        "track_count": len(tracks),
        "warnings": warnings,
    }, indent=2))
    for c in report["candidates"]:
        print(
            f'  {Path(c["path"]).name}: score={c["dialogue_score"]:.4f} '
            f'words={c["word_count"]} prob={c["avg_word_probability"]:.3f} '
            f'quiet={c["quiet_ratio_below_-50db"]:.3f} p50={c["rms_db_p50"]:.1f}dB'
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.out}")

    if args.fail_weak and (warnings or not chosen):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
