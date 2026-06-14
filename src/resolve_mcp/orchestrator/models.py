from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


def default_python(repo: Path) -> str:
    venv_python = repo / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


class SafeFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def expand_templates(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        previous = value
        for _ in range(8):
            current = previous.format_map(SafeFormat(mapping))
            if current == previous:
                return current
            previous = current
        return previous
    if isinstance(value, list):
        return [expand_templates(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: expand_templates(item, mapping) for key, item in value.items()}
    return value


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    title: str
    command: list[str]
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolDefinition":
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or data["id"]),
            command=[str(part) for part in data.get("command") or []],
            description=str(data.get("description") or ""),
        )

    def expanded_command(self, mapping: dict[str, str]) -> list[str]:
        return [str(part) for part in expand_templates(self.command, mapping) if str(part) != ""]


@dataclass(frozen=True)
class ArtifactRef:
    key: str
    required: bool = False
    kind: str = "file"
    description: str = ""

    @classmethod
    def from_any(cls, data: str | dict[str, Any]) -> "ArtifactRef":
        if isinstance(data, str):
            return cls(key=data)
        return cls(
            key=str(data["key"]),
            required=bool(data.get("required", False)),
            kind=str(data.get("kind") or "file"),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    title: str
    phase: str = "main"
    kind: str = "script"
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)
    llm_task: str = ""
    review_surface: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    artifacts_in: list[ArtifactRef] = field(default_factory=list)
    artifacts_out: list[ArtifactRef] = field(default_factory=list)
    optional: bool = False
    run_in_full: bool = True
    allow_parallel: bool = False
    pause_after: bool = False
    requires_resolve: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStep":
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or data["id"]),
            phase=str(data.get("phase") or "main"),
            kind=str(data.get("kind") or "script"),
            tool=str(data.get("tool") or ""),
            args=dict(data.get("args") or {}),
            command=[str(part) for part in data.get("command") or []],
            llm_task=str(data.get("llm_task") or ""),
            review_surface=str(data.get("review_surface") or ""),
            description=str(data.get("description") or ""),
            depends_on=[str(item) for item in data.get("depends_on") or []],
            artifacts_in=[ArtifactRef.from_any(item) for item in data.get("artifacts_in") or []],
            artifacts_out=[ArtifactRef.from_any(item) for item in data.get("artifacts_out") or []],
            optional=bool(data.get("optional", False)),
            run_in_full=bool(data.get("run_in_full", True)),
            allow_parallel=bool(data.get("allow_parallel", False)),
            pause_after=bool(data.get("pause_after", False)),
            requires_resolve=bool(data.get("requires_resolve", False)),
        )

    def expanded(self, mapping: dict[str, str]) -> "WorkflowStep":
        return replace(
            self,
            args=dict(expand_templates(self.args, mapping)),
            command=[str(part) for part in expand_templates(self.command, mapping)],
        )


@dataclass(frozen=True)
class LLMTask:
    id: str
    title: str
    task_type: str
    why_llm: str
    prompt_path: str = ""
    output_path: str = ""
    instructions_path: str = ""
    template: str = ""
    inputs: list[str] = field(default_factory=list)
    output_contract: dict[str, Any] = field(default_factory=dict)
    review_policy: str = "human_approves_before_apply"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMTask":
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or data["id"]),
            task_type=str(data.get("task_type") or "classification"),
            why_llm=str(data.get("why_llm") or ""),
            prompt_path=str(data.get("prompt_path") or ""),
            output_path=str(data.get("output_path") or ""),
            instructions_path=str(data.get("instructions_path") or ""),
            template=str(data.get("template") or ""),
            inputs=[str(item) for item in data.get("inputs") or []],
            output_contract=dict(data.get("output_contract") or {}),
            review_policy=str(data.get("review_policy") or "human_approves_before_apply"),
        )

    def expanded(self, mapping: dict[str, str]) -> "LLMTask":
        return replace(
            self,
            prompt_path=str(expand_templates(self.prompt_path, mapping)),
            output_path=str(expand_templates(self.output_path, mapping)),
            instructions_path=str(expand_templates(self.instructions_path, mapping)),
            template=str(expand_templates(self.template, mapping)),
            inputs=[str(item) for item in expand_templates(self.inputs, mapping)],
        )


@dataclass(frozen=True)
class ReviewSurface:
    id: str
    title: str
    kind: str = "fcpxml_segments"
    input_path: str = ""
    decisions_path: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewSurface":
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or data["id"]),
            kind=str(data.get("kind") or "fcpxml_segments"),
            input_path=str(data.get("input_path") or ""),
            decisions_path=str(data.get("decisions_path") or ""),
            description=str(data.get("description") or ""),
        )

    def expanded(self, mapping: dict[str, str]) -> "ReviewSurface":
        return replace(
            self,
            input_path=str(expand_templates(self.input_path, mapping)),
            decisions_path=str(expand_templates(self.decisions_path, mapping)),
        )


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    description: str
    game_versions: list[str] = field(default_factory=list)
    challenge_types: list[str] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    llm_tasks: list[str] = field(default_factory=list)
    review_surfaces: list[ReviewSurface] = field(default_factory=list)
    tooling: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDefinition":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            description=str(data.get("description") or ""),
            game_versions=[str(item) for item in data.get("game_versions") or []],
            challenge_types=[str(item) for item in data.get("challenge_types") or []],
            steps=[WorkflowStep.from_dict(item) for item in data.get("steps") or []],
            llm_tasks=[str(item) for item in data.get("llm_tasks") or []],
            review_surfaces=[ReviewSurface.from_dict(item) for item in data.get("review_surfaces") or []],
            tooling=dict(data.get("tooling") or {}),
        )

    def expanded(self, mapping: dict[str, str]) -> "WorkflowDefinition":
        return replace(
            self,
            steps=[step.expanded(mapping) for step in self.steps],
            review_surfaces=[surface.expanded(mapping) for surface in self.review_surfaces],
            tooling=dict(expand_templates(self.tooling, mapping)),
        )

    def step(self, step_id: str) -> WorkflowStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"Workflow {self.id!r} has no step {step_id!r}")


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    name: str
    workflow_id: str
    game_version: str
    challenge_type: str
    project_dir: str
    codex_dir: str
    description: str = ""
    paths: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectProfile":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            workflow_id=str(data["workflow_id"]),
            game_version=str(data.get("game_version") or ""),
            challenge_type=str(data.get("challenge_type") or ""),
            project_dir=str(data["project_dir"]),
            codex_dir=str(data["codex_dir"]),
            description=str(data.get("description") or ""),
            paths={str(key): str(value) for key, value in (data.get("paths") or {}).items()},
            parameters=dict(data.get("parameters") or {}),
        )

    def mapping(self, repo: Path) -> dict[str, str]:
        mapping: dict[str, str] = {
            "repo": str(repo),
            "python": default_python(repo),
            "profile_id": self.id,
            "profile_name": self.name,
            "workflow_id": self.workflow_id,
            "project_dir": self.project_dir,
            "codex_dir": self.codex_dir,
            "game_version": self.game_version,
            "challenge_type": self.challenge_type,
        }
        raw_parameters = dict(self.parameters)
        for _ in range(8):
            changed = False
            for key, value in raw_parameters.items():
                if not isinstance(value, (str, int, float, bool)):
                    continue
                expanded = str(expand_templates(str(value), mapping))
                if mapping.get(key) != expanded:
                    changed = True
                mapping[key] = expanded
            if not changed:
                break
        for key, value in self.parameters.items():
            if isinstance(value, (str, int, float, bool)):
                mapping.setdefault(key, str(value))
        raw_paths = dict(self.paths)
        for _ in range(8):
            changed = False
            for key, value in raw_paths.items():
                expanded = str(expand_templates(value, mapping))
                if mapping.get(key) != expanded:
                    changed = True
                mapping[key] = expanded
            if not changed:
                break
        return mapping

    def path(self, key: str, repo: Path) -> Path:
        mapping = self.mapping(repo)
        if key not in mapping:
            raise KeyError(f"Profile {self.id!r} has no path or parameter {key!r}")
        return Path(mapping[key])


@dataclass(frozen=True)
class WorkflowCatalog:
    schema: str
    profiles: list[ProjectProfile]
    workflows: list[WorkflowDefinition]
    llm_tasks: list[LLMTask]
    tools: list[ToolDefinition]
    repo: Path

    @classmethod
    def from_dict(cls, data: dict[str, Any], repo: Path) -> "WorkflowCatalog":
        schema = str(data.get("schema") or "")
        if schema != "resolve_orchestrator_workflows_v1":
            raise RuntimeError(f"Unsupported workflow catalog schema: {schema!r}")
        return cls(
            schema=schema,
            profiles=[ProjectProfile.from_dict(item) for item in data.get("profiles") or []],
            workflows=[WorkflowDefinition.from_dict(item) for item in data.get("workflows") or []],
            llm_tasks=[LLMTask.from_dict(item) for item in data.get("llm_tasks") or []],
            tools=[ToolDefinition.from_dict(item) for item in data.get("tools") or []],
            repo=repo,
        )

    def profile(self, profile_id: str) -> ProjectProfile:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise KeyError(f"No project profile {profile_id!r}")

    def workflow(self, workflow_id: str) -> WorkflowDefinition:
        for workflow in self.workflows:
            if workflow.id == workflow_id:
                return workflow
        raise KeyError(f"No workflow {workflow_id!r}")

    def llm_task(self, task_id: str) -> LLMTask:
        for task in self.llm_tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"No LLM task {task_id!r}")

    def tool(self, tool_id: str) -> ToolDefinition:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        raise KeyError(f"No tool {tool_id!r}")

    def effective_workflow(self, profile: ProjectProfile) -> WorkflowDefinition:
        mapping = profile.mapping(self.repo)
        workflow = self.workflow(profile.workflow_id).expanded(mapping)
        return replace(
            workflow,
            steps=[self.resolve_step_command(profile, step) for step in workflow.steps],
        )

    def effective_llm_task(self, profile: ProjectProfile, task_id: str) -> LLMTask:
        return self.llm_task(task_id).expanded(profile.mapping(self.repo))

    def resolve_step_command(self, profile: ProjectProfile, step: WorkflowStep) -> WorkflowStep:
        if step.command or not step.tool:
            return step
        mapping = profile.mapping(self.repo)
        expanded_args = expand_templates(step.args, mapping)
        for key, value in expanded_args.items():
            if isinstance(value, (str, int, float, bool)):
                mapping[key] = str(value)
        tool = self.tool(step.tool)
        return replace(step, args=dict(expanded_args), command=tool.expanded_command(mapping))
