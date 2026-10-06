# Automated eval runtime

Use this reference only when `eval_package` includes automated case execution. It defines the mandatory runtime boundary for `scripts/run-eval-cases.py` and the bundled `eval_*.py` modules.

## Supported environments

Automated Stage 3 requires a Unix-compatible environment:

- Linux;
- macOS;
- Windows through WSL or another compatible Unix environment.

The runtime depends on Bash, Unix process groups, file locking, no-follow path checks, and Unix filesystem semantics.

## Public entry and complete package

The only supported public Stage 3 command is:

```bash
python3 scripts/run-eval-cases.py \
  --skill . \
  --workspace ./eval-workspace \
  --iteration iteration-1 \
  --baseline snapshot
```

`run-eval-cases.py` disables live-tree bytecode writes, checks public-entry paths, enables the internal entry guard, and then enters the controller with direct implementation dependencies. Do not invoke `eval_runner.py`, compatibility exports, or another `eval_*.py` module directly.

Install these together:

```text
scripts/run-eval-cases.py
scripts/eval_*.py
evals/runner.json
```

## Stage 2 and Stage 3

Stage 2, `scripts/run-evals.sh`, performs:

- raw and canonical path validation;
- immutable previous-version baseline creation or verification;
- iteration-directory scaffolding.

Stage 3 performs:

- strict config and case selection;
- frozen-subject creation;
- isolated executor and judge invocation;
- bounded evidence validation and persistence;
- provisional grading;
- paired benchmark aggregation.

Neither stage accepts a skill change. Acceptance remains `pending_user_review`.

## Frozen subjects and point-in-time binding

One iteration freezes:

```text
subjects/source-current/
subjects/current/
subjects/source-baseline/
subjects/baseline/
subjects/inputs/
subjects/adapters/executor/
subjects/adapters/judge/
subjects/adapters/runner.source.json
subjects/adapters/runner.effective.json
subjects/adapters/runtime-policy.json
```

`source-*` roots preserve complete provenance. `current` and `baseline` are sanitized execution subjects. Inputs are selected from frozen `source-current`, not reread from the live target.

The source runner config, core config, environment policy, limits, effective config, role bundles, and subject manifests are bound to hashes from one stable no-follow snapshot. The frozen runtime policy must be derivable from the copied source config.

Before each case, after adapter diagnostics, during every subject copy, and before benchmark aggregation, the controller verifies:

- current and optional baseline source trees;
- sanitized current and optional baseline trees;
- frozen inputs;
- executor and judge bundles;
- source and effective runner configs;
- runtime policy;
- subject and adapter manifests.

A temporary copy must match the original frozen manifest digest, not merely the persistent directory at copy time. Any mutation aborts the run.

## Adapter bundle boundary

Executor and judge adapters are trusted extensions, but each receives a separate role bundle. Recommended roots are:

```text
scripts/eval-adapters/executor/
scripts/eval-adapters/judge/
```

`bundle_paths` may include only required target-local files under `scripts/`.

The executor bundle must not expose:

```text
SKILL.md
references/
assets/
memory/
evals/
grading or benchmark material
rubrics
expected outputs
golden or reference answers
```

A judge may include judge-only rubric or prompt assets under its private `scripts/eval-adapters/judge/` subtree. Those paths must never be shared with the executor bundle.

A shared dispatcher may serve both roles, but it is copied independently into each role bundle.

An external first executable such as `python3` or an Agent Host CLI may be resolved. Path-bearing later arguments must resolve inside the target skill and are rewritten to frozen role-bundle paths. Absolute external arguments and parent traversal are rejected. Use a target-local wrapper instead of inline shell or interpreter source when reproducible frozen bytes are required.

External executables are recorded without running an uncontrolled `--version` probe with the full host environment.

## No-skill and previous-version baselines

For a no-skill baseline:

- `selected_skill_root` is `null`;
- no current-skill file is exposed through the request;
- the working directory is neutral and has no discoverable parent `SKILL.md`;
- the executor bundle still contains only executor adapter code.

For a snapshot baseline:

- the selected subject is the immutable old version frozen before editing;
- the current skill is not used as baseline material;
- baseline integrity is revalidated after the iteration lock is acquired.

## Executor request isolation

Executor requests include only task-execution material:

- case ID and configuration;
- prompt;
- selected temporary skill root or explicit no-skill state;
- declared skill files;
- staged task inputs;
- execution context;
- temporary artifact directory.

They must not include:

- `expected_output`;
- assertions;
- broader review questions;
- judge prompts or grading contracts;
- reference answers;
- persistent workspace, iteration, or provenance paths generated by the controller.

The judge receives the complete case only after execution evidence has been normalized.

## Environment and secret handling

Adapters inherit a minimal controller-managed environment plus explicit `env_passthrough` names. The controller creates temporary `HOME`, temp directories, and `PWD`, and excludes controller-sensitive variables such as `OLDPWD`, `PYTHONPATH`, `PYTHONHOME`, `GITHUB_WORKSPACE`, and `RUNNER_WORKSPACE`.

Explicit passthrough values:

- must not appear inline in adapter argv;
- are redacted from stdout, stderr, status errors, raw JSON payloads, and controller JSON written during the case;
- are recorded only by variable name;
- prevent changed-file or artifact bytes from being persisted when an exact value is detected;
- are audited again across the durable case bundle.

If an adapter fails while confidential values were exposed, potentially truncated logs are omitted rather than persisted.

Exact-value redaction cannot reliably identify transformed or encoded secrets. Adapters must never emit credentials. Adapters remain trusted extensions, not an OS sandbox.

## Strict data and bounded execution

`evals/runner.json` defines limits such as:

```json
{
  "limits": {
    "stdout_bytes": 10485760,
    "stderr_bytes": 10485760,
    "artifact_total_bytes": 104857600,
    "artifact_file_count": 1000,
    "workspace_file_count": 10000,
    "workspace_total_bytes": 262144000,
    "persisted_workspace_bytes": 52428800
  }
}
```

`workspace_file_count` and `artifact_file_count` are enforced as complete filesystem-entry limits, including directories, so a large empty directory tree cannot bypass them.

The controller fails closed on output, artifact, workspace, or durable-content limits. Timeouts and output-limit violations terminate and reap the adapter process group.

Runner configs, adapter responses, grading, evidence, and benchmarks use strict JSON. Timing values must be finite and non-negative. Booleans, negative numbers, `NaN`, and Infinity are invalid.

Case IDs are length-limited and case-insensitively unique for macOS portability. Duplicate selectors, file paths, task inputs, assertions, and broader review questions are rejected. One path cannot be both a skill file and a task input.

## Workspace and artifact evidence

The complete before/after workspace inventory includes dot directories, caches, bytecode directories, created, modified, deleted, type-changed, and metadata-only entries. Symlinks, special files, and multi-link files are rejected.

The initial workspace diff is metadata-only. Content persistence follows these rules:

- adapter, environment, input, and artifact workspace areas remain metadata-only;
- undeclared changed-file content is never copied;
- only verified declared regular files under temporary `skill/` or `neutral/` may be copied;
- declared content containing an explicit passthrough secret remains metadata-only;
- the complete artifact tree is bounded and inventoried;
- only artifacts explicitly declared by the executor are copied; undeclared artifacts remain metadata-only.

Every copied input, changed file, and artifact uses no-follow descriptors, expected size and SHA-256, inode checks, preserved mode, and post-copy verification.

## Adapter output and judging

An executor returns one strict JSON object. In `agent_host` mode it must confirm:

- fresh context creation;
- actual execution CWD;
- exact loaded skill root, or explicit no-skill state;
- required execution context when the case declares one.

Touched-file and artifact paths must be unique safe relative paths.

The judge returns exactly one evidence-backed result for every assertion and broader review question, preserving text and order. Automated qualitative results are provisional and identify their `reviewer_type`; they are not human approval.

## Iteration ownership and fail-fast reporting

An iteration is a locked one-shot evidence bundle.

Workspace ownership markers and lock paths retain `.stage3-bundle.json` and `.stage3-locks/` for compatibility. These are persistent format names, not module names.

- A non-empty iteration is rejected by default.
- `--overwrite` requires a valid `.stage3-bundle.json` proving exact canonical ownership.
- An existing run manifest must prove the same identity.
- A valid marker-only interrupted initialization may be rebuilt.
- The live skill and frozen baseline are protected roots.

When fail-fast stops execution early, `benchmark.json` records planned, attempted, failed, and unattempted case IDs separately. Unattempted work is not reported as success or ordinary failure.

## Validation

Run the single canonical suite:

```bash
bash scripts/test-all.sh
```

It performs static shell/Python/strict-JSON checks and all deterministic Stage 2, Stage 3, reference-isolation, no-skill, runtime-hardening, self-improve, path-safety, and lock-stress regressions. CI should invoke this command directly rather than maintain another test list.
