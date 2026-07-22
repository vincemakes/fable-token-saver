"""Evidence-only reviewer transport and injectable route preflight."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .models import (
    FingerprintEvidenceSource,
    ModelFingerprint,
    Role,
    Route,
    RouteProbeResult,
    Status,
    Transport,
)
from .process import ProcessResult, ProcessSpec, run_process
from .sandbox import UnavailableSandbox, VerifiedSandbox


_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_VERDICT_KEYS = {
    "version",
    "decision",
    "approval_binding_hash",
    "message",
    "requested_changes",
}
_CLAUDE_REVIEW_SUFFIX = (
    "--safe-mode",
    "--no-session-persistence",
    "--permission-mode",
    "plan",
    "--tools",
    "",
    "-p",
    "-",
)


@dataclass(frozen=True)
class ReviewerVerdict:
    version: int
    decision: str
    approval_binding_hash: str
    message: str
    requested_changes: tuple[str, ...]


@dataclass(frozen=True)
class ReviewerTransportResult:
    status: Status
    verdict: ReviewerVerdict | None = None
    message: str = ""

    def __post_init__(self) -> None:
        try:
            status = Status(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("status must be a Token Saver status") from exc
        if status is Status.OK and not isinstance(self.verdict, ReviewerVerdict):
            raise ValueError("successful reviewer transport requires a verdict")
        if status is not Status.OK and self.verdict is not None:
            raise ValueError("failed reviewer transport cannot expose a verdict")
        object.__setattr__(self, "status", status)


def _failure(message: str) -> ReviewerTransportResult:
    return ReviewerTransportResult(Status.TRANSPORT_ERROR, message=message)


def _resolve_executable(command: Sequence[str]) -> tuple[str, ...] | None:
    if not command:
        return None
    candidate = Path(command[0])
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
    else:
        discovered = shutil.which(command[0])
        if discovered is None:
            return None
        try:
            resolved = Path(discovered).resolve(strict=True)
        except OSError:
            return None
    try:
        metadata = resolved.stat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return (os.fspath(resolved), *tuple(command)[1:])


def _is_codex_command(command: Sequence[str]) -> bool:
    return any(Path(member).name.lower() == "codex" for member in command[:2])


def _reviewer_argv(command: tuple[str, ...], evidence_dir: Path) -> tuple[str, ...]:
    lowered = tuple(member.lower() for member in command)
    if any("bypass" in member or "danger-full-access" in member for member in lowered):
        raise ValueError("reviewer command contains a write-capable bypass")
    if _is_codex_command(command):
        return (
            *command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "-C",
            os.fspath(evidence_dir),
            "-",
        )
    return (*command, *_CLAUDE_REVIEW_SUFFIX)


def _canonical_packet(packet: bytes, expected_hash: str) -> bool:
    if type(packet) is not bytes or not packet or b"\0" in packet:
        return False
    if _SHA256.fullmatch(expected_hash) is None:
        return False
    try:
        value = json.loads(
            packet.decode("utf-8", "strict"),
            object_pairs_hook=_reject_duplicate_object,
        )
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    except (UnicodeError, ValueError, TypeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("approval_binding_hash") == expected_hash
        and canonical == packet
    )


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_verdict(raw: bytes, expected_hash: str) -> ReviewerVerdict | None:
    try:
        text = raw.decode("utf-8", "strict")
        if not text or text != text.strip():
            return None
        value = json.loads(text, object_pairs_hook=_reject_duplicate_object)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != _VERDICT_KEYS:
        return None
    if value["version"] != 1 or value["decision"] not in {"approve", "revise"}:
        return None
    if value["approval_binding_hash"] != expected_hash:
        return None
    message = value["message"]
    changes = value["requested_changes"]
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message) > 4096
        or not isinstance(changes, list)
        or not all(isinstance(change, str) and change.strip() for change in changes)
    ):
        return None
    if value["decision"] == "approve" and changes:
        return None
    if value["decision"] == "revise" and not changes:
        return None
    return ReviewerVerdict(
        version=1,
        decision=value["decision"],
        approval_binding_hash=expected_hash,
        message=message,
        requested_changes=tuple(changes),
    )


def _evidence_manifest(directory: Path) -> tuple[tuple[str, int, int, str], ...]:
    entries = []
    for child in directory.iterdir():
        metadata = child.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("review evidence directory contains an unexpected object")
        entries.append(
            (
                child.name,
                metadata.st_dev,
                metadata.st_ino,
                hashlib.sha256(child.read_bytes()).hexdigest(),
            )
        )
    return tuple(sorted(entries))


def execute_reviewer(
    route: Route,
    packet: bytes,
    approval_binding_hash: str,
    *,
    evidence_parent: str | os.PathLike[str],
    route_state_root: str | os.PathLike[str],
    process_runner: Callable[[ProcessSpec], ProcessResult] = run_process,
    forbidden_roots: Sequence[str | os.PathLike[str]] = (),
    credentials: Mapping[str, str] | None = None,
) -> ReviewerTransportResult:
    """Run a reviewer with packet-only stdin and an immutable evidence cwd."""

    if (
        not isinstance(route, Route)
        or route.transport is not Transport.EXTERNAL_CLI
        or Role.REVIEWER not in route.roles
        or not route.read_only
    ):
        return _failure("route is not an external read-only reviewer")
    if not _canonical_packet(packet, approval_binding_hash):
        return _failure("review packet is not canonical or binding-complete")
    for root in forbidden_roots:
        try:
            encoded = os.fsencode(Path(root).resolve(strict=True))
        except (OSError, TypeError, ValueError):
            return _failure("forbidden root could not be resolved")
        if encoded and encoded in packet:
            return _failure("review packet names a forbidden repository root")
    command = _resolve_executable(route.command)
    if command is None:
        return _failure("reviewer executable is unavailable")
    try:
        parent = Path(evidence_parent).resolve(strict=True)
        state = Path(route_state_root).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return _failure("reviewer roots are unavailable")
    if not parent.is_dir() or not state.is_dir() or parent == state:
        return _failure("reviewer roots are invalid")

    root = Path(tempfile.mkdtemp(prefix="token-saver-review-", dir=parent))
    evidence = root / "evidence"
    try:
        evidence.mkdir(mode=0o700)
        packet_path = evidence / "packet.json"
        descriptor = os.open(
            packet_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(packet)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(packet_path, 0o400)
        before = _evidence_manifest(evidence)
        argv = _reviewer_argv(command, evidence)
        credential_values = tuple(
            value for value in (credentials or {}).values() if value
        )
        environment = {
            "HOME": os.fspath(state),
            "XDG_CONFIG_HOME": os.fspath(state),
            "XDG_CACHE_HOME": os.fspath(state),
            "XDG_STATE_HOME": os.fspath(state),
            "TMPDIR": os.fspath(state),
            "PATH": os.defpath,
            "LANG": "C",
            "LC_ALL": "C",
        }
        for binding in route.credential_env:
            value = (credentials or {}).get(binding.source_name)
            if value:
                environment[binding.child_name] = value
        process_result = process_runner(
            ProcessSpec(
                argv=argv,
                cwd=evidence,
                stdin=packet,
                env=environment,
                timeout_seconds=route.timeout_seconds,
                stdout_limit=262_144,
                stderr_limit=262_144,
                redact_values=credential_values,
            )
        )
        try:
            after = _evidence_manifest(evidence)
        except (OSError, ValueError):
            return _failure("reviewer changed the evidence directory")
        if after != before:
            return _failure("reviewer changed the evidence directory")
        if (
            process_result.status is not Status.OK
            or process_result.returncode != 0
            or process_result.stdout_truncated
        ):
            return _failure("reviewer process did not return a complete verdict")
        verdict = _parse_verdict(process_result.stdout, approval_binding_hash)
        if verdict is None:
            return _failure("reviewer output is not the strict verdict schema")
        return ReviewerTransportResult(Status.OK, verdict=verdict)
    except (OSError, ValueError):
        return _failure("reviewer transport failed safely")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _parse_version(output: bytes) -> tuple[int, ...] | None:
    match = re.search(rb"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", output)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _identity_from_output(output: bytes) -> ModelFingerprint | None:
    try:
        value = json.loads(output.decode("utf-8", "strict"))
    except (UnicodeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "provider_family",
        "resolved_model_id",
        "variant",
    }:
        return None
    try:
        return ModelFingerprint(
            value["provider_family"],
            value["resolved_model_id"],
            value["variant"],
        )
    except (TypeError, ValueError):
        return None


def probe_route(
    route: Route,
    role: Role,
    credentials: Mapping[str, str],
    sandbox_factory: Callable[..., object],
    process_runner: Callable[[ProcessSpec], ProcessResult],
) -> RouteProbeResult:
    """Produce credential-free preflight facts through injectable probes."""

    if not isinstance(route, Route):
        raise ValueError("route must be Route")
    try:
        role = Role(role)
    except (TypeError, ValueError) as exc:
        raise ValueError("role is unsupported") from exc
    declared = tuple(binding.source_name for binding in route.credential_env)
    configured = tuple(name for name in declared if bool(credentials.get(name)))
    missing = tuple(name for name in declared if name not in configured)

    if route.transport is Transport.HOST_SUBAGENT:
        probe_native = getattr(process_runner, "probe_native", None)
        metadata = probe_native(route, role) if callable(probe_native) else None
        fingerprint = metadata.get("fingerprint") if isinstance(metadata, dict) else None
        return RouteProbeResult(
            route_id=route.route_id,
            reachable=bool(metadata) and not missing,
            resolved_fingerprint=fingerprint if isinstance(fingerprint, ModelFingerprint) else None,
            fingerprint_evidence_source=(
                FingerprintEvidenceSource.HOST_METADATA
                if isinstance(fingerprint, ModelFingerprint)
                else None
            ),
            executable_available=False,
            native_agent_available=bool(metadata),
            reviewer_read_only_enforced=bool(
                isinstance(metadata, dict) and metadata.get("read_only") is True
            ),
            configured_credentials=configured,
            missing_credentials=missing,
        )

    command = _resolve_executable(route.command)
    if command is None:
        return RouteProbeResult(
            route_id=route.route_id,
            reachable=False,
            resolved_fingerprint=None,
            fingerprint_evidence_source=None,
            executable_available=False,
            native_agent_available=False,
            reviewer_read_only_enforced=False,
            configured_credentials=configured,
            missing_credentials=missing,
        )
    state = Path(tempfile.mkdtemp(prefix="token-saver-route-probe-"))
    try:
        environment = {
            "HOME": os.fspath(state),
            "PATH": os.defpath,
            "LANG": "C",
            "LC_ALL": "C",
        }
        version_result = process_runner(
            ProcessSpec(
                argv=(command[0], "--version"),
                cwd=state,
                env=environment,
                timeout_seconds=min(route.timeout_seconds, 30),
            )
        )
        executable_available = version_result.status is Status.OK
        if _is_codex_command(command):
            parsed = _parse_version(version_result.stdout + version_result.stderr)
            executable_available = executable_available and parsed is not None and parsed >= (
                0,
                144,
                0,
            )
        identity_result = process_runner(
            ProcessSpec(
                argv=(*command, "--token-saver-identity"),
                cwd=state,
                env=environment,
                timeout_seconds=min(route.timeout_seconds, 30),
            )
        )
        fingerprint = (
            _identity_from_output(identity_result.stdout)
            if identity_result.status is Status.OK
            else None
        )
        expected_identity = None
        verified_identity = None
        sandbox_ok = role is not Role.WORKER
        if role is Role.WORKER:
            try:
                sandbox = sandbox_factory(route, command)
            except (TypeError, ValueError, OSError):
                sandbox = UnavailableSandbox("sandbox probe failed")
            if isinstance(sandbox, VerifiedSandbox):
                try:
                    expected_identity = sandbox.worker_identity(route)
                    verified_identity = expected_identity
                    sandbox_ok = True
                except (TypeError, ValueError):
                    sandbox_ok = False
        reviewer_read_only = role is Role.REVIEWER and fingerprint is not None
        return RouteProbeResult(
            route_id=route.route_id,
            reachable=executable_available and not missing and sandbox_ok,
            resolved_fingerprint=fingerprint,
            fingerprint_evidence_source=(
                FingerprintEvidenceSource.IDENTITY_HANDSHAKE
                if fingerprint is not None
                else None
            ),
            executable_available=executable_available,
            native_agent_available=False,
            reviewer_read_only_enforced=reviewer_read_only,
            expected_worker_sandbox_identity=expected_identity,
            verified_worker_sandbox_identity=verified_identity,
            configured_credentials=configured,
            missing_credentials=missing,
        )
    finally:
        shutil.rmtree(state, ignore_errors=True)


__all__ = (
    "ReviewerTransportResult",
    "ReviewerVerdict",
    "execute_reviewer",
    "probe_route",
)
