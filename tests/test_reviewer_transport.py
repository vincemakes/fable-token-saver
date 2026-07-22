from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.token_saver.models import CapabilityBand, Role, Route, Transport
from runtime.token_saver.process import ProcessResult
from runtime.token_saver.transport import execute_reviewer


BINDING = "a" * 64
PACKET = json.dumps(
    {
        "version": 1,
        "source_snapshot_hash": "1" * 64,
        "worker_delta_hash": "2" * 64,
        "projected_task_patch_hash": "3" * 64,
        "approval_binding_hash": BINDING,
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")


def _route(command: tuple[str, ...]) -> Route:
    return Route(
        route_id="reviewer",
        transport=Transport.EXTERNAL_CLI,
        band=CapabilityBand.AUTHORITY,
        roles=frozenset({Role.REVIEWER}),
        read_only=True,
        command=command,
        provider_family="example",
        model="authority-v1",
        variant="default",
    )


def _result(stdout: bytes, *, returncode: int = 0, status: str = "ok") -> ProcessResult:
    return ProcessResult(
        status=status,
        returncode=returncode,
        stdout=stdout,
        stderr=b"",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=status == "timeout",
        duration_seconds=0.01,
    )


class ReviewerTransportTests(unittest.TestCase):
    def _run(self, command: tuple[str, ...], output: object, **kwargs):
        captured = []

        def runner(spec):
            captured.append(spec)
            if isinstance(output, ProcessResult):
                return output
            return _result(
                json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
            )

        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / "evidence-parent"
            state = Path(root) / "state"
            parent.mkdir()
            state.mkdir()
            result = execute_reviewer(
                _route(command),
                PACKET,
                BINDING,
                evidence_parent=parent,
                route_state_root=state,
                process_runner=runner,
                **kwargs,
            )
            self.assertEqual(tuple(parent.iterdir()), ())
        return result, captured

    def test_claude_exact_safe_argv_and_single_json_verdict(self) -> None:
        verdict = {
            "version": 1,
            "decision": "approve",
            "approval_binding_hash": BINDING,
            "message": "looks good",
            "requested_changes": [],
        }
        result, captured = self._run((sys.executable,), verdict)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.verdict.decision, "approve")
        self.assertEqual(
            captured[0].argv[-8:],
            (
                "--safe-mode",
                "--no-session-persistence",
                "--permission-mode",
                "plan",
                "--tools",
                "",
                "-p",
                "-",
            ),
        )
        self.assertEqual(captured[0].stdin, PACKET)
        self.assertEqual(captured[0].cwd.name, "evidence")

    def test_codex_exact_ephemeral_read_only_argv(self) -> None:
        verdict = {
            "version": 1,
            "decision": "approve",
            "approval_binding_hash": BINDING,
            "message": "ok",
            "requested_changes": [],
        }
        result, captured = self._run((sys.executable, "codex"), verdict)
        self.assertEqual(result.status, "ok")
        argv = captured[0].argv
        self.assertIn("exec", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("read-only", argv)
        self.assertNotIn("danger-full-access", argv)

    def test_revise_requires_changes_and_exact_binding(self) -> None:
        bad_outputs = (
            {
                "version": 1,
                "decision": "revise",
                "approval_binding_hash": BINDING,
                "message": "change it",
                "requested_changes": [],
            },
            {
                "version": 1,
                "decision": "approve",
                "approval_binding_hash": "b" * 64,
                "message": "wrong tuple",
                "requested_changes": [],
            },
        )
        for output in bad_outputs:
            with self.subTest(output=output):
                result, _ = self._run((sys.executable,), output)
                self.assertEqual(result.status, "transport_error")

    def test_unknown_fields_prefix_suffix_timeout_and_nonzero_fail_closed(self) -> None:
        valid = {
            "version": 1,
            "decision": "approve",
            "approval_binding_hash": BINDING,
            "message": "ok",
            "requested_changes": [],
        }
        cases = (
            _result(json.dumps({**valid, "extra": True}).encode()),
            _result(b"prefix " + json.dumps(valid).encode()),
            _result(json.dumps(valid).encode() + b" suffix"),
            _result(b"", status="timeout", returncode=-15),
            _result(json.dumps(valid).encode(), returncode=7, status="transport_error"),
        )
        for output in cases:
            with self.subTest(output=output):
                result, _ = self._run((sys.executable,), output)
                self.assertEqual(result.status, "transport_error")

    def test_packet_may_not_name_a_forbidden_repository(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            forbidden = Path(root) / "repo"
            forbidden.mkdir()
            packet = PACKET + os.fsencode(forbidden)
            parent = Path(root) / "parent"
            state = Path(root) / "state"
            parent.mkdir()
            state.mkdir()
            result = execute_reviewer(
                _route((sys.executable,)),
                packet,
                BINDING,
                evidence_parent=parent,
                route_state_root=state,
                process_runner=lambda spec: _result(b"{}"),
                forbidden_roots=(forbidden,),
            )
        self.assertEqual(result.status, "transport_error")


if __name__ == "__main__":
    unittest.main()
