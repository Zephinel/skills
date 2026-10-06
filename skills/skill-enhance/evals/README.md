# Evals

## Purpose

This package validates `skill-enhance` and provides the optional target-local eval runtime it can install.

Keep these boundaries clear:

- optimization scope and maintenance capabilities are separate;
- `eval_package` is opt-in;
- full `self_improve_package` is opt-in and depends on `eval_package`;
- `run-evals.sh` is Stage 2 baseline/workspace preparation;
- `run-eval-cases.py` plus every bundled `eval_*.py` module form the Stage 3 runtime;
- only `run-eval-cases.py` is a supported Stage 3 entry;
- final acceptance remains user-controlled.

## Primary acceptance paths

Use the smallest path that proves the changed contract:

1. **Ordinary optimization** — use `evals/fixtures/plain-target-skill/`; confirm no optional package is installed implicitly.
2. **Eval package** — validate baseline lifecycle, path safety, protected roots, owned-bundle overwrite, frozen subjects, role isolation, bounded evidence, grading, and benchmark behavior.
3. **Self-improve package** — use `evals/fixtures/target-skill/`; validate evidence schema, lifecycle locking, exactly-once append, rollover, summary update, and acceptance gating.
4. **Ambiguous target** — run from a neutral context that cannot infer a target from the current file or directory.

Do not use a self-improve fixture as evidence that ordinary whole-skill upgrades should install memory.

## Files

- `train-queries.json` — trigger-eval training queries.
- `validation-queries.json` — held-out trigger queries.
- `evals.json` — output and lifecycle cases. `files` are skill-relative; `input_files` are task inputs.
- `runner.example.json` — hardened Stage 3 configuration example.
- `fixtures/plain-target-skill/` — no maintenance package enabled.
- `fixtures/target-skill/` — eval and self-improve packages explicitly enabled.
- grading and benchmark examples — output-shape references only.
- `../scripts/run-evals.sh` — Stage 2.
- `../scripts/run-eval-cases.py` plus all `../scripts/eval_*.py` — complete Stage 3 runtime.
- `../scripts/test-all.sh` — single canonical regression entry.

`eval_*.py` files implement the runtime. `eval-*-test.sh` files test that runtime. The stage numbers describe the lifecycle below, not file names or release versions.

## Baseline lifecycle

A previous-version baseline is an explicit immutable freeze, not a normal-run side effect.

Before editing:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --create-baseline
```

After editing:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --iteration iteration-1
```

Normal snapshot runs only reuse and integrity-check the existing snapshot. When editing started before the freeze, recover an unmodified source through `--baseline-source`; otherwise report that no trustworthy comparison exists.

Stage 2 keeps raw lexical and canonical identities for skill, workspace, recovered source, snapshot, and iteration. Root and managed-child symlink aliases are rejected before copy, creation, or deletion.

## Stage 3 installation

Copy the complete runtime and config template:

```bash
cp <skill-enhance>/scripts/run-eval-cases.py scripts/run-eval-cases.py
cp <skill-enhance>/scripts/eval_*.py scripts/
cp <skill-enhance>/assets/eval-runner-config-template.json evals/runner.json
chmod +x scripts/run-eval-cases.py
```

Do not copy only compatibility exports.

Use dedicated role roots:

```text
scripts/eval-adapters/executor/
scripts/eval-adapters/judge/
```

`bundle_paths` may include only required target-local files under `scripts/`.

- The executor bundle must not expose `SKILL.md`, references, assets, memory, eval control, rubrics, expected outputs, or reference answers.
- The judge may include judge-only rubric or prompt assets under its private judge subtree.
- Judge-private material must never be shared with the executor bundle.

## Running Stage 3

After configuring executor and judge commands:

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

Do not invoke an internal `eval_*.py` module directly.

The hardened controller:

1. validates raw and canonical paths and protected roots;
2. verifies Stage 2 by default;
3. strictly validates case identities, selectors, files, inputs, and config;
4. freezes complete current and optional baseline provenance subjects;
5. creates sanitized execution subjects;
6. derives task inputs from frozen `source-current`, never the live target;
7. freezes runner config, source-bound runtime policy, and separate executor/judge bundles;
8. records and repeatedly verifies tree and control-file hashes;
9. compares every temporary case copy with the original frozen manifest digest;
10. runs each case from a fresh temporary root;
11. runs no-skill baselines from a neutral CWD with no current-skill material;
12. keeps reference answers and judge criteria out of executor requests and bundles;
13. exposes only an environment allowlist and redacts exact passthrough secrets from durable evidence;
14. enforces timeout, stdout/stderr, complete artifact-tree, and complete workspace-entry limits;
15. records a complete metadata-oriented workspace diff;
16. persists only verified declared changed files and explicitly declared artifacts after no-follow stable-copy and secret checks;
17. grades every assertion and broader review question provisionally;
18. computes deltas only over matching completed case IDs;
19. records planned, attempted, failed, and unattempted work when fail-fast stops early;
20. treats the iteration as a locked one-shot owned evidence bundle;
21. leaves acceptance as `pending_user_review`.

Use `with_skill` plus `baseline` for comparison. With `--baseline snapshot`, baseline cases use the immutable old-version subject. With `--baseline none`, baseline cases receive no skill.

## Strict data and limits

Runner configs, adapter outputs, grading, evidence, and benchmarks use strict JSON. `NaN` and Infinity are invalid. Timing values must be finite and non-negative.

Configure practical limits for:

- stdout and stderr bytes;
- artifact bytes and complete filesystem-entry count;
- execution-workspace bytes and complete filesystem-entry count;
- durable declared changed-file bytes.

Case IDs are length-limited and case-insensitively unique. Duplicate selectors, file paths, task inputs, assertions, and broader review questions are rejected. One path cannot be both a skill file and a task input.

## Adapter contract

Read `../assets/eval-adapter-contract.md` and `../references/Automated eval runtime.md` before implementing adapters.

- Commands are argv arrays with `shell=False`.
- Target-local command paths execute from frozen role bundles.
- External executables are not invoked through an uncontrolled version probe.
- Path-bearing later arguments must resolve in the target skill; use target-local wrappers for reproducible adapter logic.
- Executor and judge receive separate bundles and environment allowlists.
- Executor adapters must not receive or reconstruct reference answers.
- `agent_host` mode reports fresh context, CWD, loaded skill root, or no-skill state.
- Adapters are trusted extensions, not an OS sandbox.
- Automated qualitative review identifies `reviewer_type` and remains provisional.

## Self-improve lifecycle cases

For enabled self-improve packages, test:

- strict current and historical evidence schema;
- stable caller-provided `run_id`;
- exactly-once behavior under the lifecycle lock;
- active/archive idempotency and conflict handling;
- atomic summary update;
- stable `rollover_id` and sidecar manifest;
- rollover recovery without altering a later active window;
- symlink and hard-link rejection;
- `written`, `blocked`, and pre-run-only `skipped` semantics.

## Validation

Run one command:

```bash
bash scripts/test-all.sh
```

`test-all.sh` is the single source of truth for static and deterministic validation. CI should invoke it directly rather than maintain another test list.

The automated Stage 3 suite supports Linux and macOS. Use WSL or another Unix-compatible environment on Windows.

## Review output

Review actual outputs together with provisional grades, redacted diagnostics, execution identity, workspace diff and undeclared changes, declared persisted artifacts, frozen subject/config/adapter manifests, paired-comparison status, unattempted work, and environmental limitations.

Do not infer acceptance solely from assertion pass rate.
