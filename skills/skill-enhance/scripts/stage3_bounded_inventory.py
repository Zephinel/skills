"""Complete no-follow inventories with limits applied to every entry."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from stage3_bundle import _hash_file
from stage3_types import RunnerError


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def bounded_inventory(
    root: Path,
    *,
    max_file_count: int | None,
    max_total_bytes: int | None,
    label: str,
) -> list[dict[str, Any]]:
    """Inventory all entries and use the configured count as an entry limit.

    Counting directories prevents an adapter from bypassing a file-count limit by
    creating a very large empty directory tree.
    """

    raw_root = root
    root_stat = raw_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise RunnerError(f"{label} root must be a non-symlink directory: {root}")
    resolved_root = raw_root.resolve(strict=True)
    if resolved_root != raw_root:
        raise RunnerError(f"{label} root resolved unexpectedly: {raw_root} -> {resolved_root}")

    entries: list[dict[str, Any]] = []
    entry_count = 0
    total_bytes = 0

    def count_entry() -> None:
        nonlocal entry_count
        entry_count += 1
        if max_file_count is not None and entry_count > max_file_count:
            raise RunnerError(
                f"{label} has {entry_count} filesystem entries; limit is {max_file_count}"
            )

    for current, dir_names, file_names in os.walk(
        resolved_root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        dir_names.sort()
        file_names.sort()

        for name in dir_names:
            path = current_path / name
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise RunnerError(f"unsafe directory in {label}: {path}")
            count_entry()
            entries.append(
                {
                    "relative_path": path.relative_to(resolved_root).as_posix(),
                    "type": "directory",
                    "mode": stat.S_IMODE(before.st_mode),
                }
            )

        for name in file_names:
            path = current_path / name
            before = path.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
            ):
                raise RunnerError(f"unsafe file in {label}: {path}")
            count_entry()
            total_bytes += before.st_size
            if max_total_bytes is not None and total_bytes > max_total_bytes:
                raise RunnerError(
                    f"{label} has {total_bytes} bytes; limit is {max_total_bytes}"
                )
            digest = _hash_file(path)
            after = path.lstat()
            if (
                not _same_inode(before, after)
                or after.st_size != before.st_size
                or after.st_nlink != 1
            ):
                raise RunnerError(f"file changed while inventorying {label}: {path}")
            entries.append(
                {
                    "relative_path": path.relative_to(resolved_root).as_posix(),
                    "type": "file",
                    "mode": stat.S_IMODE(after.st_mode),
                    "size_bytes": after.st_size,
                    "sha256": digest,
                }
            )

    entries.sort(key=lambda item: item["relative_path"])
    return entries
