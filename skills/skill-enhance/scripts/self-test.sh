#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNNER="$SKILL_ROOT/scripts/run-evals.sh"
MEMORY_HELPER="$SKILL_ROOT/assets/append-memory-template.py"

fail() {
  echo "self-test failed: $*" >&2
  exit 1
}

make_eval_target() {
  local target="$1"
  mkdir -p "$target/evals"
  printf '%s\n' '# Test Skill' > "$target/SKILL.md"
  printf '%s\n' '# Evals' > "$target/evals/README.md"
  printf '[]\n' > "$target/evals/train-queries.json"
  printf '[]\n' > "$target/evals/validation-queries.json"
  printf '{"skill_name":"test","evals":[]}\n' > "$target/evals/evals.json"
}

make_memory_target() {
  local target="$1"
  mkdir -p "$target"
  printf '%s\n' '# Test Skill' > "$target/SKILL.md"
}

bash -n "$RUNNER"
python3 -m py_compile "$MEMORY_HELPER"
python3 - "$SKILL_ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for path in sorted(root.rglob("*.json")):
    json.loads(path.read_text(encoding="utf-8"))
PY

tmp="$(mktemp -d)"; tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT

canonical_root="$tmp/canonical"
make_eval_target "$canonical_root/target"
if (
  cd "$canonical_root"
  bash "$RUNNER" \
    --skill ./target \
    --workspace ./missing/../target \
    --baseline snapshot \
    --create-baseline \
    --allow-dirty-baseline >/dev/null 2>&1
); then
  fail "non-canonical workspace path bypassed workspace == skill protection"
fi
[[ ! -e "$canonical_root/target/skill-snapshot" ]] \
  || fail "canonical workspace rejection still created a snapshot"

target="$tmp/target"
make_eval_target "$target"
bash "$RUNNER" \
  --skill "$target" \
  --workspace "$target/eval-workspace" \
  --baseline snapshot \
  --create-baseline \
  --allow-dirty-baseline >/dev/null

printf '\nchanged\n' >> "$target/SKILL.md"
bash "$RUNNER" \
  --skill "$target" \
  --workspace "$target/eval-workspace" \
  --baseline snapshot \
  --iteration iteration-1 >/dev/null

if grep -q changed "$target/eval-workspace/skill-snapshot/SKILL.md"; then
  fail "modified target leaked into frozen baseline"
fi

none_dry_run="$(
  bash "$RUNNER" \
    --skill "$target" \
    --workspace "$target/eval-workspace" \
    --baseline none \
    --dry-run
)"
[[ "$none_dry_run" == *"Baseline: none"* ]] || fail "baseline-none dry-run omitted Baseline: none"
[[ "$none_dry_run" != *"Snapshot reused and verified"* ]] \
  || fail "baseline-none dry-run falsely claimed snapshot verification"

printf 'tamper\n' >> "$target/eval-workspace/skill-snapshot/SKILL.md"
if bash "$RUNNER" \
  --skill "$target" \
  --workspace "$target/eval-workspace" \
  --baseline snapshot \
  --iteration iteration-2 >/dev/null 2>&1; then
  fail "tampered baseline passed integrity validation"
fi

ancestor_root="$tmp/ancestor"
make_eval_target "$ancestor_root/target"
mkdir -p "$tmp/outside"
ln -s "$tmp/outside" "$ancestor_root/target/references"
if bash "$RUNNER" \
  --skill "$ancestor_root/target" \
  --workspace "$ancestor_root" \
  --baseline snapshot \
  --create-baseline \
  --allow-dirty-baseline >/dev/null 2>&1; then
  fail "workspace-ancestor layout skipped source symlink pre-validation"
fi
[[ ! -e "$ancestor_root/skill-snapshot" ]] \
  || fail "failed source pre-validation left a snapshot behind"

symlink_target="$tmp/symlink-target"
make_eval_target "$symlink_target"
ln -s "$tmp/outside" "$symlink_target/references"
if bash "$RUNNER" \
  --skill "$symlink_target" \
  --workspace "$symlink_target/eval-workspace" \
  --baseline snapshot \
  --create-baseline \
  --allow-dirty-baseline >/dev/null 2>&1; then
  fail "symlink baseline source was accepted"
fi

tar_target="$tmp/tar-target"
make_eval_target "$tar_target"
SKILL_ENHANCE_COPY_BACKEND=tar bash "$RUNNER" \
  --skill "$tar_target" \
  --workspace "$tar_target/eval-workspace" \
  --baseline snapshot \
  --create-baseline \
  --allow-dirty-baseline >/dev/null
[[ -f "$tar_target/eval-workspace/skill-snapshot/SKILL.md" ]] \
  || fail "tar fallback did not create snapshot"

entry='{"timestamp":"2026-07-10T00:00:00Z","run_id":"run-1","goal":"test","actions_taken":["validated"],"outcome":"pass","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"none","artifacts":[],"memory_write_status":"written"}'

memory_target="$tmp/memory-target"
make_memory_target "$memory_target"
first="$(python3 "$MEMORY_HELPER" --skill-root "$memory_target" append --entry-json "$entry")"
second="$(python3 "$MEMORY_HELPER" --skill-root "$memory_target" append --entry-json "$entry")"
[[ "$first" == *'"status": "written"'* ]] || fail "first append did not report written"
[[ "$second" == *'"status": "already_present"'* ]] || fail "retry was not idempotent"
[[ "$(wc -l < "$memory_target/memory/evidence.jsonl" | tr -d ' ')" == "1" ]] \
  || fail "retry duplicated evidence"

conflict='{"timestamp":"2026-07-10T00:00:00Z","run_id":"run-1","goal":"different","actions_taken":["validated"],"outcome":"pass","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"none","artifacts":[],"memory_write_status":"written"}'
if python3 "$MEMORY_HELPER" --skill-root "$memory_target" append --entry-json "$conflict" >/dev/null 2>&1; then
  fail "conflicting content reused an existing run_id"
fi

concurrent_target="$tmp/concurrent-target"
make_memory_target "$concurrent_target"
concurrent_entry='{"timestamp":"2026-07-10T00:00:00Z","run_id":"run-concurrent","goal":"test","actions_taken":["validated"],"outcome":"pass","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"none","artifacts":[],"memory_write_status":"written"}'
python3 "$MEMORY_HELPER" --skill-root "$concurrent_target" append --entry-json "$concurrent_entry" >"$tmp/concurrent-1.out" &
pid1=$!
python3 "$MEMORY_HELPER" --skill-root "$concurrent_target" append --entry-json "$concurrent_entry" >"$tmp/concurrent-2.out" &
pid2=$!
wait "$pid1"
wait "$pid2"
[[ "$(wc -l < "$concurrent_target/memory/evidence.jsonl" | tr -d ' ')" == "1" ]] \
  || fail "concurrent append duplicated evidence"
grep -q '"status": "written"' "$tmp/concurrent-1.out" "$tmp/concurrent-2.out" \
  || fail "concurrent append did not produce one written result"
grep -q '"status": "already_present"' "$tmp/concurrent-1.out" "$tmp/concurrent-2.out" \
  || fail "concurrent append did not produce one idempotent result"

rollover_target="$tmp/rollover-target"
make_memory_target "$rollover_target"
python3 "$MEMORY_HELPER" --skill-root "$rollover_target" append --entry-json "$entry" >/dev/null
rollover_result="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$rollover_target" \
    rollover \
    --archive-name 2026-07-10-iteration-1-evidence.jsonl \
    --rollover-id iteration-1-accepted-change
)"
[[ "$rollover_result" == *'"status": "rolled_over"'* ]] || fail "rollover did not report rolled_over"
[[ "$rollover_result" == *'"rollover_id": "iteration-1-accepted-change"'* ]] \
  || fail "rollover result omitted its stable operation ID"
manifest="$rollover_target/memory/archive/2026-07-10-iteration-1-evidence.jsonl.rollover.json"
[[ -s "$manifest" ]] || fail "rollover sidecar manifest was not created"
python3 - "$manifest" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
if value["schema_version"] != 1:
    raise SystemExit("unexpected rollover manifest version")
if value["rollover_id"] != "iteration-1-accepted-change":
    raise SystemExit("rollover manifest lost the operation ID")
if value["archive_name"] != "2026-07-10-iteration-1-evidence.jsonl":
    raise SystemExit("rollover manifest lost the archive binding")
if value["source_record_count"] != 1:
    raise SystemExit("rollover manifest has the wrong source record count")
PY

retry_rollover="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$rollover_target" \
    rollover \
    --archive-name 2026-07-10-iteration-1-evidence.jsonl \
    --rollover-id iteration-1-accepted-change
)"
[[ "$retry_rollover" == *'"status": "already_rolled_over"'* ]] \
  || fail "same rollover operation did not return already_rolled_over"

retry_after_rollover="$(
  python3 "$MEMORY_HELPER" --skill-root "$rollover_target" append --entry-json "$entry"
)"
[[ "$retry_after_rollover" == *'"status": "already_present"'* ]] \
  || fail "retry after rollover did not find archived run_id"
[[ ! -s "$rollover_target/memory/evidence.jsonl" ]] \
  || fail "retry after rollover polluted the new active window"

new_window_entry='{"timestamp":"2026-07-10T01:00:00Z","run_id":"run-2","goal":"new window","actions_taken":["observed"],"outcome":"pass","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"none","artifacts":[],"memory_write_status":"written"}'
python3 "$MEMORY_HELPER" --skill-root "$rollover_target" append --entry-json "$new_window_entry" >/dev/null
late_retry="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$rollover_target" \
    rollover \
    --archive-name 2026-07-10-iteration-1-evidence.jsonl \
    --rollover-id iteration-1-accepted-change
)"
[[ "$late_retry" == *'"status": "already_rolled_over"'* ]] \
  || fail "a completed rollover was not idempotent after the new window gained records"
[[ "$(wc -l < "$rollover_target/memory/evidence.jsonl" | tr -d ' ')" == "1" ]] \
  || fail "retrying an old rollover modified the new observation window"

if python3 "$MEMORY_HELPER" \
  --skill-root "$rollover_target" \
  rollover \
  --archive-name 2026-07-10-iteration-1-evidence.jsonl \
  --rollover-id unrelated-operation >/dev/null 2>&1; then
  fail "reusing an archive name with another rollover_id was accepted"
fi
if python3 "$MEMORY_HELPER" \
  --skill-root "$rollover_target" \
  rollover \
  --archive-name another-evidence.jsonl \
  --rollover-id iteration-1-accepted-change >/dev/null 2>&1; then
  fail "reusing a rollover_id with another archive name was accepted"
fi

missing_active_target="$tmp/missing-active-rollover"
make_memory_target "$missing_active_target"
python3 "$MEMORY_HELPER" --skill-root "$missing_active_target" append --entry-json "$entry" >/dev/null
python3 "$MEMORY_HELPER" \
  --skill-root "$missing_active_target" \
  rollover \
  --archive-name recovery-evidence.jsonl \
  --rollover-id recovery-operation >/dev/null
rm "$missing_active_target/memory/evidence.jsonl"
recovered_rollover="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$missing_active_target" \
    rollover \
    --archive-name recovery-evidence.jsonl \
    --rollover-id recovery-operation
)"
[[ "$recovered_rollover" == *'"status": "already_rolled_over"'* ]] \
  || fail "completed rollover did not recover a missing active window"
[[ -f "$missing_active_target/memory/evidence.jsonl" && ! -s "$missing_active_target/memory/evidence.jsonl" ]] \
  || fail "rollover recovery did not recreate an empty active window"

unmanifested_target="$tmp/unmanifested-rollover"
make_memory_target "$unmanifested_target"
mkdir -p "$unmanifested_target/memory/archive"
: > "$unmanifested_target/memory/evidence.jsonl"
printf '%s\n' "$entry" > "$unmanifested_target/memory/archive/reused-evidence.jsonl"
if python3 "$MEMORY_HELPER" \
  --skill-root "$unmanifested_target" \
  rollover \
  --archive-name reused-evidence.jsonl \
  --rollover-id new-operation >/dev/null 2>&1; then
  fail "an unmanifested old archive was treated as an idempotent rollover"
fi

prepared_target="$tmp/prepared-rollover"
make_memory_target "$prepared_target"
python3 "$MEMORY_HELPER" --skill-root "$prepared_target" append --entry-json "$entry" >/dev/null
mkdir -p "$prepared_target/memory/archive"
python3 - "$prepared_target/memory/evidence.jsonl" "$prepared_target/memory/archive/prepared-evidence.jsonl.rollover.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_bytes()
manifest = {
    "schema_version": 1,
    "rollover_id": "prepared-operation",
    "archive_name": "prepared-evidence.jsonl",
    "source_sha256": hashlib.sha256(source).hexdigest(),
    "source_bytes": len(source),
    "source_record_count": 1,
}
Path(sys.argv[2]).write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
prepared_result="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$prepared_target" \
    rollover \
    --archive-name prepared-evidence.jsonl \
    --rollover-id prepared-operation
)"
[[ "$prepared_result" == *'"status": "rolled_over"'* ]] \
  || fail "prepared-manifest recovery did not finish the rollover"

manifest_tamper_target="$tmp/manifest-tamper"
make_memory_target "$manifest_tamper_target"
python3 "$MEMORY_HELPER" --skill-root "$manifest_tamper_target" append --entry-json "$entry" >/dev/null
python3 "$MEMORY_HELPER" \
  --skill-root "$manifest_tamper_target" \
  rollover \
  --archive-name tamper-evidence.jsonl \
  --rollover-id tamper-operation >/dev/null
printf 'tamper\n' >> "$manifest_tamper_target/memory/archive/tamper-evidence.jsonl.rollover.json"
if python3 "$MEMORY_HELPER" \
  --skill-root "$manifest_tamper_target" \
  rollover \
  --archive-name tamper-evidence.jsonl \
  --rollover-id tamper-operation >/dev/null 2>&1; then
  fail "tampered rollover manifest was accepted"
fi

memory_symlink="$tmp/memory-symlink"
make_memory_target "$memory_symlink"
ln -s "$tmp/outside" "$memory_symlink/memory"
if python3 "$MEMORY_HELPER" --skill-root "$memory_symlink" append --entry-json "$entry" >/dev/null 2>&1; then
  fail "memory directory symlink was accepted"
fi

evidence_symlink="$tmp/evidence-symlink"
make_memory_target "$evidence_symlink"
mkdir -p "$evidence_symlink/memory"
ln -s "$tmp/outside/evidence.jsonl" "$evidence_symlink/memory/evidence.jsonl"
if python3 "$MEMORY_HELPER" --skill-root "$evidence_symlink" append --entry-json "$entry" >/dev/null 2>&1; then
  fail "evidence file symlink was accepted"
fi

evidence_hardlink="$tmp/evidence-hardlink"
make_memory_target "$evidence_hardlink"
mkdir -p "$evidence_hardlink/memory"
: > "$tmp/outside-evidence.jsonl"
ln "$tmp/outside-evidence.jsonl" "$evidence_hardlink/memory/evidence.jsonl"
if python3 "$MEMORY_HELPER" --skill-root "$evidence_hardlink" append --entry-json "$entry" >/dev/null 2>&1; then
  fail "hard-linked evidence file was accepted"
fi

manifest_symlink="$tmp/manifest-symlink"
make_memory_target "$manifest_symlink"
python3 "$MEMORY_HELPER" --skill-root "$manifest_symlink" append --entry-json "$entry" >/dev/null
mkdir -p "$manifest_symlink/memory/archive"
ln -s "$tmp/outside-manifest.json" "$manifest_symlink/memory/archive/blocked-evidence.jsonl.rollover.json"
if python3 "$MEMORY_HELPER" \
  --skill-root "$manifest_symlink" \
  rollover \
  --archive-name blocked-evidence.jsonl \
  --rollover-id blocked-operation >/dev/null 2>&1; then
  fail "rollover manifest symlink was accepted"
fi

manifest_hardlink="$tmp/manifest-hardlink"
make_memory_target "$manifest_hardlink"
python3 "$MEMORY_HELPER" --skill-root "$manifest_hardlink" append --entry-json "$entry" >/dev/null
mkdir -p "$manifest_hardlink/memory/archive"
: > "$tmp/outside-rollover-manifest.json"
ln "$tmp/outside-rollover-manifest.json" "$manifest_hardlink/memory/archive/blocked-evidence.jsonl.rollover.json"
if python3 "$MEMORY_HELPER" \
  --skill-root "$manifest_hardlink" \
  rollover \
  --archive-name blocked-evidence.jsonl \
  --rollover-id blocked-operation >/dev/null 2>&1; then
  fail "hard-linked rollover manifest was accepted"
fi

summary_target="$tmp/summary-target"
make_memory_target "$summary_target"
summary_result="$(
  python3 "$MEMORY_HELPER" \
    --skill-root "$summary_target" \
    update-summary \
    --summary-text '# Skill Memory Summary'
)"
[[ "$summary_result" == *'"status": "updated"'* ]] || fail "summary update did not succeed"
grep -q '^# Skill Memory Summary$' "$summary_target/memory/summary.md" \
  || fail "summary content was not stored"

summary_symlink="$tmp/summary-symlink"
make_memory_target "$summary_symlink"
mkdir -p "$summary_symlink/memory"
ln -s "$tmp/outside-summary.md" "$summary_symlink/memory/summary.md"
if python3 "$MEMORY_HELPER" \
  --skill-root "$summary_symlink" \
  update-summary \
  --summary-text '# blocked' >/dev/null 2>&1; then
  fail "summary symlink was accepted"
fi

summary_hardlink="$tmp/summary-hardlink"
make_memory_target "$summary_hardlink"
mkdir -p "$summary_hardlink/memory"
: > "$tmp/outside-summary-hardlink.md"
ln "$tmp/outside-summary-hardlink.md" "$summary_hardlink/memory/summary.md"
if python3 "$MEMORY_HELPER" \
  --skill-root "$summary_hardlink" \
  update-summary \
  --summary-text '# blocked' >/dev/null 2>&1; then
  fail "hard-linked summary file was accepted"
fi

echo "skill-enhance self-test passed"
