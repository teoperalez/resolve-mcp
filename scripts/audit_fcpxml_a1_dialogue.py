"""Audit A1 FCPXML sections against a fresh faster-whisper transcript.

The RBY UMB review pipeline is section-based: if auto-editor kept a cough,
throat clear, or other non-dialogue sound as an A1 section, downstream visual
assembly can make that section look like legitimate dialogue. This guard reruns
faster-whisper, then verifies every audio-only FCPXML clip has recognized
dialogue in the same source-time span.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_mcp.orchestrator.fcpxml_review import load_fcpxml_review_model


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, str]:
    manifest_path = args.manifest
    fcpxml_path = args.fcpxml
    audio_path = args.audio
    timeline_name = ""
    if manifest_path:
        manifest = read_json(manifest_path)
        timeline_name = str(manifest.get("timeline_name") or "")
        if fcpxml_path is None:
            fcpxml_value = (manifest.get("fcpxml") or {}).get("fcpxml")
            if not fcpxml_value:
                raise RuntimeError(f"Manifest lacks fcpxml.fcpxml: {manifest_path}")
            fcpxml_path = Path(fcpxml_value)
        if audio_path is None:
            audio_value = manifest.get("dialogue_audio")
            if not audio_value:
                raise RuntimeError(f"Manifest lacks dialogue_audio: {manifest_path}")
            audio_path = Path(audio_value)
    if fcpxml_path is None:
        raise RuntimeError("Provide --fcpxml or --manifest")
    if audio_path is None:
        raise RuntimeError("Provide --audio or --manifest with dialogue_audio")
    return fcpxml_path, audio_path, timeline_name


def fresh_transcript(
    audio: Path,
    out_dir: Path,
    *,
    model: str,
    device: str,
    compute_type: str,
    language: str,
    vad: bool,
) -> Path:
    cmd = [
        sys.executable,
        SCRIPT_DIR / "transcribe_audio.py",
        "--audio",
        audio,
        "--model",
        model,
        "--out",
        out_dir,
        "--device",
        device,
        "--compute-type",
        compute_type,
        "--language",
        language,
    ]
    cmd.append("--vad" if vad else "--no-vad")
    run([str(part) for part in cmd])
    transcript = out_dir / f"{audio.stem}.json"
    if not transcript.exists():
        raise FileNotFoundError(f"Expected transcript output was not written: {transcript}")
    return transcript


def normalized_word(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum() or ch == "'")


def intervals_overlap(a_start: float, a_end: float, b_start: float, b_end: float, min_overlap: float) -> bool:
    return min(a_end, b_end) - max(a_start, b_start) >= min_overlap


def transcript_index(transcript_path: Path) -> tuple[list[dict], list[dict]]:
    payload = read_json(transcript_path)
    segments = payload.get("segments") or []
    words: list[dict] = []
    for segment in segments:
        for word in segment.get("words") or []:
            token = normalized_word(str(word.get("word") or ""))
            if not token:
                continue
            try:
                start = float(word["start"])
                end = float(word["end"])
            except (KeyError, TypeError, ValueError):
                continue
            words.append(
                {
                    "word": str(word.get("word") or "").strip(),
                    "token": token,
                    "start": start,
                    "end": end,
                    "probability": word.get("probability"),
                }
            )
    words.sort(key=lambda item: (item["start"], item["end"]))
    return segments, words


def overlapping_segment_text(segments: list[dict], start: float, end: float, min_overlap: float) -> list[str]:
    texts: list[str] = []
    for segment in segments:
        try:
            seg_start = float(segment.get("start", 0.0))
            seg_end = float(segment.get("end", seg_start))
        except (TypeError, ValueError):
            continue
        if not intervals_overlap(start, end, seg_start, seg_end, min_overlap):
            continue
        text = " ".join(str(segment.get("text") or "").split())
        if text:
            texts.append(text)
    return texts


def audit(fcpxml: Path, audio: Path, transcript: Path, *, fps: float, min_word_overlap: float) -> dict:
    model = load_fcpxml_review_model(fcpxml, fps=fps, video_only=False)
    segments, words = transcript_index(transcript)
    a1_segments = [
        segment
        for segment in model.segments
        if model.assets.get(segment.ref)
        and model.assets[segment.ref].has_audio
        and not model.assets[segment.ref].has_video
    ]
    findings: list[dict] = []
    for index, segment in enumerate(a1_segments, start=1):
        start_sec = segment.source_start_frames / fps
        end_sec = segment.source_end_frames / fps
        overlapping_words = [
            word
            for word in words
            if intervals_overlap(start_sec, end_sec, float(word["start"]), float(word["end"]), min_word_overlap)
        ]
        texts = overlapping_segment_text(segments, start_sec, end_sec, min_word_overlap)
        if overlapping_words or texts:
            continue
        duration_sec = segment.duration_frames / fps
        findings.append(
            {
                "clip_index": index,
                "segment_id": segment.id,
                "name": segment.name,
                "ref": segment.ref,
                "offset_frame": segment.offset_frames,
                "offset_sec": round(segment.offset_frames / fps, 6),
                "source_start_frame": segment.source_start_frames,
                "source_end_frame": segment.source_end_frames,
                "source_start_sec": round(start_sec, 6),
                "source_end_sec": round(end_sec, 6),
                "duration_frames": segment.duration_frames,
                "duration_sec": round(duration_sec, 6),
                "dialogue_word_count": 0,
                "transcript_text_count": 0,
                "reason": "Fresh faster-whisper transcript has no recognized dialogue overlapping this A1 FCPXML section.",
                "suggested_source_cut": {
                    "start_frame": segment.source_start_frames,
                    "end_frame": segment.source_end_frames,
                    "start_sec": round(start_sec, 6),
                    "end_sec": round(end_sec, 6),
                    "confidence": "high",
                    "type": "non_dialogue_a1_section",
                    "reason": "A1 FCPXML section contains no fresh Whisper dialogue.",
                },
            }
        )
    return {
        "a1_clip_count": len(a1_segments),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--fcpxml", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--transcript-dir", type=Path)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--language", default="en")
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--min-word-overlap-sec", type=float, default=0.01)
    parser.add_argument("--no-vad", dest="vad", action="store_false", default=True)
    parser.add_argument("--fail-on-findings", dest="fail_on_findings", action="store_true", default=True)
    parser.add_argument("--no-fail-on-findings", dest="fail_on_findings", action="store_false")
    args = parser.parse_args()

    fcpxml, audio, timeline_name = resolve_inputs(args)
    if not fcpxml.exists():
        raise FileNotFoundError(fcpxml)
    if not audio.exists():
        raise FileNotFoundError(audio)

    transcript_dir = args.transcript_dir or args.out.with_suffix("").parent / "a1-dialogue-audit-transcript"
    transcript = fresh_transcript(
        audio,
        transcript_dir,
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        vad=args.vad,
    )
    result = audit(fcpxml, audio, transcript, fps=args.fps, min_word_overlap=args.min_word_overlap_sec)
    findings = result["findings"]
    report = {
        "schema": "rby_umb_a1_dialogue_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "findings" if findings else "pass",
        "manifest": str(args.manifest) if args.manifest else None,
        "fcpxml": str(fcpxml),
        "audio": str(audio),
        "transcript": str(transcript),
        "timeline_name": timeline_name,
        "fps": args.fps,
        "min_word_overlap_sec": args.min_word_overlap_sec,
        "a1_clip_count": result["a1_clip_count"],
        "finding_count": len(findings),
        "findings": findings,
        "options": [
            "Review the listed A1 sections and add their suggested_source_cut ranges to approved source cuts.",
            "If a finding is intentional, document that exception and rerun the audit with an explicit code/profile change.",
            "Regenerate the review/final FCPXML after cuts are updated, then rerun this audit.",
        ],
    }
    write_json(args.out, report)
    print(f"Wrote A1 dialogue audit: {args.out}")
    if findings:
        print(f"FOUND {len(findings)} A1 FCPXML section(s) without fresh Whisper dialogue:")
        for row in findings[:20]:
            print(
                "  - clip #{clip_index} src={source_start_sec:.3f}-{source_end_sec:.3f}s "
                "dur={duration_sec:.3f}s offset={offset_sec:.3f}s".format(**row)
            )
        if len(findings) > 20:
            print(f"  ... {len(findings) - 20} more")
        return 2 if args.fail_on_findings else 0
    print(f"PASS: all {result['a1_clip_count']} A1 FCPXML section(s) overlap fresh Whisper dialogue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
