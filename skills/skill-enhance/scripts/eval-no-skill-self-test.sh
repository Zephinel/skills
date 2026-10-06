#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"; trap 'rm -rf "$TMP"' EXIT
T="$TMP/target"; W="$TMP/workspace"; mkdir -p "$T/scripts" "$T/evals"
cp "$ROOT/scripts/run-evals.sh" "$T/scripts/"; cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"eval_*.py "$T/scripts/"
printf '# Skill\n' > "$T/SKILL.md"; printf 'input\n' > "$T/evals/input.txt"
printf '# Evals\n' > "$T/evals/README.md"; printf '[]\n' > "$T/evals/train-queries.json"; printf '[]\n' > "$T/evals/validation-queries.json"
cat > "$T/evals/evals.json" <<'JSON'
{"skill_name":"no-skill","evals":[{"id":1,"prompt":"no skill","expected_output":"SECRET REFERENCE","files":["SKILL.md"],"input_files":["evals/input.txt"],"assertions":["ok"],"human_review":[]}]}
JSON
cat > "$T/scripts/executor.py" <<'PY'
import json,os,sys
from pathlib import Path
r=json.load(sys.stdin)
for forbidden in ('expected_output','assertions','human_review','grading_contract'):
    if forbidden in r: raise SystemExit(f'leaked {forbidden}')
needle=b'SECRET '+b'REFERENCE'
def scan(root):
    root=Path(root); paths=[root] if root.is_file() else root.rglob('*')
    for path in paths:
        if path.is_file() and needle in path.read_bytes(): raise SystemExit(f'reference leaked through {path}')
assert r['selected_skill_root'] is None and r['skill_files']==[] and r['omitted_skill_files']==['SKILL.md']
scan(Path(__file__).resolve().parents[1])
for item in r['task_input_files']: scan(item['absolute_path'])
cwd=Path.cwd().resolve(); assert str(cwd)==r['execution_working_directory']
for parent in (cwd,*cwd.parents): assert not (parent/'SKILL.md').exists()
assert Path(r['task_input_files'][0]['absolute_path']).read_text()=='input\n'
out=Path(r['output_directory']); out.mkdir(parents=True,exist_ok=True); (out/'result.txt').write_text('ok')
print(json.dumps({'assistant_response':'ok','touched_files':[],'artifacts':['result.txt'],'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':None,'no_skill_loaded':True}}))
PY
cat > "$T/scripts/judge.py" <<'PY'
import json,sys
r=json.load(sys.stdin); c=r['case']; print(json.dumps({'assertion_results':[{'text':x,'passed':True,'evidence':'ok'} for x in c['assertions']], 'human_review_results':[]}))
PY
cat > "$T/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["baseline"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --baseline none --iteration iteration-1 >/dev/null
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration iteration-1 --baseline none >/dev/null
python3 - "$T" "$W/iteration-1" <<'PY'
import json,sys
from pathlib import Path
t=Path(sys.argv[1]).resolve(); r=Path(sys.argv[2]); text=(r/'eval-1/baseline/request.json').read_text(); req=json.loads(text)
assert str(t/'SKILL.md') not in text and req['skill_files']==[] and req['omitted_skill_files']==['SKILL.md']
assert not (r/'subjects/adapters/skill/evals/evals.json').exists()
assert json.load(open(r/'benchmark.json'))['run_summary']['baseline']['cases_completed']==1
PY
echo "skill-enhance eval no-skill self-test passed"
