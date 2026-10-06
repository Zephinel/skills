#!/usr/bin/env python3
"""Safely manage target-local self-improve memory under one lifecycle lock."""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import secrets
import stat
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "timestamp",
    "run_id",
    "goal",
    "actions_taken",
    "outcome",
    "confidence",
    "clarification_needed",
    "user_feedback",
    "failure_pattern",
    "suggested_followup",
    "artifacts",
    "memory_write_status",
}
STRING_FIELDS = {
    "timestamp",
    "run_id",
    "goal",
    "outcome",
    "confidence",
    "user_feedback",
    "failure_pattern",
    "suggested_followup",
    "memory_write_status",
}
LOCK_NAME = ".evidence.lock"
ROLLOVER_MANIFEST_SUFFIX = ".rollover.json"
ROLLOVER_MANIFEST_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manage self-improve evidence, archive rollover, and summary updates "
            "under one stable memory/.evidence.lock."
        )
    )
    parser.add_argument("--skill-root", default=".", help="Target skill root containing SKILL.md")
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser(
        "append", help="Idempotently append one validated written evidence object"
    )
    source = append_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--entry-json", help="Evidence object as one strict JSON string")
    source.add_argument("--entry-file", help="File containing one strict JSON object")

    rollover_parser = subparsers.add_parser(
        "rollover",
        help="Archive the active evidence window and create an empty active file",
    )
    rollover_parser.add_argument("--archive-name", required=True)
    rollover_parser.add_argument(
        "--rollover-id",
        required=True,
        help="Stable logical operation ID reused for every retry",
    )

    summary_parser = subparsers.add_parser(
        "update-summary", help="Atomically replace memory/summary.md"
    )
    summary_source = summary_parser.add_mutually_exclusive_group(required=True)
    summary_source.add_argument("--summary-text", help="Complete Markdown summary")
    summary_source.add_argument("--summary-file", help="File containing the complete summary")
    return parser.parse_args()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def strict_loads(raw: str, label: str) -> Any:
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid strict JSON: {exc}") from exc


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not strict JSON: {exc}") from exc


def _validate_timestamp(value: str, label: str) -> None:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone: {value!r}")


def validate_entry(entry: Any, label: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"{label} must be one JSON object")
    missing = REQUIRED_FIELDS - set(entry)
    extra = set(entry) - REQUIRED_FIELDS
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{label} has unsupported fields: {', '.join(sorted(extra))}")

    for field in STRING_FIELDS:
        value = entry[field]
        if not isinstance(value, str):
            raise ValueError(f"{label}.{field} must be a string")
    for field in ("timestamp", "run_id", "goal", "outcome", "suggested_followup"):
        if not entry[field].strip():
            raise ValueError(f"{label}.{field} must be non-empty")
    if len(entry["run_id"]) > 256:
        raise ValueError(f"{label}.run_id must be 256 characters or fewer")
    _validate_timestamp(entry["timestamp"], f"{label}.timestamp")

    if entry["confidence"] not in {"high", "medium", "low"}:
        raise ValueError(f"{label}.confidence must be high, medium, or low")
    if entry["memory_write_status"] != "written":
        raise ValueError(f"{label}.memory_write_status must be written")
    if not isinstance(entry["clarification_needed"], bool):
        raise ValueError(f"{label}.clarification_needed must be boolean")
    for field in ("actions_taken", "artifacts"):
        value = entry[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{label}.{field} must be an array of strings")
    return dict(entry)


def load_entry(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.entry_json
    if args.entry_file:
        raw = Path(args.entry_file).read_text(encoding="utf-8")
    entry = strict_loads(raw, "entry")
    if not isinstance(entry, dict):
        raise ValueError("entry must be one JSON object")
    result = dict(entry)
    result.setdefault("user_feedback", "")
    result.setdefault("failure_pattern", "")
    result.setdefault("artifacts", [])
    result.setdefault("memory_write_status", "written")
    return validate_entry(result, "entry")


def load_summary(args: argparse.Namespace) -> str:
    text = args.summary_text
    if args.summary_file:
        text = Path(args.summary_file).read_text(encoding="utf-8")
    assert text is not None
    return text if text.endswith("\n") else text + "\n"


def nofollow_flag() -> int:
    return getattr(os, "O_NOFOLLOW", 0)


def cloexec_flag() -> int:
    return getattr(os, "O_CLOEXEC", 0)


def directory_flag() -> int:
    return getattr(os, "O_DIRECTORY", 0)


def fsync_directory(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}:
            raise


def stat_at(dir_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def verify_regular_stat(
    st: os.stat_result,
    label: str,
    *,
    require_single_link: bool = True,
) -> None:
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"{label} must not be a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if require_single_link and st.st_nlink != 1:
        raise ValueError(f"{label} must have exactly one hard link; found {st.st_nlink}")


def same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def ensure_skill_root(raw_root: str) -> Path:
    raw = Path(os.path.abspath(os.path.expanduser(raw_root)))
    if os.path.lexists(raw) and stat.S_ISLNK(os.lstat(raw).st_mode):
        raise ValueError(f"skill root must not be a symlink alias: {raw}")
    skill_root = raw.resolve(strict=True)
    if not skill_root.is_dir():
        raise ValueError(f"skill root is not a directory: {skill_root}")
    skill_file = skill_root / "SKILL.md"
    if skill_file.is_symlink() or not skill_file.is_file():
        raise ValueError(f"regular SKILL.md not found under skill root: {skill_root}")
    return skill_root


def ensure_safe_memory_dir(skill_root: Path) -> tuple[int, Path]:
    memory_dir = skill_root / "memory"
    try:
        memory_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = os.lstat(memory_dir)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"memory path must be a non-symlink directory: {memory_dir}")
    resolved = memory_dir.resolve(strict=True)
    try:
        resolved.relative_to(skill_root)
    except ValueError as exc:
        raise ValueError(f"memory directory escapes skill root: {resolved}") from exc
    flags = os.O_RDONLY | directory_flag() | nofollow_flag() | cloexec_flag()
    dir_fd = os.open(memory_dir, flags)
    opened = os.fstat(dir_fd)
    path_st = os.stat(memory_dir, follow_symlinks=False)
    if not stat.S_ISDIR(opened.st_mode) or not same_inode(opened, path_st):
        os.close(dir_fd)
        raise RuntimeError("memory directory changed during open")
    return dir_fd, memory_dir


def open_existing_regular_at(
    dir_fd: int,
    name: str,
    flags: int,
    *,
    require_single_link: bool = True,
) -> int:
    before = stat_at(dir_fd, name)
    if before is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    verify_regular_stat(before, name, require_single_link=require_single_link)
    fd = os.open(name, flags | nofollow_flag() | cloexec_flag(), dir_fd=dir_fd)
    try:
        opened = os.fstat(fd)
        verify_regular_stat(opened, name, require_single_link=require_single_link)
        after = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not same_inode(opened, after):
            raise RuntimeError(f"{name} changed during open")
        return fd
    except BaseException:
        os.close(fd)
        raise


def create_exclusive_regular_at(
    dir_fd: int,
    name: str,
    flags: int,
    mode: int = 0o600,
) -> int:
    fd = os.open(
        name,
        flags | os.O_CREAT | os.O_EXCL | nofollow_flag() | cloexec_flag(),
        mode,
        dir_fd=dir_fd,
    )
    try:
        opened = os.fstat(fd)
        verify_regular_stat(opened, name)
        after = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not same_inode(opened, after):
            raise RuntimeError(f"{name} changed during creation")
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        try:
            count = os.write(fd, view[written:])
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError("short write")
        written += count


def open_or_create_lock(memory_fd: int, timeout: float) -> int:
    deadline = time.monotonic() + max(timeout, 0.0)
    last_error: OSError | None = None
    while True:
        try:
            fd = create_exclusive_regular_at(memory_fd, LOCK_NAME, os.O_RDWR)
        except FileExistsError:
            try:
                return open_existing_regular_at(memory_fd, LOCK_NAME, os.O_RDWR)
            except FileNotFoundError as exc:
                last_error = exc
        except FileNotFoundError as exc:
            last_error = exc
        else:
            if os.name == "nt":
                write_all(fd, b"\0")
            os.fsync(fd)
            fsync_directory(memory_fd)
            return fd
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"timed out publishing or opening {LOCK_NAME}: {last_error or 'unknown race'}"
            )
        time.sleep(0.01)


def acquire_lock(fd: int, timeout: float) -> None:
    deadline = time.monotonic() + max(timeout, 0.0)
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for memory lifecycle lock")
                time.sleep(0.05)
    else:
        import fcntl

        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for memory lifecycle lock")
                time.sleep(0.05)


def release_lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def ensure_archive_dir(
    memory_fd: int,
    memory_dir: Path,
    *,
    create: bool,
) -> tuple[int, Path] | None:
    name = "archive"
    before = stat_at(memory_fd, name)
    if before is None:
        if not create:
            return None
        try:
            os.mkdir(name, mode=0o700, dir_fd=memory_fd)
            fsync_directory(memory_fd)
        except FileExistsError:
            pass
        before = stat_at(memory_fd, name)
    assert before is not None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise ValueError("memory/archive must be a non-symlink directory")
    flags = os.O_RDONLY | directory_flag() | nofollow_flag() | cloexec_flag()
    archive_fd = os.open(name, flags, dir_fd=memory_fd)
    opened = os.fstat(archive_fd)
    after = os.stat(name, dir_fd=memory_fd, follow_symlinks=False)
    if not stat.S_ISDIR(opened.st_mode) or not same_inode(opened, after):
        os.close(archive_fd)
        raise RuntimeError("memory/archive changed during open")
    return archive_fd, memory_dir / name


def read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def read_regular_bytes(dir_fd: int, name: str) -> bytes:
    fd = open_existing_regular_at(dir_fd, name, os.O_RDONLY)
    try:
        return read_all(fd)
    finally:
        os.close(fd)


def parse_records(raw: bytes, label: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{label} is not valid UTF-8: {exc}") from exc
    if not text.endswith("\n"):
        raise RuntimeError(f"{label} ends with an incomplete JSONL record")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = strict_loads(line, f"{label} line {line_number}")
        records.append(validate_entry(value, f"{label} line {line_number}"))
    return records


def read_window(
    dir_fd: int,
    name: str,
    display_path: Path,
) -> list[tuple[Path, int, dict[str, Any]]]:
    records = parse_records(read_regular_bytes(dir_fd, name), str(display_path))
    return [
        (display_path, line_number, record)
        for line_number, record in enumerate(records, start=1)
    ]


def scan_all_windows(
    memory_fd: int,
    memory_dir: Path,
) -> list[tuple[Path, int, dict[str, Any]]]:
    windows: list[tuple[Path, int, dict[str, Any]]] = []
    if stat_at(memory_fd, "evidence.jsonl") is not None:
        windows.extend(read_window(memory_fd, "evidence.jsonl", memory_dir / "evidence.jsonl"))
    archive = ensure_archive_dir(memory_fd, memory_dir, create=False)
    if archive is not None:
        archive_fd, archive_dir = archive
        try:
            for name in sorted(os.listdir(archive_fd)):
                if name.endswith(".jsonl"):
                    windows.extend(read_window(archive_fd, name, archive_dir / name))
        finally:
            os.close(archive_fd)
    return windows


def append_entry(
    memory_fd: int,
    memory_dir: Path,
    entry: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        item
        for item in scan_all_windows(memory_fd, memory_dir)
        if item[2]["run_id"] == entry["run_id"]
    ]
    if len(matches) > 1:
        locations = ", ".join(f"{path}:{line}" for path, line, _ in matches)
        raise RuntimeError(f"duplicate existing run_id {entry['run_id']} across {locations}")
    if matches:
        path, line_number, existing = matches[0]
        if canonical_json(existing) != canonical_json(entry):
            raise RuntimeError(
                f"run_id conflict: {entry['run_id']} exists with different content at "
                f"{path}:{line_number}"
            )
        return {
            "path": str(path),
            "line": line_number,
            "timestamp": entry["timestamp"],
            "run_id": entry["run_id"],
            "status": "already_present",
            "verified": True,
        }

    if stat_at(memory_fd, "evidence.jsonl") is None:
        fd = create_exclusive_regular_at(memory_fd, "evidence.jsonl", os.O_RDWR | os.O_APPEND)
        fsync_directory(memory_fd)
    else:
        fd = open_existing_regular_at(memory_fd, "evidence.jsonl", os.O_RDWR | os.O_APPEND)
    try:
        encoded = (canonical_json(entry) + "\n").encode("utf-8")
        original_size = os.fstat(fd).st_size
        try:
            write_all(fd, encoded)
            os.fsync(fd)
        except BaseException:
            os.ftruncate(fd, original_size)
            os.fsync(fd)
            raise
    finally:
        os.close(fd)

    matches = [
        item
        for item in scan_all_windows(memory_fd, memory_dir)
        if item[2]["run_id"] == entry["run_id"]
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one record for run_id {entry['run_id']}, found {len(matches)}"
        )
    path, line_number, stored = matches[0]
    if canonical_json(stored) != canonical_json(entry):
        raise RuntimeError("stored evidence object does not match the requested entry")
    return {
        "path": str(path),
        "line": line_number,
        "timestamp": entry["timestamp"],
        "run_id": entry["run_id"],
        "status": "written",
        "verified": True,
    }


def validate_archive_name(name: str) -> str:
    if not name or name in {".", ".."}:
        raise ValueError("archive name must be a non-empty basename")
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("archive name must not contain path separators")
    if not name.endswith(".jsonl"):
        raise ValueError("archive name must end in .jsonl")
    return name


def validate_rollover_id(value: str) -> str:
    rollover_id = value.strip()
    if not rollover_id:
        raise ValueError("rollover_id must be a stable non-empty string supplied by the caller")
    if len(rollover_id) > 256:
        raise ValueError("rollover_id must be 256 characters or fewer")
    return rollover_id


def rollover_manifest_name(archive_name: str) -> str:
    return archive_name + ROLLOVER_MANIFEST_SUFFIX


def fingerprint_window(raw: bytes, label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = parse_records(raw, label)
    return (
        {
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_bytes": len(raw),
            "source_record_count": len(records),
        },
        records,
    )


def build_rollover_manifest(
    rollover_id: str,
    archive_name: str,
    fingerprint: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ROLLOVER_MANIFEST_VERSION,
        "rollover_id": rollover_id,
        "archive_name": archive_name,
        **fingerprint,
    }


def validate_rollover_manifest(value: Any, manifest_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{manifest_name} is not a JSON object")
    expected = {
        "schema_version",
        "rollover_id",
        "archive_name",
        "source_sha256",
        "source_bytes",
        "source_record_count",
    }
    if set(value) != expected:
        raise RuntimeError(f"{manifest_name} has unexpected fields")
    if value["schema_version"] != ROLLOVER_MANIFEST_VERSION:
        raise RuntimeError(f"unsupported rollover manifest version in {manifest_name}")
    if not isinstance(value["rollover_id"], str) or not value["rollover_id"]:
        raise RuntimeError(f"invalid rollover_id in {manifest_name}")
    if not isinstance(value["archive_name"], str):
        raise RuntimeError(f"invalid archive_name in {manifest_name}")
    if not isinstance(value["source_sha256"], str) or len(value["source_sha256"]) != 64:
        raise RuntimeError(f"invalid source_sha256 in {manifest_name}")
    for key in ("source_bytes", "source_record_count"):
        if isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0:
            raise RuntimeError(f"invalid {key} in {manifest_name}")
    return dict(value)


def read_rollover_manifest(archive_fd: int, manifest_name: str) -> dict[str, Any]:
    raw = read_regular_bytes(archive_fd, manifest_name)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"invalid rollover manifest {manifest_name}: {exc}") from exc
    return validate_rollover_manifest(strict_loads(text, manifest_name), manifest_name)


def write_rollover_manifest(
    archive_fd: int,
    manifest_name: str,
    manifest: dict[str, Any],
) -> None:
    payload = (canonical_json(manifest) + "\n").encode("utf-8")
    fd = create_exclusive_regular_at(archive_fd, manifest_name, os.O_WRONLY)
    completed = False
    try:
        write_all(fd, payload)
        os.fsync(fd)
        completed = True
    finally:
        os.close(fd)
        if not completed:
            try:
                os.unlink(manifest_name, dir_fd=archive_fd)
                fsync_directory(archive_fd)
            except FileNotFoundError:
                pass
    fsync_directory(archive_fd)
    if canonical_json(read_rollover_manifest(archive_fd, manifest_name)) != canonical_json(manifest):
        raise RuntimeError("stored rollover manifest does not match the requested operation")


def scan_rollover_manifests(archive_fd: int) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, read_rollover_manifest(archive_fd, name))
        for name in sorted(os.listdir(archive_fd))
        if name.endswith(ROLLOVER_MANIFEST_SUFFIX)
    ]


def verify_archive_matches_manifest(
    archive_fd: int,
    archive_dir: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    archive_name = manifest["archive_name"]
    fingerprint, records = fingerprint_window(
        read_regular_bytes(archive_fd, archive_name),
        str(archive_dir / archive_name),
    )
    for key in ("source_sha256", "source_bytes", "source_record_count"):
        if fingerprint[key] != manifest[key]:
            raise RuntimeError(
                f"archive {archive_name} does not match its rollover manifest: {key}"
            )
    return records


def create_empty_active(memory_fd: int, memory_dir: Path) -> None:
    if stat_at(memory_fd, "evidence.jsonl") is not None:
        raise RuntimeError("active memory/evidence.jsonl already exists")
    fd = create_exclusive_regular_at(memory_fd, "evidence.jsonl", os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_directory(memory_fd)
    if read_regular_bytes(memory_fd, "evidence.jsonl"):
        raise RuntimeError("new active evidence window is not empty")


def ensure_active_exists(memory_fd: int, memory_dir: Path) -> int:
    if stat_at(memory_fd, "evidence.jsonl") is None:
        create_empty_active(memory_fd, memory_dir)
    return len(parse_records(read_regular_bytes(memory_fd, "evidence.jsonl"), str(memory_dir / "evidence.jsonl")))


def rollover(
    memory_fd: int,
    memory_dir: Path,
    archive_name: str,
    rollover_id: str,
) -> dict[str, Any]:
    archive_name = validate_archive_name(archive_name)
    rollover_id = validate_rollover_id(rollover_id)
    manifest_name = rollover_manifest_name(archive_name)
    archive = ensure_archive_dir(memory_fd, memory_dir, create=True)
    assert archive is not None
    archive_fd, archive_dir = archive
    try:
        manifests = scan_rollover_manifests(archive_fd)
        same_id = [(name, item) for name, item in manifests if item["rollover_id"] == rollover_id]
        if len(same_id) > 1:
            raise RuntimeError(f"rollover_id {rollover_id!r} appears in multiple manifests")
        if same_id and same_id[0][0] != manifest_name:
            raise RuntimeError(
                f"rollover_id {rollover_id!r} is already bound to "
                f"{same_id[0][1]['archive_name']!r}"
            )

        destination_exists = stat_at(archive_fd, archive_name) is not None
        manifest_exists = stat_at(archive_fd, manifest_name) is not None
        active_exists = stat_at(memory_fd, "evidence.jsonl") is not None

        if manifest_exists:
            manifest = read_rollover_manifest(archive_fd, manifest_name)
            if manifest["rollover_id"] != rollover_id:
                raise RuntimeError(
                    f"archive name {archive_name!r} is already bound to another rollover_id"
                )
            if destination_exists:
                records = verify_archive_matches_manifest(archive_fd, archive_dir, manifest)
                active_records = ensure_active_exists(memory_fd, memory_dir)
                return {
                    "rollover_id": rollover_id,
                    "archive_path": str(archive_dir / archive_name),
                    "manifest_path": str(archive_dir / manifest_name),
                    "archived_records": len(records),
                    "active_path": str(memory_dir / "evidence.jsonl"),
                    "active_records": active_records,
                    "status": "already_rolled_over",
                    "verified": True,
                }
            if not active_exists:
                raise RuntimeError(
                    "rollover manifest exists, but both archive and active window are missing"
                )
            active_raw = read_regular_bytes(memory_fd, "evidence.jsonl")
            active_fingerprint, active_records = fingerprint_window(
                active_raw, str(memory_dir / "evidence.jsonl")
            )
            if not active_records:
                raise RuntimeError("prepared rollover manifest exists, but active window is empty")
            for key in ("source_sha256", "source_bytes", "source_record_count"):
                if active_fingerprint[key] != manifest[key]:
                    raise RuntimeError(
                        "active evidence window no longer matches prepared rollover manifest"
                    )
        else:
            if destination_exists:
                raise RuntimeError(
                    f"archive destination {archive_name!r} exists without matching manifest"
                )
            if not active_exists:
                raise RuntimeError("active memory/evidence.jsonl does not exist")
            active_raw = read_regular_bytes(memory_fd, "evidence.jsonl")
            active_fingerprint, active_records = fingerprint_window(
                active_raw, str(memory_dir / "evidence.jsonl")
            )
            if not active_records:
                raise RuntimeError("active evidence window is empty; nothing to archive")
            manifest = build_rollover_manifest(rollover_id, archive_name, active_fingerprint)
            write_rollover_manifest(archive_fd, manifest_name, manifest)

        os.rename(
            "evidence.jsonl",
            archive_name,
            src_dir_fd=memory_fd,
            dst_dir_fd=archive_fd,
        )
        fsync_directory(archive_fd)
        fsync_directory(memory_fd)
        try:
            create_empty_active(memory_fd, memory_dir)
        except BaseException:
            if stat_at(memory_fd, "evidence.jsonl") is None:
                os.rename(
                    archive_name,
                    "evidence.jsonl",
                    src_dir_fd=archive_fd,
                    dst_dir_fd=memory_fd,
                )
                fsync_directory(archive_fd)
                fsync_directory(memory_fd)
            raise

        records = verify_archive_matches_manifest(archive_fd, archive_dir, manifest)
        if ensure_active_exists(memory_fd, memory_dir) != 0:
            raise RuntimeError("new active evidence window is not empty")
        return {
            "rollover_id": rollover_id,
            "archive_path": str(archive_dir / archive_name),
            "manifest_path": str(archive_dir / manifest_name),
            "archived_records": len(records),
            "active_path": str(memory_dir / "evidence.jsonl"),
            "status": "rolled_over",
            "verified": True,
        }
    finally:
        os.close(archive_fd)


def update_summary(memory_fd: int, memory_dir: Path, text: str) -> dict[str, Any]:
    existing = stat_at(memory_fd, "summary.md")
    if existing is not None:
        verify_regular_stat(existing, "memory/summary.md")
    payload = text.encode("utf-8")
    temp_name = f".summary.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    temp_fd = create_exclusive_regular_at(memory_fd, temp_name, os.O_WRONLY)
    replaced = False
    try:
        write_all(temp_fd, payload)
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        os.replace(
            temp_name,
            "summary.md",
            src_dir_fd=memory_fd,
            dst_dir_fd=memory_fd,
        )
        replaced = True
        fsync_directory(memory_fd)
        summary_fd = open_existing_regular_at(memory_fd, "summary.md", os.O_RDONLY)
        try:
            stored = read_all(summary_fd)
            summary_stat = os.fstat(summary_fd)
        finally:
            os.close(summary_fd)
        if stored != payload or not same_inode(temp_stat, summary_stat):
            raise RuntimeError("stored memory/summary.md failed atomic verification")
        return {
            "path": str(memory_dir / "summary.md"),
            "bytes": len(payload),
            "status": "updated",
            "verified": True,
        }
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if not replaced:
            try:
                os.unlink(temp_name, dir_fd=memory_fd)
            except FileNotFoundError:
                pass


def execute(args: argparse.Namespace) -> dict[str, Any]:
    skill_root = ensure_skill_root(args.skill_root)
    memory_fd, memory_dir = ensure_safe_memory_dir(skill_root)
    lock_fd = -1
    locked = False
    try:
        lock_fd = open_or_create_lock(memory_fd, args.lock_timeout)
        acquire_lock(lock_fd, args.lock_timeout)
        locked = True
        if args.command == "append":
            return append_entry(memory_fd, memory_dir, load_entry(args))
        if args.command == "rollover":
            return rollover(memory_fd, memory_dir, args.archive_name, args.rollover_id)
        if args.command == "update-summary":
            return update_summary(memory_fd, memory_dir, load_summary(args))
        raise ValueError(f"unsupported command: {args.command}")
    finally:
        if locked:
            release_lock(lock_fd)
        if lock_fd >= 0:
            os.close(lock_fd)
        os.close(memory_fd)


def main() -> int:
    args = parse_args()
    try:
        result = execute(args)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
