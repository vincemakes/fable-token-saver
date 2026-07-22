"""Worker orchestration and machine-readable Token Saver command line interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .config import ConfigError, load_config
from .evidence import (
    SourceSnapshot,
    WorkerDelta,
    encode_canonical_patch,
    encode_source_snapshot,
    encode_worker_delta,
)
from .models import Route, Status, Transport
from .process import ProcessResult, ProcessSpec, run_process
from .repository import (
    RepositoryError,
    ScopeViolationError,
    WorktreeHandle,
    capture_destination,
    capture_worker_delta,
    project_task_patch,
)
from .sandbox import UnavailableSandbox, VerifiedSandbox
from .setup import (
    SetupError,
    install_provider_wrappers,
    load_credentials,
    migrate_legacy_credentials,
    provider_child_environment,
)


CLI_VERSION = 1
_COMMANDS = (
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


@dataclass(frozen=True)
class GateSpec:
    argv: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not isinstance(self.argv, (tuple, list)) or not self.argv or not all(
            isinstance(member, str) and member and "\0" not in member
            for member in self.argv
        ):
            raise ValueError("gate argv must be a non-empty argument tuple")
        path = Path(self.cwd)
        if path.is_absolute() or any(part in {"", ".."} for part in path.parts):
            raise ValueError("gate cwd must be a validated relative directory")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 3600
        ):
            raise ValueError("gate timeout must be between zero and 3600 seconds")
        object.__setattr__(self, "argv", tuple(self.argv))


@dataclass(frozen=True)
class WorkerTask:
    prompt: bytes
    gates: tuple[GateSpec, ...]

    def __post_init__(self) -> None:
        if type(self.prompt) is not bytes or not self.prompt or b"\0" in self.prompt:
            raise ValueError("worker prompt must be non-empty NUL-free bytes")
        if not isinstance(self.gates, (tuple, list)) or not all(
            isinstance(gate, GateSpec) for gate in self.gates
        ):
            raise ValueError("gates must contain GateSpec values")
        object.__setattr__(self, "gates", tuple(self.gates))


@dataclass(frozen=True)
class GateEvidence:
    argv: tuple[str, ...]
    cwd: str
    status: Status
    exit_code: int | None
    stdout_hash: str
    stderr_hash: str
    duration_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", Status(self.status))


@dataclass(frozen=True)
class WorkerRunResult:
    status: Status
    attempts: int
    gates: tuple[GateEvidence, ...] = ()
    source_snapshot_hash: str | None = None
    worker_delta_hash: str | None = None
    projected_task_patch_hash: str | None = None
    delta: WorkerDelta | None = None
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", Status(self.status))


def _worker_result(status: Status, attempts: int, **kwargs: object) -> WorkerRunResult:
    return WorkerRunResult(status=status, attempts=attempts, **kwargs)  # type: ignore[arg-type]


def _source_is_unchanged(repo: object, snapshot: SourceSnapshot) -> bool:
    try:
        current = capture_destination(repo, snapshot.allowed_paths)
        return encode_source_snapshot(current) == encode_source_snapshot(snapshot)
    except (OSError, RepositoryError, ValueError):
        return False


def _minimal_worker_env(
    route: Route,
    state_root: Path,
    credentials: Mapping[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    environment = {
        "HOME": os.fspath(state_root),
        "XDG_CONFIG_HOME": os.fspath(state_root),
        "XDG_CACHE_HOME": os.fspath(state_root),
        "XDG_STATE_HOME": os.fspath(state_root),
        "TMPDIR": os.fspath(state_root),
        "PATH": os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
    }
    secrets = []
    for binding in route.credential_env:
        value = credentials.get(binding.source_name)
        if not value:
            raise ValueError("required worker credential is missing")
        environment[binding.child_name] = value
        secrets.append(value)
    return environment, tuple(secrets)


def _resolve_gate_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    candidate = Path(argv[0])
    if candidate.is_absolute():
        try:
            executable = candidate.resolve(strict=True)
        except OSError:
            return None
    else:
        discovered = shutil.which(argv[0])
        if discovered is None:
            return None
        executable = Path(discovered).resolve(strict=True)
    try:
        mode = executable.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode) or not os.access(executable, os.X_OK):
        return None
    return (os.fspath(executable), *tuple(argv)[1:])


def _run_gate(
    gate: GateSpec,
    sandbox: VerifiedSandbox,
    environment: Mapping[str, str],
    process_runner: Callable[[ProcessSpec], ProcessResult],
) -> GateEvidence:
    gate_argv = _resolve_gate_argv(gate.argv)
    worktree = sandbox.policy.worktree_root
    try:
        cwd = (worktree / gate.cwd).resolve(strict=True)
        cwd.relative_to(worktree)
    except (OSError, ValueError):
        return GateEvidence(
            argv=gate.argv,
            cwd=gate.cwd,
            status=Status.GATE_FAILED,
            exit_code=None,
            stdout_hash=hashlib.sha256(b"").hexdigest(),
            stderr_hash=hashlib.sha256(b"invalid gate cwd").hexdigest(),
            duration_seconds=0.0,
        )
    if gate_argv is None or not cwd.is_dir() or not sandbox.policy.current:
        return GateEvidence(
            argv=gate.argv,
            cwd=gate.cwd,
            status=Status.GATE_FAILED,
            exit_code=None,
            stdout_hash=hashlib.sha256(b"").hexdigest(),
            stderr_hash=hashlib.sha256(b"gate unavailable").hexdigest(),
            duration_seconds=0.0,
        )
    result = process_runner(
        ProcessSpec(
            argv=(*sandbox.launcher_prefix, *gate_argv),
            cwd=cwd,
            env=environment,
            timeout_seconds=gate.timeout_seconds,
            stdout_limit=1_048_576,
            stderr_limit=1_048_576,
        )
    )
    status = Status.OK if result.status is Status.OK and result.returncode == 0 else (
        Status.TIMEOUT if result.status is Status.TIMEOUT else Status.GATE_FAILED
    )
    return GateEvidence(
        argv=gate.argv,
        cwd=gate.cwd,
        status=status,
        exit_code=result.returncode,
        stdout_hash=hashlib.sha256(result.stdout).hexdigest(),
        stderr_hash=hashlib.sha256(result.stderr).hexdigest(),
        duration_seconds=result.duration_seconds,
    )


def _retry_packet(prompt: bytes, evidence: Sequence[GateEvidence]) -> bytes:
    if not evidence:
        return prompt
    failures = [
        {
            "argv": list(item.argv),
            "cwd": item.cwd,
            "status": item.status.value,
            "exit_code": item.exit_code,
            "stdout_hash": item.stdout_hash,
            "stderr_hash": item.stderr_hash,
        }
        for item in evidence
    ]
    return prompt + b"\n\nTOKEN_SAVER_TRUSTED_GATE_FAILURES=" + json.dumps(
        failures,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def orchestrate_worker(
    repo: str | os.PathLike[str],
    snapshot: SourceSnapshot,
    handle: WorktreeHandle,
    route: Route,
    sandbox: VerifiedSandbox | UnavailableSandbox,
    task: WorkerTask,
    *,
    credentials: Mapping[str, str] | None = None,
    process_runner: Callable[[ProcessSpec], ProcessResult] = run_process,
) -> WorkerRunResult:
    """Run worker/gates in a verified worktree and return evidence, never apply it."""

    if (
        not isinstance(snapshot, SourceSnapshot)
        or not isinstance(handle, WorktreeHandle)
        or not isinstance(route, Route)
        or route.transport is not Transport.EXTERNAL_CLI
        or not isinstance(task, WorkerTask)
    ):
        return _worker_result(Status.NEEDS_CONTEXT, 0, message="invalid worker context")
    if not isinstance(sandbox, VerifiedSandbox):
        return _worker_result(
            Status.SANDBOX_UNAVAILABLE,
            0,
            message="verified worker sandbox is unavailable",
        )
    launch = sandbox.prepare(
        route_id=route.route_id,
        argv=route.command,
        policy=sandbox.policy,
        cwd=handle.path,
    )
    if (
        not launch.available
        or launch.cwd != handle.path.resolve(strict=True)
        or sandbox.policy.route_state_root == handle.path
    ):
        return _worker_result(
            Status.SANDBOX_UNAVAILABLE,
            0,
            message="sandbox binding does not match the worker invocation",
        )
    try:
        environment, secrets = _minimal_worker_env(
            route,
            sandbox.policy.route_state_root,
            credentials or {},
        )
    except ValueError:
        return _worker_result(
            Status.PROVIDER_UNAVAILABLE,
            0,
            message="required worker credentials are unavailable",
        )
    if not _source_is_unchanged(repo, snapshot):
        return _worker_result(
            Status.SCOPE_VIOLATION,
            0,
            message="source repository changed before worker launch",
        )

    all_gate_evidence: list[GateEvidence] = []
    prior_failures: list[GateEvidence] = []
    maximum_attempts = route.retry_policy.worker_attempts
    for attempt in range(1, maximum_attempts + 1):
        worker = process_runner(
            ProcessSpec(
                argv=launch.argv,
                cwd=launch.cwd or handle.path,
                stdin=_retry_packet(task.prompt, prior_failures),
                env=environment,
                timeout_seconds=route.timeout_seconds,
                redact_values=secrets,
            )
        )
        if not _source_is_unchanged(repo, snapshot):
            return _worker_result(
                Status.SCOPE_VIOLATION,
                attempt,
                gates=tuple(all_gate_evidence),
                message="source repository changed during worker execution",
            )
        if worker.status is Status.TIMEOUT:
            return _worker_result(
                Status.TIMEOUT,
                attempt,
                gates=tuple(all_gate_evidence),
                message="worker timed out",
            )
        if worker.status is not Status.OK or worker.returncode != 0:
            return _worker_result(
                Status.TRANSPORT_ERROR,
                attempt,
                gates=tuple(all_gate_evidence),
                message="worker process failed",
            )

        gate_environment = {
            key: value
            for key, value in environment.items()
            if key not in {binding.child_name for binding in route.credential_env}
        }
        this_attempt = tuple(
            _run_gate(gate, sandbox, gate_environment, process_runner)
            for gate in task.gates
        )
        all_gate_evidence.extend(this_attempt)
        if not _source_is_unchanged(repo, snapshot):
            return _worker_result(
                Status.SCOPE_VIOLATION,
                attempt,
                gates=tuple(all_gate_evidence),
                message="source repository changed during trusted gates",
            )
        failures = tuple(item for item in this_attempt if item.status is not Status.OK)
        if failures:
            prior_failures = list(failures)
            if attempt < maximum_attempts:
                continue
            return _worker_result(
                Status.GATE_FAILED,
                attempt,
                gates=tuple(all_gate_evidence),
                message="trusted gate retry limit reached",
            )

        try:
            delta = capture_worker_delta(handle, snapshot, snapshot.allowed_paths)
            projected = project_task_patch(snapshot, delta)
            source_hash = hashlib.sha256(encode_source_snapshot(snapshot)).hexdigest()
            delta_hash = hashlib.sha256(encode_worker_delta(delta)).hexdigest()
            projected_hash = hashlib.sha256(
                encode_canonical_patch(projected)
            ).hexdigest()
        except (OSError, RepositoryError, ScopeViolationError, ValueError):
            return _worker_result(
                Status.SCOPE_VIOLATION,
                attempt,
                gates=tuple(all_gate_evidence),
                message="worker delta failed scope or evidence capture",
            )
        return _worker_result(
            Status.OK,
            attempt,
            gates=tuple(all_gate_evidence),
            source_snapshot_hash=source_hash,
            worker_delta_hash=delta_hash,
            projected_task_patch_hash=projected_hash,
            delta=delta,
            message="worker delta is ready for main-loop review",
        )
    return _worker_result(Status.GATE_FAILED, maximum_attempts)


def _json_output(status: Status, **fields: object) -> str:
    value = {"version": CLI_VERSION, "status": status.value, **fields}
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-saver-route")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        child = subparsers.add_parser(name)
        if name == "validate-config":
            child.add_argument("path")
        elif name == "setup-providers":
            child.add_argument("--legacy-source")
            child.add_argument("--credentials")
            child.add_argument("--install-path")
        elif name == "provider-exec":
            child.add_argument("--route", required=True)
            child.add_argument("--policy", choices=("safe", "sandboxed-worker"), required=True)
            child.add_argument("provider_args", nargs=argparse.REMAINDER)
        else:
            child.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if arguments.command == "validate-config":
        try:
            load_config(profile=Path(arguments.path), discover=False)
        except (ConfigError, OSError, ValueError):
            print(_json_output(Status.NEEDS_CONTEXT, message="configuration is invalid"))
            return 2
        print(_json_output(Status.OK))
        return 0
    if arguments.command == "setup-providers":
        home = Path(os.environ.get("HOME", ""))
        if not home.is_absolute():
            print(_json_output(Status.NEEDS_CONTEXT, message="HOME is unavailable"))
            return 2
        legacy = Path(arguments.legacy_source) if arguments.legacy_source else (
            home / ".claude" / "fable-token-saver" / "providers.env"
        )
        if arguments.credentials:
            credential_path = Path(arguments.credentials)
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            config_root = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".config"
            credential_path = config_root / "token-saver" / "credentials.json"
        try:
            migration = migrate_legacy_credentials(legacy, credential_path)
            if arguments.install_path:
                runner = Path(__file__).resolve().parents[2] / "scripts" / "token-saver-route.py"
                install_provider_wrappers(runner, Path(arguments.install_path))
        except (OSError, SetupError, ValueError):
            print(_json_output(Status.NEEDS_CONTEXT, message="provider setup failed safely"))
            return 2
        print(_json_output(Status.OK, setup_status=migration.status))
        return 0
    if arguments.command == "provider-exec":
        provider_args = tuple(arguments.provider_args)
        if not provider_args or provider_args[0] != "--":
            print(_json_output(Status.NEEDS_CONTEXT, message="provider argv requires --"))
            return 2
        if arguments.policy == "sandboxed-worker":
            print(
                _json_output(
                    Status.SANDBOX_UNAVAILABLE,
                    message="a sealed invocation and fresh sandbox probe are required",
                )
            )
            return 3
        home = Path(os.environ.get("HOME", ""))
        credential_override = os.environ.get("TOKEN_SAVER_CREDENTIALS")
        if credential_override:
            credential_path = Path(credential_override)
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            config_root = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".config"
            credential_path = config_root / "token-saver" / "credentials.json"
        provider = shutil.which("claude")
        try:
            if provider is None:
                raise SetupError("provider executable is unavailable")
            credentials = load_credentials(credential_path)
            environment = provider_child_environment(
                arguments.route,
                credentials,
                os.environ,
            )
            executable = Path(provider).resolve(strict=True)
        except (OSError, SetupError, ValueError):
            print(_json_output(Status.PROVIDER_UNAVAILABLE, message="provider route unavailable"))
            return 3
        os.execve(
            executable,
            (os.fspath(executable), *provider_args[1:]),
            environment,
        )
        return 3
    print(_json_output(Status.NEEDS_CONTEXT, message="command requires an invocation packet"))
    return 2


__all__ = (
    "GateEvidence",
    "GateSpec",
    "WorkerRunResult",
    "WorkerTask",
    "build_parser",
    "main",
    "orchestrate_worker",
)
