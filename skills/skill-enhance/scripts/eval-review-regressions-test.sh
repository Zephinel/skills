#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
DEBUG_ROOT="${STAGE3_REVIEW_DEBUG_ROOT:-}"
cleanup() {
  status=$?
  if [[ -n "$DEBUG_ROOT" && $status -ne 0 ]]; then
    rm -rf "$DEBUG_ROOT"
    mkdir -p "$DEBUG_ROOT"
    cp -R "$TMP"/. "$DEBUG_ROOT"/
    printf 'exit_status=%s\n' "$status" > "$DEBUG_ROOT/status.txt"
  fi
  rm -rf "$TMP"
  exit "$status"
}
trap cleanup EXIT
[[ -z "$DEBUG_ROOT" ]] || set -x
T="$TMP/target"; W="$TMP/workspace"; mkdir -p "$T/scripts" "$T/evals"
cp "$ROOT/scripts/run-evals.sh" "$T/scripts/"; cp "$ROOT/scripts/run-eval-cases.py" "$ROOT/scripts/"eval_*.py "$T/scripts/"
printf '# Current\n' > "$T/SKILL.md"; printf '# Evals\n' > "$T/evals/README.md"; printf '[]\n' > "$T/evals/train-queries.json"; printf '[]\n' > "$T/evals/validation-queries.json"
cat > "$T/evals/evals.json" <<'JSON'
{"skill_name":"regressions","evals":[
 {"id":1,"prompt":"one","files":["SKILL.md"],"assertions":[],"human_review":[]},
 {"id":2,"prompt":"two","files":["SKILL.md"],"assertions":[],"human_review":[]},
 {"id":"missing","prompt":"missing","files":["missing.md"],"assertions":[],"human_review":[]}
]}
JSON
cat > "$T/scripts/good.py" <<'PY'
import json,os,sys
r=json.load(sys.stdin); print(json.dumps({'assistant_response':'ok','touched_files':[],'artifacts':[],'timing':{'total_tokens':10},'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':r['selected_skill_root'],'no_skill_loaded':r['selected_skill_root'] is None}}))
PY
cat > "$T/scripts/judge.py" <<'PY'
import json,sys
json.load(sys.stdin); print(json.dumps({'assertion_results':[],'human_review_results':[]}))
PY
write_config(){
  local configurations="${3-}"
  [[ -n "$configurations" ]] || configurations='"with_skill"'
  cat > "$T/evals/runner.json" <<JSON
{"schema_version":1,"executor":{"command":["python3","scripts/$1"],"mode":"agent_host","timeout_seconds":${2:-10}},"judge":{"command":["python3","scripts/judge.py"],"reviewer_type":"test","timeout_seconds":10},"execution":{"configurations":[$configurations],"fail_fast":${4:-true},"verify_stage2":false},"acceptance":{"user_controlled":${5:-true}}}
JSON
}
write_config good.py
if bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$TMP" --iteration target --baseline none >/dev/null 2>&1; then exit 10; fi
test -f "$T/SKILL.md"
bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --baseline snapshot --create-baseline --allow-dirty-baseline >/dev/null
if bash "$T/scripts/run-evals.sh" --skill "$T" --workspace "$W" --iteration skill-snapshot --baseline snapshot >/dev/null 2>&1; then exit 11; fi
test -f "$W/skill-snapshot/.baseline-manifest.json"
mkdir -p "$W/docs"; echo keep > "$W/docs/keep.txt"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration docs --baseline snapshot --overwrite --dry-run >/dev/null 2>&1; then exit 12; fi
test -f "$W/docs/keep.txt"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$TMP" --iteration target --baseline none --overwrite --dry-run >/dev/null 2>&1; then exit 13; fi
test -f "$T/SKILL.md"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration skill-snapshot --baseline snapshot --overwrite --dry-run >/dev/null 2>&1; then exit 14; fi
test -f "$W/skill-snapshot/.baseline-manifest.json"
cat > "$T/scripts/invalid.py" <<'PY'
import sys
print('partial-not-json'); print('diagnostic',file=sys.stderr)
PY
write_config invalid.py
mkdir -p "$W/invalid"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration invalid --baseline none --cases 1 >/dev/null 2>&1; then exit 15; fi
grep -q partial-not-json "$W/invalid/eval-1/with_skill/executor.stdout.log"; grep -q diagnostic "$W/invalid/eval-1/with_skill/executor.stderr.log"; grep -q '"json_parse_status": "failed"' "$W/invalid/eval-1/with_skill/executor-status.json"
cat > "$T/scripts/artifact.py" <<'PY'
import json,os,sys
r=json.load(sys.stdin); print(json.dumps({'assistant_response':'x','touched_files':[],'artifacts':['../../escape'],'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':r['selected_skill_root'],'no_skill_loaded':False}}))
PY
write_config artifact.py
mkdir -p "$W/artifact"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration artifact --baseline none --cases 1 >/dev/null 2>&1; then exit 16; fi
write_config good.py 10 '"with_skill"' true false
mkdir -p "$W/acceptance"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration acceptance --baseline none --dry-run >/dev/null 2>&1; then exit 17; fi
write_config good.py
mkdir -p "$W/dry-missing"
if python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration dry-missing --baseline snapshot --cases missing --dry-run >/dev/null 2>&1; then exit 18; fi
cat > "$T/scripts/partial.py" <<'PY'
import json,os,sys
r=json.load(sys.stdin)
if r['configuration']=='baseline' and str(r['case_id'])=='2': raise SystemExit(5)
print(json.dumps({'assistant_response':'ok','touched_files':[],'artifacts':[],'timing':{'total_tokens':10},'metadata':{'fresh_context_created':True,'execution_cwd':os.getcwd(),'loaded_skill_root':r['selected_skill_root'],'no_skill_loaded':False}}))
PY
write_config partial.py 10 '"with_skill","baseline"' false
mkdir -p "$W/partial"; set +e
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration partial --baseline snapshot --cases 1,2 >/dev/null; s=$?; set -e; test "$s" = 1
python3 - "$W/partial/benchmark.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))['delta']; assert d['comparison_status']=='partial' and d['paired_completed_case_ids']==['1'] and d['failed_case_ids']==['2']
PY
cat > "$T/scripts/timeout.py" <<'PY'
import json,subprocess,sys,time
from pathlib import Path
r=json.load(sys.stdin); marker=Path(r['output_directory']).parent/'child-survived.txt'
subprocess.Popen([sys.executable,'-c',f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('bad')"])
time.sleep(30)
PY
write_config timeout.py 0.2
mkdir -p "$W/timeout"; set +e
python3 "$T/scripts/run-eval-cases.py" --skill "$T" --workspace "$W" --iteration timeout --baseline none --cases 1 >/dev/null; s=$?; set -e; test "$s" = 1
sleep 1.5; test ! -e "$W/timeout/eval-1/with_skill/child-survived.txt"; grep -q '"timed_out": true' "$W/timeout/eval-1/with_skill/executor-status.json"
echo "skill-enhance eval review regressions passed"
