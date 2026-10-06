"""Aggregate Stage 3 results with finite paired case comparisons."""
from __future__ import annotations

from stage3_hardening_bundle import verify_frozen_subjects
from stage3_types import load_json, require_object

import math
from pathlib import Path
from typing import Any, Iterable

from stage3_types import RunnerError, SCHEMA_VERSION, utc_now


def _finite_values(values: Iterable[float], label: str) -> list[float]:
    result = [float(value) for value in values]
    if any(not math.isfinite(value) for value in result):
        raise RunnerError(f"benchmark {label} contains a non-finite value")
    return result


def _mean(values: Iterable[float], label: str) -> float:
    sequence = _finite_values(values, label)
    if not sequence:
        return 0.0
    value = math.fsum(sequence) / len(sequence)
    if not math.isfinite(value):
        raise RunnerError(f"benchmark {label} mean is not finite")
    return value


def _stddev(values: Iterable[float], label: str) -> float:
    sequence = _finite_values(values, label)
    if not sequence:
        return 0.0
    average = _mean(sequence, label)
    value = math.sqrt(math.fsum((item - average) ** 2 for item in sequence) / len(sequence))
    if not math.isfinite(value):
        raise RunnerError(f"benchmark {label} standard deviation is not finite")
    return value


def _metric(
    values: list[float],
    case_ids: list[str],
    label: str,
) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "mean": _mean(values, label),
        "stddev": _stddev(values, label),
        "paired_case_ids": case_ids,
    }


def aggregate_benchmark(
    *,
    skill: Path,
    workspace: Path,
    iteration: str,
    executor_mode: str,
    configurations: list[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    run_summary: dict[str, Any] = {}
    review_summary: dict[str, Any] = {}
    completed_by_config: dict[str, dict[str, dict[str, Any]]] = {}
    all_case_ids = sorted({str(item["case_id"]) for item in results})

    for configuration in configurations:
        completed = [
            item
            for item in results
            if item["configuration"] == configuration and item["status"] == "completed"
        ]
        completed_by_config[configuration] = {
            str(item["case_id"]): item for item in completed
        }
        rates = [float(item["grading"]["summary"]["pass_rate"]) for item in completed]
        durations = [
            float(item["timing"].get("duration_ms", 0)) / 1000 for item in completed
        ]
        tokens = [
            float(item["timing"]["total_tokens"])
            for item in completed
            if "total_tokens" in item["timing"]
        ]
        run_summary[configuration] = {
            "cases_completed": len(completed),
            "cases_failed": sum(
                1
                for item in results
                if item["configuration"] == configuration
                and item["status"] != "completed"
            ),
            "completed_case_ids": sorted(str(item["case_id"]) for item in completed),
            "pass_rate": {
                "mean": _mean(rates, f"{configuration}.pass_rate"),
                "stddev": _stddev(rates, f"{configuration}.pass_rate"),
            },
            "time_seconds": {
                "mean": _mean(durations, f"{configuration}.time_seconds"),
                "stddev": _stddev(durations, f"{configuration}.time_seconds"),
            },
            "tokens": {
                "mean": _mean(tokens, f"{configuration}.tokens"),
                "stddev": _stddev(tokens, f"{configuration}.tokens"),
                "reported_cases": len(tokens),
            },
        }
        review_summary[configuration] = {
            "needs_followup": sum(
                int(item["grading"]["summary"]["human_review_needs_followup"])
                for item in completed
            ),
            "failed_case_ids": [
                item["case_id"]
                for item in results
                if item["configuration"] == configuration
                and item["status"] != "completed"
            ],
        }

    delta = None
    if "with_skill" in completed_by_config and "baseline" in completed_by_config:
        current = completed_by_config["with_skill"]
        baseline = completed_by_config["baseline"]
        paired = sorted(set(current) & set(baseline))
        unpaired_current = sorted(set(current) - set(baseline))
        unpaired_baseline = sorted(set(baseline) - set(current))
        failed = sorted(
            {
                str(item["case_id"])
                for item in results
                if item["status"] != "completed"
                and item["configuration"] in {"with_skill", "baseline"}
            }
        )
        status = (
            "complete"
            if paired == all_case_ids
            and not unpaired_current
            and not unpaired_baseline
            and not failed
            else ("partial" if paired else "unavailable")
        )
        token_pairs = [
            case_id
            for case_id in paired
            if "total_tokens" in current[case_id]["timing"]
            and "total_tokens" in baseline[case_id]["timing"]
        ]
        delta = {
            "comparison_status": status,
            "paired_completed_case_ids": paired,
            "unpaired_with_skill_case_ids": unpaired_current,
            "unpaired_baseline_case_ids": unpaired_baseline,
            "failed_case_ids": failed,
            "pass_rate": _metric(
                [
                    float(current[case_id]["grading"]["summary"]["pass_rate"])
                    - float(baseline[case_id]["grading"]["summary"]["pass_rate"])
                    for case_id in paired
                ],
                paired,
                "delta.pass_rate",
            ),
            "time_seconds": _metric(
                [
                    float(current[case_id]["timing"].get("duration_ms", 0)) / 1000
                    - float(baseline[case_id]["timing"].get("duration_ms", 0)) / 1000
                    for case_id in paired
                ],
                paired,
                "delta.time_seconds",
            ),
            "tokens": _metric(
                [
                    float(current[case_id]["timing"]["total_tokens"])
                    - float(baseline[case_id]["timing"]["total_tokens"])
                    for case_id in token_pairs
                ],
                token_pairs,
                "delta.tokens",
            ),
        }

    limitations: list[str] = []
    if executor_mode == "raw_model_injection":
        limitations = [
            "raw-model execution does not prove Agent Host skill discovery or automatic loading",
            "raw-model execution does not prove host tool behavior or filesystem integration",
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "skill_root": str(skill),
        "workspace": str(workspace),
        "iteration": iteration,
        "executor_mode": executor_mode,
        "configurations": configurations,
        "case_results": results,
        "run_summary": run_summary,
        "delta": delta,
        "review_summary": review_summary,
        "limitations": limitations,
        "acceptance": {
            "status": "pending_user_review",
            "user_controlled": True,
            "note": "Provisional grades do not accept or apply a skill change by themselves.",
        },
    }


def aggregate_verified_benchmark(**kwargs: Any) -> dict[str, Any]:
    """Revalidate subjects and make fail-fast omissions explicit in the benchmark."""

    iteration_root = Path(kwargs["workspace"]) / str(kwargs["iteration"])
    verify_frozen_subjects(iteration_root)
    benchmark = aggregate_benchmark(**kwargs)

    run_manifest = require_object(
        load_json(iteration_root / "run-manifest.json", "Stage 3 run manifest"),
        "Stage 3 run manifest",
    )
    planned = [str(value) for value in run_manifest.get("case_ids", [])]
    benchmark["planned_case_ids"] = planned
    results = list(kwargs["results"])
    unattempted_by_configuration: dict[str, list[str]] = {}
    for configuration in kwargs["configurations"]:
        attempted = {
            str(item["case_id"])
            for item in results
            if item.get("configuration") == configuration
        }
        unattempted = [case_id for case_id in planned if case_id not in attempted]
        unattempted_by_configuration[configuration] = unattempted
        summary = benchmark["run_summary"][configuration]
        summary["cases_planned"] = len(planned)
        summary["cases_attempted"] = len(attempted)
        summary["unattempted_case_ids"] = unattempted

    benchmark["unattempted_case_ids"] = unattempted_by_configuration
    delta = benchmark.get("delta")
    if isinstance(delta, dict):
        delta["unattempted_with_skill_case_ids"] = unattempted_by_configuration.get(
            "with_skill", []
        )
        delta["unattempted_baseline_case_ids"] = unattempted_by_configuration.get(
            "baseline", []
        )
        if (
            delta["unattempted_with_skill_case_ids"]
            or delta["unattempted_baseline_case_ids"]
        ):
            delta["comparison_status"] = (
                "partial" if delta.get("paired_completed_case_ids") else "unavailable"
            )
    return benchmark
