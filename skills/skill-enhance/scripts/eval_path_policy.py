"""Shared Stage 3 path and reference-answer policy."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from eval_types import RunnerError

CONTROL_EXACT = {
    "evals.json",
    "runner.json",
    "runner.example.json",
    "train-queries.json",
    "validation-queries.json",
    "judge-prompt.md",
    "judge-prompt.json",
}
CONTROL_PREFIXES = (
    "grading",
    "benchmark",
    "rubric",
    "expected-output",
    "expected_output",
    "expected-result",
    "expected_result",
    "reference-answer",
    "reference_answer",
    "reference-output",
    "reference_output",
    "reference-result",
    "reference_result",
    "golden-answer",
    "golden_answer",
    "golden-output",
    "golden_output",
    "answer-key",
    "answer_key",
)
CONTROL_DIRECTORIES = {
    "rubric",
    "rubrics",
    "grading",
    "gradings",
    "benchmark",
    "benchmarks",
    "expectation",
    "expectations",
    "expected-outputs",
    "expected_outputs",
    "golden-answers",
    "golden_answers",
    "answer-keys",
    "answer_keys",
    "reference-answers",
    "reference_answers",
}


def reject_raw_path_symlinks(path: Path, label: str) -> None:
    """Reject every existing symlink component in an absolute lexical path."""

    lexical = Path(os.path.abspath(os.path.expanduser(str(path))))
    anchor = Path(lexical.anchor)
    current = anchor
    parts = lexical.parts[1:] if lexical.anchor else lexical.parts
    for part in parts:
        current = current / part
        if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):
            raise RunnerError(f"{label} must not contain a symlink component: {current}")


def sensitive(path: str | Path) -> bool:
    """Return whether a path is executor-visible eval-control material.

    Legitimate adapter code such as ``scripts/eval-adapters/judge/`` and ordinary
    references such as ``references/reference-architecture.md`` remain allowed.
    Files whose names explicitly identify expected outputs, golden answers,
    grading, benchmarks, or rubrics are withheld wherever they occur.
    """

    parts = tuple(part.lower() for part in Path(path).parts)
    if not parts:
        return False
    name = parts[-1]
    if name in CONTROL_EXACT or name.startswith(CONTROL_PREFIXES):
        return True
    return any(part in CONTROL_DIRECTORIES for part in parts[:-1])
