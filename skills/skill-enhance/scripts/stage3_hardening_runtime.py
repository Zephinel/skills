"""Hardened Stage 3 adapter execution and evidence orchestration."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import stage3_bundle
import stage3_hardening_bundle
from stage3_bounded_process import run_adapter as _run_adapter
from stage3_runtime_context import (
    bounded_snapshot_tree as snapshot_tree,
    bounded_validate_executor_output as validate_executor_output,
    redacting_atomic_write_json as atomic_write_json,
    runtime_load_json as load_json,
    verified_copy_tree,
    verified_stage_input_files,
    execute_with_context,
)
from stage3_evidence_redaction import (
    persist_declared_workspace_content,
    persist_verified_artifacts,
    record_partitioned_workspace_evidence,
)
from stage3_process import normalized_grading
from stage3_types import (
    ALLOWED_REVIEW_JUDGMENTS,
    SCHEMA_VERSION,
    AdapterConfig,
    AdapterRun,
    RunnerConfig,
    RunnerError,
    ensure_directory,
    atomic_write_text,
    file_sha256,
    is_within,
    require_object,
    require_string_list,
    utc_now,
    validate_case_id,
)

BASE_ENVIRONMENT = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


def _build_environment(
    names: list[str],
    cwd: Path,
    runtime_root: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    home = runtime_root / "home"
    temp = runtime_root / "tmp"
    home.mkdir(parents=True)
    temp.mkdir(parents=True)

    environment: dict[str, str] = {}
    for name in BASE_ENVIRONMENT:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    environment.setdefault("PATH", os.defpath)

    secrets: dict[str, str] = {}
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
            if value:
                secrets[name] = value

    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temp),
            "TMP": str(temp),
            "TEMP": str(temp),
            "PWD": str(cwd),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment, secrets


def _redact_text(text: str, secrets: dict[str, str]) -> str:
    redacted = text
    for name, value in sorted(secrets.items(), key=lambda item: len(item[1]), reverse=True):
        if value:
            redacted = redacted.replace(value, f"<redacted:{name}>")
    return redacted


def _redact_value(value: Any, secrets: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            _redact_text(str(key), secrets): _redact_value(child, secrets)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(child, secrets) for child in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _persist_safe_adapter_run(
    prefix: str,
    run: AdapterRun,
    case_output: Path,
    iteration_root: Path,
    secrets: dict[str, str],
) -> None:
    if secrets and run.error is not None:
        run = AdapterRun(
            command=run.command,
            stdout="<omitted: adapter failed while secret environment values were exposed>",
            stderr="<omitted: adapter failed while secret environment values were exposed>",
            return_code=run.return_code,
            timed_out=run.timed_out,
            duration_ms=run.duration_ms,
            json_parse_status=run.json_parse_status,
            payload=None,
            error=run.error,
        )
    command = [_redact_text(item, secrets) for item in run.command]
    stdout = _redact_text(run.stdout, secrets)
    stderr = _redact_text(run.stderr, secrets)
    payload = _redact_value(run.payload, secrets) if run.payload is not None else None

    atomic_write_text(case_output / f"{prefix}.stdout.log", stdout, iteration_root)
    atomic_write_text(case_output / f"{prefix}.stderr.log", stderr, iteration_root)
    atomic_write_json(
        case_output / f"{prefix}-status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "return_code": run.return_code,
            "timed_out": run.timed_out,
            "duration_ms": run.duration_ms,
            "json_parse_status": run.json_parse_status,
            "error": _redact_text(run.error, secrets) if run.error else None,
            "secret_redaction_applied": bool(secrets),
            "redacted_environment_names": sorted(secrets),
        },
        iteration_root,
    )
    if payload is not None:
        atomic_write_json(case_output / f"{prefix}.raw.json", payload, iteration_root)

    stage3_hardening_bundle.verify_frozen_subjects(iteration_root)


def _require_success(
    run: AdapterRun,
    label: str,
    secrets: dict[str, str],
) -> dict[str, Any]:
    if run.error is not None or run.payload is None:
        safe_error = _redact_text(run.error or "missing JSON output", secrets)
        raise RunnerError(f"{label} failed: {safe_error}")
    return require_object(_redact_value(run.payload, secrets), f"{label} output")


def _copy_bundle(source: Path, destination: Path) -> None:
    inventory = verified_copy_tree(source, destination)
    source_inventory = stage3_bundle.tree_inventory(source)
    if inventory["tree_sha256"] != source_inventory["tree_sha256"]:
        raise RunnerError("temporary adapter bundle differs from frozen bundle")


def _map_config(
    adapter: AdapterConfig,
    source_root: Path,
    destination_root: Path,
) -> AdapterConfig:
    command: list[str] = []
    for item in adapter.command:
        path = Path(item)
        if (
            path.is_absolute()
            and path.exists()
            and is_within(path.resolve(strict=True), source_root)
        ):
            mapped = destination_root / path.resolve(strict=True).relative_to(source_root)
            command.append(str(mapped.resolve(strict=True)))
        else:
            command.append(item)
    return AdapterConfig(
        command=command,
        timeout_seconds=adapter.timeout_seconds,
        mode=adapter.mode,
        reviewer_type=adapter.reviewer_type,
    )


def _runtime_manifest(
    role: str,
    persistent_root: Path,
    temporary_root: Path,
    command: list[str],
    environment_keys: list[str],
    passthrough: list[str],
) -> dict[str, Any]:
    inventory = stage3_bundle.tree_inventory(temporary_root)
    portable_command: list[dict[str, Any]] = []
    for item in command:
        path = Path(item)
        record: dict[str, Any] = {"argument": item}
        if path.is_absolute() and is_within(path.resolve(strict=False), temporary_root):
            resolved = path.resolve(strict=True)
            record = {
                "bundle_relative_path": resolved.relative_to(temporary_root).as_posix(),
                "sha256": file_sha256(resolved),
                "size_bytes": resolved.stat().st_size,
            }
        portable_command.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "persistent_bundle_root": str(persistent_root),
        "temporary_bundle_tree_sha256": inventory["tree_sha256"],
        "temporary_bundle_entries": inventory["entries"],
        "portable_command": portable_command,
        "environment_keys": sorted(environment_keys),
        "explicit_env_passthrough": passthrough,
        "environment_values_persisted": False,
    }


def execute(
    *,
    case: dict[str, Any],
    configuration: str,
    selected_subject_root: Path | None,
    inputs_subject_root: Path,
    adapter_root: Path,
    baseline_kind: str,
    case_output: Path,
    iteration_root: Path,
    runner_config: RunnerConfig,
) -> dict[str, Any]:
    stage3_hardening_bundle.verify_frozen_subjects(iteration_root)
    case_id = validate_case_id(case["id"])
    if case_output.exists() or case_output.is_symlink():
        raise RunnerError(f"case output unexpectedly exists in a fresh iteration: {case_output}")
    ensure_directory(case_output, iteration_root)

    policy = require_object(
        load_json(adapter_root / "runtime-policy.json", "adapter runtime policy"),
        "adapter runtime policy",
    )
    limits = require_object(policy.get("limits"), "runtime policy limits")
    frozen_inputs = stage3_bundle.resolve_source_files(
        list(case.get("input_files", [])),
        inputs_subject_root,
        f"eval {case_id} frozen input",
    )

    with tempfile.TemporaryDirectory(prefix="skill-enhance-stage3-") as temp_name:
        execution_root = Path(temp_name).resolve(strict=True)
        input_root = execution_root / "inputs"
        input_root.mkdir()
        staged_inputs = verified_stage_input_files(frozen_inputs, input_root)

        artifacts_root = execution_root / "artifacts"
        artifacts_root.mkdir()
        selected_skill_root: Path | None = None
        execution_cwd = execution_root / "neutral"
        execution_cwd.mkdir()
        skill_files: list[dict[str, str]] = []

        if selected_subject_root is not None:
            selected_skill_root = execution_root / "skill"
            verified_copy_tree(selected_subject_root, selected_skill_root)
            execution_cwd = selected_skill_root
            skill_files = stage3_bundle.resolve_source_files(
                list(case.get("files", [])),
                selected_skill_root,
                f"eval {case_id} staged skill",
            )
        else:
            for parent in (execution_cwd, *execution_cwd.parents):
                if (parent / "SKILL.md").exists():
                    raise RunnerError(
                        f"neutral no-skill workspace can discover a parent skill: {parent}"
                    )

        executor_persistent = adapter_root / "executor"
        executor_temporary = execution_root / "adapter"
        _copy_bundle(executor_persistent, executor_temporary)
        executor_adapter = _map_config(
            runner_config.executor, executor_persistent, executor_temporary
        )
        executor_policy = require_object(policy.get("executor"), "executor policy")
        executor_names = require_string_list(
            executor_policy.get("env_passthrough", []), "executor.env_passthrough"
        )
        executor_environment, executor_secrets = _build_environment(
            executor_names,
            execution_cwd,
            execution_root / "environment",
        )

        before = snapshot_tree(execution_root)
        request = {
            "schema_version": SCHEMA_VERSION,
            "request_type": "execute_eval_case",
            "case_id": case["id"],
            "configuration": configuration,
            "baseline_kind": baseline_kind,
            "executor_mode": runner_config.executor.mode,
            "fresh_context_required": True,
            "selected_skill_root": str(selected_skill_root) if selected_skill_root else None,
            "execution_workspace_root": str(execution_root),
            "execution_working_directory": str(execution_cwd),
            "prompt": case["prompt"],
            "skill_files": skill_files,
            "omitted_skill_files": (
                list(case.get("files", [])) if selected_skill_root is None else []
            ),
            "task_input_files": staged_inputs,
            "execution_context": case.get("execution_context", {}),
            "output_directory": str(artifacts_root),
        }
        atomic_write_json(case_output / "request.json", request, iteration_root)
        executor_run = _run_adapter(
            executor_adapter,
            request,
            execution_cwd,
            executor_temporary,
            executor_environment,
            limits,
        )
        _persist_safe_adapter_run(
            "executor",
            executor_run,
            case_output,
            iteration_root,
            executor_secrets,
        )
        atomic_write_json(
            case_output / "executor-runtime.json",
            _runtime_manifest(
                "executor",
                executor_persistent,
                executor_temporary,
                executor_run.command,
                list(executor_environment),
                executor_names,
            ),
            iteration_root,
        )

        workspace_evidence = record_partitioned_workspace_evidence(
            before=before,
            execution_workspace_root=execution_root,
            case_output=case_output,
            iteration_root=iteration_root,
            limits=limits,
            secret_values=executor_secrets.values(),
        )
        execution = validate_executor_output(
            _require_success(
                executor_run,
                f"executor for eval {case_id}/{configuration}",
                executor_secrets,
            ),
            executor_run.duration_ms,
            executor_mode=runner_config.executor.mode or "agent_host",
            requires_execution_context=bool(case.get("execution_context")),
            expected_cwd=execution_cwd,
            expected_loaded_skill_root=selected_skill_root,
            artifacts_root=artifacts_root,
            workspace_evidence=workspace_evidence,
        )
        workspace_evidence = persist_declared_workspace_content(
            execution_workspace_root=execution_root,
            case_output=case_output,
            iteration_root=iteration_root,
            evidence=workspace_evidence,
            verified_changes=execution["verified_touched_files"],
            secret_values=executor_secrets.values(),
            max_total_bytes=int(limits["persisted_workspace_bytes"]),
        )
        execution["workspace_diff"] = workspace_evidence
        persist_verified_artifacts(
            artifacts_root=artifacts_root,
            destination_root=case_output / "artifacts",
            iteration_root=iteration_root,
            inventory=execution["verified_artifact_inventory"],
            secret_values=executor_secrets.values(),
            max_file_count=int(limits["artifact_file_count"]),
            max_total_bytes=int(limits["artifact_total_bytes"]),
        )
        execution = require_object(
            _redact_value(execution, executor_secrets), "sanitized execution"
        )
        execution.update(
            {
                "schema_version": SCHEMA_VERSION,
                "case_id": case["id"],
                "configuration": configuration,
                "baseline_kind": baseline_kind,
                "executor_mode": runner_config.executor.mode,
                "completed_at_utc": utc_now(),
            }
        )
        atomic_write_json(case_output / "execution.json", execution, iteration_root)

        judge_request = {
            "schema_version": SCHEMA_VERSION,
            "request_type": "grade_eval_case",
            "case": case,
            "configuration": configuration,
            "baseline_kind": baseline_kind,
            "executor_mode": runner_config.executor.mode,
            "execution": execution,
            "grading_contract": {
                "one_result_per_assertion": True,
                "one_result_per_human_review_question": True,
                "require_concrete_evidence": True,
                "allowed_human_review_judgments": sorted(ALLOWED_REVIEW_JUDGMENTS),
                "final_acceptance_is_out_of_scope": True,
            },
        }
        atomic_write_json(case_output / "judge-request.json", judge_request, iteration_root)

        with tempfile.TemporaryDirectory(prefix="skill-enhance-judge-") as judge_name:
            judge_root = Path(judge_name).resolve(strict=True)
            judge_persistent = adapter_root / "judge"
            judge_temporary = judge_root / "adapter"
            _copy_bundle(judge_persistent, judge_temporary)
            judge_adapter = _map_config(
                runner_config.judge, judge_persistent, judge_temporary
            )
            judge_cwd = judge_root / "cwd"
            judge_cwd.mkdir()
            judge_policy = require_object(policy.get("judge"), "judge policy")
            judge_names = require_string_list(
                judge_policy.get("env_passthrough", []), "judge.env_passthrough"
            )
            judge_environment, judge_secrets = _build_environment(
                judge_names,
                judge_cwd,
                judge_root / "environment",
            )
            judge_run = _run_adapter(
                judge_adapter,
                judge_request,
                judge_cwd,
                judge_temporary,
                judge_environment,
                limits,
            )
            judge_runtime = _runtime_manifest(
                "judge",
                judge_persistent,
                judge_temporary,
                judge_run.command,
                list(judge_environment),
                judge_names,
            )

        _persist_safe_adapter_run(
            "judge",
            judge_run,
            case_output,
            iteration_root,
            judge_secrets,
        )
        atomic_write_json(
            case_output / "judge-runtime.json",
            judge_runtime,
            iteration_root,
        )
        grading = normalized_grading(
            case,
            _require_success(
                judge_run,
                f"judge for eval {case_id}/{configuration}",
                judge_secrets,
            ),
            runner_config.judge.reviewer_type or "llm_judge",
        )
        grading = require_object(
            _redact_value(grading, judge_secrets), "sanitized grading"
        )
        grading.update(
            {
                "configuration": configuration,
                "executor_mode": runner_config.executor.mode,
            }
        )
        atomic_write_json(case_output / "grading.json", grading, iteration_root)
        stage3_hardening_bundle.verify_frozen_subjects(iteration_root)
        return {
            "case_id": case["id"],
            "configuration": configuration,
            "status": "completed",
            "output_directory": str(case_output),
            "timing": execution["timing"],
            "grading": grading,
        }


def execute_one(**kwargs: Any) -> dict[str, Any]:
    """Execute one case under its verified policy and evidence context."""
    return execute_with_context(execute, **kwargs)
