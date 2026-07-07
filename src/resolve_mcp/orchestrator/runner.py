from __future__ import annotations

import subprocess
import threading
import os
from dataclasses import dataclass
from collections import deque
from pathlib import Path
from typing import Callable

from .models import ProjectProfile, WorkflowDefinition, WorkflowStep, expand_templates
from .resolve_bootstrap import ensure_resolve_ready


@dataclass(frozen=True)
class RunEvent:
    kind: str
    message: str
    step_id: str = ""
    status: str = ""


EventCallback = Callable[[RunEvent], None]
LLMStepHandler = Callable[[ProjectProfile, WorkflowDefinition, WorkflowStep], None]


class OrchestratorRunner:
    """Runs deterministic workflow steps while leaving LLM/manual gates explicit."""

    def __init__(
        self,
        repo: Path,
        callback: EventCallback,
        llm_step_handler: LLMStepHandler | None = None,
    ) -> None:
        self.repo = repo
        self.callback = callback
        self.llm_step_handler = llm_step_handler
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(
        self,
        profile: ProjectProfile,
        workflow: WorkflowDefinition,
        steps: list[WorkflowStep],
        *,
        skip_completed: bool = False,
    ) -> None:
        self.cancel_requested = False
        mapping = profile.mapping(self.repo)
        completed: set[str] = set()
        selected_ids = {step.id for step in steps}

        for step in steps:
            if self.cancel_requested:
                self.callback(RunEvent("error", "Run cancelled before the next step."))
                return
            missing_deps = [dep for dep in step.depends_on if dep not in completed and dep in selected_ids]
            if missing_deps:
                raise RuntimeError(f"Step {step.id!r} is missing selected dependency/dependencies: {', '.join(missing_deps)}")
            missing_artifacts = self._missing_required_artifacts(profile, step)
            if missing_artifacts:
                message = self._missing_artifact_message(step, missing_artifacts)
                if step.optional:
                    self.callback(RunEvent("log", f"SKIP {step.title}: {message}", step.id, "skipped"))
                    continue
                raise RuntimeError(message)

            if skip_completed and self._outputs_complete(profile, step):
                self.callback(RunEvent("log", f"CACHE {step.title}: declared outputs already exist.", step.id, "skipped"))
                self.callback(RunEvent("step", step.title, step.id, "done"))
                completed.add(step.id)
                continue

            self.callback(RunEvent("step", step.title, step.id, "running"))
            try:
                self._run_step(profile, workflow, step, mapping)
            except Exception as exc:
                self.callback(RunEvent("step", str(exc), step.id, "failed"))
                if step.optional:
                    self.callback(RunEvent("log", f"OPTIONAL STEP FAILED: {step.title}: {exc}", step.id, "failed"))
                    continue
                raise
            self.callback(RunEvent("step", step.title, step.id, "done"))
            completed.add(step.id)
            if step.pause_after:
                self.callback(RunEvent("pause", f"Paused after {step.title}.", step.id, "paused"))
                return

    def _missing_required_artifacts(self, profile: ProjectProfile, step: WorkflowStep) -> list[Path]:
        missing: list[Path] = []
        for artifact in step.artifacts_in:
            if not artifact.required:
                continue
            path = profile.path(artifact.key, self.repo)
            if not path.exists():
                missing.append(path)
        return missing

    def _outputs_complete(self, profile: ProjectProfile, step: WorkflowStep) -> bool:
        if not step.artifacts_out:
            return False
        paths = [profile.path(artifact.key, self.repo) for artifact in step.artifacts_out]
        return all(path.exists() for path in paths)

    @staticmethod
    def _missing_artifact_message(step: WorkflowStep, missing: list[Path]) -> str:
        lines = [
            f"STOP: {step.title} cannot continue autonomously.",
            "Reason: required asset/data is missing.",
            "Missing:",
            *[f"  - {path}" for path in missing],
            "Ask the user how to proceed before continuing:",
            "  1. Provide or regenerate the missing artifact, then rerun this step.",
            "  2. Update the project profile path/setting in the orchestrator GUI.",
            "  3. Explicitly approve a different artifact or fallback policy.",
        ]
        return "\n".join(lines)

    def _run_step(
        self,
        profile: ProjectProfile,
        workflow: WorkflowDefinition,
        step: WorkflowStep,
        mapping: dict[str, str],
    ) -> None:
        if step.kind == "llm_prompt":
            if self.llm_step_handler:
                self.llm_step_handler(profile, workflow, step)
            else:
                self.callback(RunEvent("log", f"{step.title}: LLM prompt packet must be generated manually.", step.id, "done"))
            return
        if step.command:
            self._run_command(profile, step, mapping)
            return
        if step.kind in {"manual_gate", "review"}:
            self.callback(RunEvent("log", f"{step.title}: handled by GUI/manual workflow.", step.id, "done"))
            return
        if step.kind != "script":
            self.callback(RunEvent("log", f"{step.title}: no executable action for kind {step.kind!r}.", step.id, "done"))
            return
        if not step.command:
            self.callback(RunEvent("log", f"{step.title}: empty command.", step.id, "done"))
            return

    def _run_command(self, profile: ProjectProfile, step: WorkflowStep, mapping: dict[str, str]) -> None:
        command = [str(part) for part in expand_templates(step.command, mapping) if str(part) != ""]
        if step.requires_resolve:
            self.callback(RunEvent("log", "Resolve required for this final assembly step. Bootstrapping Resolve...", step.id, "running"))
            result = ensure_resolve_ready(profile, self.repo)
            self.callback(RunEvent("log", f"Resolve ready: {result.summary()}", step.id, "running"))
        self.callback(RunEvent("log", self._format_command(command), step.id, "running"))
        env = os.environ.copy()
        env.update(
            {
                "ORCHESTRATOR_PROFILE_ID": profile.id,
                "ORCHESTRATOR_WORKFLOW_ID": profile.workflow_id,
            }
        )
        workflow_config = profile.parameters.get("workflow_config")
        if workflow_config:
            env["ORCHESTRATOR_CONFIG_PATH"] = str(expand_templates(str(workflow_config), mapping))
        process = subprocess.Popen(
            command,
            cwd=str(self.repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert process.stdout is not None
        output_tail: deque[str] = deque(maxlen=80)
        for line in process.stdout:
            clean = line.rstrip()
            output_tail.append(clean)
            self.callback(RunEvent("log", clean, step.id, "running"))
            if self.cancel_requested:
                process.terminate()
                raise RuntimeError("Cancelled.")
        code = process.wait()
        if code != 0:
            raise RuntimeError(self._failure_message(code, command, list(output_tail)))

    @staticmethod
    def _format_command(command: list[str]) -> str:
        return " ".join(f'"{part}"' if " " in part else part for part in command)

    @staticmethod
    def _failure_message(code: int, command: list[str], output_tail: list[str]) -> str:
        tail_text = "\n".join(output_tail).strip()
        command_text = OrchestratorRunner._format_command(command)
        if "Could not connect to Resolve" in tail_text or "Could not connect to DaVinci Resolve" in tail_text:
            return (
                "Could not connect to DaVinci Resolve. Open Resolve with a project loaded, "
                "then confirm Preferences > General > External scripting using is set to Local.\n\n"
                f"Command exited with code {code}:\n{command_text}"
            )
        if tail_text:
            return f"Command exited with code {code}:\n{command_text}\n\nLast output:\n{tail_text}"
        return f"Command exited with code {code}:\n{command_text}"


class ThreadedRun:
    def __init__(self, runner: OrchestratorRunner) -> None:
        self.runner = runner
        self.thread: threading.Thread | None = None
        self.error: Exception | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(
        self,
        profile: ProjectProfile,
        workflow: WorkflowDefinition,
        steps: list[WorkflowStep],
        *,
        skip_completed: bool = False,
    ) -> None:
        if self.running:
            raise RuntimeError("A workflow run is already active.")
        self.error = None

        def target() -> None:
            try:
                self.runner.run(profile, workflow, steps, skip_completed=skip_completed)
            except Exception as exc:
                self.error = exc
                self.runner.callback(RunEvent("error", str(exc)))

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
