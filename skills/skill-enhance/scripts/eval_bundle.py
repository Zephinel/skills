"""Stage 3 bundle ownership, protected roots, frozen subjects, and iteration locking."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any, Iterator

import fcntl

from eval_types import (
    SCHEMA_VERSION,
    RunnerConfig,
    RunnerError,
    atomic_write_json,
    check_no_symlink_components,
    ensure_directory,
    file_sha256,
    is_within,
    lexical_absolute,
    load_json,
    reject_raw_symlink_components,
    require_object,
)

BUNDLE_POLICY = "stage3-one-shot-immutable-bundle-v1"
BUNDLE_MARKER = ".stage3-bundle.json"
RUN_MANIFEST = "run-manifest.json"
MARKER_KIND = "stage3_owned_bundle"
BASELINE_POLICY = "immutable-explicit-freeze-no-symlinks"


def validate_relative_path(raw: str, label: str) -> Path:
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts or raw in {".", ".."}:
        raise RunnerError(f"{label} must be a safe relative path: {raw!r}")
    return path


def _hash_file(path: Path) -> str:
    return file_sha256(path)


def _file_entry(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    st = path.lstat()
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        raise RunnerError(f"symbolic links are not allowed in managed trees: {path}")
    if stat.S_ISDIR(st.st_mode):
        return {"relative_path": relative, "type": "directory", "mode": mode}
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RunnerError(f"managed file must be a single-link regular file: {path}")
    return {
        "relative_path": relative,
        "type": "file",
        "mode": mode,
        "size_bytes": st.st_size,
        "sha256": _hash_file(path),
    }


def tree_inventory(root: Path, excluded: Path | None = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    excluded = excluded.resolve(strict=False) if excluded is not None else None
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    digest = hashlib.sha256()
    for current, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dir_names):
            path = current_path / name
            if name in {".git", "__pycache__"} or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            entries.append(_file_entry(path, root))
            kept_dirs.append(name)
        dir_names[:] = kept_dirs
        for name in sorted(file_names):
            path = current_path / name
            if name == ".DS_Store" or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            entry = _file_entry(path, root)
            entries.append(entry)
            total_bytes += int(entry.get("size_bytes", 0))
    entries.sort(key=lambda item: item["relative_path"])
    for entry in entries:
        digest.update(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\0")
    return {
        "root": str(root),
        "tree_sha256": digest.hexdigest(),
        "entry_count": len(entries),
        "file_count": sum(1 for item in entries if item["type"] == "file"),
        "total_bytes": total_bytes,
        "entries": entries,
    }


def validate_copy_tree(root: Path, excluded: Path | None = None) -> None:
    tree_inventory(root, excluded)


def copy_tree(source: Path, destination: Path, excluded: Path | None = None) -> dict[str, Any]:
    source = source.resolve(strict=True)
    excluded = excluded.resolve(strict=False) if excluded is not None else None
    before = tree_inventory(source, excluded)

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve(strict=True)
        ignored = {name for name in names if name in {".git", "__pycache__", ".DS_Store"}}
        if excluded is not None:
            for name in names:
                if is_within((current / name).resolve(strict=False), excluded):
                    ignored.add(name)
        return ignored

    shutil.copytree(source, destination, symlinks=False, ignore=ignore, copy_function=shutil.copy2)
    after_source = tree_inventory(source, excluded)
    destination_inventory = tree_inventory(destination)
    if before["tree_sha256"] != after_source["tree_sha256"]:
        shutil.rmtree(destination, ignore_errors=True)
        raise RunnerError(f"execution source changed while it was being frozen: {source}")
    if before["tree_sha256"] != destination_inventory["tree_sha256"]:
        shutil.rmtree(destination, ignore_errors=True)
        raise RunnerError(f"frozen tree does not match its source: {source}")
    return destination_inventory


def resolve_source_files(values: list[str], root: Path, label: str) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    for raw in values:
        relative = validate_relative_path(raw, label)
        candidate = root / relative
        check_no_symlink_components(candidate.parent, root)
        if not candidate.exists() and not candidate.is_symlink():
            raise RunnerError(f"{label} not found: {candidate}")
        st = candidate.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RunnerError(f"{label} must be a single-link regular file: {candidate}")
        absolute = candidate.resolve(strict=True)
        if not is_within(absolute, root):
            raise RunnerError(f"{label} escapes its root: {raw}")
        resolved.append({"relative_path": relative.as_posix(), "absolute_path": str(absolute)})
    return resolved


def validate_protected_iteration(iteration_root: Path, skill_root: Path, baseline_root: Path | None) -> None:
    if is_within(skill_root, iteration_root):
        raise RunnerError(
            f"iteration must not equal or contain the skill root: iteration={iteration_root} skill={skill_root}"
        )
    if baseline_root is not None:
        if is_within(baseline_root, iteration_root):
            raise RunnerError(
                f"iteration must not equal or contain the frozen baseline: iteration={iteration_root} baseline={baseline_root}"
            )
        if is_within(iteration_root, baseline_root):
            raise RunnerError(
                f"iteration must not be inside the frozen baseline: iteration={iteration_root} baseline={baseline_root}"
            )


def bundle_identity(skill_root: Path, workspace: Path, iteration: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "iteration_policy": BUNDLE_POLICY,
        "skill_root": str(skill_root),
        "workspace": str(workspace),
        "iteration": iteration,
    }


def _load_owned_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RunnerError(f"{label} is missing or unsafe: {path}")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RunnerError(f"{label} must be a single-link regular file: {path}")
    return require_object(load_json(path, label), label)


def _validate_identity(value: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise RunnerError(
                f"{label} does not prove ownership for this run: {key}={value.get(key)!r}, expected {expected_value!r}"
            )


def validate_bundle_ownership(iteration_root: Path, skill_root: Path, workspace: Path, iteration: str) -> None:
    expected = bundle_identity(skill_root, workspace, iteration)
    marker = _load_owned_json(iteration_root / BUNDLE_MARKER, "Stage 3 bundle marker")
    _validate_identity(marker, expected, "Stage 3 bundle marker")
    if marker.get("marker_kind") != MARKER_KIND:
        raise RunnerError("Stage 3 bundle marker has an invalid marker_kind")
    manifest_path = iteration_root / RUN_MANIFEST
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _load_owned_json(manifest_path, "Stage 3 run manifest")
        _validate_identity(manifest, expected, "Stage 3 run manifest")


def create_bundle_marker(iteration_root: Path, skill_root: Path, workspace: Path, iteration: str) -> dict[str, Any]:
    marker = bundle_identity(skill_root, workspace, iteration)
    marker["marker_kind"] = MARKER_KIND
    atomic_write_json(iteration_root / BUNDLE_MARKER, marker, iteration_root)
    return marker


def _validate_managed_tree(root: Path) -> None:
    for current, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in dir_names:
            path = current_path / name
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise RunnerError(f"unsafe directory in Stage 3 bundle: {path}")
        for name in file_names:
            path = current_path / name
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise RunnerError(f"unsafe file in Stage 3 bundle: {path}")


def clear_iteration(iteration_root: Path) -> None:
    _validate_managed_tree(iteration_root)
    for entry in sorted(iteration_root.iterdir(), key=lambda item: item.name):
        st = entry.lstat()
        if stat.S_ISDIR(st.st_mode):
            shutil.rmtree(entry)
        elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            entry.unlink()
        else:
            raise RunnerError(f"refusing to clear unsafe iteration entry: {entry}")


def preflight_iteration_bundle(*, iteration_root: Path, overwrite: bool, dry_run: bool,
                               skill_root: Path, workspace: Path, iteration: str,
                               baseline_root: Path | None) -> bool:
    validate_protected_iteration(iteration_root, skill_root, baseline_root)
    entries = sorted(iteration_root.iterdir(), key=lambda item: item.name)
    if entries:
        _validate_managed_tree(iteration_root)
    if entries and not overwrite:
        raise RunnerError(
            "iteration already contains evidence; use a new iteration or --overwrite to rebuild the whole bundle"
        )
    if entries and overwrite:
        validate_bundle_ownership(iteration_root, skill_root, workspace, iteration)
        if not dry_run:
            clear_iteration(iteration_root)
    return bool(entries and overwrite)


def _unique_input_paths(cases: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for case in cases:
        for raw in case.get("input_files", []):
            if raw not in seen:
                seen.add(raw)
                result.append(raw)
    return result


def _baseline_digest(root: Path, manifest: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path == manifest:
            continue
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            raise RunnerError(f"symbolic link found in frozen baseline: {rel}")
        mode = stat.S_IMODE(st.st_mode)
        if stat.S_ISDIR(st.st_mode):
            digest.update(f"D\0{rel}\0{mode:o}\0".encode())
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RunnerError(f"unsafe file found in frozen baseline: {rel}")
        digest.update(f"F\0{rel}\0{mode:o}\0{st.st_size}\0".encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def verify_frozen_baseline(snapshot: Path) -> dict[str, Any]:
    manifest = snapshot / ".baseline-manifest.json"
    data = _load_owned_json(manifest, "baseline manifest")
    if data.get("baseline_policy") != BASELINE_POLICY:
        raise RunnerError("unsupported or unsafe baseline policy in manifest")
    if data.get("snapshot_path") != str(snapshot.resolve(strict=True)):
        raise RunnerError("baseline manifest snapshot_path does not match the selected baseline")
    actual, count = _baseline_digest(snapshot, manifest)
    if actual != data.get("snapshot_sha256"):
        raise RunnerError(
            f"frozen baseline integrity mismatch: expected {data.get('snapshot_sha256')}, got {actual}"
        )
    if count != data.get("file_count"):
        raise RunnerError(
            f"frozen baseline file-count mismatch: expected {data.get('file_count')}, got {count}"
        )
    return data


def freeze_run_subjects(*, iteration_root: Path, skill_root: Path,
                        baseline_root: Path | None, cases: list[dict[str, Any]],
                        workspace: Path, config_path: Path, config_sha256: str,
                        runner_config: RunnerConfig) -> dict[str, Any]:
    from eval_hardening_bundle import copy_execution, freeze_runtime, reject_case_paths
    from eval_stable_copy import stage_input_files

    reject_case_paths(cases)
    subjects_root = iteration_root / "subjects"
    ensure_directory(subjects_root, iteration_root)

    source_current_root = subjects_root / "source-current"
    source_current_inventory = copy_tree(
        skill_root,
        source_current_root,
        workspace if is_within(workspace, skill_root) else None,
    )
    execution_current_root = subjects_root / "current"
    execution_current_inventory, current_removed = copy_execution(
        source_current_root, execution_current_root
    )

    source_baseline_root = None
    source_baseline_inventory = None
    execution_baseline_root = None
    execution_baseline_inventory = None
    baseline_removed: list[str] = []
    if baseline_root is not None:
        verify_frozen_baseline(baseline_root)
        source_baseline_root = subjects_root / "source-baseline"
        source_baseline_inventory = copy_tree(baseline_root, source_baseline_root)
        verify_frozen_baseline(baseline_root)
        execution_baseline_root = subjects_root / "baseline"
        execution_baseline_inventory, baseline_removed = copy_execution(
            source_baseline_root, execution_baseline_root
        )

    inputs_root = subjects_root / "inputs"
    inputs_root.mkdir()
    input_sources = resolve_source_files(
        _unique_input_paths(cases), source_current_root, "selected frozen task input file"
    )
    stage_input_files(input_sources, inputs_root)
    inputs_inventory = tree_inventory(inputs_root)

    adapters = freeze_runtime(
        subjects_root=subjects_root,
        execution_current_root=execution_current_root,
        source_current_root=source_current_root,
        live_skill_root=skill_root,
        config_path=config_path,
        config_sha256=config_sha256,
        initial_config=runner_config,
        iteration_root=iteration_root,
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_current": {
            "source_path": str(skill_root),
            "frozen_root": str(source_current_root),
            **{key: value for key, value in source_current_inventory.items() if key != "root"},
        },
        "current": {
            "source_root": str(source_current_root),
            "source_kind": "sanitized_execution_subject",
            "frozen_root": str(execution_current_root),
            "removed_eval_control_files": current_removed,
            **{key: value for key, value in execution_current_inventory.items() if key != "root"},
        },
        "source_baseline": None
        if source_baseline_inventory is None
        else {
            "source_path": str(baseline_root),
            "frozen_root": str(source_baseline_root),
            **{key: value for key, value in source_baseline_inventory.items() if key != "root"},
        },
        "baseline": None
        if execution_baseline_inventory is None
        else {
            "source_root": str(source_baseline_root),
            "source_kind": "sanitized_execution_subject",
            "frozen_root": str(execution_baseline_root),
            "removed_eval_control_files": baseline_removed,
            **{key: value for key, value in execution_baseline_inventory.items() if key != "root"},
        },
        "inputs": {
            "source_root": str(source_current_root),
            "source_kind": "frozen_source_current_subject",
            "frozen_root": str(inputs_root),
            **{key: value for key, value in inputs_inventory.items() if key != "root"},
        },
        "adapters": adapters["manifest"],
    }
    atomic_write_json(subjects_root / "manifest.json", manifest, iteration_root)
    return {
        "source_current_root": source_current_root,
        "current_root": execution_current_root,
        "source_baseline_root": source_baseline_root,
        "baseline_root": execution_baseline_root,
        "inputs_root": inputs_root,
        "adapter_root": adapters["skill_root"],
        "runner_config": adapters["runner_config"],
        "manifest": manifest,
    }


@contextlib.contextmanager
def iteration_lock(*, workspace_raw: Path, workspace: Path, iteration: str,
                   skill_root: Path, baseline_root: Path | None,
                   iteration_root: Path) -> Iterator[None]:
    workspace_lexical = lexical_absolute(workspace_raw)
    lock_dir_raw = workspace_lexical / ".stage3-locks"
    reject_raw_symlink_components(lock_dir_raw, workspace_lexical, "raw Stage 3 lock path")
    lock_dir_raw.mkdir(parents=True, exist_ok=True)
    reject_raw_symlink_components(lock_dir_raw, workspace_lexical, "raw Stage 3 lock path")
    if lock_dir_raw.is_symlink():
        raise RunnerError(f"Stage 3 lock directory must not be a symlink: {lock_dir_raw}")
    lock_dir = lock_dir_raw.resolve(strict=True)
    expected_lock_dir = (workspace / ".stage3-locks").resolve(strict=False)
    if lock_dir != expected_lock_dir or not is_within(lock_dir, workspace):
        raise RunnerError(f"unsafe Stage 3 lock directory: {lock_dir}")
    for label, protected in (
        ("skill root", skill_root),
        ("frozen baseline", baseline_root),
        ("iteration bundle", iteration_root),
    ):
        if protected is not None and is_within(lock_dir, protected):
            raise RunnerError(f"Stage 3 lock directory must not be inside the {label}: {lock_dir}")

    lock_path = lock_dir_raw / f"{iteration}.lock"
    reject_raw_symlink_components(lock_path, workspace_lexical, "raw Stage 3 lock file path")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RunnerError(f"Stage 3 lock must be a single-link regular file: {lock_path}")
        if lock_path.is_symlink() or lock_path.resolve(strict=True).parent != lock_dir:
            raise RunnerError(f"Stage 3 lock file resolved unsafely: {lock_path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerError(f"another Stage 3 controller is already using iteration {iteration}") from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def preflight_case_plan(*, cases: list[dict[str, Any]], configurations: list[str],
                        current_skill_root: Path, baseline_root: Path | None,
                        workspace: Path) -> list[dict[str, Any]]:
    from eval_hardening_bundle import reject_case_paths

    reject_case_paths(cases)
    plan: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["id"])
        inputs = resolve_source_files(
            list(case.get("input_files", [])), current_skill_root, f"eval {case_id} input file"
        )
        for configuration in configurations:
            if configuration == "with_skill":
                selected, baseline_kind = current_skill_root, "not_applicable"
            elif baseline_root is not None:
                selected, baseline_kind = baseline_root, "snapshot"
            else:
                selected, baseline_kind = None, "no_skill"
            skill_files: list[dict[str, str]] = []
            if selected is not None:
                validate_copy_tree(selected, workspace if is_within(workspace, selected) else None)
                skill_files = resolve_source_files(
                    list(case.get("files", [])), selected, f"eval {case_id} skill file for {configuration}"
                )
            plan.append({
                "case_id": case["id"],
                "configuration": configuration,
                "baseline_kind": baseline_kind,
                "skill_file_count": len(skill_files),
                "omitted_skill_files": list(case.get("files", [])) if selected is None else [],
                "input_file_count": len(inputs),
            })
    return plan
