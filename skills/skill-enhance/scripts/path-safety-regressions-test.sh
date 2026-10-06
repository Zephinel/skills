#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
STAGE2="$ROOT/scripts/run-evals.sh"
STAGE3="$ROOT/scripts/run-eval-cases.py"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "path safety regression failed: $*" >&2
  exit 1
}

make_target() {
  local target="$1"
  mkdir -p "$target/evals" "$target/scripts"
  cp "$ROOT/scripts/run-evals.sh" "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"stage3_*.py "$target/scripts/"
  chmod +x "$target/scripts/run-evals.sh" "$target/scripts/run-eval-cases.py"
  printf '# Test Skill\n' > "$target/SKILL.md"
  printf '# Evals\n' > "$target/evals/README.md"
  printf '[]\n' > "$target/evals/train-queries.json"
  printf '[]\n' > "$target/evals/validation-queries.json"
  printf '{"skill_name":"path-safety","evals":[]}\n' > "$target/evals/evals.json"
  cat > "$target/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["true"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["true"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":false},"acceptance":{"user_controlled":true}}
JSON
}

TARGET="$TMP/target"
WORKSPACE="$TMP/workspace"
mkdir -p "$WORKSPACE/important-data"
make_target "$TARGET"

printf 'keep-me\n' > "$WORKSPACE/important-data/sentinel.txt"
ln -s important-data "$WORKSPACE/skill-snapshot"
if bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --create-baseline --reset-baseline --allow-dirty-baseline >/dev/null 2>&1; then
  fail "snapshot symlink was accepted by --reset-baseline"
fi
test -f "$WORKSPACE/important-data/sentinel.txt" || fail "snapshot symlink target was modified"
rm "$WORKSPACE/skill-snapshot"

bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --create-baseline --allow-dirty-baseline >/dev/null
manifest_before="$(python3 - "$WORKSPACE/skill-snapshot/.baseline-manifest.json" <<'PY'
import hashlib,sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PY
)"

ln -s skill-snapshot/hidden-iteration "$WORKSPACE/alias"
if bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --iteration alias >/dev/null 2>&1; then
  fail "Stage 2 accepted an iteration symlink into the frozen baseline"
fi
if python3 "$STAGE3" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --iteration alias --dry-run >/dev/null 2>&1; then
  fail "Stage 3 accepted a raw iteration symlink"
fi
manifest_after="$(python3 - "$WORKSPACE/skill-snapshot/.baseline-manifest.json" <<'PY'
import hashlib,sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PY
)"
[[ "$manifest_before" == "$manifest_after" ]] || fail "baseline manifest changed after alias rejection"
test ! -e "$WORKSPACE/skill-snapshot/hidden-iteration" || fail "iteration alias created content in baseline"
rm "$WORKSPACE/alias"

bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --iteration lock-baseline >/dev/null
ln -s skill-snapshot "$WORKSPACE/.stage3-locks"
if python3 "$STAGE3" --skill "$TARGET" --workspace "$WORKSPACE" --baseline snapshot \
  --iteration lock-baseline --dry-run >/dev/null 2>&1; then
  fail "Stage 3 accepted a lock-directory symlink into the baseline"
fi
test ! -e "$WORKSPACE/skill-snapshot/lock-baseline.lock" || fail "lock file was written into baseline"
rm "$WORKSPACE/.stage3-locks"

ANCESTOR="$TMP/ancestor"
ANCESTOR_TARGET="$ANCESTOR/target"
make_target "$ANCESTOR_TARGET"
mkdir -p "$ANCESTOR/iteration-live"
ln -s target "$ANCESTOR/.stage3-locks"
if python3 "$ANCESTOR_TARGET/scripts/run-eval-cases.py" --skill "$ANCESTOR_TARGET" \
  --workspace "$ANCESTOR" --baseline none --iteration iteration-live --dry-run >/dev/null 2>&1; then
  fail "Stage 3 accepted a lock-directory symlink into the live skill"
fi
test ! -e "$ANCESTOR_TARGET/iteration-live.lock" || fail "lock file was written into live skill"

TAMPER_TARGET="$TMP/tamper-target"
TAMPER_WORKSPACE="$TMP/tamper-workspace"
make_target "$TAMPER_TARGET"
bash "$TAMPER_TARGET/scripts/run-evals.sh" --skill "$TAMPER_TARGET" --workspace "$TAMPER_WORKSPACE" \
  --baseline snapshot --create-baseline --allow-dirty-baseline >/dev/null
bash "$TAMPER_TARGET/scripts/run-evals.sh" --skill "$TAMPER_TARGET" --workspace "$TAMPER_WORKSPACE" \
  --baseline snapshot --iteration tampered >/dev/null
printf 'tamper\n' >> "$TAMPER_WORKSPACE/skill-snapshot/SKILL.md"
if python3 "$TAMPER_TARGET/scripts/run-eval-cases.py" --skill "$TAMPER_TARGET" \
  --workspace "$TAMPER_WORKSPACE" --baseline snapshot --iteration tampered >/dev/null 2>&1; then
  fail "Stage 3 accepted a baseline modified after Stage 2 verification"
fi

bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline none \
  --iteration marker-only >/dev/null
python3 - "$TARGET" "$WORKSPACE" <<'PY'
import json,sys
from pathlib import Path
skill=Path(sys.argv[1]).resolve(); workspace=Path(sys.argv[2]).resolve(); root=workspace/'marker-only'
marker={"schema_version":1,"iteration_policy":"stage3-one-shot-immutable-bundle-v1","skill_root":str(skill),"workspace":str(workspace),"iteration":"marker-only","marker_kind":"stage3_owned_bundle"}
(root/'.stage3-bundle.json').write_text(json.dumps(marker)+'\n')
PY
python3 "$STAGE3" --skill "$TARGET" --workspace "$WORKSPACE" --baseline none \
  --iteration marker-only --overwrite >/dev/null
test -f "$WORKSPACE/marker-only/run-manifest.json" || fail "marker-only recovery did not complete"
test -f "$WORKSPACE/marker-only/benchmark.json" || fail "marker-only recovery did not create benchmark"

bash "$STAGE2" --skill "$TARGET" --workspace "$WORKSPACE" --baseline none \
  --iteration bad-marker >/dev/null
python3 - "$TARGET" "$WORKSPACE" <<'PY'
import json,sys
from pathlib import Path
skill=Path(sys.argv[1]).resolve(); workspace=Path(sys.argv[2]).resolve(); root=workspace/'bad-marker'
marker={"schema_version":1,"iteration_policy":"stage3-one-shot-immutable-bundle-v1","skill_root":str(skill),"workspace":str(workspace),"iteration":"bad-marker"}
(root/'.stage3-bundle.json').write_text(json.dumps(marker)+'\n')
PY
if python3 "$STAGE3" --skill "$TARGET" --workspace "$WORKSPACE" --baseline none \
  --iteration bad-marker --overwrite >/dev/null 2>&1; then
  fail "overwrite accepted an ownership marker without marker_kind"
fi

EXTERNAL_ROOT="$TMP/external"
EXTERNAL_TARGET="$EXTERNAL_ROOT/target"
EXTERNAL_WORKSPACE="$EXTERNAL_ROOT/workspace"
mkdir -p "$EXTERNAL_ROOT/shared"
make_target "$EXTERNAL_TARGET"
printf 'print()\n' > "$EXTERNAL_ROOT/shared/executor.py"
python3 - "$EXTERNAL_TARGET/evals/runner.json" <<'PY'
import json,sys
path=sys.argv[1]; value=json.load(open(path)); value['executor']['command']=['python3','../shared/executor.py']; open(path,'w').write(json.dumps(value))
PY
bash "$EXTERNAL_TARGET/scripts/run-evals.sh" --skill "$EXTERNAL_TARGET" \
  --workspace "$EXTERNAL_WORKSPACE" --baseline none --iteration external >/dev/null
if python3 "$EXTERNAL_TARGET/scripts/run-eval-cases.py" --skill "$EXTERNAL_TARGET" \
  --workspace "$EXTERNAL_WORKSPACE" --baseline none --iteration external \
  >"$TMP/external.out" 2>"$TMP/external.err"; then
  fail "relative external adapter path was accepted"
fi
grep -q 'relative adapter command path escapes' "$TMP/external.err" \
  || fail "relative external adapter error was not normalized"
if grep -q 'Traceback' "$TMP/external.err"; then
  fail "relative external adapter path produced a traceback"
fi

echo "skill-enhance raw path, lock, baseline, and ownership regressions passed"
