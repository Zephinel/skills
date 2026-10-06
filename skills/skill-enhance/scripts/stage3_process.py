"""Stage 3 grading helpers and disabled legacy process entry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from stage3_types import (
    ALLOWED_REVIEW_JUDGMENTS,
    SCHEMA_VERSION,
    AdapterConfig,
    AdapterRun,
    RunnerError,
    atomic_write_json,
    atomic_write_text,
    require_object,
    require_string,
)


def run_adapter(
    adapter: AdapterConfig,
    request: dict[str, Any],
    cwd: Path,
    adapter_root: Path,
) -> AdapterRun:
    """Reject the legacy unbounded process path.

    The hardened public entry replaces adapter execution with
    ``stage3_bounded_process.run_adapter``. Keeping a callable legacy launcher
    here would recreate the direct ``stage3_runner.py`` bypass.
    """

    raise RunnerError(
        "legacy Stage 3 adapter execution is disabled; use scripts/run-eval-cases.py"
    )


def persist_adapter_run(
    prefix: str,
    run: AdapterRun,
    case_output: Path,
    iteration_root: Path,
) -> None:
    """Compatibility persistence helper for non-secret test data.

    The hardened runtime uses its redacting persistence implementation.
    """

    atomic_write_text(case_output / f"{prefix}.stdout.log", run.stdout, iteration_root)
    atomic_write_text(case_output / f"{prefix}.stderr.log", run.stderr, iteration_root)
    atomic_write_json(
        case_output / f"{prefix}-status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "command": run.command,
            "return_code": run.return_code,
            "timed_out": run.timed_out,
            "duration_ms": run.duration_ms,
            "json_parse_status": run.json_parse_status,
            "error": run.error,
        },
        iteration_root,
    )
    if run.payload is not None:
        atomic_write_json(case_output / f"{prefix}.raw.json", run.payload, iteration_root)


def require_adapter_success(run: AdapterRun, label: str) -> dict[str, Any]:
    if run.error is not None or run.payload is None:
        raise RunnerError(f"{label} failed: {run.error or 'missing JSON output'}")
    return run.payload


def normalized_grading(
    case: dict[str, Any],
    judge: dict[str, Any],
    reviewer_type: str,
) -> dict[str, Any]:
    expected_assertions = list(case.get("assertions", []))
    expected_reviews = list(case.get("human_review", []))
    raw_assertions = judge.get("assertion_results")
    raw_reviews = judge.get("human_review_results")
    if not isinstance(raw_assertions, list) or len(raw_assertions) != len(expected_assertions):
        raise RunnerError(
            "judge must return exactly one assertion result for every case assertion"
        )
    if not isinstance(raw_reviews, list) or len(raw_reviews) != len(expected_reviews):
        raise RunnerError(
            "judge must return exactly one human review result for every case review question"
        )

    assertions: list[dict[str, Any]] = []
    for index, (expected, raw) in enumerate(
        zip(expected_assertions, raw_assertions, strict=True)
    ):
        item = require_object(raw, f"judge assertion_results[{index}]")
        text = require_string(
            item.get("text"), f"judge assertion_results[{index}].text"
        )
        if text != expected:
            raise RunnerError(f"judge assertion text mismatch at index {index}")
        passed = item.get("passed")
        if not isinstance(passed, bool):
            raise RunnerError(
                f"judge assertion_results[{index}].passed must be boolean"
            )
        assertions.append(
            {
                "text": text,
                "passed": passed,
                "evidence": require_string(
                    item.get("evidence"),
                    f"judge assertion_results[{index}].evidence",
                ),
            }
        )

    reviews: list[dict[str, Any]] = []
    for index, (expected, raw) in enumerate(
        zip(expected_reviews, raw_reviews, strict=True)
    ):
        item = require_object(raw, f"judge human_review_results[{index}]")
        text = require_string(
            item.get("text"), f"judge human_review_results[{index}].text"
        )
        if text != expected:
            raise RunnerError(f"judge human review text mismatch at index {index}")
        judgment = require_string(
            item.get("judgment"),
            f"judge human_review_results[{index}].judgment",
        )
        if judgment not in ALLOWED_REVIEW_JUDGMENTS:
            raise RunnerError(
                "judge human review judgment must be one of: "
                f"{', '.join(sorted(ALLOWED_REVIEW_JUDGMENTS))}"
            )
        reviews.append(
            {
                "text": text,
                "judgment": judgment,
                "evidence": require_string(
                    item.get("evidence"),
                    f"judge human_review_results[{index}].evidence",
                ),
                "reviewer_type": reviewer_type,
            }
        )

    passed_count = sum(1 for item in assertions if item["passed"])
    total = len(assertions)
    return {
        "schema_version": SCHEMA_VERSION,
        "eval_id": case["id"],
        "assertion_results": assertions,
        "human_review_results": reviews,
        "summary": {
            "passed": passed_count,
            "failed": total - passed_count,
            "total": total,
            "pass_rate": passed_count / total if total else 1.0,
            "human_review_needs_followup": sum(
                1 for item in reviews if item["judgment"] == "needs_followup"
            ),
        },
    }
