# Skill Structure and Frontmatter Reference

Use this reference when an existing skill has broken frontmatter, mismatched folder naming, unclear directory layout, or broken relative links.

## Required layout

A skill lives in a single directory whose name matches its `name` field:

```text
<skill-name>/
├── SKILL.md          # Required: YAML frontmatter + core instructions
├── agents/           # Optional: host-specific UI metadata (e.g. openai.yaml)
├── references/       # Optional: deep rules, checklists, or fallback procedures
├── scripts/          # Optional: deterministic helpers and self-tests
├── assets/           # Optional: output templates or starter files
└── evals/            # Optional: opt-in trigger/output evals (only when enabled)
```

Keep `SKILL.md` focused on what the agent needs on every run (practically under ~500 lines). Move fallback paths, large example catalogs, and lookup tables into `references/` with explicit pointers telling the agent *when* to read each file.

## `SKILL.md` YAML frontmatter

Start `SKILL.md` on line 1 with a valid YAML frontmatter block delimited by `---`:

```yaml
---
name: my-skill
description: >
  State what the skill does, the concrete user intents that should trigger it,
  and clear near-miss boundaries (what it is not for).
---
```

### Core fields

- **`name`** (required): lowercase identifier (`a-z`, `0-9`, `-`) matching the parent folder name.
- **`description`** (required): always-loaded trigger pointer. Keep it concise and under **1024 characters**. Front-load user intent, list distinct trigger branches once, and include near-miss boundaries.
- **Optional host fields** (include only when the target host uses them):
  - `argument-hint`: short parameter hint shown for explicit slash invocation.
  - `user-invocable`: boolean indicating whether users can invoke the skill directly.
  - `disable-model-invocation`: set `true` only for strictly manual skills that should never auto-trigger.
  - `compatibility`: explicit platform or runtime constraints (e.g. macOS + Google Chrome) when the skill cannot run everywhere.

## Common structural defects to repair

1. **Missing or malformed frontmatter**: ensure `---` appears on line 1, YAML keys are properly quoted when values contain colons (`: `) or leading quotes, and the closing `---` exists.
2. **`name` / folder mismatch**: align `name` with the skill directory name so skill loaders discover it reliably.
3. **Broken relative links**: every `[label](references/...)` or `assets/...` link must resolve inside the skill root; URL-encode spaces (`%20`) in Markdown link targets or rename files without spaces.
4. **CWD-dependent script calls**: avoid assuming the shell working directory equals the skill root. Instruct the agent to resolve scripts relative to `<skill-dir>` (the directory containing `SKILL.md`).
5. **Unverified claims or dangling references**: remove references to other skills, files, or flags that do not exist in the repository.

## Related references

- [Best practices](./Best%20practices.md) — progressive disclosure, defaults, and gotchas.
- [Optimizing skill descriptions](./Optimizing%20skill%20descriptions.md) — trigger wording and query evals.
- [Using scripts in skills](./Using%20scripts%20in%20skills.md) — non-interactive script design.
