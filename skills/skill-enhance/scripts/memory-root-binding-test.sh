#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "memory root binding test failed: $*" >&2
  exit 1
}

REPO="$TMP/repository"
TARGET="$REPO/.agents/skills/release-helper"
HELPER_REL=".agents/skills/release-helper/scripts/append-memory.py"
TARGET_REL=".agents/skills/release-helper"
mkdir -p "$TARGET/scripts"
printf '# Repository Root\n' > "$REPO/SKILL.md"
printf '# Release Helper\n' > "$TARGET/SKILL.md"
cp "$ROOT/assets/append-memory-entry-template.py" "$TARGET/scripts/append-memory.py"
cp "$ROOT/assets/append-memory-template.py" "$TARGET/scripts/append-memory-runtime.py"
chmod +x "$TARGET/scripts/append-memory.py"

entry='{"timestamp":"2026-07-13T00:00:00Z","run_id":"root-binding-1","goal":"verify target binding","actions_taken":["invoked helper from repository root"],"outcome":"memory was written to the installed skill","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"cwd-based root guessing","suggested_followup":"keep using the target-bound entrypoint","artifacts":[],"memory_write_status":"written"}'

result="$(
  cd "$REPO"
  python3 "$HELPER_REL" append --entry-json "$entry"
)"
[[ "$result" == *'"status": "written"'* ]] \
  || fail "target-bound append did not report written"
[[ -s "$TARGET/memory/evidence.jsonl" ]] \
  || fail "target-bound append did not write inside the installed skill"
[[ ! -e "$REPO/memory" ]] \
  || fail "helper wrote memory under the shell working directory"

matching="$(
  cd "$REPO"
  python3 "$HELPER_REL" \
    --skill-root "$TARGET_REL" \
    append \
    --entry-json "$entry"
)"
[[ "$matching" == *'"status": "already_present"'* ]] \
  || fail "matching explicit root was not idempotent"

if (
  cd "$REPO"
  python3 "$HELPER_REL" \
    --skill-root . \
    append \
    --entry-json "$entry" >/dev/null 2>&1
); then
  fail "helper accepted repository root as a fallback skill root"
fi
[[ ! -e "$REPO/memory" ]] \
  || fail "mismatched explicit root created repository-root memory"

for invalid_timeout in nan inf -1 0; do
  if python3 "$TARGET/scripts/append-memory.py" \
    --lock-timeout "$invalid_timeout" \
    append \
    --entry-json "$entry" >/dev/null 2>&1; then
    fail "helper accepted invalid --lock-timeout=$invalid_timeout"
  fi
done

ln -s "$TARGET/scripts/append-memory.py" "$TMP/append-memory-link.py"
if python3 "$TMP/append-memory-link.py" append --entry-json "$entry" >/dev/null 2>&1; then
  fail "helper accepted a symlink entrypoint"
fi

echo "memory root binding test passed"
