"""Complete bounded workspace diff, artifact verification, and executor validation."""
from __future__ import annotations

from eval_bounded_inventory import bounded_inventory as _bounded_inventory

from pathlib import Path
from typing import Any

from eval_bundle import validate_relative_path
from eval_types import (
    RunnerError,
    canonical,
    require_nonnegative_number,
    require_object,
    require_string,
    require_string_list,
)


def snapshot_tree(
    root: Path,
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    entries = _bounded_inventory(
        root,
        max_file_count=(limits or {}).get("workspace_file_count"),
        max_total_bytes=(limits or {}).get("workspace_total_bytes"),
        label="execution workspace",
    )
    return {entry["relative_path"]: entry for entry in entries}


def workspace_diff(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old is None:
            kind = "created"
        elif new is None:
            kind = "deleted"
        elif old["type"] != new["type"]:
            kind = "type_changed"
        elif old["type"] == "file" and old.get("sha256") != new.get("sha256"):
            kind = "modified"
        elif old.get("mode") != new.get("mode"):
            kind = "metadata_only"
        else:
            continue
        changes.append(
            {
                "relative_path": path,
                "change_type": kind,
                "before": old,
                "after": new,
            }
        )
    return changes


def record_workspace_evidence(
    *,
    before: dict[str, dict[str, Any]],
    execution_workspace_root: Path,
    case_output: Path,
    iteration_root: Path,
) -> dict[str, Any]:
    """Compatibility implementation; the hardened entry replaces this function."""

    raise RunnerError(
        "generic workspace evidence persistence is disabled; use scripts/run-eval-cases.py"
    )


def validate_touched_declarations(
    declared: list[str],
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(declared) != len(set(declared)):
        raise RunnerError("executor touched_files must not contain duplicates")
    changes = {item["relative_path"]: item for item in evidence.get("changes", [])}
    verified: list[dict[str, Any]] = []
    declared_paths: set[str] = set()
    for raw in declared:
        relative = validate_relative_path(raw, "executor touched_files path").as_posix()
        if relative not in changes:
            raise RunnerError(
                "declared touched file was not created, modified, deleted, or "
                f"metadata-changed: {relative}"
            )
        declared_paths.add(relative)
        verified.append(changes[relative])
    undeclared = [
        item
        for item in evidence.get("changes", [])
        if item["relative_path"] not in declared_paths
    ]
    return verified, undeclared


def verify_artifacts(
    declared: list[str],
    artifacts_root: Path,
    *,
    limits: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    if len(declared) != len(set(declared)):
        raise RunnerError("executor artifacts must not contain duplicates")

    entries = _bounded_inventory(
        artifacts_root,
        max_file_count=(limits or {}).get("artifact_file_count"),
        max_total_bytes=(limits or {}).get("artifact_total_bytes"),
        label="artifact tree",
    )
    files = {
        entry["relative_path"]: entry
        for entry in entries
        if entry["type"] == "file"
    }
    declared_paths: set[str] = set()
    for raw in declared:
        relative = validate_relative_path(raw, "executor artifact path").as_posix()
        if relative not in files:
            raise RunnerError(f"declared artifact does not exist as a regular file: {relative}")
        declared_paths.add(relative)

    inventory: list[dict[str, Any]] = []
    for relative, entry in sorted(files.items()):
        item = dict(entry)
        item["declared_by_adapter"] = relative in declared_paths
        inventory.append(item)
    return inventory


def validate_executor_output(
    value: dict[str, Any],
    measured_duration_ms: int,
    *,
    executor_mode: str,
    requires_execution_context: bool,
    expected_cwd: Path,
    expected_loaded_skill_root: Path | None,
    artifacts_root: Path,
    workspace_evidence: dict[str, Any],
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    response = require_string(
        value.get("assistant_response"),
        "executor output.assistant_response",
        allow_empty=True,
    )
    touched = require_string_list(value.get("touched_files", []), "executor output.touched_files")
    artifacts = require_string_list(value.get("artifacts", []), "executor output.artifacts")
    timing = require_object(value.get("timing", {}), "executor output.timing")
    normalized_timing = dict(timing)
    normalized_timing["duration_ms"] = require_nonnegative_number(
        normalized_timing.get("duration_ms", measured_duration_ms),
        "executor output.timing.duration_ms",
    )
    if "total_tokens" in normalized_timing:
        normalized_timing["total_tokens"] = require_nonnegative_number(
            normalized_timing["total_tokens"],
            "executor output.timing.total_tokens",
        )

    metadata = require_object(value.get("metadata", {}), "executor output.metadata")
    if requires_execution_context and metadata.get("execution_context_satisfied") is not True:
        raise RunnerError(
            "executor must confirm metadata.execution_context_satisfied=true for this case"
        )
    if executor_mode == "agent_host":
        if metadata.get("fresh_context_created") is not True:
            raise RunnerError(
                "agent_host executor must confirm metadata.fresh_context_created=true"
            )
        if canonical(
            require_string(
                metadata.get("execution_cwd"), "executor metadata.execution_cwd"
            )
        ) != expected_cwd:
            raise RunnerError("agent_host executor reported an unexpected execution_cwd")
        if expected_loaded_skill_root is None:
            if (
                metadata.get("no_skill_loaded") is not True
                or metadata.get("loaded_skill_root") is not None
            ):
                raise RunnerError(
                    "no-skill agent_host execution must confirm no_skill_loaded=true "
                    "and loaded_skill_root=null"
                )
        else:
            if canonical(
                require_string(
                    metadata.get("loaded_skill_root"),
                    "executor metadata.loaded_skill_root",
                )
            ) != expected_loaded_skill_root:
                raise RunnerError(
                    "agent_host executor loaded a different skill root than requested"
                )
            if metadata.get("no_skill_loaded") is not False:
                raise RunnerError(
                    "skill-loaded agent_host execution must report no_skill_loaded=false"
                )

    verified, undeclared = validate_touched_declarations(touched, workspace_evidence)
    enriched = dict(workspace_evidence)
    enriched["verified_declared_changes"] = verified
    enriched["undeclared_changes"] = undeclared
    return {
        "assistant_response": response,
        "declared_touched_files": touched,
        "declared_artifacts": artifacts,
        "verified_touched_files": verified,
        "undeclared_workspace_changes": undeclared,
        "workspace_diff": enriched,
        "verified_artifact_inventory": verify_artifacts(
            artifacts, artifacts_root, limits=limits
        ),
        "timing": normalized_timing,
        "metadata": metadata,
    }
