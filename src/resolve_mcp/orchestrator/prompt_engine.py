from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LLMTask, ProjectProfile, WorkflowDefinition, write_json


@dataclass(frozen=True)
class PromptPacket:
    task_id: str
    prompt_path: Path
    output_path: Path
    packet_path: Path
    prompt_text: str
    metadata: dict[str, Any]


class PromptEngine:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def build_packet(
        self,
        profile: ProjectProfile,
        workflow: WorkflowDefinition,
        task: LLMTask,
        overrides: dict[str, Any] | None = None,
    ) -> PromptPacket:
        mapping = profile.mapping(self.repo)
        context = dict(mapping)
        if overrides:
            context.update({key: str(value) for key, value in overrides.items()})

        source_prompt_path = Path(task.prompt_path) if task.prompt_path else None
        if source_prompt_path:
            prompt_path = source_prompt_path.with_name(source_prompt_path.stem + ".llm_packet.md")
        else:
            prompt_path = Path(f"{mapping['codex_dir']}/llm/{task.id}.in.md")
        output_path = Path(task.output_path or f"{mapping['codex_dir']}/llm/{task.id}.out.json")
        packet_path = prompt_path.with_suffix(".packet.json")

        prompt_text = self._prompt_text(task, context, source_prompt_path)
        metadata = {
            "schema": "resolve_orchestrator_llm_packet_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile.id,
            "workflow": workflow.id,
            "task": task.id,
            "task_type": task.task_type,
            "why_llm": task.why_llm,
            "source_prompt_path": str(source_prompt_path or ""),
            "instructions_path": task.instructions_path,
            "inputs": task.inputs,
            "prompt_path": str(prompt_path),
            "expected_output_path": str(output_path),
            "output_contract": task.output_contract,
            "review_policy": task.review_policy,
        }
        return PromptPacket(task.id, prompt_path, output_path, packet_path, prompt_text, metadata)

    def write_packet(self, packet: PromptPacket) -> None:
        packet.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        packet.prompt_path.write_text(packet.prompt_text, encoding="utf-8")
        write_json(packet.packet_path, packet.metadata)

    def _prompt_text(self, task: LLMTask, context: dict[str, str], source_prompt_path: Path | None) -> str:
        if source_prompt_path and source_prompt_path.exists():
            prompt_body = source_prompt_path.read_text(encoding="utf-8")
        elif task.template:
            prompt_body = task.template.format_map(context)
        else:
            prompt_body = self._default_prompt_body(task, context)

        instructions = ""
        if task.instructions_path and Path(task.instructions_path).exists():
            instructions = Path(task.instructions_path).read_text(encoding="utf-8").strip()

        header = [
            f"# LLM Packet: {task.title}",
            "",
            f"Task id: `{task.id}`",
            f"Task type: `{task.task_type}`",
            "",
            "## Why This Needs An LLM",
            "",
            task.why_llm or "This task requires semantic or visual judgment that deterministic scripts should not guess.",
            "",
            "## Output Contract",
            "",
            "Return only the JSON described by this packet. Do not wrap the result in Markdown fences.",
            "",
        ]
        if instructions:
            header.extend(["## Shared Instructions", "", instructions, ""])
        header.extend(["## Task Prompt", "", prompt_body.rstrip(), ""])
        return "\n".join(header)

    @staticmethod
    def _default_prompt_body(task: LLMTask, context: dict[str, str]) -> str:
        input_lines = "\n".join(f"- {item}" for item in task.inputs) or "- No input files configured yet."
        return (
            f"Review the configured inputs for `{task.id}` and produce the JSON output for this task.\n\n"
            f"Inputs:\n{input_lines}\n\n"
            "Project context:\n"
            f"- project_dir: {context.get('project_dir', '')}\n"
            f"- codex_dir: {context.get('codex_dir', '')}\n"
            f"- game_version: {context.get('game_version', '')}\n"
            f"- challenge_type: {context.get('challenge_type', '')}\n"
        )
