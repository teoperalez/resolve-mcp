from __future__ import annotations

from pathlib import Path

from .models import WorkflowCatalog, read_json


def repo_dir() -> Path:
    source = Path(__file__).resolve()
    for parent in source.parents:
        if (parent / "pyproject.toml").exists() and (parent / "scripts").is_dir():
            return parent
    return Path.cwd()


DEFAULT_WORKFLOW_CONFIG = repo_dir() / "config" / "orchestrator_workflows.json"


def load_catalog(path: Path = DEFAULT_WORKFLOW_CONFIG) -> WorkflowCatalog:
    return WorkflowCatalog.from_dict(read_json(path), repo_dir())
