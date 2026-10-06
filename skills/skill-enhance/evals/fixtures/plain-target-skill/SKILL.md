---
name: plain-target-skill
description: "Runs a small example workflow and validates the requested output."
user-invocable: true
---

# Plain Target Skill

## When to Use

Use this skill when the user asks to generate or validate the example output.

## Workflow

1. Resolve the requested output.
2. Read only the files needed for the task.
3. Produce the output.
4. Validate it.
5. Summarize the result and remaining uncertainty.

## Notes

This fixture intentionally has no eval or self-improve package. A normal whole-skill upgrade must not add `memory/` unless the user explicitly opts in.
