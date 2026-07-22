from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "token-saver-route.py"
COMMANDS = (
    "resolve",
    "review",
    "worker",
    "snapshot",
    "integrate",
    "validate-config",
    "setup-providers",
    "provider-exec",
    "cleanup",
)


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, str(SCRIPT), *args),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_help_exposes_exact_command_surface(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in COMMANDS:
            self.assertIn(command, result.stdout)
        self.assertNotIn("shell-command", result.stdout)

    def test_validate_config_prints_one_versioned_json_object(self) -> None:
        result = self._run(
            "validate-config",
            str(ROOT / "config" / "token-saver.example.json"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value, {"status": "ok", "version": 1})
        self.assertEqual(result.stderr, "")

    def test_configuration_error_uses_exit_code_two_and_json_stdout(self) -> None:
        result = self._run("validate-config", str(ROOT / "missing.json"))
        self.assertEqual(result.returncode, 2)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "needs_context")

    def test_provider_exec_requires_argument_terminator(self) -> None:
        result = self._run(
            "provider-exec",
            "--route",
            "kimi",
            "--policy",
            "safe",
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
