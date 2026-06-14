from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v"}


@dataclass(frozen=True)
class MediaCandidate:
    path: str
    stem: str
    duration_sec: float | None = None
    creation_time: str | None = None
    size_bytes: int = 0


@dataclass(frozen=True)
class SessionMatch:
    session_dir: str
    events_path: str
    meta_path: str
    subject: str
    challenge_label: str
    started_at: str
    score: float
    matched_by: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectDiscovery:
    schema: str
    project_dir: str
    codex_dir: str
    project_name: str
    profile_id_base: str
    needs_manual: bool
    reason: str
    workflow_id: str
    game_version: str
    challenge_type: str
    source_media: str
    media: list[MediaCandidate]
    session: SessionMatch | None
    parameters: dict[str, Any]
    paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_project(project_dir: Path) -> ProjectDiscovery:
    project_dir = project_dir.resolve()
    media = find_media_candidates(project_dir)
    session = choose_session_match(project_dir, media)
    source = choose_source_media(media)

    if session:
        challenge_type = challenge_type_from_label(session.challenge_label)
        workflow_id = workflow_for_challenge(challenge_type)
        game_version = "pokemon_red_blue"
        reason = f"Matched RBY session log: {session.session_dir}"
        needs_manual = False
    else:
        challenge_type = ""
        workflow_id = "gen1_rby_umb_review_first"
        game_version = ""
        reason = "No matching rbypc-frontend session log was found for this project folder."
        needs_manual = True

    source_media = source.path if source else ""
    parameters: dict[str, Any] = {
        "source_name": Path(source_media).stem if source_media else project_dir.name,
        "source_media": source_media,
    }
    paths: dict[str, str] = {}

    if session:
        parameters.update(
            {
                "session_dir": session.session_dir,
                "session_events": session.events_path,
                "session_meta": session.meta_path,
                "session_started_at": session.started_at,
                "log_subject": session.subject,
                "log_challenge": session.challenge_label,
                "log_match_score": round(session.score, 3),
            }
        )
        paths["session_dir"] = "{session_dir}"
        paths["session_events"] = "{session_events}"
        paths["session_meta"] = "{session_meta}"
    if source:
        parameters.update(
            {
                "source_duration_sec": source.duration_sec if source.duration_sec is not None else "",
                "source_creation_time": source.creation_time or "",
            }
        )

    return ProjectDiscovery(
        schema="resolve_orchestrator_project_discovery_v1",
        project_dir=str(project_dir).replace("\\", "/"),
        codex_dir=str(project_dir / "CODEx").replace("\\", "/"),
        project_name=project_dir.name,
        profile_id_base=slugify(project_dir.name),
        needs_manual=needs_manual,
        reason=reason,
        workflow_id=workflow_id,
        game_version=game_version,
        challenge_type=challenge_type,
        source_media=source_media,
        media=media,
        session=session,
        parameters=parameters,
        paths=paths,
    )


def find_media_candidates(project_dir: Path) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    if not project_dir.exists():
        return candidates
    for path in sorted(project_dir.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        if should_skip_media_path(project_dir, path):
            continue
        info = read_media_info(path)
        candidates.append(
            MediaCandidate(
                path=str(path.resolve()).replace("\\", "/"),
                stem=path.stem,
                duration_sec=info.get("duration_sec"),
                creation_time=info.get("creation_time"),
                size_bytes=path.stat().st_size,
            )
        )
    return candidates


def should_skip_media_path(project_dir: Path, path: Path) -> bool:
    try:
        parts = {part.lower() for part in path.relative_to(project_dir).parts}
    except ValueError:
        return False
    return bool(parts & {"codex", ".git", "__pycache__", "cache", "review", "cut_review"})


def read_media_info(path: Path) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        data = json.loads(process.stdout)
    except Exception:
        return {}
    fmt = data.get("format") or {}
    tags = fmt.get("tags") or {}
    duration = fmt.get("duration")
    return {
        "duration_sec": float(duration) if duration not in (None, "") else None,
        "creation_time": normalize_dt(tags.get("creation_time")) if tags.get("creation_time") else None,
    }


def find_session_logs() -> list[Path]:
    base = Path(os.environ.get("APPDATA", "")) / "rbypc-frontend" / "logs"
    if not base.exists():
        return []
    sessions = [
        path
        for path in base.iterdir()
        if path.is_dir() and (path / "events.json").exists() and (path / "meta.json").exists()
    ]
    return sorted(sessions, key=lambda path: (path / "events.json").stat().st_mtime, reverse=True)


def choose_session_match(project_dir: Path, media: list[MediaCandidate]) -> SessionMatch | None:
    project_terms = terms_for_project(project_dir, media)
    scored: list[SessionMatch] = []
    for session_dir in find_session_logs():
        parsed = parse_session_folder(session_dir)
        if not parsed:
            continue
        subject, challenge_label = parsed
        try:
            meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8-sig"))
            started_at = normalize_dt(meta["startedAt"])
        except Exception:
            continue
        score, matched_by = score_session(subject, challenge_label, started_at, project_terms, media)
        if score <= 0:
            continue
        scored.append(
            SessionMatch(
                session_dir=str(session_dir.resolve()).replace("\\", "/"),
                events_path=str((session_dir / "events.json").resolve()).replace("\\", "/"),
                meta_path=str((session_dir / "meta.json").resolve()).replace("\\", "/"),
                subject=subject,
                challenge_label=challenge_label,
                started_at=started_at,
                score=score,
                matched_by=matched_by,
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[0]


def parse_session_folder(session_dir: Path) -> tuple[str, str] | None:
    parts = session_dir.name.split("__")
    if len(parts) < 3:
        return None
    subject = parts[1].replace("_", " ").strip()
    challenge = parts[2].replace("_", " ").strip()
    return subject, challenge


def score_session(
    subject: str,
    challenge_label: str,
    started_at: str,
    project_terms: set[str],
    media: list[MediaCandidate],
) -> tuple[float, list[str]]:
    score = 0.0
    matched_by: list[str] = []
    subject_terms = tokenize(subject)
    challenge_terms = tokenize(challenge_label)
    subject_hits = subject_terms & project_terms
    if subject_hits:
        score += 70 + (10 * len(subject_hits))
        matched_by.append(f"folder/media name matched log subject: {', '.join(sorted(subject_hits))}")
    challenge_hits = challenge_terms & project_terms
    if challenge_hits:
        score += 10 + (3 * len(challenge_hits))
        matched_by.append(f"folder/media name matched challenge: {', '.join(sorted(challenge_hits))}")

    started = parse_dt(started_at)
    best_time_score = 0.0
    for item in media:
        if not item.creation_time:
            continue
        media_start = parse_dt(item.creation_time)
        delta_sec = (media_start - started).total_seconds()
        duration_sec = item.duration_sec or 0
        upper_bound = max(duration_sec + 3600, 3600)
        if -60 <= delta_sec <= upper_bound:
            closeness = max(0.0, 50.0 - (max(delta_sec, 0.0) / 3600.0))
            best_time_score = max(best_time_score, 120.0 + closeness)
    if best_time_score:
        score += best_time_score
        matched_by.append("media creation_time aligns with session startedAt")

    if best_time_score or subject_hits:
        return score, matched_by
    return 0.0, []


def choose_source_media(media: list[MediaCandidate]) -> MediaCandidate | None:
    if not media:
        return None
    return sorted(
        media,
        key=lambda item: (
            item.duration_sec if item.duration_sec is not None else 0,
            item.size_bytes,
        ),
        reverse=True,
    )[0]


def terms_for_project(project_dir: Path, media: list[MediaCandidate]) -> set[str]:
    text = " ".join([project_dir.name] + [item.stem for item in media])
    return tokenize(text)


def tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1}


def challenge_type_from_label(label: str) -> str:
    normalized = "_".join(sorted(tokenize(label)))
    raw = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if "ultra" in normalized and "minimum" in normalized:
        return "ultra_minimum_battles"
    if "minimum" in normalized:
        return "minimum_battles"
    if "gym" in normalized:
        return "gym_leader_challenge"
    if raw == "standard":
        return "standard_challenge"
    return raw or "standard_challenge"


def workflow_for_challenge(challenge_type: str) -> str:
    if challenge_type in {"ultra_minimum_battles", "minimum_battles"}:
        return "gen1_rby_umb_review_first"
    return "pokemon_gym_leader_challenge"


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def normalize_dt(value: str) -> str:
    return parse_dt(value).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
    return slug or "project"
