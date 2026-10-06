"""Single-read Stage 3 runner-config parsing and policy registration."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

import eval_hardening_bundle
import eval_types
from eval_types import (
    RunnerConfig,
    RunnerError,
    require_object,
    require_string_list,
    strict_json_loads,
)

ROOT_KEYS = {"schema_version", "executor", "judge", "limits", "execution", "acceptance"}
EXECUTOR_KEYS = {"command", "bundle_paths", "env_passthrough", "mode", "timeout_seconds"}
JUDGE_KEYS = {"command", "bundle_paths", "env_passthrough", "reviewer_type", "timeout_seconds"}
EXECUTION_KEYS = {"configurations", "fail_fast", "verify_stage2"}
ACCEPTANCE_KEYS = {"user_controlled"}
SENSITIVE_OPTION_NAMES = {
    "api-key",
    "api_key",
    "access-token",
    "access_token",
    "auth-token",
    "auth_token",
    "authorization",
    "password",
    "secret",
    "token",
}


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise RunnerError(f"{label} has unsupported fields: {', '.join(sorted(unknown))}")


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _read_stable_text(path: Path) -> str:
    """Read one immutable point-in-time file without following its final path."""

    raw_path = Path(path)
    before = raw_path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise RunnerError(f"managed JSON must be a single-link regular file: {raw_path}")
    resolved = raw_path.resolve(strict=True)
    if resolved != raw_path:
        raise RunnerError(f"managed JSON must not use path aliases: {raw_path} -> {resolved}")

    before_digest = eval_types.file_sha256(raw_path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(raw_path, flags)
    try:
        opened = os.fstat(fd)
        if not _same_inode(before, opened):
            raise RunnerError("managed JSON changed while it was being opened")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after_fd = os.fstat(fd)
        if not _same_inode(opened, after_fd) or after_fd.st_size != len(raw):
            raise RunnerError("managed JSON changed while it was being read")
    finally:
        os.close(fd)

    after = raw_path.lstat()
    after_digest = eval_types.file_sha256(raw_path)
    read_digest = hashlib.sha256(raw).hexdigest()
    if not _same_inode(before, after) or not (
        before_digest == read_digest == after_digest
    ):
        raise RunnerError("managed JSON changed during stable snapshot creation")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunnerError(f"managed JSON is not UTF-8: {raw_path}: {exc}") from exc


def _parse_core(root: dict[str, Any]) -> RunnerConfig:
    _reject_unknown(root, ROOT_KEYS, "runner config")
    if root.get("schema_version") != eval_types.SCHEMA_VERSION:
        raise RunnerError(
            f"runner config schema_version must be {eval_types.SCHEMA_VERSION}"
        )

    executor_obj = require_object(root.get("executor"), "executor")
    judge_obj = require_object(root.get("judge"), "judge")
    execution = require_object(root.get("execution", {}), "execution")
    acceptance = require_object(root.get("acceptance", {}), "acceptance")
    _reject_unknown(executor_obj, EXECUTOR_KEYS, "executor")
    _reject_unknown(judge_obj, JUDGE_KEYS, "judge")
    _reject_unknown(execution, EXECUTION_KEYS, "execution")
    _reject_unknown(acceptance, ACCEPTANCE_KEYS, "acceptance")

    executor = eval_types._parse_adapter(executor_obj, "executor", executor=True)
    judge = eval_types._parse_adapter(judge_obj, "judge", executor=False)
    configurations = require_string_list(
        execution.get("configurations", ["with_skill"]),
        "execution.configurations",
    )
    if not configurations or any(
        item not in eval_types.ALLOWED_CONFIGURATIONS for item in configurations
    ):
        raise RunnerError("execution.configurations must contain with_skill and/or baseline")
    if len(set(configurations)) != len(configurations):
        raise RunnerError("execution.configurations must not contain duplicates")
    fail_fast = execution.get("fail_fast", False)
    verify_stage2 = execution.get("verify_stage2", True)
    if not isinstance(fail_fast, bool) or not isinstance(verify_stage2, bool):
        raise RunnerError("execution.fail_fast and execution.verify_stage2 must be booleans")
    if acceptance.get("user_controlled", True) is not True:
        raise RunnerError(
            "acceptance.user_controlled=false is unsupported until an explicit "
            "acceptance policy is implemented"
        )
    return RunnerConfig(executor, judge, configurations, fail_fast, verify_stage2)


def _parse_policy(root: dict[str, Any]) -> dict[str, Any]:
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
                or not all(character.isalnum() or character == "_" for character in name)
            ):
                raise RunnerError(f"invalid environment variable name: {name!r}")
            if name in eval_hardening_bundle.MANAGED_ENV:
                raise RunnerError(f"{role}.env_passthrough must not override {name}")

        bundle_paths: list[str] = []
        for raw in require_string_list(obj.get("bundle_paths", []), f"{role}.bundle_paths"):
            relative = eval_hardening_bundle.safe_rel(raw, f"{role}.bundle_paths")
            if not relative.parts or relative.parts[0] != "scripts":
                raise RunnerError(
                    f"{role}.bundle_paths may include only adapter code under scripts/: "
                    f"{relative.as_posix()}"
                )
            if role == "executor" and eval_hardening_bundle.sensitive(relative):
                raise RunnerError(
                    "executor.bundle_paths exposes eval-control or reference-answer material: "
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
    unknown = set(raw_limits) - set(eval_hardening_bundle.DEFAULT_LIMITS)
    if unknown:
        raise RunnerError(f"unknown limits fields: {', '.join(sorted(unknown))}")
    result["limits"] = {
        name: eval_hardening_bundle._positive_int(
            raw_limits.get(name, default), f"limits.{name}"
        )
        for name, default in eval_hardening_bundle.DEFAULT_LIMITS.items()
    }
    return result


def _inline_credential_option(command: list[str]) -> str | None:
    for index, argument in enumerate(command):
        lowered = argument.lower()
        if lowered.startswith("bearer "):
            return "Bearer"
        if not argument.startswith("-"):
            continue
        option, separator, inline_value = lowered.lstrip("-").partition("=")
        if option not in SENSITIVE_OPTION_NAMES:
            continue
        if separator and inline_value:
            return option
        if not separator and index + 1 < len(command) and not command[index + 1].startswith("-"):
            return option
    return None


def _reject_inline_credentials(root: dict[str, Any], policy: dict[str, Any]) -> None:
    for role in ("executor", "judge"):
        obj = require_object(root.get(role), role)
        command = require_string_list(obj.get("command"), f"{role}.command")
        sensitive_option = _inline_credential_option(command)
        if sensitive_option is not None:
            raise RunnerError(
                f"{role}.command appears to contain an inline credential for "
                f"{sensitive_option!r}; pass credentials only through env_passthrough"
            )
        for name in policy[role]["env_passthrough"]:
            value = os.environ.get(name)
            if value and any(value in argument for argument in command):
                raise RunnerError(
                    f"{role}.command contains the value of env_passthrough variable {name}; "
                    "pass only the variable name through env_passthrough"
                )


def load_config(path: Path) -> RunnerConfig:
    eval_types.require_hardening()
    raw_path = Path(path)
    text = _read_stable_text(raw_path)
    root = require_object(
        strict_json_loads(text, f"runner config: {raw_path}"), "runner config"
    )
    config = _parse_core(root)
    policy = _parse_policy(root)
    _reject_inline_credentials(root, policy)
    eval_hardening_bundle._POLICY[str(raw_path.resolve(strict=True))] = policy
    return config
