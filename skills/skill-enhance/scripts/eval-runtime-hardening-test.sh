#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"; trap 'rm -rf "$TMP"' EXIT
T="$TMP/target"; W="$TMP/workspace"
mkdir -p "$T/scripts/executor_lib" "$T/scripts/judge_lib" "$T/evals/rubrics"
cp "$ROOT/scripts/run-evals.sh" "$T/scripts/"
cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"eval_*.py "$T/scripts/"
chmod +x "$T/scripts/run-evals.sh" "$T/scripts/run-eval-cases.py"
printf '# Hardened Skill\n' > "$T/SKILL.md"
printf '# Evals\n' > "$T/evals/README.md"
printf '[]\n' > "$T/evals/train-queries.json"
printf '[]\n' > "$T/evals/validation-queries.json"
printf 'safe input\n' > "$T/evals/input.txt"
printf 'SECRET REFERENCE\n' > "$T/evals/rubrics/private.txt"
cat > "$T/evals/evals.json" <<'JSON'
{"skill_name":"hardening","evals":[{"id":1,"prompt":"run","expected_output":"SECRET REFERENCE","files":["SKILL.md"],"input_files":["evals/input.txt"],"assertions":["ok"],"human_review":[]}]}
JSON
cat > "$T/scripts/executor.py" <<'PY'
import json,os,sys
from pathlib import Path
r=json.load(sys.stdin)
secret=os.environ['EXPLICIT_EXECUTOR']
assert secret
for name in ('HOST_SECRET','GITHUB_WORKSPACE','PYTHONPATH','OLDPWD'):
    assert name not in os.environ, (name, os.environ.get(name))
assert os.environ['PWD']==os.getcwd()
root=Path(__file__).resolve().parents[1]
assert (root/'scripts/executor.py').is_file()
assert (root/'scripts/executor_lib/helper.py').is_file()
assert not (root/'scripts/judge.py').exists()
for p in Path(r['execution_workspace_root']).rglob('*'):
    if p.is_file(): assert (b'SECRET ' + b'REFERENCE') not in p.read_bytes(), p
home=Path(os.environ['HOME']); cache=home/'.cache'; cache.mkdir(parents=True,exist_ok=True)
(cache/'session.json').write_text(secret)
tmp=Path(os.environ['TMPDIR']); tmp.mkdir(parents=True,exist_ok=True)
(tmp/'request-debug.json').write_text(secret)
out=Path(r['output_directory']); out.mkdir(parents=True,exist_ok=True); (out/'result.txt').write_text('ok\n')
print(json.dumps({'assistant_response':'ok','touched_files':[],'artifacts':['result.txt'],'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':r['selected_skill_root'],'no_skill_loaded':False}}))
PY
printf 'VALUE=1\n' > "$T/scripts/executor_lib/helper.py"
cat > "$T/scripts/judge.py" <<'PY'
import json,os,sys
from pathlib import Path
r=json.load(sys.stdin)
assert os.environ['EXPLICIT_JUDGE']=='allowed'
assert 'EXPLICIT_EXECUTOR' not in os.environ
root=Path(__file__).resolve().parents[1]
assert (root/'scripts/judge.py').is_file()
assert (root/'scripts/judge_lib/helper.py').is_file()
assert not (root/'scripts/executor.py').exists()
print(json.dumps({'assertion_results':[{'text':x,'passed':True,'evidence':'ok'} for x in r['case']['assertions']], 'human_review_results':[]}))
PY
printf 'VALUE=2\n' > "$T/scripts/judge_lib/helper.py"
cat > "$T/evals/runner.json" <<'JSON'
{"schema_version":1,"executor":{"command":["python3","scripts/executor.py"],"bundle_paths":["scripts/executor_lib"],"env_passthrough":["EXPLICIT_EXECUTOR"],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/judge.py"],"bundle_paths":["scripts/judge_lib"],"env_passthrough":["EXPLICIT_JUDGE"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON
export EXPLICIT_EXECUTOR=RUNTIME_SECRET_DO_NOT_PERSIST_42 EXPLICIT_JUDGE=allowed HOST_SECRET=blocked GITHUB_WORKSPACE="$T" PYTHONPATH="$T" OLDPWD="$T"
bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --baseline none --iteration iteration-1 >/dev/null
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --baseline none --iteration iteration-1 >/dev/null
python3 - "$W/iteration-1" <<'PY'
import json,sys
from pathlib import Path
r=Path(sys.argv[1]); m=json.load(open(r/'subjects/manifest.json'))
assert 'evals/rubrics/private.txt' in m['current']['removed_eval_control_files']
assert not (r/'subjects/current/evals/rubrics/private.txt').exists()
a=m['adapters']; assert (r/'subjects/adapters/executor/scripts/executor.py').is_file(); assert not (r/'subjects/adapters/executor/scripts/judge.py').exists()
assert a['executor']['command'][0]['source_resolved_path']
assert a['executor']['command'][0]['version_probe']=='disabled_for_environment_isolation'
assert a['executor']['command'][1]['source_matches_frozen'] is True
assert (r/'subjects/adapters/judge/scripts/judge.py').is_file(); assert not (r/'subjects/adapters/judge/scripts/executor.py').exists()
e=json.load(open(r/'eval-1/with_skill/executor-runtime.json')); j=json.load(open(r/'eval-1/with_skill/judge-runtime.json'))
assert e['explicit_env_passthrough']==['EXPLICIT_EXECUTOR']; assert j['explicit_env_passthrough']==['EXPLICIT_JUDGE']
assert 'HOST_SECRET' not in e['environment_keys']; assert 'GITHUB_WORKSPACE' not in e['environment_keys']; assert 'PYTHONPATH' not in e['environment_keys']; assert 'OLDPWD' not in e['environment_keys']
diff=json.load(open(r/'eval-1/with_skill/workspace-diff.json'))
changes={item['relative_path']:item for item in diff['changes']}
for path,reason in {
    'environment/home/.cache/session.json':'environment_runtime_file',
    'environment/tmp/request-debug.json':'environment_runtime_file',
}.items():
    assert path in changes, (path, changes)
    assert changes[path]['content_persisted'] is False
    assert changes[path]['redaction_reason']==reason
    assert not (r/'eval-1/with_skill/workspace-changes/after'/path).exists()
assert changes['artifacts/result.txt']['content_persisted'] is False
assert changes['artifacts/result.txt']['redaction_reason']=='artifact_persisted_separately'
assert (r/'eval-1/with_skill/artifacts/result.txt').read_text()=='ok\n'
secret=b'RUNTIME_SECRET_DO_NOT_PERSIST_42'
for path in r.rglob('*'):
    if path.is_file():
        assert secret not in path.read_bytes(), f'secret persisted in {path}'
PY
# One dispatcher may intentionally serve both roles; it is copied into separate role bundles.
S="$TMP/shared-target"; SW="$TMP/shared-workspace"
mkdir -p "$S/scripts" "$S/evals"
cp "$ROOT/scripts/run-evals.sh" "$S/scripts/"
cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"eval_*.py "$S/scripts/"
chmod +x "$S/scripts/run-evals.sh" "$S/scripts/run-eval-cases.py"
printf '# Shared Adapter Skill\n' > "$S/SKILL.md"
printf '# Evals\n' > "$S/evals/README.md"
printf '[]\n' > "$S/evals/train-queries.json"
printf '[]\n' > "$S/evals/validation-queries.json"
printf '{"skill_name":"shared","evals":[{"id":1,"prompt":"run","expected_output":"ok","files":["SKILL.md"],"assertions":["ok"],"human_review":[]}]}\n' > "$S/evals/evals.json"
cat > "$S/scripts/adapter.py" <<'PY_SHARED'
import json,os,sys
from pathlib import Path
r=json.load(sys.stdin)
if r['request_type']=='execute_eval_case':
    out=Path(r['output_directory']); out.mkdir(parents=True,exist_ok=True); (out/'result.txt').write_text('ok\n')
    root=Path(r['selected_skill_root'])
    print(json.dumps({'assistant_response':'ok','touched_files':[],'artifacts':['result.txt'],'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':str(root),'no_skill_loaded':False}}))
else:
    print(json.dumps({'assertion_results':[{'text':x,'passed':True,'evidence':'ok'} for x in r['case']['assertions']], 'human_review_results':[]}))
PY_SHARED
cat > "$S/evals/runner.json" <<'JSON_SHARED'
{"schema_version":1,"executor":{"command":["python3","scripts/adapter.py"],"bundle_paths":["scripts/adapter.py"],"env_passthrough":[],"mode":"agent_host","timeout_seconds":10},"judge":{"command":["python3","scripts/adapter.py"],"bundle_paths":["scripts/adapter.py"],"env_passthrough":[],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":["with_skill"],"fail_fast":true,"verify_stage2":true},"acceptance":{"user_controlled":true}}
JSON_SHARED
bash "$S/scripts/run-evals.sh" --skill "$S" --workspace "$SW" --baseline none --iteration iteration-1 >/dev/null
python3 "$S/scripts/run-eval-cases.py" --skill "$S" --workspace "$SW" --baseline none --iteration iteration-1 >/dev/null
test -f "$SW/iteration-1/eval-1/with_skill/grading.json"

echo 'skill-enhance eval runtime hardening test passed'
