from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FPS_DEFAULT = 60
OUT_PATH = Path("transcripts") / "session-markers-preflight.json"
RBY_SCRIPTS = Path(r"C:\Programming\RBYNewLayout\scripts")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def ffprobe(path: Path) -> dict[str, Any]:
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(p.stdout)


def media_info(path: Path) -> dict[str, Any] | None:
    try:
        data = ffprobe(path)
    except Exception:
        return None
    tags = data.get("format", {}).get("tags", {}) or {}
    creation = tags.get("creation_time")
    duration = data.get("format", {}).get("duration")
    if not creation or duration is None:
        return None
    return {
        "path": str(path),
        "creation_time": parse_dt(creation).isoformat(),
        "duration_sec": float(duration),
    }


def latest_transcript_audio() -> Path | None:
    transcripts = Path("transcripts")
    if not transcripts.exists():
        return None
    candidates = sorted(transcripts.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        if path.name in {"battles.json", "battle-types.json", "rival-starter.json", "min-battles.json"}:
            continue
        try:
            data = load_json(path)
        except Exception:
            continue
        audio = data.get("audio") or data.get("source") or data.get("path")
        if audio:
            p = Path(audio)
            if p.exists():
                return p
    return None


def source_media_candidates(source: Path | None, explicit_dir: Path | None) -> list[Path]:
    roots: list[Path] = []
    if explicit_dir is not None:
        roots.append(explicit_dir)
    if source is not None:
        roots.append(source.parent if source.is_file() else source)
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for ext in ("*.mp4", "*.mov", "*.m4v"):
            for path in root.glob(ext):
                key = str(path.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(path)
    return sorted(out, key=lambda p: p.name.lower())


def find_session_logs() -> list[Path]:
    base = Path(os.environ.get("APPDATA", "")) / "rbypc-frontend" / "logs"
    if not base.exists():
        return []
    sessions = [p for p in base.iterdir() if p.is_dir() and (p / "events.json").exists() and (p / "meta.json").exists()]
    return sorted(sessions, key=lambda p: (p / "events.json").stat().st_mtime, reverse=True)


def replay_markers(session_dir: Path) -> list[Any]:
    if str(RBY_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(RBY_SCRIPTS))
    import session_marker_labels as sml  # type: ignore

    events = json.loads((session_dir / "events.json").read_text(encoding="utf-8"))
    return sml.replay_markers(events)


def choose_session(sessions: list[Path], media: list[dict[str, Any]]) -> Path | None:
    if not sessions:
        return None
    if not media:
        return sessions[0]
    media_times = [parse_dt(m["creation_time"]) for m in media]
    best: tuple[float, Path] | None = None
    for session in sessions:
        try:
            started = parse_dt(load_json(session / "meta.json")["startedAt"])
        except Exception:
            continue
        # Pick the session whose start is closest before one of the media creation times.
        deltas = [(mt - started).total_seconds() for mt in media_times]
        positive = [d for d in deltas if d >= -60]
        if not positive:
            continue
        score = min(abs(d) for d in positive)
        if best is None or score < best[0]:
            best = (score, session)
    return best[1] if best else sessions[0]


def build_report(source_dir: Path | None) -> dict[str, Any]:
    source = latest_transcript_audio()
    media_paths = source_media_candidates(source, source_dir)
    media = [info for p in media_paths if (info := media_info(p))]
    sessions = find_session_logs()
    session = choose_session(sessions, media)

    report: dict[str, Any] = {
        "should_embed_session_markers": False,
        "reason": "",
        "source_from_transcript": str(source) if source else None,
        "media": media,
        "session_dir": str(session) if session else None,
        "markers": [],
        "markers_by_media": {},
    }
    if session is None:
        report["reason"] = "No rbypc-frontend session log with events.json/meta.json was found."
        return report
    if not media:
        report["reason"] = "Session log found, but no source MP4/MOV with creation_time was available to map markers."
        return report

    try:
        meta = load_json(session / "meta.json")
        session_start = parse_dt(meta["startedAt"])
        intended = replay_markers(session)
    except Exception as exc:
        report["reason"] = f"Session log found, but marker replay failed: {exc}"
        return report

    report["should_embed_session_markers"] = True
    report["reason"] = "RBYNewLayout session log found and marker replay succeeded; use these markers as canonical."
    report["session_started_at"] = session_start.isoformat()
    report["marker_count_replayed"] = len(intended)

    markers = []
    by_media: dict[str, list[dict[str, Any]]] = {}
    for im in intended:
        elapsed = im.t_elapsed_ms / 1000.0
        rec = {
            "label": im.label,
            "note": im.note,
            "color": im.color,
            "category": im.category,
            "name": im.name,
            "session_elapsed_sec": elapsed,
        }
        markers.append(rec)
        for m in media:
            media_start = parse_dt(m["creation_time"])
            media_elapsed = (media_start - session_start).total_seconds()
            source_sec = elapsed - media_elapsed
            if 0 <= source_sec <= float(m["duration_sec"]):
                item = dict(rec)
                item.update({
                    "media_path": m["path"],
                    "source_sec": source_sec,
                    "source_frame_60fps": int(round(source_sec * FPS_DEFAULT)),
                    "media_start_elapsed_sec": media_elapsed,
                })
                by_media.setdefault(m["path"], []).append(item)

    report["markers"] = markers
    report["markers_by_media"] = by_media
    report["mapped_marker_count"] = sum(len(v) for v in by_media.values())
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Preflight RBYNewLayout session-log markers for orchestrator workflows.")
    ap.add_argument("--source-dir", help="Optional source media directory to scan for MP4/MOV creation_time.")
    ap.add_argument("--out", default=str(OUT_PATH), help=f"Output JSON report path (default: {OUT_PATH}).")
    args = ap.parse_args()

    source_dir = Path(args.source_dir) if args.source_dir else None
    report = build_report(source_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "should_embed_session_markers": report["should_embed_session_markers"],
        "reason": report["reason"],
        "session_dir": report.get("session_dir"),
        "media_count": len(report.get("media", [])),
        "marker_count_replayed": report.get("marker_count_replayed", 0),
        "mapped_marker_count": report.get("mapped_marker_count", 0),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
