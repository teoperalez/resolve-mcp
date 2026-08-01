from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import runner


class GscWorkflowDeadlineTests(unittest.TestCase):
    def test_gsc_children_receive_one_strictly_decreasing_shared_budget(self) -> None:
        command = [
            "python",
            "scripts/run_gsc_gym_deterministic_workflow.py",
            "stage",
        ]
        with patch.object(runner.time, "monotonic", side_effect=(100.0, 200.0, 300.0)):
            rendered = [
                runner.OrchestratorRunner._with_workflow_deadline_arg(
                    command,
                    deadline_monotonic=700.0,
                )
                for _ in range(3)
            ]
        budgets = [float(row[row.index("--timeout-seconds") + 1]) for row in rendered]
        self.assertEqual(budgets, [600.0, 500.0, 400.0])

    def test_expired_shared_budget_refuses_to_launch(self) -> None:
        command = ["python", "run_gsc_gym_deterministic_workflow.py", "full"]
        with (
            patch.object(runner.time, "monotonic", return_value=701.0),
            self.assertRaisesRegex(RuntimeError, "shared 600-second deadline"),
        ):
            runner.OrchestratorRunner._with_workflow_deadline_arg(
                command,
                deadline_monotonic=700.0,
            )

    def test_existing_timeout_is_replaced_without_duplication(self) -> None:
        command = [
            "python",
            "scripts/run_gsc_gym_deterministic_workflow.py",
            "full",
            "--timeout-seconds",
            "600",
        ]
        with patch.object(runner.time, "monotonic", return_value=350.0):
            rendered = runner.OrchestratorRunner._with_workflow_deadline_arg(
                command,
                deadline_monotonic=700.0,
            )
        self.assertEqual(rendered.count("--timeout-seconds"), 1)
        self.assertEqual(rendered[-2:], ["--timeout-seconds", "350.000"])

    def test_unrelated_workflow_command_is_unchanged(self) -> None:
        command = ["python", "scripts/run_rby_deterministic_workflow.py", "full"]
        rendered = runner.OrchestratorRunner._with_workflow_deadline_arg(
            command,
            deadline_monotonic=700.0,
        )
        self.assertIs(rendered, command)

    def test_resolve_bootstrap_precedes_remaining_budget_calculation(self) -> None:
        order: list[str] = []
        process = MagicMock()
        process.stdout = []
        process.wait.return_value = 0
        subject = runner.OrchestratorRunner(REPO_DIR, lambda _event: None)

        def bootstrap(*_args, **_kwargs):
            order.append("bootstrap")
            return SimpleNamespace(summary=lambda: "fixture ready")

        def bind_budget(command, *, deadline_monotonic):
            self.assertEqual(deadline_monotonic, 700.0)
            order.append("budget")
            return command

        profile = SimpleNamespace(
            id="fixture",
            workflow_id="gsc_gym_leader_deterministic_single_build",
            parameters={},
        )
        step = SimpleNamespace(
            id="full",
            command=["python", "scripts/run_gsc_gym_deterministic_workflow.py", "full"],
            requires_resolve=True,
        )
        with (
            patch.object(runner, "ensure_resolve_ready", side_effect=bootstrap),
            patch.object(subject, "_with_workflow_deadline_arg", side_effect=bind_budget),
            patch.object(runner.subprocess, "Popen", return_value=process),
        ):
            subject._run_command(
                profile,
                step,
                {},
                workflow_deadline_monotonic=700.0,
            )
        self.assertEqual(order, ["bootstrap", "budget"])


if __name__ == "__main__":
    unittest.main()
