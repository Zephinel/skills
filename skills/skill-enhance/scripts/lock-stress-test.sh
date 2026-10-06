#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MEMORY_HELPER="$SKILL_ROOT/assets/append-memory-template.py"

fail() {
  echo "lock-stress-test failed: $*" >&2
  exit 1
}

tmp="$(mktemp -d)"; tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT

for round in {1..3}; do
  target="$tmp/target-$round"
  mkdir -p "$target"
  printf '# Test Skill\n' > "$target/SKILL.md"
  run_id="stress-$round"
  entry="{\"timestamp\":\"2026-07-10T00:00:00Z\",\"run_id\":\"$run_id\",\"goal\":\"stress\",\"actions_taken\":[\"parallel append\"],\"outcome\":\"pass\",\"confidence\":\"high\",\"clarification_needed\":false,\"user_feedback\":\"\",\"failure_pattern\":\"\",\"suggested_followup\":\"none\",\"artifacts\":[],\"memory_write_status\":\"written\"}"

  pids=()
  for worker in {1..6}; do
    python3 "$MEMORY_HELPER" \
      --skill-root "$target" \
      append \
      --entry-json "$entry" >"$tmp/result-$round-$worker.json" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || fail "parallel append process failed in round $round"
  done

  [[ "$(wc -l < "$target/memory/evidence.jsonl" | tr -d ' ')" == "1" ]] \
    || fail "round $round produced duplicate evidence"
  python3 - "$tmp" "$round" <<'PY'
import glob
import json
import sys

root, round_id = sys.argv[1:]
statuses = [
    json.load(open(path, encoding="utf-8"))["status"]
    for path in glob.glob(f"{root}/result-{round_id}-*.json")
]
if statuses.count("written") != 1 or statuses.count("already_present") != 5:
    raise SystemExit(f"unexpected statuses: {statuses}")
PY

  python3 - "$target/memory/.evidence.lock" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
st = os.lstat(path)
if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink != 1:
    raise SystemExit("lifecycle lock is not a single-link regular file")
PY
done

hardlink_target="$tmp/hardlink-target"
mkdir -p "$hardlink_target"
printf '# Test Skill\n' > "$hardlink_target/SKILL.md"
entry='{"timestamp":"2026-07-10T00:00:00Z","run_id":"hardlink-run","goal":"stress","actions_taken":["initialize lock"],"outcome":"pass","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"none","artifacts":[],"memory_write_status":"written"}'
python3 "$MEMORY_HELPER" --skill-root "$hardlink_target" append --entry-json "$entry" >/dev/null
ln "$hardlink_target/memory/.evidence.lock" "$tmp/outside-lock-link"
if python3 "$MEMORY_HELPER" --skill-root "$hardlink_target" append --entry-json "$entry" >/dev/null 2>&1; then
  fail "hard-linked lifecycle lock was accepted"
fi

echo "skill-enhance lock stress test passed"
