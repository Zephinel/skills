"""Shared types, strict validation, configuration, and atomic persistence."""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ALLOWED_CONFIGURATIONS = {"with_skill", "baseline"}
ALLOWED_EXECUTOR_MODES = {"agent_host", "raw_model_injection"}
ALLOWED_REVIEW_JUDGMENTS = {"pass", "needs_followup"}
_HARDENING_ACTIVE = False


class RunnerError(RuntimeError):
    """A user-visible Stage 3 controller error."""


@dataclass(frozen=True)
class AdapterConfig:
    command: list[str]
    timeout_seconds: float
    mode: str | None = None
    reviewer_type: str | None = None


@dataclass(frozen=True)
class RunnerConfig:
    executor: AdapterConfig
    judge: AdapterConfig
    configurations: list[str]
    fail_fast: bool
    verify_stage2: bool


@dataclass(frozen=True)
class AdapterRun:
    command: list[str]
    stdout: str
    stderr: str
    return_code: int | None
    timed_out: bool
    duration_ms: int
    json_parse_status: str
    payload: dict[str, Any] | None
    error: str | None


def activate_hardening() -> None:
    """Allow the internal controller runtime to load configuration.

    The only supported public Stage 3 entry is ``run-eval-cases.py``. The
    hardened entry activates this gate before entering the internal runner.
    """

    global _HARDENING_ACTIVE
    _HARDENING_ACTIVE = True


def require_hardening() -> None:
    if not _HARDENING_ACTIVE:
        raise RunnerError(
            "internal Stage 3 modules are not standalone entry points; "
            "use scripts/run-eval-cases.py"
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def strict_json_loads(text: str, label: str = "JSON") -> Any:
    try:
        return json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RunnerError(f"{label} is invalid strict JSON: {exc}") from exc


def strict_json_dumps(value: Any, *, indent: int | None = None) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            allow_nan=False,
            separators=None if indent is not None else (",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise RunnerError(f"value cannot be serialized as strict JSON: {exc}") from exc


def load_json(path: Path, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunnerError(f"{label} not found: {path}") from exc
    return strict_json_loads(text, f"{label}: {path}")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunnerError(f"{label} must be a JSON object")
    return value


def require_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise RunnerError(f"{label} must be a non-empty string")
    return value


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RunnerError(f"{label} must be an array of strings")
    return list(value)


def require_nonnegative_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise RunnerError(f"{label} must be a finite non-negative number")
    return float(value)


def canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def lexical_absolute(path: str | Path) -> Path:
    """Return an absolute lexical path without following symlinks."""

    return Path(os.path.abspath(os.path.expanduser(str(path))))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def reject_raw_root_symlink(path: Path, label: str) -> None:
    """Reject a user-supplied root whose final lexical component is a symlink."""

    if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
        raise RunnerError(f"{label} must not be a symlink alias: {path}")


def reject_raw_symlink_components(path: Path, root: Path, label: str) -> None:
    """Reject symlinks in a raw root and existing components below it."""

    reject_raw_root_symlink(root, f"{label} root")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RunnerError(f"{label} escapes its raw root: path={path} root={root}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):
            raise RunnerError(f"{label} must not contain a symlink component: {current}")


def validate_iteration_name(name: str) -> str:
    if not SAFE_NAME_RE.fullmatch(name) or name in {".", ".."} or ".." in name:
        raise RunnerError("--iteration must be one safe folder name")
    return name


def validate_case_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RunnerError(f"eval case id must be a string or integer: {value!r}")
    case_id = str(value)
    if not SAFE_NAME_RE.fullmatch(case_id) or case_id in {".", ".."} or ".." in case_id:
        raise RunnerError(f"unsafe eval case id: {case_id!r}")
    return case_id


def check_no_symlink_components(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.exists() or current.is_symlink():
            if stat.S_ISLNK(current.lstat().st_mode):
                raise RunnerError(f"symlink path component is not allowed: {current}")
        if current == stop:
            return
        if not is_within(current, stop):
            raise RunnerError(f"path escapes containment root: path={path} root={stop}")
        current = current.parent


def ensure_directory(path: Path, containment_root: Path) -> None:
    if not is_within(path, containment_root):
        raise RunnerError(f"directory escapes containment root: {path}")
    check_no_symlink_components(path if path == containment_root else path.parent, containment_root)
    path.mkdir(parents=True, exist_ok=True)
    actual = path.resolve(strict=True)
    if actual != path or path.is_symlink():
        raise RunnerError(f"unsafe directory resolution: expected={path} actual={actual}")


def ensure_regular_single_link(path: Path) -> None:
    if not path.exists():
        return
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RunnerError(f"output must be a single-link regular file: {path}")


def file_sha256(path: Path) -> str:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RunnerError(f"file must be a single-link regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str, containment_root: Path) -> None:
    if not is_within(path, containment_root):
        raise RunnerError(f"output escapes iteration root: {path}")
    ensure_directory(path.parent, containment_root)
    ensure_regular_single_link(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def atomic_write_json(path: Path, value: Any, containment_root: Path) -> None:
    atomic_write_text(path, strict_json_dumps(value, indent=2) + "\n", containment_root)


def _parse_adapter(value: Any, label: str, *, executor: bool) -> AdapterConfig:
    obj = require_object(value, label)
    timeout = obj.get("timeout_seconds", 300 if executor else 180)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        raise RunnerError(f"{label}.timeout_seconds must be a finite positive number")
    command = require_string_list(obj.get("command"), f"{label}.command")
    if not command or any(not item for item in command):
        raise RunnerError(f"{label}.command must contain at least one non-empty element")
    timeout = require_nonnegative_number(
        obj.get("timeout_seconds", 300 if executor else 180),
        f"{label}.timeout_seconds",
    )
    if timeout == 0:
        raise RunnerError(f"{label}.timeout_seconds must be greater than zero")
    mode = None
    reviewer_type = None
    if executor:
        mode = require_string(obj.get("mode", "agent_host"), f"{label}.mode")
        if mode not in ALLOWED_EXECUTOR_MODES:
            raise RunnerError(
                f"{label}.mode must be one of: {', '.join(sorted(ALLOWED_EXECUTOR_MODES))}"
            )
    else:
        reviewer_type = require_string(
            obj.get("reviewer_type", "llm_judge"), f"{label}.reviewer_type"
        )
    return AdapterConfig(command, timeout, mode, reviewer_type)


def load_runner_config(path: Path) -> RunnerConfig:
    require_hardening()
    root = require_object(load_json(path, "runner config"), "runner config")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise RunnerError(f"runner config schema_version must be {SCHEMA_VERSION}")
    executor = _parse_adapter(root.get("executor"), "executor", executor=True)
    judge = _parse_adapter(root.get("judge"), "judge", executor=False)
    execution = require_object(root.get("execution", {}), "execution")
    configurations = require_string_list(
        execution.get("configurations", ["with_skill"]), "execution.configurations"
    )
    if not configurations or any(item not in ALLOWED_CONFIGURATIONS for item in configurations):
        raise RunnerError("execution.configurations must contain with_skill and/or baseline")
    if len(set(configurations)) != len(configurations):
        raise RunnerError("execution.configurations must not contain duplicates")
    fail_fast = execution.get("fail_fast", False)
    verify_stage2 = execution.get("verify_stage2", True)
    if not isinstance(fail_fast, bool) or not isinstance(verify_stage2, bool):
        raise RunnerError("execution.fail_fast and execution.verify_stage2 must be booleans")
    acceptance = require_object(root.get("acceptance", {}), "acceptance")
    if acceptance.get("user_controlled", True) is not True:
        raise RunnerError(
            "acceptance.user_controlled=false is unsupported until an explicit "
            "acceptance policy is implemented"
        )
    return RunnerConfig(executor, judge, configurations, fail_fast, verify_stage2)


def runner_config_json(config: RunnerConfig) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "executor": {
            "command": list(config.executor.command),
            "mode": config.executor.mode,
            "timeout_seconds": config.executor.timeout_seconds,
        },
        "judge": {
            "command": list(config.judge.command),
            "reviewer_type": config.judge.reviewer_type,
            "timeout_seconds": config.judge.timeout_seconds,
        },
        "execution": {
            "configurations": list(config.configurations),
            "fail_fast": config.fail_fast,
            "verify_stage2": config.verify_stage2,
        },
        "acceptance": {"user_controlled": True},
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    root = require_object(load_json(path, "evals/evals.json"), "evals/evals.json")
    evals = root.get("evals")
    if not isinstance(evals, list):
        raise RunnerError("evals/evals.json.evals must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(evals):
        case = require_object(raw, f"evals[{index}]")
        case_id = validate_case_id(case.get("id"))
        if case_id in seen:
            raise RunnerError(f"duplicate eval case id: {case_id}")
        seen.add(case_id)
        require_string(case.get("prompt"), f"eval {case_id}.prompt")
        require_string(
            case.get("expected_output", ""),
            f"eval {case_id}.expected_output",
            allow_empty=True,
        )
        require_string_list(case.get("files", []), f"eval {case_id}.files")
        require_string_list(case.get("input_files", []), f"eval {case_id}.input_files")
        require_string_list(case.get("assertions", []), f"eval {case_id}.assertions")
        require_string_list(case.get("human_review", []), f"eval {case_id}.human_review")
        if "execution_context" in case:
            require_object(case["execution_context"], f"eval {case_id}.execution_context")
        result.append(case)
    return result


def select_cases(cases: list[dict[str, Any]], selector: str) -> list[dict[str, Any]]:
    if selector == "all":
        return cases
    requested = [item.strip() for item in selector.split(",") if item.strip()]
    if not requested:
        raise RunnerError("--cases must be all or a comma-separated list of case ids")
    by_id = {str(case["id"]): case for case in cases}
    missing = [item for item in requested if item not in by_id]
    if missing:
        raise RunnerError(f"unknown eval case ids: {', '.join(missing)}")
    return [by_id[item] for item in requested]


def selected_configurations(config: RunnerConfig, override: str | None) -> list[str]:
    if override is None:
        return config.configurations
    values = [item.strip() for item in override.split(",") if item.strip()]
    if not values or any(item not in ALLOWED_CONFIGURATIONS for item in values):
        raise RunnerError("--configurations must contain with_skill and/or baseline")
    if len(set(values)) != len(values):
        raise RunnerError("--configurations must not contain duplicates")
    return values


def verify_stage2(skill: Path, workspace: Path, iteration: str, baseline_mode: str) -> None:
    runner = skill / "scripts" / "run-evals.sh"
    if not runner.is_file():
        raise RunnerError(f"Stage 2 runner not found: {runner}")
    completed = subprocess.run(
        [
            "bash",
            str(runner),
            "--skill",
            str(skill),
            "--workspace",
            str(workspace),
            "--baseline",
            baseline_mode,
            "--iteration",
            iteration,
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown Stage 2 error"
        raise RunnerError(f"Stage 2 verification failed: {message}")


def resolve_adapter_command(command: list[str], current_skill_root: Path) -> list[str]:
    resolved: list[str] = []
    for index, item in enumerate(command):
        candidate = Path(item)
        rooted = current_skill_root / candidate
        should_resolve = not candidate.is_absolute() and (index > 0 or "/" in item or "\\" in item)
        resolved.append(
            str(rooted.resolve(strict=True)) if should_resolve and rooted.exists() else item
        )
    return resolved
