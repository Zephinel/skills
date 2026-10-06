#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
TARGET="$TMP/target"
WORKSPACE="$TMP/workspace"
mkdir -p "$TARGET/scripts" "$TARGET/evals/rubrics" "$TARGET/evals/archive" "$TARGET/evals/cases"
cp "$ROOT/scripts/run-evals.sh" "$TARGET/scripts/"
cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"stage3_*.py "$TARGET/scripts/"
chmod +x "$TARGET/scripts/run-evals.sh" "$TARGET/scripts/run-eval-cases.py"

printf '# Reference Isolation Skill\n' > "$TARGET/SKILL.md"
printf '# Evals\n' > "$TARGET/evals/README.md"
printf '[]\n' > "$TARGET/evals/train-queries.json"
printf '[]\n' > "$TARGET/evals/validation-queries.json"
printf 'safe-input\n' > "$TARGET/evals/input.txt"
printf 'SECRET REFERENCE nested rubric\n' > "$TARGET/evals/rubrics/main.json"
printf 'SECRET REFERENCE archived control\n' > "$TARGET/evals/archive/evals.json"
printf 'SECRET REFERENCE expected output\n' > "$TARGET/evals/cases/expected-output.json"
cat > "$TARGET/evals/evals.json" <<'JSON'
{"skill_name":"reference-isolation","evals":[{"id":1,"prompt":"Return an isolated result.","expected_output":"SECRET REFERENCE","files":["SKILL.md"],"input_files":["evals/input.txt"],"assertions":["ok"],"human_review":[]}]}
JSON

cat > "$TARGET/scripts/executor.py" <<'PY'
import json
import os
import sys
from pathlib import Path

request = json.load(sys.stdin)
needles = (b"SECRET " + b"REFERENCE",)
execution_root = Path(request["execution_workspace_root"]).resolve()

def absolute_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from absolute_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from absolute_strings(child)
    elif isinstance(value, str) and Path(value).is_absolute():
        yield value

for raw in absolute_strings(request):
    path = Path(raw).resolve(strict=False)
    if path != execution_root and execution_root not in path.parents:
        raise SystemExit(f"request exposed non-temporary absolute path: {path}")

adapter_file = Path(__file__).resolve()
if execution_root not in adapter_file.parents:
    raise SystemExit(f"adapter executed outside the temporary root: {adapter_file}")

for path in execution_root.rglob("*"):
    if path.is_file():
        data = path.read_bytes()
        if any(needle in data for needle in needles):
            raise SystemExit(f"reference material visible through temporary execution tree: {path}")

selected = Path(request["selected_skill_root"]) if request["selected_skill_root"] else None
output = Path(request["output_directory"])
output.mkdir(parents=True, exist_ok=True)
(output / "result.txt").write_text("isolated\n")
print(json.dumps({
    "assistant_response": "isolated",
    "touched_files": [],
    "artifacts": ["result.txt"],
    "metadata": {
        "fresh_context_created": True,
        "execution_cwd": os.getcwd(),
        "loaded_skill_root": str(selected) if selected else None,
        "no_skill_loaded": selected is None,
    },
}))
PY

cat > "$TARGET/scripts/judge.py" <<'PY'
import json
import sys
request = json.load(sys.stdin)
case = request["case"]
print(json.dumps({
    "assertion_results": [{"text": text, "passed": True, "evidence": "isolated"} for text in case["assertions"]],
    "human_review_results": [],
}))
PY

cat > "$TARGET/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill","baseline"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON

bash "$TARGET/scripts/run-evals.sh" --skill "$TARGET" --workspace "$WORKSPACE" \
  --baseline none --iteration iteration-1 >/dev/null
python3 "$TARGET/scripts/run-eval-cases.py" --skill "$TARGET" --workspace "$WORKSPACE" \
  --baseline none --iteration iteration-1 >/dev/null

python3 - "$WORKSPACE" "$WORKSPACE/iteration-1" <<'PY'
import json
import sys
from pathlib import Path
workspace = Path(sys.argv[1]).resolve()
iteration = Path(sys.argv[2]).resolve()
source = iteration / "subjects/source-current/evals/evals.json"
assert "SECRET REFERENCE" in source.read_text()
for configuration in ("with_skill", "baseline"):
    case_root = iteration / "eval-1" / configuration
    request_text = (case_root / "request.json").read_text()
    request = json.loads(request_text)
    assert str(workspace) not in request_text
    assert "/subjects/" not in request_text
    assert Path(request["output_directory"]).name == "artifacts"
    assert not Path(request["output_directory"]).exists()
    status = json.load(open(case_root / "executor-status.json"))
    command_text = json.dumps(status["command"])
    assert str(workspace) not in command_text
    assert "skill-enhance-stage3-" in command_text
    assert (case_root / "artifacts/result.txt").read_text() == "isolated\n"
PY

echo "skill-enhance executor provenance isolation regression passed"
