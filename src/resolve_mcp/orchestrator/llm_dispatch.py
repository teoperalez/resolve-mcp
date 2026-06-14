from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from .models import LLMTask, ProjectProfile, WorkflowDefinition
from .prompt_engine import PromptEngine, PromptPacket


LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class LLMDispatchResult:
    mode: str
    prompt_path: Path
    packet_path: Path
    output_path: Path
    raw_output_path: Path | None
    valid_json: bool
    bytes_written: int


class LLMDispatchError(RuntimeError):
    pass


class LLMDispatcher:
    """Sends orchestrator prompt packets to a local LLM surface and verifies output."""

    def __init__(self, repo: Path, log: LogCallback | None = None) -> None:
        self.repo = repo
        self.log = log or (lambda _message: None)
        self.prompt_engine = PromptEngine(repo)

    def dispatch(
        self,
        profile: ProjectProfile,
        workflow: WorkflowDefinition,
        task: LLMTask,
        *,
        mode: str | None = None,
        dry_run: bool = False,
    ) -> LLMDispatchResult:
        packet = self.prompt_engine.build_packet(profile, workflow, task)
        self.prompt_engine.write_packet(packet)
        self.log(f"Wrote LLM prompt packet: {packet.prompt_path}")
        self.log(f"Wrote LLM packet metadata: {packet.packet_path}")

        effective_mode = (mode or str(profile.parameters.get("llm_dispatch_mode") or "auto")).strip().lower()
        if effective_mode in {"", "auto"}:
            effective_mode = "codex_cli" if shutil.which("codex") else "code_workspace"

        if dry_run:
            self.log(f"Dry run: would dispatch LLM task {task.id!r} through {effective_mode}.")
            if self._bool_param(profile, "llm_open_code_workspace", True):
                self.log("Dry run: would open/reuse Code with the prompt and output files.")
            return LLMDispatchResult(
                mode=effective_mode,
                prompt_path=packet.prompt_path,
                packet_path=packet.packet_path,
                output_path=packet.output_path,
                raw_output_path=None,
                valid_json=False,
                bytes_written=0,
            )

        if self._bool_param(profile, "llm_open_code_workspace", True):
            self._open_code_workspace(packet)

        if effective_mode == "codex_cli":
            return self._dispatch_codex_cli(profile, task, packet)
        if effective_mode == "code_workspace":
            return self._dispatch_code_workspace(profile, task, packet)

        raise LLMDispatchError(
            f"Unsupported LLM dispatch mode {effective_mode!r}. Use auto, codex_cli, or code_workspace."
        )

    def _dispatch_codex_cli(
        self,
        profile: ProjectProfile,
        task: LLMTask,
        packet: PromptPacket,
    ) -> LLMDispatchResult:
        codex = shutil.which("codex")
        if not codex:
            raise LLMDispatchError(
                "Codex CLI was not found on PATH. Install it with:\n"
                "npm install -g @openai/codex\n\n"
                "Or set llm_dispatch_mode to code_workspace for manual-output fallback."
            )

        packet.output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_output_path = packet.output_path.with_name(packet.output_path.name + ".raw.md")
        if raw_output_path.exists():
            raw_output_path.unlink()

        command = [
            codex,
            "--ask-for-approval",
            "never",
            "exec",
            "--cd",
            str(self.repo),
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            str(raw_output_path),
        ]
        model = str(profile.parameters.get("llm_model") or "").strip()
        if model:
            command.extend(["--model", model])

        for path in self._codex_read_roots(profile):
            command.extend(["--add-dir", str(path)])
        command.append("-")

        timeout_sec = self._int_param(profile, "llm_timeout_sec", 3600)
        prompt = self._dispatch_prompt(packet)
        self.log("Sending prompt to Codex CLI...")
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo),
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMDispatchError(f"Codex CLI timed out after {timeout_sec} seconds.") from exc

        if completed.stdout:
            tail = self._tail(completed.stdout)
            if tail:
                self.log(tail)

        if completed.returncode != 0:
            raise LLMDispatchError(
                f"Codex CLI exited with code {completed.returncode}.\n\n{self._tail(completed.stdout)}"
            )

        raw_text = ""
        if raw_output_path.exists():
            raw_text = raw_output_path.read_text(encoding="utf-8", errors="replace")
        if not raw_text.strip() and completed.stdout:
            raw_text = completed.stdout
            raw_output_path.write_text(raw_text, encoding="utf-8")
        if not raw_text.strip():
            raise LLMDispatchError("Codex CLI completed, but no LLM feedback was returned.")

        normalized, valid_json = self._normalize_response(raw_text, task.output_contract)
        packet.output_path.write_text(normalized, encoding="utf-8")
        self.log(f"LLM feedback received: {packet.output_path}")
        if valid_json:
            self.log("LLM feedback parsed as valid JSON for the configured output contract.")
        self.log(f"Raw Codex feedback saved: {raw_output_path}")
        return LLMDispatchResult(
            mode="codex_cli",
            prompt_path=packet.prompt_path,
            packet_path=packet.packet_path,
            output_path=packet.output_path,
            raw_output_path=raw_output_path,
            valid_json=valid_json,
            bytes_written=packet.output_path.stat().st_size,
        )

    def _dispatch_code_workspace(
        self,
        profile: ProjectProfile,
        task: LLMTask,
        packet: PromptPacket,
    ) -> LLMDispatchResult:
        timeout_sec = self._int_param(profile, "llm_timeout_sec", 3600)
        packet.output_path.parent.mkdir(parents=True, exist_ok=True)
        previous = self._file_signature(packet.output_path)
        self.log(f"Waiting for LLM feedback at: {packet.output_path}")
        self.log("Codex CLI is not being used for this task; save the LLM response to the output path above.")
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            current = self._file_signature(packet.output_path)
            if current and current != previous:
                raw_text = packet.output_path.read_text(encoding="utf-8", errors="replace")
                normalized, valid_json = self._normalize_response(raw_text, task.output_contract)
                packet.output_path.write_text(normalized, encoding="utf-8")
                self.log(f"LLM feedback received: {packet.output_path}")
                return LLMDispatchResult(
                    mode="code_workspace",
                    prompt_path=packet.prompt_path,
                    packet_path=packet.packet_path,
                    output_path=packet.output_path,
                    raw_output_path=None,
                    valid_json=valid_json,
                    bytes_written=packet.output_path.stat().st_size,
                )
            time.sleep(2)
        raise LLMDispatchError(f"Timed out waiting for LLM feedback at {packet.output_path}.")

    def _open_code_workspace(self, packet: PromptPacket) -> None:
        code = shutil.which("code")
        if not code:
            self.log("VS Code command 'code' was not found; continuing without opening the workspace.")
            return
        packet.output_path.parent.mkdir(parents=True, exist_ok=True)
        running = self._process_running("Code") if os.name == "nt" else False
        verb = "Reusing" if running else "Opening"
        self.log(f"{verb} Code workspace for the LLM packet.")
        try:
            subprocess.Popen(
                [code, "--reuse-window", str(self.repo), str(packet.prompt_path), str(packet.output_path)],
                cwd=str(self.repo),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            self.log(f"Could not open Code workspace: {exc}")

    def _dispatch_prompt(self, packet: PromptPacket) -> str:
        return (
            "You are the LLM worker for Resolve Orchestrator.\n"
            "Read the packet below and return the requested editorial feedback.\n"
            "Important constraints:\n"
            "- This is an offline review/classification task. Do not connect to Resolve, launch Resolve, or run project pipeline scripts.\n"
            "- Do not edit project files.\n"
            "- Return only the requested JSON or text output, with no Markdown fences unless the packet explicitly asks for Markdown.\n"
            f"- The orchestrator will write your final response to: {packet.output_path}\n\n"
            "## Packet Metadata\n"
            f"{json.dumps(packet.metadata, indent=2, ensure_ascii=False)}\n\n"
            "## Packet Prompt\n\n"
            f"{packet.prompt_text}\n"
        )

    def _normalize_response(self, text: str, output_contract: dict[str, Any]) -> tuple[str, bool]:
        contract_type = str(output_contract.get("type") or "").lower()
        expects_json = contract_type.startswith("json")
        if not expects_json:
            return text.rstrip() + "\n", False

        candidate = self._extract_json(text)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raw_preview = text.strip()[:500]
            raise LLMDispatchError(f"LLM feedback was not valid JSON: {exc}\n\nFirst output bytes:\n{raw_preview}") from exc

        if contract_type == "json_array" and not isinstance(payload, list):
            raise LLMDispatchError("LLM feedback must be a JSON array for this task.")
        if contract_type == "json_object" and not isinstance(payload, dict):
            raise LLMDispatchError("LLM feedback must be a JSON object for this task.")

        required_fields = [str(item) for item in output_contract.get("required_fields") or []]
        if required_fields:
            self._validate_required_fields(payload, required_fields)
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n", True

    @staticmethod
    def _extract_json(text: str) -> str:
        stripped = text.strip()
        fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
        if fence:
            stripped = fence.group(1).strip()
        decoder = json.JSONDecoder()
        starts = [index for index, char in enumerate(stripped) if char in "[{"]
        for start in starts:
            try:
                _payload, end = decoder.raw_decode(stripped[start:])
            except json.JSONDecodeError:
                continue
            return stripped[start : start + end]
        return stripped

    @staticmethod
    def _validate_required_fields(payload: Any, required_fields: list[str]) -> None:
        if isinstance(payload, list):
            for index, item in enumerate(payload):
                if not isinstance(item, dict):
                    raise LLMDispatchError(f"JSON array item {index} must be an object.")
                missing = [field for field in required_fields if field not in item]
                if missing:
                    raise LLMDispatchError(f"JSON array item {index} is missing required field(s): {', '.join(missing)}")
            return
        if isinstance(payload, dict):
            missing = [field for field in required_fields if field not in payload]
            if missing:
                raise LLMDispatchError(f"JSON object is missing required field(s): {', '.join(missing)}")

    def _codex_read_roots(self, profile: ProjectProfile) -> list[Path]:
        mapping = profile.mapping(self.repo)
        roots: list[Path] = []
        for value in (mapping.get("project_dir", ""), mapping.get("codex_dir", "")):
            if not value:
                continue
            path = Path(value)
            if path.exists() and path.resolve() != self.repo.resolve():
                roots.append(path)
        unique: list[Path] = []
        seen: set[str] = set()
        for path in roots:
            resolved = str(path.resolve()).lower()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        return unique

    @staticmethod
    def _bool_param(profile: ProjectProfile, key: str, default: bool) -> bool:
        value = profile.parameters.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _int_param(profile: ProjectProfile, key: str, default: int) -> int:
        try:
            return int(profile.parameters.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int] | None:
        if not path.exists():
            return None
        stat = path.stat()
        if stat.st_size <= 0:
            return None
        return (int(stat.st_mtime_ns), int(stat.st_size))

    @staticmethod
    def _process_running(name: str) -> bool:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"if (Get-Process -Name {name!r} -ErrorAction SilentlyContinue) {{ '1' }}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "1" in completed.stdout

    @staticmethod
    def _tail(text: str, lines: int = 40) -> str:
        return "\n".join(text.splitlines()[-lines:]).strip()
