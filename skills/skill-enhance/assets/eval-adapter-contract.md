# Eval adapter contract

`run-eval-cases.py` is the only supported public Stage 3 entry. It checks public-entry paths, enables the internal entry guard, and then invokes one executor and one judge process per selected case/configuration. Internal `eval_*.py` modules are implementation details and must reject standalone use.

The controller directly imports its mandatory policy, freezing, execution, and evidence implementations. Startup does not replace functions in other modules. Executor and judge processes remain the configurable adapters.

Each adapter reads one strict UTF-8 JSON object from stdin, writes one strict UTF-8 JSON object to stdout, and may write diagnostics to stderr. The controller invokes argv arrays with `shell=False`. Do not hide adapter source in `sh -c`, `bash -c`, `python -c`, or another inline command string when reproducible frozen adapter bytes are required.

## Platform and trust boundary

Automated Stage 3 supports Linux and macOS. On Windows, use WSL or another Unix-compatible environment.

Executor and judge adapters are trusted controller extensions. The controller constrains the paths and environment values it provides, validates outputs, bounds resource use, and terminates the process group on timeout. This is not an operating-system sandbox: a malicious adapter may access anything available to the OS account. Use a container, sandbox profile, or restricted account for untrusted adapters.

## Runner configuration

A hardened adapter configuration looks like:

```json
{
  "executor": {
    "command": [
      "python3",
      "scripts/eval-adapters/executor/agent-host-executor.py"
    ],
    "bundle_paths": [
      "scripts/eval-adapters/executor"
    ],
    "env_passthrough": [
      "OPENAI_API_KEY"
    ],
    "timeout_seconds": 300
  }
}
```

`bundle_paths` may include only required target-local code or assets under `scripts/`. Recommended roots are:

```text
scripts/eval-adapters/executor/
scripts/eval-adapters/judge/
```

Executor and judge bundles are assembled separately. A shared dispatcher may be selected by both roles, but it is copied independently into both role bundles.

Executor bundles must not contain `SKILL.md`, `references/`, `assets/`, `memory/`, `evals/`, grading material, rubrics, expected outputs, golden answers, or reference answers. A judge may include a judge-only rubric or prompt asset under its private `scripts/eval-adapters/judge/` subtree; that path must never be shared with the executor bundle.

Target-local command files are included automatically. Imported modules and prompt assets must be listed explicitly. Path-bearing command arguments must resolve inside the target skill and are rewritten to the frozen role bundle. An external first executable such as `python3`, `codex`, or another Agent Host CLI may be resolved by the controller; later absolute or parent-traversing command arguments are rejected.

`env_passthrough` is an explicit allowlist of host environment-variable names. Treat every exposed value as confidential. The controller does not inherit the complete host environment. It creates temporary `HOME` and temp directories, sets `PWD` to the selected CWD, disables Python user-site loading, and excludes controller-managed variables such as `OLDPWD`, `PYTHONPATH`, `PYTHONHOME`, `GITHUB_WORKSPACE`, and `RUNNER_WORKSPACE`.

The runner config also defines limits for stdout, stderr, artifact bytes/count, workspace bytes/count, and durable changed-file bytes. Timeout values must be finite positive numbers. Exceeding a limit fails the adapter run.

## Mandatory hardened lifecycle

At iteration creation, the controller freezes:

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

The complete source subjects remain for provenance and judge-side case loading. Executor subjects are sanitized copies.

Before each case, the controller verifies persistent tree and control-file hashes against the frozen manifest. Each copy into a temporary case root must also match the original manifest digest, closing the verify-then-copy race. Adapter diagnostics are followed by another frozen-subject check, and subjects are checked again before final benchmark aggregation.

Each case receives a fresh temporary execution root containing only:

```text
adapter/    executor-only bundle
skill/      selected sanitized current or baseline subject
inputs/     selected frozen task inputs
artifacts/  temporary artifact directory
neutral/    no-skill CWD
```

The executor is not given persistent workspace, iteration, provenance, or manifest paths. Controller-generated absolute paths in the request are temporary-root paths. User-authored prompt or `execution_context` values remain task data and should not contain live controller paths.

## Reference-answer isolation

Executor-visible skill and adapter trees remove eval-control or reference-answer material regardless of its top-level directory. Sensitive names include:

```text
evals.json
runner.json
judge prompts
grading
benchmark
rubric
expected-output
golden-answer
reference-answer
```

Sensitive paths are forbidden in executor case `files`, case `input_files`, and executor bundles. Ordinary operational references such as `references/reference-architecture.md` are not removed merely because their names begin with `reference-`.

The executor request never contains:

- `expected_output`;
- assertions;
- broader review questions;
- judge rubrics or grading contracts;
- reference answers.

The judge receives the complete case only after normalized execution evidence is available.

## Secret and environment handling

Only explicit passthrough variable names are exposed. Their values:

- are never stored in manifests;
- must not appear inline in adapter argv;
- are redacted from stdout, stderr, status errors, raw JSON payloads, and durable controller JSON written during the case;
- prevent changed-file or artifact bytes from being persisted when an exact value is detected;
- are checked again across the completed durable case bundle.

If an adapter fails while confidential values were exposed, potentially truncated stdout/stderr is omitted rather than persisted. Exact-value redaction is a fallback, not permission for adapters to print credentials. Transformed, encoded, or otherwise derived secrets cannot be recognized reliably and must never be emitted by an adapter.

External executable paths may be recorded, but the controller does not execute an uncontrolled `--version` probe with the full host environment.

## Executor request

Important fields:

- `request_type`: `execute_eval_case`;
- `case_id` and `configuration`;
- `baseline_kind`: `not_applicable`, `snapshot`, or `no_skill`;
- `executor_mode`: `agent_host` or `raw_model_injection`;
- `fresh_context_required`: always `true`;
- `selected_skill_root`: temporary sanitized skill root, or `null`;
- `execution_workspace_root` and `execution_working_directory`;
- declared `skill_files` and staged `task_input_files`;
- omitted skill files for no-skill runs;
- prompt, execution context, and temporary output directory.

## Executor response

```json
{
  "assistant_response": "...",
  "touched_files": [
    "skill/generated.txt"
  ],
  "artifacts": [
    "result.json"
  ],
  "timing": {
    "duration_ms": 0,
    "total_tokens": 0
  },
  "metadata": {
    "fresh_context_created": true,
    "execution_context_satisfied": true,
    "execution_cwd": "/temporary/skill",
    "loaded_skill_root": "/temporary/skill",
    "no_skill_loaded": false
  }
}
```

The response must be strict JSON. Numeric timing values must be finite and non-negative; booleans, negative values, `NaN`, and Infinity are invalid. Touched-file and artifact paths must be unique safe relative paths.

For `agent_host`, the controller validates fresh context, actual CWD, exact loaded skill root or explicit no-skill state, and required execution context.

## Evidence and diagnostics

The controller records a complete bounded workspace diff, including dot directories and bytecode/cache directories created during execution. It includes created, modified, deleted, type-changed, metadata-only, declared, and undeclared changes.

The initial workspace diff is metadata-only. Only verified declared regular files under temporary `skill/` or `neutral/` may later be persisted. Undeclared changed-file content is never copied. Adapter, environment, input, and artifact workspace areas remain metadata-only.

The complete artifact tree is bounded and inventoried. Only artifact files explicitly listed by the executor are copied into durable evidence; undeclared artifacts remain metadata-only. Every copied evidence file is opened no-follow and checked against expected size and SHA-256 while it is copied.

Adapter diagnostics are persisted before schema validation, after secret handling:

```text
executor.stdout.log
executor.stderr.log
executor-status.json
executor.raw.json
executor-runtime.json
judge.stdout.log
judge.stderr.log
judge-status.json
judge.raw.json
judge-runtime.json
```

Status files record command, return code, timeout, duration, JSON parse state, errors, redaction state, and exposed environment-variable names.

## Process lifecycle

Each adapter runs in a new process session. On timeout or output-limit violation, the controller terminates the process group, waits, escalates to `SIGKILL` when needed, and reaps the direct process. Adapters must not daemonize or intentionally leave background work running.

## Judge contract

The judge receives the complete eval case, sanitized executor result, verified artifact inventory, metadata-oriented workspace diff, configuration, executor mode, and grading contract.

It returns exactly one evidence-backed result for every assertion and every broader review question, preserving text and order. Automated qualitative results are provisional and carry the configured `reviewer_type`; they are not human approval.

## Iteration ownership and acceptance

An iteration is a locked, one-shot evidence bundle. Destructive overwrite requires a valid `.stage3-bundle.json` with matching canonical identity; an existing run manifest must also match. A valid marker-only interrupted initialization may be recovered.

When fail-fast stops a run early, `benchmark.json` records planned, attempted, failed, and unattempted case IDs separately. Unattempted cases are never presented as successful or as ordinary failures.

Final acceptance remains `pending_user_review`.

## Validation

Run the complete target-local regression set with:

```bash
bash scripts/test-all.sh
```

This is the single source of truth used by CI when CI capacity is available.
