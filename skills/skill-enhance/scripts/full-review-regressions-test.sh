#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "full review regression failed: $*" >&2
  exit 1
}

copy_runtime() {
  local target="$1"
  mkdir -p "$target/scripts" "$target/evals"
  cp "$ROOT/scripts/run-evals.sh" "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"stage3_*.py "$target/scripts/"
  chmod +x "$target/scripts/run-evals.sh" "$target/scripts/run-eval-cases.py"
  printf '# Review Target\n' > "$target/SKILL.md"
  printf '# Evals\n' > "$target/evals/README.md"
  printf '[]\n' > "$target/evals/train-queries.json"
  printf '[]\n' > "$target/evals/validation-queries.json"
}

write_minimal_adapters() {
  local target="$1"
  cat > "$target/scripts/executor.py" <<'PY'
import json, os, sys
request = json.load(sys.stdin)
print(json.dumps({
    "assistant_response": "ok",
    "touched_files": [],
    "artifacts": [],
    "metadata": {
        "fresh_context_created": True,
        "execution_cwd": os.getcwd(),
        "loaded_skill_root": request["selected_skill_root"],
        "no_skill_loaded": request["selected_skill_root"] is None,
    },
}))
PY
  cat > "$target/scripts/judge.py" <<'PY'
import json, sys
request = json.load(sys.stdin)
case = request["case"]
print(json.dumps({
    "assertion_results": [
        {"text": text, "passed": True, "evidence": "ok"}
        for text in case.get("assertions", [])
    ],
    "human_review_results": [],
}))
PY
}

# Internal implementation modules must not be executable entry points.
GUARD="$TMP/guard"
GUARD_W="$TMP/guard-workspace"
copy_runtime "$GUARD"
write_minimal_adapters "$GUARD"
printf '{"skill_name":"guard","evals":[]}\n' > "$GUARD/evals/evals.json"
cat > "$GUARD/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$GUARD/scripts/run-evals.sh" --skill "$GUARD" --workspace "$GUARD_W" --baseline none --iteration iteration-1 >/dev/null
if python3 "$GUARD/scripts/stage3_runner.py" --skill "$GUARD" --workspace "$GUARD_W" --baseline none --iteration iteration-1 --dry-run >"$TMP/guard.out" 2>"$TMP/guard.err"; then
  fail "stage3_runner.py bypassed the hardened public entry"
fi
grep -q 'internal Stage 3 modules are not standalone' "$TMP/guard.err" \
  || fail "internal entry rejection was not explicit"

# Raw skill, workspace, and baseline-source aliases must be rejected before canonicalization.
ln -s "$GUARD" "$TMP/guard-alias"
if bash "$GUARD/scripts/run-evals.sh" --skill "$TMP/guard-alias" --workspace "$TMP/raw-w" --baseline none --dry-run >/dev/null 2>&1; then
  fail "Stage 2 accepted a symlink skill root"
fi
mkdir -p "$TMP/real-workspace"
ln -s "$TMP/real-workspace" "$TMP/workspace-alias"
if bash "$GUARD/scripts/run-evals.sh" --skill "$GUARD" --workspace "$TMP/workspace-alias" --baseline none --dry-run >/dev/null 2>&1; then
  fail "Stage 2 accepted a symlink workspace root"
fi
mkdir -p "$TMP/old-skill"
printf '# Old Skill\n' > "$TMP/old-skill/SKILL.md"
ln -s "$TMP/old-skill" "$TMP/old-skill-alias"
if bash "$GUARD/scripts/run-evals.sh" --skill "$GUARD" --workspace "$TMP/baseline-w" --baseline snapshot --create-baseline --baseline-source "$TMP/old-skill-alias" --allow-dirty-baseline >/dev/null 2>&1; then
  fail "Stage 2 accepted a symlink baseline-source root"
fi

# Broad adapter bundles and strict-JSON violations must fail during public preflight.
CONTAM="$TMP/contam"
CONTAM_W="$TMP/contam-workspace"
copy_runtime "$CONTAM"
write_minimal_adapters "$CONTAM"
printf '{"skill_name":"contam","evals":[]}\n' > "$CONTAM/evals/evals.json"
cat > "$CONTAM/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"bundle_paths":["SKILL.md"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$CONTAM/scripts/run-evals.sh" --skill "$CONTAM" --workspace "$CONTAM_W" --baseline none --iteration iteration-1 >/dev/null
if python3 "$CONTAM/scripts/run-eval-cases.py" --skill "$CONTAM" --workspace "$CONTAM_W" --baseline none --iteration iteration-1 --dry-run >"$TMP/contam.out" 2>"$TMP/contam.err"; then
  fail "executor bundle accepted SKILL.md"
fi
grep -q 'only adapter code under scripts' "$TMP/contam.err" \
  || fail "bundle contamination error was not normalized"

python3 - "$CONTAM/evals/runner.json" <<'PY'
from pathlib import Path
path = Path(__import__('sys').argv[1])
path.write_text('{"schema_version":1,"executor":{"command":["true"],"mode":"agent_host","timeout_seconds":NaN},"judge":{"command":["true"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":false},"acceptance":{"user_controlled":true}}\n')
PY
if python3 "$CONTAM/scripts/run-eval-cases.py" --skill "$CONTAM" --workspace "$CONTAM_W" --baseline none --iteration iteration-1 --dry-run >/dev/null 2>&1; then
  fail "runner config accepted NaN"
fi

# Reference-answer material outside evals/ must be removed from executor subjects.
SAFE="$TMP/safe"
SAFE_W="$TMP/safe-workspace"
copy_runtime "$SAFE"
mkdir -p "$SAFE/references"
printf 'REFERENCE_SENTINEL_42\n' > "$SAFE/references/expected-output.md"
cat > "$SAFE/evals/evals.json" <<'JSON'
{"skill_name":"safe","evals":[{"id":1,"prompt":"run","files":["SKILL.md"],"assertions":["ok"],"human_review":[]}]}
JSON
cat > "$SAFE/scripts/executor.py" <<'PY'
import json, os, sys
from pathlib import Path
request = json.load(sys.stdin)
for path in Path(request["execution_workspace_root"]).rglob("*"):
    if path.is_file() and (b"REFERENCE_" + b"SENTINEL_42") in path.read_bytes():
        raise SystemExit(f"reference leaked through {path}")
print(json.dumps({
    "assistant_response": "ok",
    "touched_files": [],
    "artifacts": [],
    "metadata": {
        "fresh_context_created": True,
        "execution_cwd": os.getcwd(),
        "loaded_skill_root": request["selected_skill_root"],
        "no_skill_loaded": False,
    },
}))
PY
cat > "$SAFE/scripts/judge.py" <<'PY'
import json, sys
json.load(sys.stdin)
print(json.dumps({"assertion_results":[{"text":"ok","passed":True,"evidence":"safe"}],"human_review_results":[]}))
PY
cat > "$SAFE/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$SAFE/scripts/run-evals.sh" --skill "$SAFE" --workspace "$SAFE_W" --baseline none --iteration iteration-1 >/dev/null
python3 "$SAFE/scripts/run-eval-cases.py" --skill "$SAFE" --workspace "$SAFE_W" --baseline none --iteration iteration-1 >/dev/null

test ! -e "$SAFE_W/iteration-1/subjects/current/references/expected-output.md" \
  || fail "reference answer remained in the execution subject"

# Secrets in logs, payloads, and declared changed files must never be durable.
SECRET="$TMP/secret"
SECRET_W="$TMP/secret-workspace"
copy_runtime "$SECRET"
cat > "$SECRET/evals/evals.json" <<'JSON'
{"skill_name":"secret","evals":[{"id":1,"prompt":"run","files":["SKILL.md"],"assertions":["ok"],"human_review":[]}]}
JSON
cat > "$SECRET/scripts/executor.py" <<'PY'
import json, os, sys
from pathlib import Path
request = json.load(sys.stdin)
secret = os.environ["EXPLICIT_SECRET"]
print(secret, file=sys.stderr)
root = Path(request["selected_skill_root"])
(root / "debug.log").write_text(secret)
out = Path(request["output_directory"])
out.mkdir(parents=True, exist_ok=True)
(out / "result.txt").write_text("safe")
print(json.dumps({
    "assistant_response": f"value={secret}",
    "touched_files": ["skill/debug.log"],
    "artifacts": ["result.txt"],
    "timing": {"duration_ms": 1, "total_tokens": 1},
    "metadata": {
        "fresh_context_created": True,
        "execution_cwd": os.getcwd(),
        "loaded_skill_root": request["selected_skill_root"],
        "no_skill_loaded": False,
    },
}))
PY
cat > "$SECRET/scripts/judge.py" <<'PY'
import json, sys
json.load(sys.stdin)
print(json.dumps({"assertion_results":[{"text":"ok","passed":True,"evidence":"safe"}],"human_review_results":[]}))
PY
cat > "$SECRET/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"env_passthrough":["EXPLICIT_SECRET"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"limits":{"stdout_bytes":1048576,"stderr_bytes":1048576,"artifact_total_bytes":1048576,"artifact_file_count":10,"workspace_file_count":1000,"workspace_total_bytes":10485760,"persisted_workspace_bytes":1048576},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
export EXPLICIT_SECRET='DURABLE_SECRET_SENTINEL_42'
bash "$SECRET/scripts/run-evals.sh" --skill "$SECRET" --workspace "$SECRET_W" --baseline none --iteration iteration-1 >/dev/null
python3 "$SECRET/scripts/run-eval-cases.py" --skill "$SECRET" --workspace "$SECRET_W" --baseline none --iteration iteration-1 >/dev/null
if grep -R -a -q "$EXPLICIT_SECRET" "$SECRET_W/iteration-1"; then
  fail "explicit secret persisted in the iteration bundle"
fi
grep -q '<redacted:EXPLICIT_SECRET>' "$SECRET_W/iteration-1/eval-1/with_skill/executor.stderr.log" \
  || fail "executor stderr was not redacted"
python3 - "$SECRET_W/iteration-1/eval-1/with_skill/workspace-diff.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
change = next(item for item in value["changes"] if item["relative_path"] == "skill/debug.log")
assert change["content_persisted"] is False
assert change["redaction_reason"] == "secret_value_detected"
PY

# Output limits and finite timing checks must fail closed.
LIMIT="$TMP/limit"
LIMIT_W="$TMP/limit-workspace"
copy_runtime "$LIMIT"
cat > "$LIMIT/evals/evals.json" <<'JSON'
{"skill_name":"limit","evals":[{"id":1,"prompt":"run","files":["SKILL.md"],"assertions":[],"human_review":[]}]}
JSON
cat > "$LIMIT/scripts/executor.py" <<'PY'
import time
print("x" * 4096, flush=True)
time.sleep(0.2)
PY
cp "$SECRET/scripts/judge.py" "$LIMIT/scripts/judge.py"
cat > "$LIMIT/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"limits":{"stdout_bytes":128,"stderr_bytes":128,"artifact_total_bytes":1024,"artifact_file_count":10,"workspace_file_count":1000,"workspace_total_bytes":1048576,"persisted_workspace_bytes":1024},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$LIMIT/scripts/run-evals.sh" --skill "$LIMIT" --workspace "$LIMIT_W" --baseline none --iteration iteration-1 >/dev/null
if python3 "$LIMIT/scripts/run-eval-cases.py" --skill "$LIMIT" --workspace "$LIMIT_W" --baseline none --iteration iteration-1 >/dev/null 2>&1; then
  fail "stdout byte limit was not enforced"
fi
grep -q 'exceeded configured byte limit' "$LIMIT_W/iteration-1/eval-1/with_skill/executor-status.json" \
  || fail "output-limit failure was not persisted"

# The memory helper must reject malformed new and historical source-of-truth records.
MEMORY="$TMP/memory"
mkdir -p "$MEMORY"
printf '# Memory Target\n' > "$MEMORY/SKILL.md"
invalid='{"timestamp":"not-a-time","run_id":"bad","goal":"x","actions_taken":[1],"outcome":"x","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"x","artifacts":[],"memory_write_status":"written"}'
if python3 "$ROOT/assets/append-memory-template.py" --skill-root "$MEMORY" append --entry-json "$invalid" >/dev/null 2>&1; then
  fail "memory helper accepted an invalid evidence schema"
fi
mkdir -p "$MEMORY/memory"
printf '%s\n' "$invalid" > "$MEMORY/memory/evidence.jsonl"
valid='{"timestamp":"2026-07-10T00:00:00Z","run_id":"good","goal":"x","actions_taken":["ok"],"outcome":"x","confidence":"high","clarification_needed":false,"user_feedback":"","failure_pattern":"","suggested_followup":"x","artifacts":[],"memory_write_status":"written"}'
if python3 "$ROOT/assets/append-memory-template.py" --skill-root "$MEMORY" append --entry-json "$valid" >/dev/null 2>&1; then
  fail "memory helper accepted an invalid historical evidence record"
fi

# Frozen subjects and runtime policy must be revalidated before/after every case.
TAMPER="$TMP/tamper"
TAMPER_W="$TMP/tamper-workspace"
copy_runtime "$TAMPER"
cat > "$TAMPER/evals/evals.json" <<'JSON'
{"skill_name":"tamper","evals":[{"id":1,"prompt":"run","files":["SKILL.md"],"assertions":[],"human_review":[]},{"id":2,"prompt":"run again","files":["SKILL.md"],"assertions":[],"human_review":[]}]}
JSON
cat > "$TAMPER/scripts/executor.py" <<'PY'
import json, os, sys
from pathlib import Path
request = json.load(sys.stdin)
if str(request["case_id"]) == "1":
    root = Path(os.environ["ITERATION_ROOT"])
    (root / "subjects/current/SKILL.md").write_text("tampered")
print(json.dumps({
    "assistant_response": "ok",
    "touched_files": [],
    "artifacts": [],
    "metadata": {
        "fresh_context_created": True,
        "execution_cwd": os.getcwd(),
        "loaded_skill_root": request["selected_skill_root"],
        "no_skill_loaded": False,
    },
}))
PY
cp "$SECRET/scripts/judge.py" "$TAMPER/scripts/judge.py"
cat > "$TAMPER/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"env_passthrough":["ITERATION_ROOT"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$TAMPER/scripts/run-evals.sh" --skill "$TAMPER" --workspace "$TAMPER_W" --baseline none --iteration iteration-1 >/dev/null
export ITERATION_ROOT="$TAMPER_W/iteration-1"
if python3 "$TAMPER/scripts/run-eval-cases.py" --skill "$TAMPER" --workspace "$TAMPER_W" --baseline none --iteration iteration-1 >/dev/null 2>&1; then
  fail "persistent frozen-subject tampering was not detected"
fi
grep -R -q 'frozen subject changed after freezing' "$TAMPER_W/iteration-1/controller-errors" \
  || fail "frozen-subject tamper error was not recorded"

echo "skill-enhance full review regressions passed"
