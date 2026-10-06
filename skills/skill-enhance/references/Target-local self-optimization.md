# Target-local self-optimization

> This reference applies only when the user explicitly enables the full `self_improve_package` and approves its required `eval_package`, or when an already-enabled package is being revised. It is not a default consequence of ordinary optimization or `整技能升级`.

## Capability boundary

- Do not add `memory/`, persistent evidence, self-improve triggers, or memory-specific closeout fields unless the capability is enabled.
- A normal execution summary does not imply persistent memory.
- Dormant files alone do not prove enablement.
- Full self-improve depends on evals because applied changes require an acceptance gate.
- Evidence collection without local modification is observation-only behavior, not a complete self-improve loop.

## Role split

- `skill-enhance` performs one grounded bootstrap improvement and installs or refreshes the opt-in package.
- The optimized target skill owns later reflection, persistence, trigger detection, confirmation, focused self-improvement, and acceptance checks.
- Evals remain the acceptance gate for keeping or rejecting later changes.
- Do not rewrite the target skill after every run.

## Authoritative target root

Resolve the target skill root once from the target `SKILL.md`, retain its canonical path for the full run, and treat that path as authoritative.

The shell working directory is not the target identity. In particular, do not use this failure-driven pattern:

```text
try repository root or `.`
→ write fails
→ retry `.agents/skills/<name>` or another guessed location
```

Install the public target-bound entry and its implementation as:

```text
<TARGET_SKILL_ROOT>/scripts/append-memory.py
<TARGET_SKILL_ROOT>/scripts/append-memory-runtime.py
```

Invoke the public entry through its path under the resolved target root:

```bash
TARGET_SKILL_ROOT=/absolute/path/to/.agents/skills/release-helper
python3 "$TARGET_SKILL_ROOT/scripts/append-memory.py" append --entry-file ./tmp/current-run-evidence.json
```

The entry derives the target root from its own verified installed location. Omitting `--skill-root` is the normal path. An explicit `--skill-root` is accepted only when it resolves to that same installed root. A mismatch is a persistence blocker; do not probe a fallback root.

## Per-run reflection

After every completed evidence-collected run, output a short closeout covering target understanding, actions, result, memory status, uncertainty, and next step.

Emit a clean closeout only after persistence resolves to `written`. Otherwise report `blocked` in the same closeout.

```text
本次执行总结
- 目标理解：...
- 实际动作：...
- 当前结果：...
- 记忆写入：已写入并验证 `memory/evidence.jsonl`，entry=<timestamp/run_id>；`memory/summary.md` <已更新/无需更新>
- 不确定点：...
- 建议下一步：...
```

Blocked form:

```text
本次执行总结
- 目标理解：...
- 实际动作：...
- 当前结果：任务动作已完成，但 self-improve 持久化未完成
- 记忆写入：失败，原因：...
- 不确定点：memory persistence 未完成
- 建议下一步：修复目标绑定、路径、权限或工具能力后，用同一 run_id 重试
```

Pre-run opt-out form:

```text
本次执行总结
- 目标理解：...
- 实际动作：...
- 当前结果：...
- 记忆写入：本次在执行前由用户明确排除出 evidence collection，未写入且不参与阈值计数
- 不确定点：...
- 建议下一步：...
```

For skills without self-improve, omit the memory-status line and do not require memory files.

## Persistence states

For a run inside evidence collection:

- `written` — exactly one complete verified object exists for the stable `run_id`.
- `blocked` — persistence could not be completed; the same closeout reports the blocker.
- `skipped` — allowed only when the user explicitly opts out before execution. No object is appended and the run is excluded from threshold counting.

Do not convert a failed append into `skipped`.

## Evidence record contract

The caller creates a stable `run_id` before execution and reuses it for every retry.

Append exactly one strict JSON object per line:

```json
{
  "timestamp": "2026-07-10T00:00:00Z",
  "run_id": "release-2.3.1-20260710",
  "goal": "Release patch version 2.3.1",
  "actions_taken": [
    "updated version files",
    "validated build",
    "pushed tag"
  ],
  "outcome": "Tag v2.3.1 was pushed; CI artifacts are pending",
  "confidence": "high",
  "clarification_needed": false,
  "user_feedback": "",
  "failure_pattern": "",
  "suggested_followup": "Monitor the CI build",
  "artifacts": [
    "tag:v2.3.1"
  ],
  "memory_write_status": "written"
}
```

The schema is exact: unsupported extra fields are rejected.

Required types and constraints:

- `timestamp` — non-empty ISO-8601 string with timezone;
- `run_id` — non-empty string, at most 256 characters;
- `goal` — non-empty string;
- `actions_taken` — array of strings;
- `outcome` — non-empty string;
- `confidence` — `high`, `medium`, or `low`;
- `clarification_needed` — boolean;
- `user_feedback` — string;
- `failure_pattern` — string;
- `suggested_followup` — non-empty string;
- `artifacts` — array of strings;
- `memory_write_status` — exactly `written` for appended records.

JSON must be strict. `NaN`, Infinity, incomplete lines, non-object lines, wrong field types, and malformed historical records are blockers. The helper applies the same schema to every existing active and archived record before using memory as threshold evidence.

Do not store secrets, credentials, tokens, private user data, or raw transcripts.

## Target-bound helper and stable lifecycle lock

Install both bundled files:

```bash
cp <skill-enhance>/assets/append-memory-entry-template.py \
  "$TARGET_SKILL_ROOT/scripts/append-memory.py"
cp <skill-enhance>/assets/append-memory-template.py \
  "$TARGET_SKILL_ROOT/scripts/append-memory-runtime.py"
chmod +x "$TARGET_SKILL_ROOT/scripts/append-memory.py"
```

Only `scripts/append-memory.py` is the public entry. It verifies:

- its own path is a non-symlink single-link file under `<target>/scripts/`;
- the sibling runtime is a non-symlink single-link regular file;
- the installed root contains the authoritative `SKILL.md`;
- an explicit `--skill-root`, when supplied, matches the installed root;
- `--lock-timeout` is finite and positive.

All persistence operations use:

```text
memory/.evidence.lock
```

The lock is independent of the current active evidence inode and remains stable across archive rollover.

These operations must acquire it:

- append and cross-window idempotency search;
- archive rollover;
- active-file recreation;
- `memory/summary.md` update.

Do not implement rollover with an ad hoc `mv`.

## Append and cross-window idempotency

Use:

```bash
python3 "$TARGET_SKILL_ROOT/scripts/append-memory.py" \
  append \
  --entry-file ./tmp/current-run-evidence.json
```

While holding the lock, the helper searches:

```text
memory/evidence.jsonl
memory/archive/*.jsonl
```

Rules:

- no matching `run_id` — append to the current active file;
- one matching identical object — return `already_present` without appending;
- one matching different object — report a conflict;
- more than one match — report that history already violates exactly-once.

The helper uses checked write-all behavior, `fsync`, failure truncation, strict schema validation, and complete-object verification.

A retry after rollover must resolve from the archive and leave the new active file unchanged.

## Path and link safety

The helper independently enforces:

- target identity is derived from the installed public entry, not the caller CWD;
- an explicit skill root cannot redirect the helper to another skill;
- the entry, runtime, `SKILL.md`, managed directories, and managed files do not traverse symlink aliases;
- `memory/` and `memory/archive/` are real directories;
- `.evidence.lock`, active evidence, archived JSONL, rollover manifests, and `summary.md` are regular single-link files;
- symbolic links and hard-linked managed files are rejected;
- maintenance files are opened relative to a verified directory FD;
- no-follow flags are used when supported;
- opened inode/device values match the final path entry;
- every generated path stays inside the resolved target skill root.

Prompt instructions alone are not a containment guarantee.

## Safe summary update

Update the digest only when repeated issues, conclusions, or the current recommendation materially change.

```bash
python3 "$TARGET_SKILL_ROOT/scripts/append-memory.py" \
  update-summary \
  --summary-file ./tmp/new-memory-summary.md
```

The helper acquires the lifecycle lock, rejects unsafe existing summary paths, writes and `fsync`s a single-link temporary file inside `memory/`, atomically replaces `summary.md`, `fsync`s the directory, and verifies stored content and inode.

`memory/summary.md` is a readable digest, not the authoritative threshold counter.

Suggested shape:

```md
# Skill Memory Summary

## Repeated Issues
- ...

## Recent Conclusions
- ...

## Current Recommendation
- ...
```

## Locked observation-window rollover

After an accepted self-improvement:

```bash
python3 "$TARGET_SKILL_ROOT/scripts/append-memory.py" \
  rollover \
  --archive-name 2026-07-10-iteration-2-evidence.jsonl \
  --rollover-id iteration-2-accepted-change
```

The caller creates one stable `rollover_id` and reuses it with the same archive basename for every retry.

Before archive rename, the helper writes:

```text
memory/archive/<archive-name>.rollover.json
```

The sidecar binds:

- `rollover_id`;
- archive basename;
- source-window SHA-256;
- source byte count;
- source record count.

`already_rolled_over` requires manifest identity and archive fingerprint verification. Reusing one archive name with another ID, one ID with another name, or an unmanifested existing archive is a conflict.

The helper supports recovery from:

- manifest prepared before archive rename;
- archive rename completed before new active-file creation.

A retry of an old completed rollover must not alter a later active window, even after the later window gains records.

Do not hard-delete prior memory. Preserve `memory/summary.md` and update it with the accepted change and new observation focus.

Threshold counting after rollover uses only the new active file. Archives remain searchable solely for global `run_id` idempotency and conflict detection.
