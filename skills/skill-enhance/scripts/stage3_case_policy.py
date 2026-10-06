"""Cross-platform Stage 3 eval-case validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import stage3_types
from stage3_types import RunnerError

_ORIGINAL_LOAD_CASES = stage3_types.load_cases
_ORIGINAL_SELECT_CASES = stage3_types.select_cases
MAX_CASE_ID_LENGTH = 128


def _casefold_unique(values: list[str], label: str) -> None:
    seen: dict[str, str] = {}
    for value in values:
        key = value.casefold()
        previous = seen.get(key)
        if previous is not None:
            raise RunnerError(
                f"{label} contains a case-insensitive duplicate: {previous!r} and {value!r}"
            )
        seen[key] = value


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = _ORIGINAL_LOAD_CASES(path)
    seen_ids: dict[str, str] = {}
    for case in cases:
        case_id = str(case["id"])
        if len(case_id) > MAX_CASE_ID_LENGTH:
            raise RunnerError(
                f"eval case id is longer than {MAX_CASE_ID_LENGTH} characters: {case_id!r}"
            )
        folded_id = case_id.casefold()
        previous = seen_ids.get(folded_id)
        if previous is not None:
            raise RunnerError(
                "eval case ids must be case-insensitively unique for macOS portability: "
                f"{previous!r} and {case_id!r}"
            )
        seen_ids[folded_id] = case_id

        for field in ("files", "input_files", "assertions", "human_review"):
            _casefold_unique(list(case.get(field, [])), f"eval {case_id}.{field}")

        files = {value.casefold() for value in case.get("files", [])}
        overlap = [
            value
            for value in case.get("input_files", [])
            if value.casefold() in files
        ]
        if overlap:
            raise RunnerError(
                f"eval {case_id} must not expose the same path as both files and "
                f"input_files: {', '.join(overlap)}"
            )
    return cases


def select_cases(cases: list[dict[str, Any]], selector: str) -> list[dict[str, Any]]:
    if selector != "all":
        requested = [item.strip() for item in selector.split(",") if item.strip()]
        _casefold_unique(requested, "--cases")
    return _ORIGINAL_SELECT_CASES(cases, selector)
