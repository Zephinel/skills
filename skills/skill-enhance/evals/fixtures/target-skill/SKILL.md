---
name: sample-target-skill
description: "Helps with an example workflow, writes outputs, validates them, and can be improved when needed."
argument-hint: "optional input path or goal"
user-invocable: true
---

# Sample Target Skill

## When to Use

- Use this skill when the user asks for the example workflow.
- Before running, inspect the repository and choose the safest command.
- Use this skill when the user asks to validate or revise the example output.
- Always run scripts with dry-run first and stop if required tokens are missing.

## Clarification Gate

Ask one focused question when the user did not provide the target file, output format, or acceptance criteria. Do not ask multiple unrelated questions in one turn.

## Workflow

1. Resolve the target input.
2. Read the smallest useful files.
3. Produce the requested output.
4. Validate the result.
5. Summarize files changed and any remaining uncertainty.

## Available Files

Day-to-day files:

- `references/example-format.md` — Format notes for normal execution.
- `scripts/validate.sh` — Normal validation script.

Enabled maintenance files:

- `evals/evals.json` — Acceptance eval cases.
- `evals/README.md` — Eval workflow instructions.
- `memory/evidence.jsonl` — Current active evidence window.
- `memory/archive/` — Prior accepted observation windows and rollover sidecar manifests.
- `memory/summary.md` — Human-readable continuity digest.
- `memory/.evidence.lock` — Stable lifecycle lock created and used by the memory helper.
- `scripts/append-memory.py` — Target-bound public memory entrypoint.
- `scripts/append-memory-runtime.py` — Private append, rollover, manifest, and summary implementation loaded by the public entrypoint.

## Script Usage

- Run `scripts/validate.sh --dry-run` before applying changes.
- Stop if a required token or environment variable is missing.
- Check for duplicate operations before writing output files.

## Output Checklist

- [ ] The target input is resolved.
- [ ] The output matches the requested format.
- [ ] Dry-run validation passed before write actions.
- [ ] Token blockers and duplicate-operation checks were handled.
- [ ] Remaining uncertainty is surfaced.

## Maintenance Capabilities

- `eval_package`: enabled.
- `self_improve_package`: enabled and explicitly depends on the enabled eval package.
- The canonical target root is resolved from this `SKILL.md` once and retained for the run.
- Memory operations invoke this skill's own `scripts/append-memory.py` by path; they do not try the repository root or `.` and then fall back to `.agents/skills/...`.
- The public entry derives its target root from its installed location and rejects a mismatched explicit `--skill-root`.
- Each evidence-collected run uses a stable caller-provided `run_id`.
- Append, archive rollover, and summary update all acquire `memory/.evidence.lock`.
- Append retries search both the active evidence file and every archive window before writing.
- An identical archived retry returns `already_present` and does not enter the new active window.
- Each rollover uses one stable caller-provided `rollover_id` and one stable archive basename.
- `memory/archive/<archive-name>.rollover.json` binds the rollover ID, archive basename, and source-window SHA-256, byte count, and record count.
- `already_rolled_over` is valid only after both the sidecar manifest and archived content verify the same operation.
- Reusing an archive name for another rollover, reusing one rollover ID with another archive, or finding an unmanifested existing archive is a conflict.
- Symlinked or multi-linked entry, runtime, lock, evidence, archive, rollover-manifest, and summary files are rejected.
- The fixture intentionally mixes enabled maintenance files into the inventory so evals can test restructuring, dependency closure, persistence, target binding, and rollover behavior.

## Notes

- This fixture intentionally mixes trigger wording, execution policy, day-to-day files, and enabled maintenance files so `skill-enhance` evals can test restructuring without depending on an external skill.
