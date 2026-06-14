from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.prompt_engine import PromptEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an orchestrator LLM prompt packet.")
    parser.add_argument("--config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.config)
    profile = catalog.profile(args.profile)
    workflow = catalog.effective_workflow(profile)
    task = catalog.effective_llm_task(profile, args.task)
    packet = PromptEngine(catalog.repo).build_packet(profile, workflow, task)

    if args.write:
        PromptEngine(catalog.repo).write_packet(packet)
        print(f"Wrote LLM prompt packet: {packet.prompt_path}")
        print(f"Wrote LLM packet metadata: {packet.packet_path}")
        print(f"Expected LLM output: {packet.output_path}")
    if args.print:
        print(packet.prompt_text)
    if not args.write and not args.print:
        print(packet.prompt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
