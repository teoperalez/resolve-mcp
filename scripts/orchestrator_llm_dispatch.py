from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.llm_dispatch import LLMDispatcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch an orchestrator LLM packet through Codex/Code.")
    parser.add_argument("--config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--mode", choices=["auto", "codex_cli", "code_workspace"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.config)
    profile = catalog.profile(args.profile)
    workflow = catalog.effective_workflow(profile)
    task = catalog.effective_llm_task(profile, args.task)
    dispatcher = LLMDispatcher(catalog.repo, log=lambda message: print(message, flush=True))
    result = dispatcher.dispatch(profile, workflow, task, mode=args.mode, dry_run=args.dry_run)
    if args.dry_run:
        print(f"LLM dispatch dry run complete. Expected output: {result.output_path}", flush=True)
    else:
        print(f"LLM feedback confirmed: {result.output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
