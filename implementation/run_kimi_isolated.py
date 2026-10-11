"""Start a scoped Kimi task. Does not certify implementation completion."""
import argparse
import datetime
import json
import os
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--phase', choices=['database', 'traceability'], default='database')
args = parser.parse_args()
if args.phase == 'traceability':
    gate = json.loads((root / 'database-gate.json').read_text(encoding='utf-8'))
    if gate.get('passed') is not True or not gate.get('evidence'):
        raise SystemExit('Database gate has not passed with evidence; traceability task was not started.')
env = os.environ.copy()
env['KIMI_CODE_HOME'] = str(root / '.kimi-runtime')
env['KIMI_DISABLE_TELEMETRY'] = '1'
(root / '.kimi-runtime').mkdir(exist_ok=True)
(root / '.kimi-skills').mkdir(exist_ok=True)
log_dir = root / 'run-logs'
log_dir.mkdir(exist_ok=True)
run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
prompt_file = root / ('KIMI_TASK_DATABASE.txt' if args.phase == 'database' else 'KIMI_TASK_TRACEABILITY.txt')
prompt = prompt_file.read_text(encoding='utf-8')
command = ['C:/Users/robot/.kimi-code/bin/kimi.exe', '-p', prompt,
           '--output-format', 'stream-json', '--skills-dir', str(root / '.kimi-skills')]
stdout_path = log_dir / (run_id + '-' + args.phase + '.stdout.jsonl')
stderr_path = log_dir / (run_id + '-' + args.phase + '.stderr.log')
with stdout_path.open('w', encoding='utf-8') as out, stderr_path.open('w', encoding='utf-8') as err:
    result = subprocess.run(command, cwd=root, env=env, stdout=out, stderr=err)
record = {'run_id': run_id, 'phase': args.phase, 'exit_code': result.returncode,
          'stdout': str(stdout_path.relative_to(root)), 'stderr': str(stderr_path.relative_to(root)),
          'review_required': True, 'implementation_completion_inferred': False}
(log_dir / (run_id + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=2))
raise SystemExit(result.returncode)
