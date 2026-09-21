"""Fail-closed environment and evidence gate before publication runs."""
import argparse
import json
import re
import subprocess
import sys
from scripts.common import ROOT, config, digest, dump, source_digest, verify_seal

def environment_errors(manifest):
    errors = []
    commands = manifest['commands']
    def output(name):
        v = commands[name]
        return v.get('stdout','')+v.get('stderr','')
    if not ('Ubuntu' in output('lsb_release') and '22.04' in output('lsb_release')):
        errors.append('Ubuntu 22.04 is required')
    if manifest['machine'].lower() not in ('x86_64','amd64'):
        errors.append('x86-64 architecture required')
    if not manifest['python'].startswith('3.10.') or 'Python 3.10.' not in output('system_python'):
        errors.append('System and analysis Python 3.10.x required')
    for name,pattern in [('java',r'version "11\.'),('mininet',r'2\.3\.1b4'),
                         ('ovs_vsctl',r'3\.7\.1'),('ovs_ofctl',r'3\.7\.1'),('ovs_running',r'3\.7\.1')]:
        if not re.search(pattern,output(name)):
            errors.append(f'{name} version mismatch or unavailable')
    for name,sha in [('ifogsim_commit','643c433'),('mininet_commit','88f14e9')]:
        if not output(name).strip().startswith(sha):
            errors.append(f'{name} is not pinned')
    if 'v2.0.0' not in output('ifogsim_tag'):
        errors.append('iFogSim release tag mismatch')
    if manifest['packages'].get('os-ken') != '4.2.2':
        errors.append('OS-Ken 4.2.2 required')
    for name,version in manifest['packages'].items():
        if version is None:
            errors.append(f'Missing Python package: {name}')
    for line in (ROOT/'requirements.txt').read_text().splitlines():
        if '==' in line:
            name,wanted=line.split(';')[0].strip().split('==')
            if manifest['packages'].get(name)!=wanted:
                errors.append(f'Package version mismatch: {name}, expected {wanted}')
    for name in ('uname','lsb_release','lscpu','memory','java','mininet','ovs_vsctl','ovs_ofctl','ovs_running','pip_freeze','git','submodules','tc','iperf'):
        if commands[name]['returncode'] != 0:
            errors.append(f'Environment command failed: {name}')
    return errors

def require_environment():
    from scripts.capture_environment import capture
    manifest = capture()
    if manifest['errors']:
        raise RuntimeError('Environment preflight failed; see results/environment/environment_manifest.json')

def require_gate():
    gate = json.loads((ROOT/'results/environment/preflight_gate.json').read_text())
    if not gate.get('passed') or gate['source_sha256'] != source_digest():
        raise RuntimeError('Missing/stale preflight evidence; run make preflight after make smoke')
    smoke = ROOT/gate['smoke_path']
    verify_seal(smoke)
    if digest(smoke/'SHA256SUMS.json')!=gate['smoke_sha256']:
        raise RuntimeError('Smoke evidence changed')

def gate():
    require_environment()
    subprocess.run([sys.executable,'-m','scripts.validate_topology'],check=True,cwd=ROOT)
    subprocess.run([sys.executable,'-m','scripts.run_tests'],check=True,cwd=ROOT)
    tests=json.loads((ROOT/'results/environment/unit_tests.json').read_text())
    if tests['skipped']:
        raise RuntimeError('Target preflight requires all tests, including actual OS-Ken serialization')
    subprocess.run([sys.executable,'-m','scripts.audit_constants'],check=True,cwd=ROOT)
    path = ROOT/'results/smoke/mininet/smoke_1001_A3'
    verify_seal(path)
    meta = json.loads((path/'metadata.json').read_text())
    if meta['status']!='complete' or not meta['smoke'] or meta['provenance']['source_sha256']!=source_digest():
        raise RuntimeError('A complete smoke run from this source revision is required')
    from analysis.metrics import read_cycles
    _,cycles,_ = read_cycles(path)
    critical=cycles[cycles['class']=='C0']
    if critical.flow_id.nunique()!=8 or not critical.success.any():
        raise RuntimeError('Smoke traffic missing or no successful service cycle')
    events = (path/'controller_events.jsonl').read_text()
    if 'openflow_error' in events or 'port_status' not in events or 'ready' not in events:
        raise RuntimeError('Smoke controller/fault evidence incomplete')
    compute=ROOT/'results/smoke/ifogsim/compute_nominal_1001_A3'
    verify_seal(compute)
    compute_meta=json.loads((compute/'metadata.json').read_text())
    if (compute_meta['status']!='complete' or compute_meta.get('development_only') or
        compute_meta['provenance']['source_sha256']!=source_digest()):
        raise RuntimeError('A real target-environment iFogSim smoke run is required')
    from analysis.metrics import network_run_metrics
    metrics=network_run_metrics(path)
    dump(ROOT/'results/environment/smoke_metrics.json',metrics)
    tree = '\n'.join(str(p.relative_to(ROOT)) for p in sorted(ROOT.rglob('*'))
                     if p.is_file() and not any(x in p.parts for x in ('.git','.venv','.tools','third_party','__pycache__','work')))
    (ROOT/'results/environment/repository_tree.txt').write_text(tree+'\n')
    dump(ROOT/'results/environment/preflight_gate.json',dict(passed=True,source_sha256=source_digest(),
         smoke_path=path.relative_to(ROOT).as_posix(),smoke_sha256=digest(path/'SHA256SUMS.json')))
    print(tree)
    print((ROOT/'results/environment/environment_manifest.json').read_text())
    print((path/'flow_summary.csv').read_text())
    print('Preflight passed: topology, controller tests, one-seed smoke, constant audit.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--gate',action='store_true')
    args = p.parse_args()
    gate() if args.gate else require_environment()
