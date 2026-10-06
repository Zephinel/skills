"""Execute Stage 3 Agent Skill evals as one owned, immutable evidence bundle."""
from __future__ import annotations

from stage3_case_policy import load_cases, select_cases
from stage3_config_snapshot import load_config as load_runner_config
from stage3_hardening_bundle import freeze_subjects as freeze_run_subjects
from stage3_hardening_runtime import execute_one

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stage3_types import (
    SCHEMA_VERSION,
    RunnerError,
    atomic_write_json,
    canonical,
    check_no_symlink_components,
    file_sha256,
    is_within,
    lexical_absolute,
    reject_raw_symlink_components,
    selected_configurations,
    utc_now,
    validate_case_id,
    validate_iteration_name,
    verify_stage2,
)
from stage3_bundle import (
    bundle_identity,
    create_bundle_marker,
    iteration_lock,
    preflight_case_plan,
    preflight_iteration_bundle,
    validate_protected_iteration,
    verify_frozen_baseline,
)
from stage3_benchmark import aggregate_verified_benchmark as aggregate_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute Stage 3 eval cases through isolated adapters.")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--iteration", default="iteration-1")
    parser.add_argument("--baseline", choices=("none", "snapshot"), default="none")
    parser.add_argument("--config")
    parser.add_argument("--cases", default="all", help="one-shot case selection for this iteration")
    parser.add_argument("--configurations")
    parser.add_argument("--overwrite", action="store_true", help="rebuild an owned Stage 3 bundle")
    parser.add_argument("--dry-run", action="store_true", help="complete preflight without adapters")
    args = parser.parse_args(argv)
    try:
        iteration_name = validate_iteration_name(args.iteration)
        workspace_raw = lexical_absolute(args.workspace)
        iteration_raw = workspace_raw / iteration_name
        snapshot_raw = workspace_raw / "skill-snapshot"
        reject_raw_symlink_components(iteration_raw, workspace_raw, "raw iteration path")
        if args.baseline == "snapshot":
            reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")

        skill, workspace = canonical(args.skill), canonical(args.workspace)
        iteration_root = canonical(iteration_raw)
        if not skill.is_dir() or not (skill / "SKILL.md").is_file():
            raise RunnerError(f"skill root must exist and contain SKILL.md: {skill}")
        if workspace == Path("/") or workspace == skill or not workspace.is_dir():
            raise RunnerError("workspace must exist, be separate from the skill, and not be filesystem root")
        if not is_within(iteration_root, workspace) or not iteration_root.is_dir():
            raise RunnerError(f"Stage 2 iteration directory not found or escapes workspace: {iteration_root}")
        check_no_symlink_components(iteration_root, workspace)

        config_path = canonical(args.config) if args.config else canonical(skill / "evals" / "runner.json")
        config_sha256 = file_sha256(config_path)
        config = load_runner_config(config_path)
        if file_sha256(config_path) != config_sha256:
            raise RunnerError("runner config changed while it was being loaded")
        cases = select_cases(load_cases(skill / "evals" / "evals.json"), args.cases)
        configurations = selected_configurations(config, args.configurations)
        baseline_root = canonical(snapshot_raw) if args.baseline == "snapshot" else None
        if baseline_root is not None and not baseline_root.is_dir():
            raise RunnerError(f"frozen baseline not found: {baseline_root}")
        validate_protected_iteration(iteration_root, skill, baseline_root)
        if config.verify_stage2:
            verify_stage2(skill, workspace, iteration_name, args.baseline)
        case_plan = preflight_case_plan(
            cases=cases,
            configurations=configurations,
            current_skill_root=skill,
            baseline_root=baseline_root,
            workspace=workspace,
        )

        with iteration_lock(
            workspace_raw=workspace_raw,
            workspace=workspace,
            iteration=iteration_name,
            skill_root=skill,
            baseline_root=baseline_root,
            iteration_root=iteration_root,
        ):
            reject_raw_symlink_components(iteration_raw, workspace_raw, "raw iteration path")
            if args.baseline == "snapshot":
                reject_raw_symlink_components(snapshot_raw, workspace_raw, "raw snapshot path")
                assert baseline_root is not None
                verify_frozen_baseline(baseline_root)
            would_overwrite = preflight_iteration_bundle(
                iteration_root=iteration_root,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
                skill_root=skill,
                workspace=workspace,
                iteration=iteration_name,
                baseline_root=baseline_root,
            )
            plan = {
                **bundle_identity(skill, workspace, iteration_name),
                "baseline": args.baseline,
                "config_path": str(config_path),
                "config_sha256": config_sha256,
                "executor_mode": config.executor.mode,
                "case_ids": [case["id"] for case in cases],
                "configurations": configurations,
                "acceptance_status": "pending_user_review",
                "would_overwrite_existing_bundle": would_overwrite,
                "case_plan": case_plan,
            }
            if args.dry_run:
                print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
                return 0

            create_bundle_marker(iteration_root, skill, workspace, iteration_name)
            manifest = {**plan, "status": "preparing_subjects", "started_at_utc": utc_now()}
            atomic_write_json(iteration_root / "run-manifest.json", manifest, iteration_root)
            subjects = freeze_run_subjects(
                iteration_root=iteration_root,
                skill_root=skill,
                baseline_root=baseline_root,
                cases=cases,
                workspace=workspace,
                config_path=config_path,
                config_sha256=config_sha256,
                runner_config=config,
            )

            frozen_cases = select_cases(
                load_cases(subjects["source_current_root"] / "evals" / "evals.json"), args.cases
            )
            if frozen_cases != cases:
                raise RunnerError("eval cases changed between preflight and current-subject freezing")
            config = subjects["runner_config"]
            configurations = selected_configurations(config, args.configurations)
            manifest.update({
                "status": "running",
                "subjects_manifest": "subjects/manifest.json",
                "subjects": subjects["manifest"],
                "effective_config": "subjects/adapters/runner.effective.json",
            })
            atomic_write_json(iteration_root / "run-manifest.json", manifest, iteration_root)

            results: list[dict[str, Any]] = []
            failures = 0
            for case in frozen_cases:
                for configuration in configurations:
                    if configuration == "with_skill":
                        selected_subject, baseline_kind = subjects["current_root"], "not_applicable"
                    elif subjects["baseline_root"] is not None:
                        selected_subject, baseline_kind = subjects["baseline_root"], "snapshot"
                    else:
                        selected_subject, baseline_kind = None, "no_skill"
                    output = iteration_root / f"eval-{validate_case_id(case['id'])}" / configuration
                    try:
                        result = execute_one(
                            case=case,
                            configuration=configuration,
                            selected_subject_root=selected_subject,
                            inputs_subject_root=subjects["inputs_root"],
                            adapter_root=subjects["adapter_root"],
                            baseline_kind=baseline_kind,
                            case_output=output,
                            iteration_root=iteration_root,
                            runner_config=config,
                        )
                    except RunnerError as exc:
                        failures += 1
                        atomic_write_json(
                            iteration_root / "controller-errors" /
                            f"eval-{validate_case_id(case['id'])}-{configuration}.json",
                            {
                                "schema_version": SCHEMA_VERSION,
                                "case_id": case["id"],
                                "configuration": configuration,
                                "status": "failed",
                                "error": str(exc),
                                "failed_at_utc": utc_now(),
                            },
                            iteration_root,
                        )
                        result = {
                            "case_id": case["id"],
                            "configuration": configuration,
                            "status": "failed",
                            "output_directory": str(output),
                            "error": str(exc),
                        }
                        if config.fail_fast:
                            results.append(result)
                            break
                    results.append(result)
                if failures and config.fail_fast:
                    break

            benchmark = aggregate_benchmark(
                skill=skill,
                workspace=workspace,
                iteration=iteration_name,
                executor_mode=config.executor.mode or "agent_host",
                configurations=configurations,
                results=results,
            )
            atomic_write_json(iteration_root / "benchmark.json", benchmark, iteration_root)
            manifest.update({
                "status": "completed" if failures == 0 else "completed_with_failures",
                "completed_at_utc": utc_now(),
                "failed_runs": failures,
            })
            atomic_write_json(iteration_root / "run-manifest.json", manifest, iteration_root)
            print(json.dumps({
                "status": manifest["status"],
                "benchmark": str(iteration_root / "benchmark.json"),
                "failed_runs": failures,
            }, ensure_ascii=False))
            return 0 if failures == 0 else 1
    except RunnerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
