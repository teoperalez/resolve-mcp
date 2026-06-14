from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator.project_discovery import discover_project


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect orchestrator project settings from a source folder.")
    parser.add_argument("--project-dir", required=True, type=Path, help="Project/source folder to inspect.")
    parser.add_argument("--out", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    discovery = discover_project(args.project_dir).to_dict()
    payload = json.dumps(discovery, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
