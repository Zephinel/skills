#!/usr/bin/env python3
"""Target-bound public entry for the self-improve memory runtime.

Install this file as ``scripts/append-memory.py`` and install
``append-memory-template.py`` beside it as ``scripts/append-memory-runtime.py``.
The entry derives the target skill root from its own verified location, so the
caller never has to guess from the shell working directory.
"""
from __future__ import annotations

import importlib.util
import math
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

RUNTIME_NAME = "append-memory-runtime.py"


class EntryError(RuntimeError):
    """A user-visible target-binding failure."""


def _lexical_absolute(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def _regular_single_link(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except FileNotFoundError as exc:
        raise EntryError(f"{label} not found: {path}") from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise EntryError(f"{label} must be a non-symlink single-link regular file: {path}")
    return value


def _reject_final_symlink(path: Path, label: str) -> None:
    if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
        raise EntryError(f"{label} must not be a symlink alias: {path}")


def _installed_paths() -> tuple[Path, Path]:
    entry_raw = _lexical_absolute(__file__)
    _regular_single_link(entry_raw, "memory helper entry")
    entry = entry_raw.resolve(strict=True)
    scripts_dir = entry.parent
    if scripts_dir.name != "scripts":
        raise EntryError(
            "memory helper must be installed as <target-skill>/scripts/append-memory.py"
        )
    skill_root = scripts_dir.parent.resolve(strict=True)
    _regular_single_link(skill_root / "SKILL.md", "installed target SKILL.md")

    runtime = scripts_dir / RUNTIME_NAME
    _regular_single_link(runtime, "memory helper runtime")
    runtime_resolved = runtime.resolve(strict=True)
    if runtime_resolved.parent != scripts_dir:
        raise EntryError("memory helper runtime escaped the installed scripts directory")
    return skill_root, runtime_resolved


def _take_option(arguments: list[str], name: str) -> tuple[list[str], list[str]]:
    remaining: list[str] = []
    values: list[str] = []
    prefix = name + "="
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item.startswith(prefix):
            values.append(item[len(prefix) :])
            index += 1
            continue
        if item == name:
            if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
                raise EntryError(f"{name} requires a value")
            values.append(arguments[index + 1])
            index += 2
            continue
        remaining.append(item)
        index += 1
    if len(values) > 1:
        raise EntryError(f"{name} may be supplied at most once")
    return remaining, values


def _normalize_arguments(arguments: list[str], installed_root: Path) -> list[str]:
    remaining, roots = _take_option(arguments, "--skill-root")
    if roots:
        explicit_raw = _lexical_absolute(roots[0])
        _reject_final_symlink(explicit_raw, "explicit target skill root")
        try:
            explicit = explicit_raw.resolve(strict=True)
        except FileNotFoundError as exc:
            raise EntryError(f"explicit target skill root not found: {explicit_raw}") from exc
        if explicit != installed_root:
            raise EntryError(
                "--skill-root does not match the helper's installed target skill root: "
                f"explicit={explicit} installed={installed_root}. Invoke the helper located "
                "inside the intended target skill; do not probe fallback roots."
            )

    remaining, timeout_values = _take_option(remaining, "--lock-timeout")
    normalized = ["--skill-root", str(installed_root)]
    if timeout_values:
        try:
            timeout = float(timeout_values[0])
        except ValueError as exc:
            raise EntryError("--lock-timeout must be a finite positive number") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise EntryError("--lock-timeout must be a finite positive number")
        normalized.extend(["--lock-timeout", timeout_values[0]])
    normalized.extend(remaining)
    return normalized


def _load_runtime(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_skill_enhance_memory_runtime", path)
    if spec is None or spec.loader is None:
        raise EntryError(f"unable to load memory runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "main", None)):
        raise EntryError(f"memory runtime does not expose main(): {path}")
    return module


def main() -> int:
    try:
        skill_root, runtime_path = _installed_paths()
        normalized = _normalize_arguments(list(sys.argv[1:]), skill_root)
        runtime = _load_runtime(runtime_path)
        sys.argv = [str(Path(__file__).resolve(strict=True)), *normalized]
        return int(runtime.main())
    except (EntryError, OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
