"""Hardened Stage 3 subject freezing, sanitization, and integrity checks."""
from __future__ import annotations

from stage3_path_policy import sensitive

import contextlib
import shutil
import stat
from pathlib import Path
from typing import Any

import stage3_bundle
import stage3_types
from stage3_types import (
    AdapterConfig,
    RunnerConfig,
    RunnerError,
    atomic_write_json,
    file_sha256,
    is_within,
    load_json,
    require_object,
    require_string_list,
    runner_config_json,
)

MANAGED_ENV = {
    "HOME",
    "PWD",
    "OLDPWD",
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONPATH",
    "PYTHONHOME",
    "GITHUB_WORKSPACE",
    "RUNNER_WORKSPACE",
}
DEFAULT_LIMITS = {
    "stdout_bytes": 10 * 1024 * 1024,
    "stderr_bytes": 10 * 1024 * 1024,
    "artifact_total_bytes": 100 * 1024 * 1024,
    "artifact_file_count": 1000,
    "workspace_file_count": 10000,
    "workspace_total_bytes": 250 * 1024 * 1024,
    "persisted_workspace_bytes": 50 * 1024 * 1024,
}

_POLICY: dict[str, dict[str, Any]] = {}
_FROZEN_EXPECTATIONS: dict[str, dict[str, Any]] = {}


def safe_rel(raw: str, label: str) -> Path:
    path = Path(raw)
    if not raw or path.is_absolute() or raw in {".", ".."} or ".." in path.parts:
        raise RunnerError(f"{label} must be a safe target-relative path: {raw!r}")
    return path


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RunnerError(f"{label} must be a positive integer")
    return value


def _policy(path: Path) -> dict[str, Any]:
    root = require_object(load_json(path, "runner config"), "runner config")
    result: dict[str, Any] = {}
    for role in ("executor", "judge"):
        obj = require_object(root.get(role), role)
        env_names = require_string_list(
            obj.get("env_passthrough", []), f"{role}.env_passthrough"
        )
        if len(env_names) != len(set(env_names)):
            raise RunnerError(f"{role}.env_passthrough contains duplicates")
        for name in env_names:
            if (
                not name
                or not (name[0].isalpha() or name[0] == "_")
                or not all(char.isalnum() or char == "_" for char in name)
            ):
                raise RunnerError(f"invalid environment variable name: {name!r}")
            if name in MANAGED_ENV:
                raise RunnerError(f"{role}.env_passthrough must not override {name}")

        bundle_paths: list[str] = []
        for raw in require_string_list(obj.get("bundle_paths", []), f"{role}.bundle_paths"):
            relative = safe_rel(raw, f"{role}.bundle_paths")
            if not relative.parts or relative.parts[0] != "scripts":
                raise RunnerError(
                    f"{role}.bundle_paths may include only adapter code under scripts/: "
                    f"{relative.as_posix()}"
                )
            if sensitive(relative):
                raise RunnerError(
                    f"{role}.bundle_paths exposes eval-control or reference-answer material: "
                    f"{relative.as_posix()}"
                )
            value = relative.as_posix()
            if value in bundle_paths:
                raise RunnerError(f"duplicate {role}.bundle_paths entry: {value}")
            bundle_paths.append(value)
        result[role] = {
            "env_passthrough": env_names,
            "bundle_paths": bundle_paths,
        }

    raw_limits = require_object(root.get("limits", {}), "limits")
    unknown = set(raw_limits) - set(DEFAULT_LIMITS)
    if unknown:
        raise RunnerError(f"unknown limits fields: {', '.join(sorted(unknown))}")
    result["limits"] = {
        name: _positive_int(raw_limits.get(name, default), f"limits.{name}")
        for name, default in DEFAULT_LIMITS.items()
    }
    return result


def load_config(path: Path) -> RunnerConfig:
    config = stage3_types.load_runner_config(path)
    _POLICY[str(path.resolve(strict=True))] = _policy(path)
    return config


def copy_execution(source: Path, destination: Path) -> tuple[dict[str, Any], list[str]]:
    stage3_bundle.copy_tree(source, destination)
    removed: list[str] = []
    paths = sorted(
        destination.rglob("*"),
        key=lambda item: (len(item.relative_to(destination).parts), item.as_posix()),
        reverse=True,
    )
    for path in paths:
        relative = path.relative_to(destination)
        if path.is_file() and not path.is_symlink() and sensitive(relative):
            path.unlink()
            removed.append(relative.as_posix())
        elif path.is_dir() and not path.is_symlink():
            with contextlib.suppress(StopIteration):
                next(path.iterdir())
                continue
            path.rmdir()
    return stage3_bundle.tree_inventory(destination), sorted(removed)


def reject_case_paths(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        for field in ("files", "input_files"):
            for raw in case.get(field, []):
                relative = safe_rel(raw, f"eval {case['id']} {field}")
                if sensitive(relative):
                    raise RunnerError(
                        f"eval {case['id']} {field} exposes eval-control or "
                        f"reference-answer material: {relative.as_posix()}"
                    )


def _resolve_command_path(item: str, index: int, live_skill_root: Path) -> Path | None:
    candidate = Path(item)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve(strict=True)
    if not candidate.is_absolute() and (index > 0 or "/" in item or "\\" in item):
        rooted = live_skill_root / candidate
        if rooted.exists():
            resolved = rooted.resolve(strict=True)
            if not is_within(resolved, live_skill_root):
                raise RunnerError(
                    f"relative adapter command path escapes the target skill: "
                    f"{item} -> {resolved}"
                )
            return resolved
    if index == 0 and not candidate.is_absolute():
        found = shutil.which(item)
        if found:
            return Path(found).resolve(strict=True)
    return None


def _command_paths(
    command: list[str], live_skill_root: Path
) -> list[Path]:
    """Collect target-local command paths; role-specific secrecy is checked later."""

    result: list[Path] = []
    for index, item in enumerate(command):
        resolved = _resolve_command_path(
            item, index, live_skill_root
        )
        if resolved is None or not is_within(resolved, live_skill_root):
            continue
        relative = resolved.relative_to(live_skill_root)
        if not relative.parts or relative.parts[0] != "scripts":
            raise RunnerError(
                f"target-local adapter commands must live under scripts/: {relative}"
            )
        result.append(relative)
    return result


def _selected_paths(
    role: str,
    command: list[str],
    requested: list[str],
    live_skill_root: Path,
) -> list[Path]:
    """Keep reference-answer material out of executor bundles, not judge bundles."""

    selected: list[Path] = []
    seen: set[str] = set()
    command_paths = [
        path.as_posix()
        for path in _command_paths(command, live_skill_root)
    ]
    for raw in [*requested, *command_paths]:
        relative = safe_rel(raw, f"{role}.bundle_paths")
        if not relative.parts or relative.parts[0] != "scripts":
            raise RunnerError(
                f"{role} adapter bundle may include only scripts/: {relative.as_posix()}"
            )
        if role == "executor" and sensitive(relative):
            raise RunnerError(
                "executor adapter bundle exposes eval-control or reference-answer "
                f"material: {relative.as_posix()}"
            )
        key = relative.as_posix()
        if key not in seen:
            seen.add(key)
            selected.append(relative)
    return selected


def _copy(source_root: Path, destination_root: Path, relative: Path) -> None:
    source = source_root / relative
    if not source.exists() and not source.is_symlink():
        raise RunnerError(f"adapter bundle path not found: {source}")
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    st = source.lstat()
    if stat.S_ISLNK(st.st_mode):
        raise RunnerError(f"adapter bundle path is a symlink: {source}")
    if stat.S_ISDIR(st.st_mode):
        stage3_bundle.copy_tree(source, destination)
    elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
        shutil.copy2(source, destination)
    else:
        raise RunnerError(f"unsafe adapter bundle path: {source}")


def _rewrite_command(
    command: list[str],
    live_skill_root: Path,
    destination_root: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    effective: list[str] = []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(command):
        resolved = _resolve_command_path(item, index, live_skill_root)
        target_local = resolved is not None and is_within(resolved, live_skill_root)
        if target_local:
            assert resolved is not None
            mapped = destination_root / resolved.relative_to(live_skill_root)
            if not mapped.is_file():
                raise RunnerError(f"adapter command file is missing from its role bundle: {mapped}")
            effective_item = str(mapped.resolve(strict=True))
        elif resolved is not None:
            effective_item = str(resolved)
        else:
            effective_item = item

        record: dict[str, Any] = {
            "index": index,
            "original": item,
            "effective": effective_item,
            "target_local": target_local,
        }
        if resolved is not None:
            record["source_resolved_path"] = str(resolved)
            if resolved.is_file() and not resolved.is_symlink():
                record["source_sha256"] = file_sha256(resolved)
        effective_path = Path(effective_item)
        if effective_path.is_file() and not effective_path.is_symlink():
            record["sha256"] = file_sha256(effective_path)
            record["size_bytes"] = effective_path.stat().st_size
        if target_local and "source_sha256" in record:
            record["source_matches_frozen"] = (
                record["source_sha256"] == record.get("sha256")
            )
            if record["source_matches_frozen"] is not True:
                raise RunnerError(f"frozen adapter command does not match its source: {item}")
        if index == 0 and resolved is not None and not target_local:
            record["version_probe"] = "disabled_for_environment_isolation"
        effective.append(effective_item)
        records.append(record)
    for index, (argument, record) in enumerate(zip(command, records, strict=True)):
        if index == 0:
            continue
        candidate = Path(argument)
        if candidate.is_absolute():
            raise RunnerError(
                "adapter command arguments must not reference external absolute paths; "
                "bundle target-local adapter code under scripts/"
            )
        resolved = record.get("source_resolved_path")
        if resolved is not None and record.get("target_local") is not True:
            raise RunnerError(
                "path-bearing adapter command arguments must resolve inside the target skill"
            )
        if ".." in candidate.parts:
            raise RunnerError("adapter command arguments must not contain parent traversal")
    return effective, records


def _bundle(
    role: str,
    source_root: Path,
    live_skill_root: Path,
    command: list[str],
    selected: list[Path],
    forbidden: list[Path],
    destination: Path,
) -> tuple[list[str], dict[str, Any]]:
    destination.mkdir(parents=True)
    for relative in selected:
        _copy(source_root, destination, relative)
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(destination)
        if role == "executor" and sensitive(relative):
            raise RunnerError(
                "executor bundle exposes eval-control or reference-answer material: "
                f"{relative}"
            )
        if any(relative == item or item in relative.parents for item in forbidden):
            raise RunnerError(
                f"{role} bundle exposes the other role's private bundle path: {relative}"
            )
    effective, records = _rewrite_command(
        command, live_skill_root, destination
    )
    inventory = stage3_bundle.tree_inventory(destination)
    return effective, {
        "role": role,
        "bundle_paths": [path.as_posix() for path in selected],
        "frozen_root": str(destination),
        **{key: value for key, value in inventory.items() if key != "root"},
        "command": records,
    }


def _stable_copy(source: Path, destination: Path, expected_sha256: str, label: str) -> None:
    if file_sha256(source) != expected_sha256:
        raise RunnerError(f"{label} changed before freezing: {source}")
    shutil.copy2(source, destination)
    if file_sha256(source) != expected_sha256 or file_sha256(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RunnerError(f"{label} changed while freezing: {source}")


def freeze_runtime(
    *,
    subjects_root: Path,
    execution_current_root: Path,
    source_current_root: Path,
    live_skill_root: Path,
    config_path: Path,
    config_sha256: str,
    initial_config: RunnerConfig,
    iteration_root: Path,
) -> dict[str, Any]:
    policy = _POLICY.get(str(config_path.resolve(strict=True))) or _policy(config_path)
    root = subjects_root / "adapters"
    root.mkdir()
    source_config = root / "runner.source.json"
    source = (
        source_current_root / config_path.relative_to(live_skill_root)
        if is_within(config_path, live_skill_root)
        else config_path
    )
    _stable_copy(source, source_config, config_sha256, "runner config")
    frozen = stage3_types.load_runner_config(source_config)
    if frozen != initial_config:
        raise RunnerError("runner config changed between preflight and adapter freezing")

    executor_selected = _selected_paths(
        "executor", frozen.executor.command, policy["executor"]["bundle_paths"], live_skill_root
    )
    judge_selected = _selected_paths(
        "judge", frozen.judge.command, policy["judge"]["bundle_paths"], live_skill_root
    )
    shared = {path.as_posix() for path in executor_selected} & {
        path.as_posix() for path in judge_selected
    }
    executor_commands = _command_paths(frozen.executor.command, live_skill_root)
    judge_commands = _command_paths(frozen.judge.command, live_skill_root)
    executor_forbidden = [
        path for path in judge_selected if path.as_posix() not in shared
    ]
    executor_forbidden += [
        path for path in judge_commands if path not in executor_commands
    ]
    judge_forbidden = [
        path for path in executor_selected if path.as_posix() not in shared
    ]
    judge_forbidden += [
        path for path in executor_commands if path not in judge_commands
    ]

    executor_command, executor_manifest = _bundle(
        "executor",
        source_current_root,
        live_skill_root,
        frozen.executor.command,
        executor_selected,
        executor_forbidden,
        root / "executor",
    )
    judge_command, judge_manifest = _bundle(
        "judge",
        source_current_root,
        live_skill_root,
        frozen.judge.command,
        judge_selected,
        judge_forbidden,
        root / "judge",
    )
    effective = RunnerConfig(
        AdapterConfig(
            executor_command,
            frozen.executor.timeout_seconds,
            frozen.executor.mode,
            frozen.executor.reviewer_type,
        ),
        AdapterConfig(
            judge_command,
            frozen.judge.timeout_seconds,
            frozen.judge.mode,
            frozen.judge.reviewer_type,
        ),
        list(frozen.configurations),
        frozen.fail_fast,
        frozen.verify_stage2,
    )
    effective_path = root / "runner.effective.json"
    policy_path = root / "runtime-policy.json"
    atomic_write_json(effective_path, runner_config_json(effective), iteration_root)
    atomic_write_json(policy_path, policy, iteration_root)
    manifest = {
        "schema_version": stage3_types.SCHEMA_VERSION,
        "source_config_path": str(config_path),
        "source_config_sha256": config_sha256,
        "frozen_source_config": str(source_config),
        "frozen_source_config_sha256": file_sha256(source_config),
        "effective_config": str(effective_path),
        "effective_config_sha256": file_sha256(effective_path),
        "runtime_policy": str(policy_path),
        "runtime_policy_sha256": file_sha256(policy_path),
        "executor": executor_manifest,
        "judge": judge_manifest,
        "environment_policy": {
            "base_passthrough": [
                "PATH",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "TZ",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            ],
            "managed_names": sorted(MANAGED_ENV),
            "values_persisted": False,
        },
    }
    atomic_write_json(root / "manifest.json", manifest, iteration_root)
    return {
        "root": root,
        "skill_root": root,
        "runner_config": effective,
        "manifest": manifest,
    }


def freeze_subjects(**kwargs: Any) -> dict[str, Any]:
    """Freeze all subjects and capture in-memory expectations for this process."""

    result = stage3_bundle.freeze_run_subjects(**kwargs)
    iteration_root = Path(kwargs["iteration_root"]).resolve(strict=True)
    subjects_root = iteration_root / "subjects"
    manifest_path = subjects_root / "manifest.json"
    adapter_root = Path(result["adapter_root"]).resolve(strict=True)
    expected = {
        "subjects_manifest_sha256": file_sha256(manifest_path),
        "adapters_manifest_sha256": file_sha256(adapter_root / "manifest.json"),
        "roots": {},
        "files": {
            "runner.source.json": file_sha256(adapter_root / "runner.source.json"),
            "runner.effective.json": file_sha256(adapter_root / "runner.effective.json"),
            "runtime-policy.json": file_sha256(adapter_root / "runtime-policy.json"),
        },
    }
    manifest = result["manifest"]
    root_specs = {
        "source_current": result.get("source_current_root"),
        "current": result.get("current_root"),
        "source_baseline": result.get("source_baseline_root"),
        "baseline": result.get("baseline_root"),
        "inputs": result.get("inputs_root"),
    }
    for key, root in root_specs.items():
        if root is None:
            continue
        inventory = stage3_bundle.tree_inventory(Path(root))
        expected["roots"][key] = inventory["tree_sha256"]
        manifest_entry = manifest.get(key)
        if not isinstance(manifest_entry, dict) or manifest_entry.get("tree_sha256") != inventory["tree_sha256"]:
            raise RunnerError(f"frozen {key} subject does not match its manifest")

    adapters_manifest = manifest.get("adapters")
    if not isinstance(adapters_manifest, dict):
        raise RunnerError("subjects manifest is missing adapter provenance")
    for role in ("executor", "judge"):
        role_root = adapter_root / role
        inventory = stage3_bundle.tree_inventory(role_root)
        expected["roots"][f"adapter_{role}"] = inventory["tree_sha256"]
        role_manifest = adapters_manifest.get(role)
        if not isinstance(role_manifest, dict) or role_manifest.get("tree_sha256") != inventory["tree_sha256"]:
            raise RunnerError(f"frozen {role} adapter does not match its manifest")

    _FROZEN_EXPECTATIONS[str(iteration_root)] = expected
    # Config parsing depends on this module's policy constants.
    from stage3_config_snapshot import _parse_policy, _read_stable_text
    from stage3_types import strict_json_loads

    adapter_root = Path(result["adapter_root"]).resolve(strict=True)
    source_config = adapter_root / "runner.source.json"
    runtime_policy = adapter_root / "runtime-policy.json"

    source_root = require_object(
        strict_json_loads(
            _read_stable_text(source_config), "frozen source runner config"
        ),
        "frozen source runner config",
    )
    expected_policy = _parse_policy(source_root)
    actual_policy = require_object(
        strict_json_loads(
            _read_stable_text(runtime_policy), "frozen runtime policy"
        ),
        "frozen runtime policy",
    )
    if actual_policy != expected_policy:
        raise RunnerError(
            "frozen runtime policy does not match the frozen source runner config"
        )
    adapter_root = Path(result["adapter_root"])
    adapters_manifest = result["manifest"].get("adapters")
    if not isinstance(adapters_manifest, dict):
        raise RunnerError("subjects manifest is missing adapter provenance")
    checks = {
        "frozen_source_config_sha256": adapter_root / "runner.source.json",
        "effective_config_sha256": adapter_root / "runner.effective.json",
        "runtime_policy_sha256": adapter_root / "runtime-policy.json",
    }
    for field, path in checks.items():
        expected = adapters_manifest.get(field)
        actual = file_sha256(path)
        if expected != actual:
            raise RunnerError(
                "frozen adapter control file does not match its manifest: "
                f"{path.name}; expected {expected!r}, got {actual!r}"
            )
    return result


def verify_frozen_subjects(iteration_root: Path) -> None:
    """Revalidate every persistent frozen subject before each case/configuration."""

    root = iteration_root.resolve(strict=True)
    expected = _FROZEN_EXPECTATIONS.get(str(root))
    if expected is None:
        raise RunnerError("frozen-subject expectations are unavailable for this Stage 3 run")
    subjects_root = root / "subjects"
    adapter_root = subjects_root / "adapters"
    if file_sha256(subjects_root / "manifest.json") != expected["subjects_manifest_sha256"]:
        raise RunnerError("subjects/manifest.json changed after subject freezing")
    if file_sha256(adapter_root / "manifest.json") != expected["adapters_manifest_sha256"]:
        raise RunnerError("adapter manifest changed after subject freezing")
    for name, digest in expected["files"].items():
        if file_sha256(adapter_root / name) != digest:
            raise RunnerError(f"frozen adapter control file changed after freezing: {name}")

    roots = {
        "source_current": subjects_root / "source-current",
        "current": subjects_root / "current",
        "source_baseline": subjects_root / "source-baseline",
        "baseline": subjects_root / "baseline",
        "inputs": subjects_root / "inputs",
        "adapter_executor": adapter_root / "executor",
        "adapter_judge": adapter_root / "judge",
    }
    for key, digest in expected["roots"].items():
        path = roots[key]
        if not path.is_dir():
            raise RunnerError(f"frozen subject disappeared after freezing: {path}")
        actual = stage3_bundle.tree_inventory(path)["tree_sha256"]
        if actual != digest:
            raise RunnerError(
                f"frozen subject changed after freezing: {key}; expected {digest}, got {actual}"
            )
