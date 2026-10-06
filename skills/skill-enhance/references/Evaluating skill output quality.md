# Evaluating skill output quality

Use structured evals to determine whether a skill improves real tasks, remains reliable at its boundaries, and performs better than no skill or an unmodified previous version.

This reference covers eval design and interpretation. For automated execution hardening, also read [`Automated eval runtime.md`](./Automated%20eval%20runtime.md) and [`../assets/eval-adapter-contract.md`](../assets/eval-adapter-contract.md).

## Separate trigger and output evaluation

Measure two different questions:

1. **Trigger accuracy** — should the host select this skill for the request?
2. **Output quality** — once the skill is loaded, does it perform the task correctly?

Do not infer good discovery behavior from a forced skill injection. A raw-model executor can test loaded-instruction quality but cannot prove Agent Host discovery, automatic loading, tool use, or filesystem integration.

## Design realistic cases

Each output case should contain:

- `id` — stable safe identifier;
- `prompt` — realistic user request;
- `expected_output` — human-readable success description for judge-side use only;
- `files` — skill-relative files the loaded skill may use;
- `input_files` — task inputs copied from the frozen current source subject;
- `assertions` — objective observable requirements;
- `human_review` — broader provisional review questions.

Example:

```json
{
  "skill_name": "csv-analyzer",
  "evals": [
    {
      "id": 1,
      "prompt": "Find the top three months by revenue and create a labeled bar chart.",
      "expected_output": "A chart artifact plus a short explanation of the selected months.",
      "files": [
        "SKILL.md"
      ],
      "input_files": [
        "evals/files/sales.csv"
      ],
      "assertions": [
        "A chart artifact exists",
        "The chart contains exactly three months",
        "Both axes are labeled"
      ],
      "human_review": [
        "Is the result clear and immediately usable?"
      ]
    }
  ]
}
```

Start with two or three cases. Vary phrasing, detail level, and edge conditions. Use actual file and workflow shapes rather than vague prompts such as “process this data.”

## Keep reference answers away from the executor

`expected_output`, assertions, review questions, rubrics, golden answers, and judge prompts are controller-side material. They must not appear in:

- executor requests;
- executor adapter bundles;
- executor-visible skill subjects;
- task inputs.

The judge receives them only after execution evidence is normalized.

## Choose a baseline

Use one of:

- **no skill** — useful when asking whether a skill adds value at all;
- **previous version** — preferred when improving an existing skill.

A previous-version baseline must be frozen before editing:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --create-baseline
```

After editing, normal runs reuse and verify it:

```bash
bash scripts/run-evals.sh \
  --skill . \
  --workspace ./eval-workspace \
  --baseline snapshot \
  --iteration iteration-1
```

Do not use `cp -r` after editing and call the result a previous-version baseline. When the freeze was missed, recover an unmodified source through `--baseline-source`, or report that the comparison is unavailable.

## Three-stage lifecycle

### Stage 1 — bootstrap and edit

`skill-enhance` resolves target, scope, direction, and optional capabilities; freezes a requested previous-version baseline before editing; then changes the target and installs only approved packages.

### Stage 2 — deterministic workspace preparation

`run-evals.sh` validates paths, creates or verifies the immutable baseline, and prepares the iteration directory. It does not run cases or grade outputs.

### Stage 3 — isolated execution and provisional grading

`run-eval-cases.py`:

- freezes current, optional baseline, inputs, runner config, and role-specific adapters once;
- revalidates frozen subjects before and after every case;
- executes each case from a fresh temporary root;
- records bounded, secret-safe evidence;
- runs a separate judge;
- writes grading and benchmark results;
- leaves acceptance pending for user review.

Use only the hardened public entry and install every bundled `eval_*.py` module with it.

## Write useful assertions

Good assertions are specific and observable:

```text
The output file is valid JSON
The chart contains exactly three bars
The final response reports the generated file path
The skill does not create memory files when self-improve is disabled
```

Weak assertions are vague or brittle:

```text
The output is good
The response uses one exact phrase
The answer feels professional
```

Put broad style, clarity, and usability questions in `human_review`. Automated judgments over these questions are provisional and must identify their reviewer type.

## Require concrete grading evidence

For every assertion result, store:

```json
{
  "text": "The chart contains exactly three bars",
  "passed": true,
  "evidence": "Controller inventory found chart.png; visual inspection identified March, July, and November"
}
```

A PASS without concrete evidence is not a trustworthy grade.

Use scripts for mechanical checks when possible. Use an LLM judge for semantic or holistic criteria that cannot be reliably expressed as code.

## Evidence to review

Do not review only the final assistant text. Inspect:

- executor and judge status;
- redacted stdout and stderr;
- execution identity metadata;
- workspace diff and undeclared changes;
- verified artifacts and hashes;
- frozen subject/config/adapter manifests;
- assertion and qualitative grades;
- paired-comparison completeness;
- environmental limitations.

Changed-file content is not automatically persisted. The hardened controller initially records metadata only, then copies only verified declared regular files that pass size, stable-hash, and secret checks. Undeclared changed-file content remains metadata-only.

## Timing and resource data

Timing may include:

```json
{
  "duration_ms": 23332,
  "total_tokens": 84852
}
```

Values must be finite and non-negative. Boolean values, negative values, `NaN`, and Infinity are invalid.

Configure practical limits for output, artifacts, workspace size/count, and durable changed-file content. A failed limit check is execution evidence, not a result to ignore.

## Aggregate paired results

Compute deltas only over case IDs that completed in both compared configurations.

A benchmark should distinguish:

- paired completed cases;
- unpaired completed cases;
- failed cases;
- complete, partial, or unavailable comparison status;
- pass-rate, time, and token deltas where both values exist.

Do not compare unmatched means as if they came from identical cases.

## Interpret patterns

After an iteration:

- remove assertions that always pass in both configurations and reveal no skill value;
- investigate assertions that fail in both configurations;
- study requirements that pass only with the skill;
- tighten ambiguous instructions when results vary;
- inspect time, token, artifact, or workspace outliers;
- review undeclared changes and evidence redactions;
- distinguish model limitations from skill-instruction weaknesses.

## Human acceptance

Automated grading can execute cases, normalize evidence, and recommend follow-up. It must not automatically accept or apply a skill change unless the user explicitly delegates a defined acceptance policy.

Default final state:

```json
{
  "acceptance": {
    "status": "pending_user_review",
    "user_controlled": true
  }
}
```

Review actual outputs and lifecycle artifacts before deciding to keep, revise, or reject the change.

## Deterministic validation

For the bundled `skill-enhance` package, run:

```bash
bash scripts/test-all.sh
```

This is the single source of truth for the deterministic regression suite. CI should call this entry rather than duplicate its internal test list.
