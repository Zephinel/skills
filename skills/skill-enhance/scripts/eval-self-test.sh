#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"; trap 'rm -rf "$TMP"' EXIT
T="$TMP/target"; W="$TMP/workspace"
mkdir -p "$T/scripts" "$T/evals"
cp "$ROOT/scripts/run-evals.sh" "$T/scripts/"
cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"eval_*.py "$T/scripts/"
chmod +x "$T/scripts/run-evals.sh" "$T/scripts/run-eval-cases.py"
cat > "$T/SKILL.md" <<'EOF'
# Current Skill
VERSION=A
EOF
printf 'old\n' > "$T/to-modify.txt"; printf 'delete\n' > "$T/to-delete.txt"
printf 'input-v1\n' > "$T/evals/input.txt"
printf '# Evals\n' > "$T/evals/README.md"; printf '[]\n' > "$T/evals/train-queries.json"; printf '[]\n' > "$T/evals/validation-queries.json"
cat > "$T/evals/evals.json" <<'JSON'
{"skill_name":"fixture","evals":[
 {"id":1,"prompt":"case 1","expected_output":"SECRET REFERENCE","files":["SKILL.md"],"input_files":["evals/input.txt"],"assertions":["ok"],"human_review":[]},
 {"id":2,"prompt":"case 2","expected_output":"SECRET TWO","files":["SKILL.md"],"input_files":["evals/input.txt"],"assertions":["ok"],"human_review":[]}
]}
JSON
cat > "$T/scripts/executor.py" <<'PY'
import json, os, sys
from pathlib import Path
ADAPTER_VERSION="EXECUTOR-A"
r=json.load(sys.stdin)
for forbidden in ("expected_output","assertions","human_review","grading_contract"):
    if forbidden in r: raise SystemExit(f"leaked {forbidden}")
for forbidden_env in ("OLDPWD","PYTHONPATH","GITHUB_WORKSPACE","STAGE3_HOST_SECRET"):
    if forbidden_env in os.environ: raise SystemExit(f"inherited {forbidden_env}")
if os.environ.get("PWD") != os.getcwd(): raise SystemExit("PWD was not controller-managed")
if os.environ.get("STAGE3_TEST_LIVE_TARGET") is None: raise SystemExit("explicit env passthrough missing")
adapter_root=Path(__file__).resolve().parents[1]
if (adapter_root/"scripts/judge.py").exists(): raise SystemExit("judge bundle leaked into executor")
needles=[b"SECRET "+b"REFERENCE",b"SECRET "+b"TWO"]
def scan(root):
    if root is None: return
    root=Path(root)
    paths=[root] if root.is_file() else root.rglob('*')
    for p in paths:
        if p.is_file() and any(n in p.read_bytes() for n in needles):
            raise SystemExit(f"reference leaked through {p}")
root=Path(r["selected_skill_root"]) if r["selected_skill_root"] else None
scan(root); scan(adapter_root)
for item in r["task_input_files"]: scan(Path(item["absolute_path"]))
content=(root/"SKILL.md").read_text() if root else "NO_SKILL"
input_text=Path(r["task_input_files"][0]["absolute_path"]).read_text()
if root:
    (root/"to-modify.txt").write_text("new\n")
    (root/"to-delete.txt").unlink()
    (root/"generated.txt").write_text("generated\n")
    (root/"undeclared.txt").write_text("undeclared\n")
out=Path(r["output_directory"]); out.mkdir(parents=True,exist_ok=True); (out/"result.txt").write_text(content+input_text+ADAPTER_VERSION)
if str(r["case_id"])=="1" and r["configuration"]=="with_skill":
    live=Path(os.environ["STAGE3_TEST_LIVE_TARGET"])
    (live/"SKILL.md").write_text("# Current Skill\nVERSION=LIVE-MUTATED\n")
    (live/"evals/input.txt").write_text("input-v2\n")
    (live/"scripts/executor.py").write_text('raise SystemExit("LIVE EXECUTOR USED")\n')
    (live/"scripts/judge.py").write_text('raise SystemExit("LIVE JUDGE USED")\n')
print(json.dumps({"assistant_response":content+"|"+input_text.strip()+"|"+ADAPTER_VERSION,"touched_files":["skill/to-modify.txt","skill/to-delete.txt","skill/generated.txt"] if root else [],"artifacts":["result.txt"],"timing":{"duration_ms":10,"total_tokens":5},"metadata":{"fresh_context_created":True,"execution_cwd":os.getcwd(),"loaded_skill_root":str(root) if root else None,"no_skill_loaded":root is None}}))
PY
cat > "$T/scripts/judge.py" <<'PY'
import json,sys
from pathlib import Path
JUDGE_VERSION="JUDGE-A"
if (Path(__file__).resolve().parents[1]/"scripts/executor.py").exists(): raise SystemExit("executor bundle leaked into judge")
r=json.load(sys.stdin); c=r['case']
print(json.dumps({"assertion_results":[{"text":x,"passed":True,"evidence":JUDGE_VERSION} for x in c.get('assertions',[])],"human_review_results":[]}))
PY
cat > "$T/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"bundle_paths":["scripts/executor.py"],"env_passthrough":["STAGE3_TEST_LIVE_TARGET"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"bundle_paths":["scripts/judge.py"],"env_passthrough":[],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill","baseline"],"fail_fast":false,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --baseline snapshot --create-baseline --allow-dirty-baseline >/dev/null
printf '\nPOST_BASELINE=YES\n' >> "$T/SKILL.md"
bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --baseline snapshot --iteration iteration-1 >/dev/null
export STAGE3_TEST_LIVE_TARGET="$T"
export STAGE3_HOST_SECRET="$W/should-not-leak"
export GITHUB_WORKSPACE="$W/should-not-leak"
export PYTHONPATH="$W/should-not-leak"
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration iteration-1 --baseline snapshot >/dev/null
python3 - "$W/iteration-1" <<'PY'
import json,sys
from pathlib import Path
r=Path(sys.argv[1]); b=json.load(open(r/'benchmark.json'))
assert b['delta']['comparison_status']=='complete', b['delta']
m=json.load(open(r/'subjects/manifest.json'))
assert m['source_current']['tree_sha256'] and m['current']['tree_sha256'] and m['baseline']['tree_sha256'] and m['inputs']['tree_sha256']
assert m['inputs']['source_kind']=='frozen_source_current_subject'
for cid in ('1','2'):
    current=json.load(open(r/f'eval-{cid}/with_skill/execution.json'))
    base=json.load(open(r/f'eval-{cid}/baseline/execution.json'))
    assert 'VERSION=A' in current['assistant_response'] and 'POST_BASELINE=YES' in current['assistant_response']
    assert 'input-v1' in current['assistant_response'] and 'EXECUTOR-A' in current['assistant_response']
    assert 'POST_BASELINE=YES' not in base['assistant_response']
    grading=json.load(open(r/f'eval-{cid}/with_skill/grading.json'))
    assert grading['assertion_results'][0]['evidence']=='JUDGE-A'
    executor_runtime=json.load(open(r/f'eval-{cid}/with_skill/executor-runtime.json'))
    executor_paths={x['relative_path'] for x in executor_runtime['temporary_bundle_entries']}
    assert 'scripts/executor.py' in executor_paths and 'scripts/judge.py' not in executor_paths
    judge_runtime=json.load(open(r/f'eval-{cid}/with_skill/judge-runtime.json'))
    judge_paths={x['relative_path'] for x in judge_runtime['temporary_bundle_entries']}
    assert 'scripts/judge.py' in judge_paths and 'scripts/executor.py' not in judge_paths
    assert 'STAGE3_TEST_LIVE_TARGET' in executor_runtime['environment_keys']
    for forbidden in ('OLDPWD','PYTHONPATH','GITHUB_WORKSPACE','STAGE3_HOST_SECRET'):
        assert forbidden not in executor_runtime['environment_keys']
req=json.load(open(r/'eval-1/with_skill/request.json'))
for forbidden in ('expected_output','assertions','human_review','grading_contract'): assert forbidden not in req
assert (r/'eval-1/with_skill/artifacts/result.txt').exists()
PY
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration iteration-1 --baseline snapshot >/dev/null 2>&1; then exit 11; fi
cp "$W/iteration-1/subjects/adapters/executor/scripts/executor.py" "$T/scripts/executor.py"
cp "$W/iteration-1/subjects/adapters/judge/scripts/judge.py" "$T/scripts/judge.py"
printf 'input-v1\n' > "$T/evals/input.txt"
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration iteration-1 --baseline snapshot --cases 1 --overwrite >/dev/null
test ! -e "$W/iteration-1/eval-2"
echo "skill-enhance eval self-test passed"
