#!/usr/bin/env bash
set -euo pipefail

python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

RUNNER_VERSION = "8"
BASELINE_POLICY = "immutable-explicit-freeze-no-symlinks"
SKIP_DIR_NAMES = {".git", "__MACOSX", "__pycache__"}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"Error: {message}")


def canonical(raw: str | Path) -> Path:
    return Path(raw).expanduser().resolve(strict=False)


def lexical_absolute(raw: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(raw))))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def reject_raw_root_symlink(path: Path, label: str) -> None:
    if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
        fail(f"{label} must not be a symlink alias: {path}")


def reject_raw_symlink_components(path: Path, root: Path, label: str) -> None:
    reject_raw_root_symlink(root, f"{label} root")
    try:
        relative = path.relative_to(root)
    except ValueError:
        fail(f"{label} escapes raw workspace: path={path} workspace={root}")
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):
            fail(f"{label} must not contain a symlink component: {current}")


def validate_iteration_name(name: str) -> None:
    if not name or name.startswith("/") or ".." in name or "/" in name or "\\" in name:
        fail("--iteration must be one safe relative folder name")


def validate_tree(root: Path, excluded: Path | None = None, *, source: bool = False) -> None:
    root = root.resolve(strict=True)
    excluded = excluded.resolve(strict=False) if excluded is not None else None
    for current, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(dir_names):
            path = current_path / name
            if name in SKIP_DIR_NAMES or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                fail(
                    "symbolic links and non-directories are not allowed in snapshot "
                    f"baselines: {path}"
                )
            kept.append(name)
        dir_names[:] = kept
        for name in sorted(file_names):
            path = current_path / name
            if name == ".DS_Store" or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            if source and path == root / ".baseline-manifest.json":
                fail("source contains reserved .baseline-manifest.json")
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                fail(
                    "symbolic links, special files, and multi-link files are not allowed "
                    f"in snapshot baselines: {path}"
                )


def digest_tree(
    root: Path,
    manifest: Path | None = None,
    excluded: Path | None = None,
) -> tuple[str, int]:
    root = root.resolve(strict=True)
    manifest = manifest.resolve(strict=False) if manifest is not None else None
    excluded = excluded.resolve(strict=False) if excluded is not None else None
    entries: list[Path] = []
    for current, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(dir_names):
            path = current_path / name
            if name in SKIP_DIR_NAMES or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            kept.append(name)
            entries.append(path)
        dir_names[:] = kept
        for name in sorted(file_names):
            path = current_path / name
            if name == ".DS_Store" or path == manifest or (
                excluded is not None and is_within(path.resolve(strict=False), excluded)
            ):
                continue
            entries.append(path)

    digest = hashlib.sha256()
    count = 0
    for path in sorted(entries, key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            fail(f"symbolic link found in frozen baseline: {rel}")
        mode = stat.S_IMODE(st.st_mode)
        if stat.S_ISDIR(st.st_mode):
            digest.update(f"D\0{rel}\0{mode:o}\0".encode())
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            fail(f"unsafe file found in frozen baseline: {rel}")
        digest.update(f"F\0{rel}\0{mode:o}\0{st.st_size}\0".encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def copy_snapshot(source: Path, destination_raw: Path, workspace: Path) -> Path:
    excluded = workspace if is_within(workspace, source) else None
    if excluded == source:
        fail("Workspace path must not be the same as the skill path")
    validate_tree(source, excluded, source=True)
    source_before = digest_tree(source, excluded=excluded)

    destination_raw.mkdir(parents=True, exist_ok=False)
    destination = destination_raw.resolve(strict=True)
    if destination_raw.is_symlink() or destination_raw.parent.resolve(strict=True) != workspace:
        fail(f"Snapshot destination resolved unsafely: {destination_raw}")

    backend = os.environ.get("SKILL_ENHANCE_COPY_BACKEND", "auto")
    if backend not in {"auto", "rsync", "tar"}:
        fail("SKILL_ENHANCE_COPY_BACKEND must be auto, rsync, or tar")
    excludes = [".git", ".DS_Store", "__MACOSX", "__pycache__"]
    if excluded is not None:
        excludes.append(excluded.relative_to(source).as_posix())

    use_rsync = backend == "rsync" or (backend == "auto" and shutil.which("rsync"))
    if use_rsync:
        if not shutil.which("rsync"):
            fail("rsync copy backend requested but rsync is unavailable")
        command = ["rsync", "-a"]
        for item in excludes:
            command += ["--exclude", item, "--exclude", item + "/"]
        command += [str(source) + "/", str(destination) + "/"]
        completed = subprocess.run(command, check=False)
    else:
        if not shutil.which("tar"):
            fail("tar copy backend requested but tar is unavailable")
        create = ["tar", "-cf", "-"]
        for item in excludes:
            create += ["--exclude", "./" + item]
        create += ["."]
        producer = subprocess.Popen(create, cwd=source, stdout=subprocess.PIPE)
        assert producer.stdout is not None
        consumer = subprocess.run(
            ["tar", "-xf", "-"],
            cwd=destination,
            stdin=producer.stdout,
            check=False,
        )
        producer.stdout.close()
        producer_status = producer.wait()
        completed = (
            consumer
            if producer_status == 0
            else subprocess.CompletedProcess(create, producer_status)
        )
    if completed.returncode != 0:
        shutil.rmtree(destination_raw, ignore_errors=True)
        fail("Failed to create a safe self-contained baseline snapshot")

    validate_tree(destination)
    source_after = digest_tree(source, excluded=excluded)
    destination_digest = digest_tree(destination)
    if source_before != source_after:
        shutil.rmtree(destination_raw, ignore_errors=True)
        fail("Baseline source changed while the snapshot was being created")
    if source_before != destination_digest:
        shutil.rmtree(destination_raw, ignore_errors=True)
        fail("Baseline snapshot does not match the source point-in-time digest")
    return destination


def write_manifest(
    source_raw: Path,
    source: Path,
    workspace_raw: Path,
    snapshot_raw: Path,
    snapshot: Path,
) -> Path:
    manifest = snapshot / ".baseline-manifest.json"
    tree_hash, file_count = digest_tree(snapshot, manifest)
    payload = {
        "runner_version": RUNNER_VERSION,
        "baseline_policy": BASELINE_POLICY,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_skill_raw_path": str(source_raw),
        "source_skill_path": str(source.resolve(strict=True)),
        "workspace_raw_path": str(workspace_raw),
        "snapshot_raw_path": str(snapshot_raw),
        "snapshot_path": str(snapshot.resolve(strict=True)),
        "snapshot_sha256": tree_hash,
        "file_count": file_count,
    }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_manifest(snapshot: Path) -> Path:
    manifest = snapshot / ".baseline-manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        fail(f"Baseline manifest not found or unsafe: {manifest}")
    st = manifest.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        fail("baseline manifest must be a single-link regular file")
    try:
        data = json.loads(
            manifest.read_text(encoding="utf-8"),
            parse_constant=lambda value: fail(f"non-finite JSON number in manifest: {value}"),
        )
    except json.JSONDecodeError as exc:
        fail(f"invalid baseline manifest: {exc}")
    if data.get("baseline_policy") != BASELINE_POLICY:
        fail("unsupported or unsafe baseline policy in manifest")
    if data.get("snapshot_path") != str(snapshot.resolve(strict=True)):
        fail("baseline manifest snapshot_path does not match the selected baseline")
    actual, count = digest_tree(snapshot, manifest)
    if actual != data.get("snapshot_sha256"):
        fail(
            "frozen baseline integrity mismatch: "
            f"expected {data.get('snapshot_sha256')}, got {actual}"
        )
    if count != data.get("file_count"):
        fail(
            "frozen baseline file-count mismatch: "
            f"expected {data.get('file_count')}, got {count}"
        )
    return manifest


def require_eval_package(skill: Path) -> None:
    for relative in (
        "evals/README.md",
        "evals/train-queries.json",
        "evals/validation-queries.json",
        "evals/evals.json",
    ):
        if not (skill / relative).is_file():
            fail(f"Required eval package file not found: {skill / relative}")


def check_clean(source: Path, allow_dirty: bool) -> None:
    if allow_dirty or not shutil.which("git"):
        return
    inside = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inside.returncode != 0:
        return
    dirty = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    if dirty.stdout.strip():
        fail(
            "Baseline source has target-local Git changes. Freeze an unmodified version "
            "or use --allow-dirty-baseline deliberately."
        )


def safe_remove_snapshot(
    snapshot_raw: Path,
    snapshot: Path,
    source: Path,
    workspace: Path,
    workspace_raw: Path,
) -> None:
    reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")
    if snapshot == Path("/") or snapshot == source or not is_within(snapshot, workspace):
        fail(f"Refusing unsafe snapshot destination: {snapshot}")
    if is_within(source, snapshot):
        fail(f"Snapshot destination contains source: snapshot={snapshot} source={source}")
    if snapshot_raw.is_symlink() or not snapshot_raw.is_dir():
        fail(f"Snapshot destination must be a non-symlink directory: {snapshot_raw}")
    if (
        snapshot_raw.parent.resolve(strict=True) != workspace
        or snapshot_raw.resolve(strict=True) != snapshot
    ):
        fail(f"Snapshot raw path resolved unexpectedly: raw={snapshot_raw} resolved={snapshot}")
    validate_tree(snapshot)
    shutil.rmtree(snapshot_raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a target-local eval workspace")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--baseline", choices=("none", "snapshot"), default="none")
    parser.add_argument("--iteration", default="iteration-1")
    parser.add_argument("--create-baseline", action="store_true")
    parser.add_argument("--baseline-source")
    parser.add_argument("--reset-baseline", action="store_true")
    parser.add_argument("--allow-dirty-baseline", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    validate_iteration_name(args.iteration)
    skill_raw = lexical_absolute(args.skill)
    workspace_raw = lexical_absolute(args.workspace)
    baseline_source_raw = (
        lexical_absolute(args.baseline_source) if args.baseline_source else None
    )
    reject_raw_root_symlink(skill_raw, "raw skill root")
    reject_raw_root_symlink(workspace_raw, "raw workspace root")
    if baseline_source_raw is not None:
        reject_raw_root_symlink(baseline_source_raw, "raw baseline source")

    snapshot_raw = workspace_raw / "skill-snapshot"
    iteration_raw = workspace_raw / args.iteration
    reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")
    reject_raw_symlink_components(iteration_raw, workspace_raw, "raw iteration path")

    skill = canonical(skill_raw)
    workspace = canonical(workspace_raw)
    snapshot = canonical(snapshot_raw)
    iteration = canonical(iteration_raw)
    if not skill.is_dir() or not (skill / "SKILL.md").is_file():
        fail(f"Missing SKILL.md under: {skill}")
    if workspace == Path("/") or workspace == skill:
        fail("Workspace path must not be filesystem root or the same as the skill path")
    if not is_within(snapshot, workspace) or not is_within(iteration, workspace):
        fail("Snapshot or iteration path escapes workspace")
    if iteration == workspace:
        fail("Iteration path must not equal workspace")
    if is_within(skill, snapshot):
        fail(f"Snapshot path must not equal or contain the skill path: snapshot={snapshot} skill={skill}")
    if is_within(skill, iteration):
        fail(f"Iteration path must not equal or contain the skill path: iteration={iteration} skill={skill}")
    if is_within(snapshot, iteration):
        fail(f"Iteration path must not equal or contain the frozen baseline: iteration={iteration} snapshot={snapshot}")
    if is_within(iteration, snapshot):
        fail(f"Iteration path must not be inside the frozen baseline: iteration={iteration} snapshot={snapshot}")

    if args.create_baseline:
        if args.baseline != "snapshot":
            fail("--create-baseline requires --baseline snapshot")
        source_raw = baseline_source_raw or skill_raw
        source = canonical(source_raw)
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            fail(f"Baseline source is not a skill root: {source}")
        check_clean(source, args.allow_dirty_baseline)
        if (snapshot_raw.exists() or snapshot_raw.is_symlink()) and not args.reset_baseline:
            fail(
                f"Frozen baseline already exists: {snapshot_raw}. Reuse it, or pass "
                "--reset-baseline only when deliberately replacing it before evaluation."
            )
        if args.dry_run:
            print("Action: create immutable baseline")
            print(f"Current skill raw/canonical: {skill_raw} -> {skill}")
            print(f"Baseline source raw/canonical: {source_raw} -> {source}")
            print(f"Workspace raw/canonical: {workspace_raw} -> {workspace}")
            print(f"Snapshot raw/canonical: {snapshot_raw} -> {snapshot}")
            print(f"Reset existing: {int(args.reset_baseline)}")
            print("Symlink policy: reject root aliases and managed child aliases")
            return 0
        workspace_raw.mkdir(parents=True, exist_ok=True)
        if workspace_raw.resolve(strict=True) != workspace:
            fail("Workspace resolved differently after creation")
        reject_raw_root_symlink(workspace_raw, "raw workspace root")
        reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")
        if snapshot_raw.exists() or snapshot_raw.is_symlink():
            safe_remove_snapshot(snapshot_raw, snapshot, source, workspace, workspace_raw)
        snapshot = copy_snapshot(source, snapshot_raw, workspace)
        manifest = write_manifest(
            source_raw, source, workspace_raw, snapshot_raw, snapshot
        )
        verify_manifest(snapshot)
        print("Frozen baseline created:")
        print(f"- Source: {source}")
        print(f"- Snapshot: {snapshot}")
        print(f"- Manifest: {manifest}")
        print("- Symlink policy: rejected")
        print(
            "\nDo not recreate this snapshot after editing the target. "
            "Normal snapshot runs reuse and verify it."
        )
        return 0

    if args.baseline_source:
        fail("--baseline-source is valid only with --create-baseline")
    if args.reset_baseline:
        fail("--reset-baseline is valid only with --create-baseline")
    if args.allow_dirty_baseline:
        fail("--allow-dirty-baseline is valid only with --create-baseline")
    require_eval_package(skill)
    if args.baseline == "snapshot":
        reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")
        if not snapshot_raw.is_dir() or snapshot_raw.is_symlink():
            fail(
                f"Frozen baseline not found or unsafe: {snapshot_raw}. Create it from "
                "the unmodified skill before editing with --create-baseline."
            )
        snapshot = snapshot_raw.resolve(strict=True)
        verify_manifest(snapshot)
    if args.dry_run:
        print("Action: prepare eval iteration")
        print(f"Skill raw/canonical: {skill_raw} -> {skill}")
        print(f"Workspace raw/canonical: {workspace_raw} -> {workspace}")
        print(f"Iteration raw/canonical: {iteration_raw} -> {iteration}")
        print(f"Baseline mode: {args.baseline}")
        if args.baseline == "snapshot":
            print(f"Snapshot reused and verified: {snapshot}")
        else:
            print("Baseline: none")
        return 0

    reject_raw_symlink_components(iteration_raw, workspace_raw, "raw iteration path")
    iteration_raw.mkdir(parents=True, exist_ok=True)
    if iteration_raw.is_symlink() or iteration_raw.resolve(strict=True) != iteration:
        fail("Iteration resolved differently after creation")
    if args.baseline == "snapshot":
        verify_manifest(snapshot)
    print("Prepared eval workspace:")
    print(f"- Skill: {skill}")
    print(f"- Workspace: {workspace}")
    print(f"- Iteration: {iteration}")
    print(f"- Baseline: {args.baseline}")
    print(
        "\nThis script only performs preflight, immutable-baseline verification, "
        "and workspace scaffolding."
    )
    print(
        "Next, scripts/run-eval-cases.py should run cases from evals/evals.json, "
        "save isolated outputs, grade assertions, and write benchmark results."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
