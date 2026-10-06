"""Bounded Stage 3 adapter process execution."""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import stage3_types
from stage3_types import (
    AdapterConfig,
    AdapterRun,
    RunnerError,
    require_object,
    strict_json_dumps,
    strict_json_loads,
)

BASE_ENVIRONMENT = {
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}
MANAGED_ENVIRONMENT = {
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "PWD",
    "PYTHONNOUSERSITE",
    "PYTHONDONTWRITEBYTECODE",
}


def _signal_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, sig)


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float = 1.0) -> None:
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.wait()


def _cleanup_descendants(process: subprocess.Popen[bytes]) -> None:
    _signal_group(process, signal.SIGTERM)
    time.sleep(0.05)
    _signal_group(process, signal.SIGKILL)


def _read_bounded(handle: Any, limit: int) -> str:
    handle.seek(0)
    return handle.read(limit).decode("utf-8", errors="replace")


def _explicit_secrets(environment: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environment.items()
        if name not in BASE_ENVIRONMENT
        and name not in MANAGED_ENVIRONMENT
        and value
    }


def _reject_secret_argv(command: list[str], secrets: dict[str, str]) -> None:
    for name, value in secrets.items():
        if any(value in argument for argument in command):
            raise RunnerError(
                f"adapter command contains the value of env_passthrough variable {name}"
            )


def _output_limit_error(
    stdout_file: Any,
    stderr_file: Any,
    limits: dict[str, int],
) -> str | None:
    if os.fstat(stdout_file.fileno()).st_size > limits["stdout_bytes"]:
        return "adapter stdout exceeded configured byte limit"
    if os.fstat(stderr_file.fileno()).st_size > limits["stderr_bytes"]:
        return "adapter stderr exceeded configured byte limit"
    return None


def run_adapter(
    adapter: AdapterConfig,
    request: dict[str, Any],
    cwd: Path,
    adapter_root: Path,
    environment: dict[str, str],
    limits: dict[str, int],
) -> AdapterRun:
    command = stage3_types.resolve_adapter_command(adapter.command, adapter_root)
    _reject_secret_argv(command, _explicit_secrets(environment))

    started = time.monotonic()
    return_code: int | None = None
    timed_out = False
    payload: dict[str, Any] | None = None
    parse_status = "not_attempted"
    error: str | None = None
    process: subprocess.Popen[bytes] | None = None

    with (
        tempfile.TemporaryFile() as stdin_file,
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        stdin_file.write(strict_json_dumps(request).encode("utf-8"))
        stdin_file.seek(0)
        try:
            process = subprocess.Popen(
                command,
                stdin=stdin_file,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=str(cwd),
                env=environment,
                start_new_session=True,
            )
            deadline = started + adapter.timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    error = f"adapter timed out after {adapter.timeout_seconds:g} seconds"
                    _terminate_group(process)
                    break
                error = _output_limit_error(stdout_file, stderr_file, limits)
                if error is not None:
                    _terminate_group(process)
                    break
                time.sleep(0.02)

            if process.poll() is None:
                process.wait()
            return_code = process.returncode

            if not timed_out:
                # The direct process may exit while descendants remain in its
                # session. Always clean the group, including failure/limit paths.
                _cleanup_descendants(process)

            # Recheck after descendant cleanup. A short-lived parent or child can
            # write additional bytes between the polling interval and teardown.
            final_limit_error = _output_limit_error(stdout_file, stderr_file, limits)
            if final_limit_error is not None:
                error = final_limit_error
            elif not timed_out and error is None and return_code != 0:
                error = f"adapter exited with {return_code}"
        except OSError as exc:
            error = f"adapter launch failed: {exc}"
            if process is not None:
                _signal_group(process, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    process.wait(timeout=1)

        stdout = _read_bounded(stdout_file, limits["stdout_bytes"])
        stderr = _read_bounded(stderr_file, limits["stderr_bytes"])

    if error is None and return_code == 0:
        try:
            payload = require_object(
                strict_json_loads(stdout, "adapter output"), "adapter output"
            )
            parse_status = "success"
        except RunnerError as exc:
            parse_status = "failed"
            error = f"adapter returned invalid JSON object: {exc}"

    return AdapterRun(
        command=command,
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        timed_out=timed_out,
        duration_ms=max(0, int(round((time.monotonic() - started) * 1000))),
        json_parse_status=parse_status,
        payload=payload,
        error=error,
    )
