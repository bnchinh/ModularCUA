#!/usr/bin/env bash
set -u -o pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/new-suite-output" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
suite_root="$1"
if [[ "$suite_root" != /* ]]; then
  echo "Suite output path must be absolute" >&2
  exit 2
fi
mkdir -p "$suite_root"
exec 9>"$suite_root/suite.lock"
if ! flock -n 9; then
  echo "Another suite runner holds $suite_root/suite.lock" >&2
  exit 2
fi

cd "$repo_root"
tasks=(001 003 013 014 061)
suite_start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"status":"RUNNING","started_utc":"%s","tasks":["001","003","013","014","061"],"action_budget":"150 model turns per task","stage":"P0","modules":"all off","source_commit":"%s"}\n' \
  "$suite_start" "$(git rev-parse HEAD)" > "$suite_root/suite_manifest.json"

for task_id in "${tasks[@]}"; do
  task_dir="$suite_root/task-$task_id"
  mkdir -p "$task_dir"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"task_id":"%s","status":"RUNNING","started_utc":"%s"}\n' "$task_id" "$started" > "$task_dir/completion.json"
  if PYTHONPATH="ModularCUA/src:$repo_root" python ModularCUA/src/modularcua/environments/osworld_v2/runner.py \
      --config ModularCUA/configs/core_v0.yaml --output "$task_dir" --task-id "$task_id" --stage p0 \
      > "$task_dir/runner.log" 2>&1; then
    runner_rc=0
  else
    runner_rc=$?
  fi
  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python - "$task_dir" "$task_id" "$started" "$finished" "$runner_rc" <<'PY'
import glob,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); task_id=sys.argv[2]
started,finished=sys.argv[3:5]; runner_rc=int(sys.argv[5])
candidates=glob.glob(str(root/'**'/'official_result.json'),recursive=True)
official=None
if candidates:
    try: official=json.loads(pathlib.Path(candidates[-1]).read_text())
    except Exception: official=None
measured=bool(official and official.get('status')=='MEASURED'
              and official.get('partial_score') is not None
              and official.get('binary_success') is not None)
result={'task_id':task_id,'started_utc':started,'finished_utc':finished,
        'runner_exit_code':runner_rc,'status':'MEASURED' if measured else 'NOT_MEASURED',
        'official_partial_score':official.get('partial_score') if measured else None,
        'official_binary_success':official.get('binary_success') if measured else None,
        'official_result_path':candidates[-1] if candidates else None}
(root/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
done

python - "$suite_root" "$suite_start" <<'PY'
import json,pathlib,sys,time
root=pathlib.Path(sys.argv[1]); rows=[]
for task_id in ('001','003','013','014','061'):
 p=root/f'task-{task_id}'/'completion.json'
 rows.append(json.loads(p.read_text()) if p.exists() else {'task_id':task_id,'status':'MISSING'})
measured=[r for r in rows if r.get('status')=='MEASURED']
summary={'status':'COMPLETED' if len(measured)==5 else 'COMPLETED_WITH_INVALID_OR_MISSING_RUNS',
 'started_utc':sys.argv[2],'finished_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 'task_count':5,'measured_count':len(measured),'not_measured_count':5-len(measured),
 'tasks':rows}
(root/'suite_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
PY

python - "$suite_root" <<'PY'
import json,pathlib,sys
d=json.loads((pathlib.Path(sys.argv[1])/'suite_summary.json').read_text())
raise SystemExit(0 if d['status']=='COMPLETED' else 1)
PY
