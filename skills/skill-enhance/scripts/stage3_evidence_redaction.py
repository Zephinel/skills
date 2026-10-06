"""Secret-safe, bounded Stage 3 workspace and artifact persistence."""
from __future__ import annotations

from stage3_stable_copy import stable_copy_file as _stable_copy

from pathlib import Path
from typing import Any, Iterable

from stage3_evidence import workspace_diff
from stage3_types import (
    SCHEMA_VERSION,
    RunnerError,
    atomic_write_json,
    ensure_directory,
    is_within,
)

METADATA_ONLY_EVIDENCE = {
    "adapter": "adapter_runtime_file",
    "environment": "environment_runtime_file",
    "inputs": "staged_input_file",
    "artifacts": "artifact_persisted_separately",
    "skill": "awaiting_declared_change_validation",
    "neutral": "awaiting_declared_change_validation",
}


def _secret_list(secret_values: Iterable[str]) -> list[str]:
    return sorted({value for value in secret_values if value}, key=len, reverse=True)


def _redact_text(text: str, secret_values: Iterable[str]) -> str:
    result = text
    for index, value in enumerate(_secret_list(secret_values), start=1):
        result = result.replace(value, f"<redacted-secret-{index}>")
    return result


def _redact_value(value: Any, secret_values: Iterable[str]) -> Any:
    if isinstance(value, dict):
        return {
            _redact_text(str(key), secret_values): _redact_value(child, secret_values)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(child, secret_values) for child in value]
    if isinstance(value, str):
        return _redact_text(value, secret_values)
    return value


def _secret_bytes(secret_values: Iterable[str]) -> list[bytes]:
    return [value.encode("utf-8") for value in _secret_list(secret_values)]


def _text_contains_secret(text: str, secret_values: Iterable[str]) -> bool:
    return any(value in text for value in _secret_list(secret_values))


def _contains_secret(path: Path, secret_values: Iterable[str]) -> bool:
    needles = _secret_bytes(secret_values)
    if not needles:
        return False
    with path.open("rb") as handle:
        overlap = max(len(item) for item in needles) - 1
        tail = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return False
            data = tail + chunk
            if any(needle in data for needle in needles):
                return True
            tail = data[-overlap:] if overlap > 0 else b""


def _write_redacted_evidence(
    path: Path,
    evidence: dict[str, Any],
    iteration_root: Path,
    secret_values: Iterable[str],
) -> None:
    atomic_write_json(path, _redact_value(evidence, secret_values), iteration_root)


def _enforce_workspace_limits(
    after: dict[str, dict[str, Any]],
    limits: dict[str, int],
) -> None:
    files = [entry for entry in after.values() if entry.get("type") == "file"]
    total = sum(int(entry.get("size_bytes", 0)) for entry in files)
    if len(files) > limits["workspace_file_count"]:
        raise RunnerError(
            f"execution workspace has {len(files)} files; limit is "
            f"{limits['workspace_file_count']}"
        )
    if total > limits["workspace_total_bytes"]:
        raise RunnerError(
            f"execution workspace has {total} bytes; limit is "
            f"{limits['workspace_total_bytes']}"
        )


def record_partitioned_workspace_evidence(
    *,
    before: dict[str, dict[str, Any]],
    execution_workspace_root: Path,
    case_output: Path,
    iteration_root: Path,
    limits: dict[str, int] | None = None,
    secret_values: Iterable[str] = (),
) -> dict[str, Any]:
    # Runtime context supplies limits for this case.
    from stage3_runtime_context import bounded_snapshot_tree

    after = bounded_snapshot_tree(execution_workspace_root)
    if limits is not None:
        _enforce_workspace_limits(after, limits)
    changes = workspace_diff(before, after)
    metadata_only: list[str] = []

    for change in changes:
        relative = Path(change["relative_path"])
        top_level = relative.parts[0] if relative.parts else ""
        reason = METADATA_ONLY_EVIDENCE.get(top_level, "unapproved_workspace_root")
        if _text_contains_secret(relative.as_posix(), secret_values):
            reason = "secret_value_detected_in_path"
        change["content_persisted"] = False
        change["redaction_reason"] = reason
        metadata_only.append(relative.as_posix())

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "content_policy": {
            "initial_persistence": "metadata_only",
            "declared_content_roots": ["skill", "neutral"],
            "metadata_only_roots": METADATA_ONLY_EVIDENCE,
            "undeclared_changed_file_content_persisted": False,
            "secret_values_persisted": False,
        },
        "before": list(before.values()),
        "after": list(after.values()),
        "changes": changes,
        "persisted_after_files": [],
        "metadata_only_paths": metadata_only,
    }
    _write_redacted_evidence(
        case_output / "workspace-diff.json",
        evidence,
        iteration_root,
        secret_values,
    )
    return evidence


def persist_declared_workspace_content(
    *,
    execution_workspace_root: Path,
    case_output: Path,
    iteration_root: Path,
    evidence: dict[str, Any],
    verified_changes: list[dict[str, Any]],
    secret_values: Iterable[str],
    max_total_bytes: int,
) -> dict[str, Any]:
    secrets = _secret_list(secret_values)
    changes_by_path = {
        item["relative_path"]: item for item in evidence.get("changes", [])
    }
    persisted: list[str] = []
    total = 0
    evidence_root = case_output / "workspace-changes" / "after"

    for verified in verified_changes:
        relative = Path(verified["relative_path"])
        if not relative.parts or relative.parts[0] not in {"skill", "neutral"}:
            continue
        after_entry = verified.get("after")
        if not isinstance(after_entry, dict) or after_entry.get("type") != "file":
            continue
        size = int(after_entry.get("size_bytes", -1))
        sha256 = after_entry.get("sha256")
        if size < 0 or not isinstance(sha256, str):
            raise RunnerError(f"declared workspace file lacks stable metadata: {relative}")
        total += size
        if total > max_total_bytes:
            raise RunnerError(
                f"declared workspace evidence exceeds {max_total_bytes} bytes"
            )
        source = execution_workspace_root / relative
        change = changes_by_path[relative.as_posix()]
        if _text_contains_secret(relative.as_posix(), secrets):
            change["content_persisted"] = False
            change["redaction_reason"] = "secret_value_detected_in_path"
            continue
        if _contains_secret(source, secrets):
            change["content_persisted"] = False
            change["redaction_reason"] = "secret_value_detected"
            continue
        destination = evidence_root / relative
        _stable_copy(
            source,
            destination,
            expected_sha256=sha256,
            expected_size=size,
            containment_root=iteration_root,
        )
        change["content_persisted"] = True
        change["redaction_reason"] = None
        change["persisted_relative_path"] = str(destination.relative_to(case_output))
        persisted.append(relative.as_posix())

    evidence["persisted_after_files"] = persisted
    evidence["metadata_only_paths"] = [
        item["relative_path"]
        for item in evidence.get("changes", [])
        if item.get("content_persisted") is not True
    ]
    _write_redacted_evidence(
        case_output / "workspace-diff.json",
        evidence,
        iteration_root,
        secrets,
    )
    return evidence


def persist_verified_artifacts(
    *,
    artifacts_root: Path,
    destination_root: Path,
    iteration_root: Path,
    inventory: list[dict[str, Any]],
    secret_values: Iterable[str],
    max_file_count: int,
    max_total_bytes: int,
) -> None:
    secrets = _secret_list(secret_values)
    if len(inventory) > max_file_count:
        raise RunnerError(
            f"artifact count {len(inventory)} exceeds limit {max_file_count}"
        )
    total = sum(int(item.get("size_bytes", 0)) for item in inventory)
    if total > max_total_bytes:
        raise RunnerError(f"artifact bytes {total} exceed limit {max_total_bytes}")
    ensure_directory(destination_root, iteration_root)

    for item in inventory:
        if item.get("declared_by_adapter") is not True:
            continue
        relative = Path(item["relative_path"])
        if _text_contains_secret(relative.as_posix(), secrets):
            raise RunnerError(
                "artifact path contains an explicitly passed secret and was not persisted"
            )
        source = artifacts_root / relative
        absolute = source.resolve(strict=True)
        if not is_within(absolute, artifacts_root):
            raise RunnerError(f"artifact escaped its root before persistence: {relative}")
        if _contains_secret(source, secrets):
            raise RunnerError(
                f"artifact contains an explicitly passed secret and was not persisted: {relative}"
            )
        _stable_copy(
            source,
            destination_root / relative,
            expected_sha256=str(item["sha256"]),
            expected_size=int(item["size_bytes"]),
            containment_root=iteration_root,
        )
