"""No-follow point-in-time stable copies for Stage 3 inputs and evidence."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from stage3_types import RunnerError, ensure_directory, is_within


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        try:
            count = os.write(fd, view[written:])
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError("short write while creating a stable copy")
        written += count


def _unlink_created(destination: Path, created: os.stat_result | None) -> None:
    if created is None:
        return
    try:
        current = destination.lstat()
    except FileNotFoundError:
        return
    if _same_inode(current, created):
        destination.unlink()


def _fingerprint_source(source: Path) -> tuple[int, str, int]:
    """Fingerprint a source through one no-follow descriptor."""

    raw = source
    before = raw.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise RunnerError(f"stable-copy source must be a single-link regular file: {raw}")
    resolved = raw.resolve(strict=True)
    if resolved != raw:
        raise RunnerError(f"stable-copy source must not use path aliases: {raw} -> {resolved}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(raw, flags)
    try:
        opened = os.fstat(fd)
        if not _same_inode(before, opened):
            raise RunnerError(f"stable-copy source changed during open: {raw}")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        after_fd = os.fstat(fd)
        after_path = raw.lstat()
        if (
            not _same_inode(opened, after_fd)
            or not _same_inode(opened, after_path)
            or total != opened.st_size
        ):
            raise RunnerError(f"stable-copy source changed while fingerprinting: {raw}")
        return total, digest.hexdigest(), stat.S_IMODE(opened.st_mode)
    finally:
        os.close(fd)


def stable_copy_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    containment_root: Path,
    expected_mode: int | None = None,
) -> None:
    """Copy one regular file without following source or destination symlinks."""

    source = Path(source)
    containment_root = containment_root.resolve(strict=True)
    if not is_within(destination, containment_root):
        raise RunnerError(f"stable-copy destination escapes containment root: {destination}")
    ensure_directory(destination.parent, containment_root)
    if os.path.lexists(destination):
        raise RunnerError(f"stable-copy destination already exists: {destination}")

    source_before = source.lstat()
    if (
        stat.S_ISLNK(source_before.st_mode)
        or not stat.S_ISREG(source_before.st_mode)
        or source_before.st_nlink != 1
    ):
        raise RunnerError(f"stable-copy source must be a single-link regular file: {source}")
    resolved_source = source.resolve(strict=True)
    if resolved_source != source:
        raise RunnerError(
            f"stable-copy source must not use path aliases: {source} -> {resolved_source}"
        )
    if source_before.st_size != expected_size:
        raise RunnerError(f"stable-copy source size changed before open: {source}")
    source_mode = stat.S_IMODE(source_before.st_mode)
    if expected_mode is not None and source_mode != expected_mode:
        raise RunnerError(
            f"stable-copy source mode changed before open: {source}; "
            f"expected {expected_mode:o}, got {source_mode:o}"
        )

    source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_fd = os.open(source, source_flags)
    destination_fd: int | None = None
    created_stat: os.stat_result | None = None
    try:
        source_opened = os.fstat(source_fd)
        if not _same_inode(source_before, source_opened):
            raise RunnerError(f"stable-copy source changed during open: {source}")
        opened_mode = stat.S_IMODE(source_opened.st_mode)
        if expected_mode is not None and opened_mode != expected_mode:
            raise RunnerError(f"stable-copy source mode changed during open: {source}")
        destination_fd = os.open(destination, destination_flags, opened_mode or 0o600)
        os.fchmod(destination_fd, opened_mode)
        created_stat = os.fstat(destination_fd)
        if not stat.S_ISREG(created_stat.st_mode) or created_stat.st_nlink != 1:
            raise RunnerError(f"stable-copy destination is not a safe regular file: {destination}")

        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise RunnerError(f"stable-copy source grew during read: {source}")
            digest.update(chunk)
            _write_all(destination_fd, chunk)
        if total != expected_size or digest.hexdigest() != expected_sha256:
            raise RunnerError(f"stable-copy source content changed during read: {source}")
        os.fsync(destination_fd)

        source_after_fd = os.fstat(source_fd)
        source_after_path = source.lstat()
        destination_after_fd = os.fstat(destination_fd)
        destination_after_path = destination.lstat()
        if (
            not _same_inode(source_opened, source_after_fd)
            or not _same_inode(source_opened, source_after_path)
            or source_after_fd.st_size != expected_size
            or stat.S_IMODE(source_after_fd.st_mode) != opened_mode
        ):
            raise RunnerError(f"stable-copy source changed before completion: {source}")
        if (
            not _same_inode(created_stat, destination_after_fd)
            or not _same_inode(created_stat, destination_after_path)
            or destination_after_fd.st_size != expected_size
            or stat.S_IMODE(destination_after_fd.st_mode) != opened_mode
        ):
            raise RunnerError(f"stable-copy destination changed before completion: {destination}")
    except BaseException:
        _unlink_created(destination, created_stat)
        raise
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        os.close(source_fd)


def stage_input_files(
    source_files: list[dict[str, str]],
    destination_root: Path,
) -> list[dict[str, str]]:
    destination_root = destination_root.resolve(strict=True)
    staged: list[dict[str, str]] = []
    for item in source_files:
        relative = Path(item["relative_path"])
        source = Path(item["absolute_path"])
        expected_size, expected_sha256, expected_mode = _fingerprint_source(source)
        destination = destination_root / relative
        stable_copy_file(
            source,
            destination,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            expected_mode=expected_mode,
            containment_root=destination_root,
        )
        staged.append(
            {
                "relative_path": relative.as_posix(),
                "absolute_path": str(destination.resolve(strict=True)),
                "size_bytes": expected_size,
                "sha256": expected_sha256,
                "mode": expected_mode,
            }
        )
    return staged
