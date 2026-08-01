from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_validators import artifact_validation_error
from .models import ProjectProfile, WorkflowDefinition, WorkflowStep


@dataclass
class ArtifactStatus:
    key: str
    path: Path
    exists: bool
    validation_error: str | None = None
    required_by: set[str] = field(default_factory=set)
    produced_by: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": str(self.path),
            "exists": self.exists,
            "valid": self.exists and not self.validation_error,
            "validation_error": self.validation_error,
            "required_by": sorted(self.required_by),
            "produced_by": sorted(self.produced_by),
        }


def collect_artifact_status(
    profile: ProjectProfile,
    workflow: WorkflowDefinition,
    repo: Path,
) -> list[ArtifactStatus]:
    statuses: dict[str, ArtifactStatus] = {}

    def ensure(key: str) -> ArtifactStatus:
        if key not in statuses:
            path = profile.path(key, repo)
            exists = path.exists()
            statuses[key] = ArtifactStatus(
                key=key,
                path=path,
                exists=exists,
                validation_error=artifact_validation_error(key, path) if exists else None,
            )
        return statuses[key]

    for step in workflow.steps:
        for artifact in step.artifacts_in:
            status = ensure(artifact.key)
            if artifact.required:
                status.required_by.add(step.id)
        for artifact in step.artifacts_out:
            ensure(artifact.key).produced_by.add(step.id)

    return sorted(statuses.values(), key=lambda item: item.key)


def step_readiness(
    profile: ProjectProfile,
    workflow: WorkflowDefinition,
    repo: Path,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for step in workflow.steps:
        blocked = [dep for dep in step.depends_on if out.get(dep) != "done"]
        if blocked:
            out[step.id] = "blocked"
            continue
        missing = []
        invalid = []
        for artifact in step.artifacts_in:
            if not artifact.required:
                continue
            path = profile.path(artifact.key, repo)
            if not path.exists():
                missing.append(artifact.key)
                continue
            if artifact_validation_error(artifact.key, path):
                invalid.append(artifact.key)
        if missing:
            out[step.id] = "missing"
            continue
        if invalid:
            out[step.id] = "invalid"
            continue
        outputs = [(artifact.key, profile.path(artifact.key, repo)) for artifact in step.artifacts_out]
        if outputs and all(path.exists() and not artifact_validation_error(key, path) for key, path in outputs):
            out[step.id] = "done"
            continue
        out[step.id] = "ready"
    return out


def workflow_plan(profile: ProjectProfile, workflow: WorkflowDefinition, repo: Path) -> dict[str, Any]:
    return {
        "profile": profile.id,
        "workflow": workflow.id,
        "game_version": profile.game_version,
        "challenge_type": profile.challenge_type,
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "phase": step.phase,
                "kind": step.kind,
                "tool": step.tool,
                "args": step.args,
                "depends_on": step.depends_on,
                "run_in_full": step.run_in_full,
                "pause_after": step.pause_after,
                "command": step.command,
            }
            for step in workflow.steps
        ],
        "artifacts": [item.as_dict() for item in collect_artifact_status(profile, workflow, repo)],
    }
