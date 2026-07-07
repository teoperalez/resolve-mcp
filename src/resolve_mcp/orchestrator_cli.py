from __future__ import annotations

import argparse
import json
from pathlib import Path

from .orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from .orchestrator.llm_dispatch import LLMDispatcher
from .orchestrator.models import ProjectProfile, WorkflowDefinition
from .orchestrator.prompt_engine import PromptEngine
from .orchestrator.runner import OrchestratorRunner, RunEvent
from .orchestrator.status import collect_artifact_status, step_readiness, workflow_plan


def print_event(event: RunEvent) -> None:
    if event.kind == "step":
        print(f"[{event.status}] {event.step_id}: {event.message}", flush=True)
        return
    if event.step_id:
        print(f"{event.kind.upper()} {event.step_id}: {event.message}", flush=True)
    else:
        print(event.message, flush=True)


def load_profile_workflow(config: Path, profile_id: str) -> tuple:
    catalog = load_catalog(config)
    profile = catalog.profile(profile_id)
    workflow = catalog.effective_workflow(profile)
    return catalog, profile, workflow


def select_steps(workflow: WorkflowDefinition, args: argparse.Namespace) -> list:
    if getattr(args, "full", False):
        return [step for step in workflow.steps if step.run_in_full]
    selected_ids = set(getattr(args, "step", []) or [])
    selected_phases = set(getattr(args, "phase", []) or [])
    if selected_ids:
        return [step for step in workflow.steps if step.id in selected_ids]
    if selected_phases:
        return [step for step in workflow.steps if step.phase in selected_phases]
    raise RuntimeError("Choose --full, --phase, or --step.")


def llm_handler_factory(catalog):
    def handle(profile: ProjectProfile, workflow: WorkflowDefinition, step) -> None:
        if not step.llm_task:
            print(f"{step.id}: no llm_task configured")
            return
        task = catalog.effective_llm_task(profile, step.llm_task)
        dispatcher = LLMDispatcher(catalog.repo, log=lambda message: print(message, flush=True))
        result = dispatcher.dispatch(profile, workflow, task)
        print(f"LLM feedback confirmed: {result.output_path}", flush=True)

    return handle


def cmd_profiles(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.config)
    for profile in catalog.profiles:
        print(f"{profile.id}\t{profile.name}\t{profile.workflow_id}")
    return 0


def cmd_workflows(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.config)
    for workflow in catalog.workflows:
        print(f"{workflow.id}\t{workflow.name}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.config)
    errors: list[str] = []
    tool_ids = {tool.id for tool in catalog.tools}
    for workflow in catalog.workflows:
        for step in workflow.steps:
            if not step.tool and not step.command:
                errors.append(f"{workflow.id}.{step.id}: missing tool/command")
                continue
            if step.tool and step.tool not in tool_ids:
                errors.append(f"{workflow.id}.{step.id}: unknown tool {step.tool!r}")
    for tool in catalog.tools:
        if not tool.command:
            errors.append(f"tool {tool.id}: empty command")
            continue
        if "{python}" not in tool.command[0] and "python" not in tool.command[0].lower():
            errors.append(f"tool {tool.id}: command is not Python-backed: {tool.command}")
        if not any(str(part).endswith(".py") or str(part) == "{pipeline_script}" for part in tool.command):
            errors.append(f"tool {tool.id}: command does not reference a Python script: {tool.command}")
    for profile in catalog.profiles:
        workflow = catalog.effective_workflow(profile)
        for step in workflow.steps:
            if not step.command:
                errors.append(f"profile {profile.id}.{step.id}: did not expand to a command")
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2, ensure_ascii=False))
    elif errors:
        print("Catalog validation failed:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("Catalog validation passed.")
    return 1 if errors else 0


def cmd_plan(args: argparse.Namespace) -> int:
    catalog, profile, workflow = load_profile_workflow(args.config, args.profile)
    plan = workflow_plan(profile, workflow, catalog.repo)
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    print(f"{profile.name} -> {workflow.name}")
    for step in workflow.steps:
        command = " ".join(f'"{part}"' if " " in part else part for part in step.command)
        print(f"{step.phase:10} {step.id:24} {step.kind:12} {command}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    catalog, profile, workflow = load_profile_workflow(args.config, args.profile)
    artifacts = collect_artifact_status(profile, workflow, catalog.repo)
    readiness = step_readiness(profile, workflow, catalog.repo)
    if args.json:
        print(json.dumps({
            "profile": profile.id,
            "workflow": workflow.id,
            "steps": readiness,
            "artifacts": [artifact.as_dict() for artifact in artifacts],
        }, indent=2, ensure_ascii=False))
        return 0
    print(f"{profile.name} -> {workflow.name}")
    print("\nSteps:")
    for step in workflow.steps:
        print(f"  {readiness[step.id]:8} {step.phase:10} {step.id}")
    print("\nArtifacts:")
    for artifact in artifacts:
        state = "ok" if artifact.exists else "missing"
        print(f"  {state:8} {artifact.key:28} {artifact.path}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    catalog, profile, workflow = load_profile_workflow(args.config, args.profile)
    task = catalog.effective_llm_task(profile, args.task)
    packet = PromptEngine(catalog.repo).build_packet(profile, workflow, task)
    if args.write:
        PromptEngine(catalog.repo).write_packet(packet)
        print(f"Wrote LLM prompt packet: {packet.prompt_path}")
        print(f"Wrote LLM packet metadata: {packet.packet_path}")
    if args.print:
        print(packet.prompt_text)
    if args.dispatch:
        dispatcher = LLMDispatcher(catalog.repo, log=lambda message: print(message, flush=True))
        result = dispatcher.dispatch(profile, workflow, task, mode=args.mode, dry_run=args.dry_run)
        if args.dry_run:
            print(f"LLM dispatch dry run complete. Expected output: {result.output_path}")
        else:
            print(f"LLM feedback confirmed: {result.output_path}")
    if not args.write and not args.print and not args.dispatch:
        print(packet.prompt_path)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    catalog, profile, workflow = load_profile_workflow(args.config, args.profile)
    steps = select_steps(workflow, args)
    runner = OrchestratorRunner(
        catalog.repo,
        print_event,
        llm_step_handler=llm_handler_factory(catalog),
    )
    runner.run(profile, workflow, steps, skip_completed=args.full and not args.no_resume)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve workflow orchestrator")
    parser.add_argument("--config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profiles", help="List configured project profiles.")
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("workflows", help="List workflow templates.")
    p.set_defaults(func=cmd_workflows)

    p = sub.add_parser("validate", help="Validate workflow catalog wiring.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("plan", help="Show expanded commands for a profile.")
    p.add_argument("--profile", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("status", help="Show artifact and step readiness.")
    p.add_argument("--profile", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("prompt", help="Generate or preview an LLM prompt packet.")
    p.add_argument("--profile", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--write", action="store_true")
    p.add_argument("--print", action="store_true")
    p.add_argument("--dispatch", action="store_true", help="Send the packet to the configured LLM dispatcher and verify output.")
    p.add_argument("--mode", choices=["auto", "codex_cli", "code_workspace"], default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("run", help="Run workflow steps.")
    p.add_argument("--profile", required=True)
    p.add_argument("--full", action="store_true")
    p.add_argument("--phase", action="append", default=[])
    p.add_argument("--step", action="append", default=[])
    p.add_argument("--no-resume", action="store_true", help="Do not skip completed output-producing steps during --full runs.")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
