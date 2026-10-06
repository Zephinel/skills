"""Validate the public Stage 3 entry and invoke the controller."""
from __future__ import annotations

import sys
from pathlib import Path

from eval_path_policy import reject_raw_path_symlinks
from eval_types import RunnerError, activate_hardening, lexical_absolute
from eval_runner import main as run

def _option_value(argv: list[str], name: str) -> str | None:
    prefix = name + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _reject_cli_root_aliases(argv: list[str]) -> None:
    for option, label in (
        ("--skill", "raw skill root"),
        ("--workspace", "raw workspace root"),
        ("--config", "raw runner config"),
    ):
        value = _option_value(argv, option)
        if value:
            reject_raw_path_symlinks(lexical_absolute(value), label)

    skill_value = _option_value(argv, "--skill")
    if skill_value:
        skill_raw = lexical_absolute(skill_value)
        for relative, label in (
            (Path("SKILL.md"), "raw SKILL.md"),
            (Path("evals/evals.json"), "raw eval case file"),
            (Path("evals/runner.json"), "raw default runner config"),
        ):
            reject_raw_path_symlinks(skill_raw / relative, label)


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        _reject_cli_root_aliases(effective_argv)
        activate_hardening()
        return run(effective_argv)
    except RunnerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
