---
name: skill-enhance
description: "Use this skill to improve an existing Agent Skill / 技能: refine triggers, scope, workflow, references, scripts, or evals; optionally add an acceptance-eval package or a controlled self-improve package only with explicit approval. Do not use for creating a new skill."
argument-hint: "可选：目标技能路径或名称、优化范围（单点修复 / 整技能升级）、主要方向、可选能力（none / eval package / self-improve + eval package）"
user-invocable: true
---

# Skill Enhance

Improve an existing skill without silently expanding its scope or maintenance burden.

## When to Use

Use this skill when the user wants to improve an existing skill, for example:

- refine `description`, `When to Use`, boundaries, defaults, workflow, or validation;
- fix over-triggering, under-triggering, weak assumptions, or excessive clarification;
- reorganize `SKILL.md`, references, scripts, or eval scaffolding;
- optionally install an acceptance-eval package;
- optionally install a controlled self-improve package that accumulates evidence.

Do not use it to create a brand-new skill. Hand off to an installed skill-creation workflow when available; otherwise explain the boundary.

## Resolve Two Decisions Separately

Always resolve:

1. **Optimization scope** — how much to improve now.
2. **Optional capabilities** — whether to install eval or self-improve machinery.

A whole-skill upgrade does **not** imply evals, memory, or self-improve.

### Optimization scope

- `单点修复` — one requested slice or one highest-value weakness. Change only the relevant surface.
- `整技能升级` — broad improvement of triggers, boundaries, workflow, defaults, structure, and ordinary validation.

Ask one concise scope question when both remain materially plausible and the request does not choose.

### Optional capabilities

- `none` — default. Do not create maintenance-only files.
- `eval_package` — enable only when the user explicitly requests evals, benchmarking, acceptance checks, or previous-version comparison.
- `self_improve_package` — enable only when the user explicitly requests persistent evidence or a target-local improvement loop. A full self-improve package requires `eval_package`.

If self-improve is requested without approval for its eval dependency, explain the dependency and ask one concise question before installing either package.

An already-enabled package may be preserved or refreshed during a broad upgrade. Dormant files alone do not prove enablement.

## Resolve the Target First

1. Use an explicit target path or skill name when supplied.
2. Interpret `这个技能` as the skill being optimized, not `skill-enhance`, unless the user explicitly names `skill-enhance`.
3. Treat `skill-enhance` as the target only for explicit self-targeting.
4. When the current file or working directory is inside a skill root containing `SKILL.md`, use that root.
5. Otherwise ask one concise target-selection question.

The shell working directory may differ from the target root as long as the target is unambiguous.

## Interaction Model

### Direct mode

When target, scope, direction, and capabilities are clear, proceed without repeating answered questions.

### Guided mode

When the user provides only a target or a broad request:

1. inspect the target `SKILL.md`;
2. name one or two grounded improvement directions;
3. ask one concise scope or direction question before editing.

A compact choice set is:

1. 单点修复
2. 触发优化
3. 工作流优化
4. 结构优化
5. 只补 eval package
6. 整技能升级，不安装维护能力
7. 整技能升级 + self-improve（同时安装 eval package）

Ask one question at a time. Use the host's interactive question UI when available.

## Workflow

1. Resolve the target skill.
2. Resolve scope and primary direction.
3. Resolve optional capabilities separately; default to `none`.
4. When previous-version comparison is requested, freeze an unmodified baseline **before editing**.
5. Read the smallest useful file set, starting with target `SKILL.md`.
6. Make the smallest grounded change set.
7. Install only explicitly approved capabilities.
8. Validate every touched surface.
9. Report changed files, rationale, validation, selected capabilities, and uncertainty.

If editing began before a requested baseline was frozen, use an explicitly recovered unmodified source through `--baseline-source`, or report that a trustworthy previous-version comparison is unavailable. Never copy the modified target as its own old-version baseline.

## Edit Rules

### Trigger wording

- Front-load user intent in `description`.
- Keep `When to Use` limited to user-facing trigger conditions.
- Move execution policy into workflow, defaults, gotchas, or references.
- Include clear near-miss boundaries.

### Structure and workflow

- Prefer procedures over declarations.
- Prefer one useful default over a flat menu of equal choices.
- Keep controlling steps easy to find.
- Move deep or rare detail into references.
- Keep ordinary execution instructions independently understandable.

### Scripts

- Add a script only when it removes repeated fragile work.
- Keep scripts skill-relative, non-interactive, retry-safe, and explicit about failures.
- Separate structured stdout from diagnostics on stderr.
- Enforce filesystem and lifecycle invariants in code, not only in prose.

## Eval Package Contract

When `eval_package` is selected:

- freeze a previous-version snapshot explicitly before edits when comparison needs it;
- normal snapshot runs only reuse and integrity-check that baseline;
- install `run-eval-cases.py`, every bundled `eval_*.py` module, and `evals/runner.json` together when automated Stage 3 is requested;
- use only `scripts/run-eval-cases.py` as the public Stage 3 entry; internal `eval_*.py` modules are not standalone commands;
- keep executor and judge adapters under dedicated `scripts/` subtrees and expose only their required code;
- keep executor requests free of reference answers and judge criteria;
- use bounded, secret-safe evidence persistence and revalidate frozen subjects before every case;
- keep final acceptance under user control.

Read [`references/Automated eval runtime.md`](./references/Automated%20eval%20runtime.md) and [`assets/eval-adapter-contract.md`](./assets/eval-adapter-contract.md) before installing or changing automated Stage 3.

Stage 2 prepares and verifies the workspace. Stage 3 executes cases, grades provisional results, and builds benchmark evidence. Neither stage accepts a skill change by itself.

## Self-Improve Package Contract

Apply these rules only when the full `self_improve_package` and its required eval package are enabled.

- Resolve the authoritative target root once from the selected target `SKILL.md` and retain its canonical path for the full run.
- Install the target-bound entry as `scripts/append-memory.py` and its implementation as `scripts/append-memory-runtime.py`.
- Invoke the entry by its path under the resolved target root; do not depend on the shell working directory and do not probe `.` before retrying `.agents/skills/...` or another fallback.
- The entry must derive and verify its target root from its own installed location. An explicit `--skill-root` is accepted only when it matches that installed root.
- The caller creates one stable `run_id` per evidence-collected run and reuses it for retries.
- A completed evidence-collected run resolves to `written` or `blocked`.
- `skipped` is allowed only after an explicit pre-run opt-out.
- Append only through the target-bound `scripts/append-memory.py append` entry.
- Update the summary only through the target-bound `scripts/append-memory.py update-summary` entry.
- Roll observation windows only through the target-bound `scripts/append-memory.py rollover` entry with one stable `rollover_id` and archive basename.
- Require user confirmation before preparing a self-improvement patch.
- Run relevant acceptance evals before keeping an applied change.
- Do not treat a visible run summary as memory persistence.

Read [`references/Target-local self-optimization.md`](./references/Target-local%20self-optimization.md) before installing or changing this package.

## Safety Boundaries

- Write only inside the resolved target root unless the user explicitly approves another location.
- Generated helpers must independently enforce target-root containment.
- Never use a failed write as a path-discovery mechanism; a target-root mismatch is a blocker, not a signal to try another root.
- Reject symlink and multi-link write targets for managed maintenance files.
- Retain raw and canonical path identities where copy, deletion, baseline provenance, or overwrite safety depends on both.
- Do not store secrets, tokens, credentials, private user data, or raw transcripts in memory or eval evidence.
- Treat executor and judge adapters as trusted controller extensions, not as an operating-system sandbox. Use a container or restricted account for untrusted adapters.
- Automated Stage 3 is supported on Linux and macOS. On Windows, use WSL or another compatible Unix environment.
- Reuse existing scaffolds and read the smallest useful file set.

## References to Load When Needed

- [`references/Optimizing skill descriptions.md`](./references/Optimizing%20skill%20descriptions.md) — trigger wording.
- [`references/Best practices.md`](./references/Best%20practices.md) — structure and workflow.
- [`references/Evaluating skill output quality.md`](./references/Evaluating%20skill%20output%20quality.md) — eval design and grading.
- [`references/Automated eval runtime.md`](./references/Automated%20eval%20runtime.md) — automated Stage 3 lifecycle and hardening.
- [`assets/eval-adapter-contract.md`](./assets/eval-adapter-contract.md) — adapter integration.
- [`references/Using scripts in skills.md`](./references/Using%20scripts%20in%20skills.md) — script design.
- [`references/Target-local self-optimization.md`](./references/Target-local%20self-optimization.md) — opt-in self-improve.
- [`references/Quickstart.md`](./references/Quickstart.md) — broken structure or frontmatter.

## Bundled Assets and Scripts

Use only what the selected capability needs:

- eval templates under `assets/`;
- `scripts/run-evals.sh` for Stage 2;
- `scripts/run-eval-cases.py` plus all `scripts/eval_*.py` modules for automated Stage 3;
- `assets/append-memory-entry-template.py` installed as target-local `scripts/append-memory.py`;
- `assets/append-memory-template.py` installed beside it as `scripts/append-memory-runtime.py`;
- `scripts/test-all.sh` for the complete package regression suite.

## Output Checklist

Check only applicable items:

- [ ] Target, scope, direction, and capabilities were resolved separately.
- [ ] Broad guided requests paused for one concise choice before editing.
- [ ] Optional packages were not installed implicitly.
- [ ] Requested previous-version baseline was frozen before edits.
- [ ] Automated Stage 3 uses the hardened public entry and complete runtime.
- [ ] Frozen subjects, adapter bundles, secrets, outputs, artifacts, and limits follow the Stage 3 reference contract.
- [ ] Self-improve persistence uses a target-bound helper, stable operation IDs, and safe lifecycle operations.
- [ ] Memory writes do not depend on the repository CWD or failure-driven root fallback.
- [ ] Main-body rules are not duplicated in maintenance content.
- [ ] New files remain inside the target root.
- [ ] Relevant JSON, shell, Python, Markdown-link, and lifecycle checks passed.
- [ ] Final response states changed files, validation, installed capabilities, and uncertainty.

## Example Prompts

Should trigger:

```text
/skill-enhance 优化当前这个 SKILL.md 的 description，让它更容易在正确场景触发。
/skill-enhance 整技能升级 ./skills/report-writer，不要安装维护能力。
/skill-enhance 整技能升级 ./skills/release-helper，并安装 self-improve；我同意同时安装它依赖的 eval package。
```

Should not trigger:

```text
帮我从零创建一个全新的 skill。
帮我执行这个 repo 的普通测试任务。
帮我总结这篇文章，不需要改 skill。
```

## Notes

- Preserve the user's chosen direction even when another weakness looks more interesting.
- Prefer a partial grounded improvement over silently expanding scope.
- Be explicit when validation could not be run.
