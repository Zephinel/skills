"""Run-scoped Stage 3 policy, frozen subjects, redaction, and leak audit."""
from __future__ import annotations

import os
import shutil
import stat
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import eval_bundle
import eval_evidence
import eval_hardening_bundle
import eval_types
from eval_config_snapshot import _read_stable_text
from eval_stable_copy import stable_copy_file, stage_input_files as _stable_stage_inputs
from eval_types import (
    RunnerError,
    require_object,
    require_string_list,
    strict_json_loads,
)


@dataclass(frozen=True)
class RuntimeContext:
    iteration_root: Path
    policy: dict[str, Any]
    secrets: dict[str, str]
    limits: dict[str, int]
    expected_trees: dict[str, str]
    expected_input_files: dict[str, dict[str, Any]]


_CURRENT: ContextVar[RuntimeContext | None] = ContextVar(
    "skill_enhance_stage3_runtime_context", default=None
)


def _load_expected_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    text = _read_stable_text(path)
    if eval_types.file_sha256(path) != expected_sha256:
        raise RunnerError(f"{label} changed while its stable snapshot was loaded")
    return require_object(strict_json_loads(text, label), label)


def _build_context(adapter_root: Path, iteration_root: Path) -> RuntimeContext:
    iteration_root = iteration_root.resolve(strict=True)
    adapter_root = adapter_root.resolve(strict=True)
    eval_hardening_bundle.verify_frozen_subjects(iteration_root)
    expected = eval_hardening_bundle._FROZEN_EXPECTATIONS.get(str(iteration_root))
    if expected is None:
        raise RunnerError("frozen-subject expectations are unavailable for this Stage 3 run")

    subjects_root = iteration_root / "subjects"
    manifest = _load_expected_json(
        subjects_root / "manifest.json",
        expected["subjects_manifest_sha256"],
        "frozen subjects manifest",
    )
    policy = _load_expected_json(
        adapter_root / "runtime-policy.json",
        expected["files"]["runtime-policy.json"],
        "frozen runtime policy",
    )

    secrets: dict[str, str] = {}
    for role in ("executor", "judge"):
        role_policy = require_object(policy.get(role), f"{role} policy")
        for name in require_string_list(
            role_policy.get("env_passthrough", []), f"{role}.env_passthrough"
        ):
            value = os.environ.get(name)
            if value:
                secrets[name] = value

    raw_limits = require_object(policy.get("limits"), "runtime policy limits")
    limits: dict[str, int] = {}
    for name, value in raw_limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RunnerError(f"runtime limit {name} must be a positive integer")
        limits[name] = value

    root_paths = {
        "source_current": subjects_root / "source-current",
        "current": subjects_root / "current",
        "source_baseline": subjects_root / "source-baseline",
        "baseline": subjects_root / "baseline",
        "inputs": subjects_root / "inputs",
        "adapter_executor": adapter_root / "executor",
        "adapter_judge": adapter_root / "judge",
    }
    expected_trees = {
        str(root_paths[name].resolve(strict=True)): digest
        for name, digest in expected["roots"].items()
    }

    inputs_manifest = require_object(manifest.get("inputs"), "frozen inputs manifest")
    input_files: dict[str, dict[str, Any]] = {}
    entries = inputs_manifest.get("entries", [])
    if not isinstance(entries, list):
        raise RunnerError("frozen inputs manifest entries must be an array")
    for raw in entries:
        entry = require_object(raw, "frozen input entry")
        if entry.get("type") != "file":
            continue
        relative = entry.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise RunnerError("frozen input entry has an invalid relative_path")
        input_files[relative] = dict(entry)

    return RuntimeContext(
        iteration_root=iteration_root,
        policy=policy,
        secrets=secrets,
        limits=limits,
        expected_trees=expected_trees,
        expected_input_files=input_files,
    )


def current_context() -> RuntimeContext:
    context = _CURRENT.get()
    if context is None:
        raise RunnerError("Stage 3 runtime context is not active")
    return context


def runtime_load_json(path: Path, label: str) -> Any:
    """Return the verified policy snapshot instead of rereading its path."""

    context = current_context()
    candidate = path.resolve(strict=False)
    policy_path = context.iteration_root / "subjects" / "adapters" / "runtime-policy.json"
    if candidate == policy_path:
        return context.policy
    return eval_types.load_json(path, label)


def redact_text(text: str, secrets: dict[str, str] | None = None) -> str:
    values = current_context().secrets if secrets is None else secrets
    redacted = text
    for name, value in sorted(values.items(), key=lambda item: len(item[1]), reverse=True):
        if value:
            redacted = redacted.replace(value, f"<redacted:{name}>")
    return redacted


def redact_value(value: Any, secrets: dict[str, str] | None = None) -> Any:
    values = current_context().secrets if secrets is None else secrets
    if isinstance(value, dict):
        return {
            redact_text(str(key), values): redact_value(child, values)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_value(child, values) for child in value]
    if isinstance(value, str):
        return redact_text(value, values)
    return value


def redacting_atomic_write_json(path: Path, value: Any, containment_root: Path) -> None:
    eval_types.atomic_write_json(path, redact_value(value), containment_root)


def bounded_snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    return eval_evidence.snapshot_tree(root, limits=current_context().limits)


def bounded_validate_executor_output(*args: Any, **kwargs: Any) -> dict[str, Any]:
    kwargs["limits"] = current_context().limits
    return eval_evidence.validate_executor_output(*args, **kwargs)


def verified_copy_tree(
    source: Path,
    destination: Path,
    excluded: Path | None = None,
) -> dict[str, Any]:
    """Copy a frozen subject and compare the copy with its manifest digest."""

    inventory = eval_bundle.copy_tree(source, destination, excluded)
    context = _CURRENT.get()
    if context is None:
        return inventory
    source_key = str(source.resolve(strict=True))
    expected = context.expected_trees.get(source_key)
    if expected is not None and inventory.get("tree_sha256") != expected:
        shutil.rmtree(destination, ignore_errors=True)
        raise RunnerError(
            f"frozen subject changed before case copy: {source}; "
            f"expected {expected}, got {inventory.get('tree_sha256')}"
        )
    return inventory


def verified_stage_input_files(
    source_files: list[dict[str, str]],
    destination_root: Path,
) -> list[dict[str, str]]:
    context = _CURRENT.get()
    if context is None:
        return _stable_stage_inputs(source_files, destination_root)

    destination_root = destination_root.resolve(strict=True)
    staged: list[dict[str, str]] = []
    for item in source_files:
        relative = Path(item["relative_path"])
        expected = context.expected_input_files.get(relative.as_posix())
        if expected is None:
            raise RunnerError(f"frozen input is absent from its manifest: {relative}")
        source = Path(item["absolute_path"])
        destination = destination_root / relative
        stable_copy_file(
            source,
            destination,
            expected_sha256=str(expected["sha256"]),
            expected_size=int(expected["size_bytes"]),
            expected_mode=int(expected["mode"]),
            containment_root=destination_root,
        )
        staged.append(
            {
                "relative_path": relative.as_posix(),
                "absolute_path": str(destination.resolve(strict=True)),
                "size_bytes": int(expected["size_bytes"]),
                "sha256": str(expected["sha256"]),
                "mode": int(expected["mode"]),
            }
        )
    return staged


def _contains_secret_bytes(path: Path, secrets: dict[str, str]) -> bool:
    needles = [value.encode("utf-8") for value in secrets.values() if value]
    if not needles:
        return False
    overlap = max(len(value) for value in needles) - 1
    tail = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return False
            data = tail + chunk
            if any(value in data for value in needles):
                return True
            tail = data[-overlap:] if overlap > 0 else b""


def _remove_unsafe_entry(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def audit_case_output(case_output: Path, secrets: dict[str, str]) -> None:
    """Ensure no exact passthrough secret remains in durable case evidence."""

    if not secrets or not case_output.exists():
        return
    root = case_output.resolve(strict=True)
    offending: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(root).as_posix()
        if any(value and value in relative for value in secrets.values()):
            offending.append(path)
            continue
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISREG(mode) and _contains_secret_bytes(path, secrets):
            offending.append(path)
    if offending:
        relative_names = sorted({path.relative_to(root).as_posix() for path in offending})
        for path in offending:
            _remove_unsafe_entry(path)
        raise RunnerError(
            "durable Stage 3 evidence contained an explicitly passed secret and was removed: "
            + ", ".join(relative_names)
        )


def execute_with_context(
    implementation: Callable[..., dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    iteration_root = Path(kwargs["iteration_root"])
    adapter_root = Path(kwargs["adapter_root"])
    context = _build_context(adapter_root, iteration_root)
    token = _CURRENT.set(context)
    case_output = Path(kwargs["case_output"])
    try:
        result = implementation(**kwargs)
        audit_case_output(case_output, context.secrets)
        return result
    except Exception as exc:
        audit_error: Exception | None = None
        try:
            audit_case_output(case_output, context.secrets)
        except Exception as candidate:
            audit_error = candidate
        message = redact_text(str(audit_error or exc), context.secrets)
        raise RunnerError(message) from exc
    finally:
        _CURRENT.reset(token)
