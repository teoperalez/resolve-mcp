from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator.gsc_gym_reference import audit_surge_reference  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO_DIR / "config" / "gsc_gym_leader_reference_contract.json",
    )
    parser.add_argument(
        "--workflow-config",
        type=Path,
        default=REPO_DIR / "config" / "orchestrator_workflows.json",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = audit_surge_reference(
            contract_path=args.contract,
            workflow_config_path=args.workflow_config,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[gsc-surge-reference] ERROR: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
