# Evals

## Enabled capability

This package exists only because `eval_package` was explicitly selected or already enabled. It does not imply persistent memory. Full `self_improve_package` depends on this eval package, but an eval package may exist without self-improve.

## Supported environment

Automated Stage 3 supports Linux and macOS. On Windows, use WSL or another compatible Unix environment.

## Baseline

Choose one baseline:

- `none` — evaluate the current skill and optionally a no-skill baseline;
- `snapshot` — compare against an unmodified previous version.

Freeze a snapshot before editing:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --create-baseline
```

Reuse it after editing:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --iteration iteration-1
```

Stage 2 keeps raw and canonical identities for skill, workspace, recovered baseline source, snapshot, and iteration. Root and managed-child symlink aliases are rejected before copy, creation, or deletion. Normal runs never recreate the baseline.

## Stage 2

`run-evals.sh` performs preflight, immutable-baseline creation or verification, and iteration-directory scaffolding. It does not execute cases, call an Agent Host, grade results, or accept changes.

## Stage 3 installation

Copy the complete runtime and config template:

```bash
cp <skill-enhance>/scripts/run-eval-cases.py scripts/run-eval-cases.py
cp <skill-enhance>/scripts/eval_*.py scripts/
cp <skill-enhance>/assets/eval-runner-config-template.json evals/runner.json
chmod +x scripts/run-eval-cases.py
```

Only `scripts/run-eval-cases.py` is a public Stage 3 command. Internal `eval_*.py` modules are not standalone entry points.

Use dedicated role roots:

```text
scripts/eval-adapters/executor/
scripts/eval-adapters/judge/
```

`bundle_paths` may include only required target-local files under `scripts/`.

- The executor bundle must not expose the skill, references, assets, memory, eval-control material, rubrics, expected outputs, or reference answers.
- The judge may include judge-only rubric or prompt assets under its private judge subtree.
- Judge-private paths must never be shared with the executor bundle.

## Running Stage 3

After replacing executor and judge commands in `evals/runner.json`:

```bash
python3 scripts/run-eval-cases.py \
  --skill . \
  --workspace ./eval-workspace \
  --iteration iteration-1 \
  --baseline snapshot \
  --dry-run

python3 scripts/run-eval-cases.py \
  --skill . \
  --workspace ./eval-workspace \
  --iteration iteration-1 \
  --baseline snapshot
```

The hardened controller:

1. validates raw and canonical paths and protected roots;
2. verifies Stage 2 by default;
3. strictly validates cases and config;
4. freezes complete current and optional baseline provenance subjects;
5. creates sanitized execution subjects;
6. derives task inputs from frozen `source-current`, not the live target;
7. freezes source-bound policy, runner config, and separate role bundles;
8. verifies persistent subjects and every temporary copy against frozen hashes;
9. runs each case from a fresh temporary root;
10. keeps reference answers and judge criteria out of executor requests and bundles;
11. runs no-skill baselines from a neutral CWD;
12. exposes only explicit environment variables and redacts exact passthrough secret values from durable evidence;
13. enforces timeout, output, complete artifact-tree, and complete workspace-entry limits;
14. records a complete metadata-oriented workspace diff;
15. persists only verified declared changed files and explicitly declared artifacts after stable-copy and secret checks;
16. grades results provisionally and computes paired deltas;
17. records unattempted cases when fail-fast stops early;
18. treats each iteration as a locked one-shot owned evidence bundle;
19. leaves final acceptance at `pending_user_review`.

Use `with_skill` plus `baseline` for comparison. With `--baseline snapshot`, baseline runs use the immutable old-version subject. With `--baseline none`, baseline runs receive no skill.

`acceptance.user_controlled` must remain `true`.

## Strict data and limits

Runner configs and adapter outputs use strict JSON. `NaN` and Infinity are invalid. Timing values must be finite and non-negative.

Configure practical limits for:

```text
stdout bytes
stderr bytes
artifact bytes and complete entry count
workspace bytes and complete entry count
durable declared changed-file bytes
```

Case IDs are length-limited and case-insensitively unique. Duplicate selectors, file paths, inputs, assertions, and broader review questions are rejected. One path cannot be both a skill file and a task input.

## Adapter contract

Read `assets/eval-adapter-contract.md` and `references/Automated eval runtime.md` from `skill-enhance` before implementing adapters.

- Commands are argv arrays with `shell=False`.
- Target-local command paths execute from frozen role bundles.
- Path-bearing later arguments must resolve inside the target skill.
- External executables are not invoked through an uncontrolled version probe.
- Executor and judge receive separate bundles and environment allowlists.
- Executor adapters must not receive or reconstruct reference answers or grading criteria.
- `agent_host` responses identify fresh context, CWD, loaded skill root, or no-skill state.
- Adapters are trusted controller extensions, not an OS sandbox.
- Automated qualitative results identify `reviewer_type` and remain provisional.

## Review

Review actual outputs together with assertion and qualitative grades, redacted diagnostics, execution identity, workspace diff and undeclared changes, declared persisted artifacts, frozen subject/config/adapter manifests, paired-comparison status, unattempted work, and limitations.

Do not automatically accept a change from provisional grades.

## Self-improve cases

Add memory-persistence cases only when full self-improve is enabled. Verify strict current and historical evidence schema, stable operation IDs, lifecycle locking, cross-window exactly-once behavior, atomic summary update, safe rollover, link safety, and `written` / `blocked` / pre-run-only `skipped` semantics.

A normal skill without self-improve must not fail because `memory/` is absent.

## Validation

When the complete target-local regression scripts are installed, use their canonical entry:

```bash
bash scripts/test-all.sh
```
