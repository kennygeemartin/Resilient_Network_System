"""Capture failures as evidence as well as successful version probes."""
import datetime
import importlib.metadata
import platform
import sys
from scripts.common import ROOT, command, config, dump, source_digest

COMMANDS = {
    'uname':['uname','-a'], 'lsb_release':['lsb_release','-a'], 'lscpu':['lscpu'],
    'memory':['free','-b'], 'system_python':['python3','--version'],
    'analysis_python':[sys.executable,'--version'], 'java':['java','-version'],
    'mininet':['mn','--version'], 'ovs_vsctl':['ovs-vsctl','--version'],
    'ovs_ofctl':['ovs-ofctl','--version'], 'ovs_vswitchd':['ovs-vswitchd','--version'],
    'ovs_running':['ovs-vsctl','get','Open_vSwitch','.','ovs_version'],
    'pip_freeze':[sys.executable,'-m','pip','freeze'], 'git':['git','rev-parse','HEAD'],
    'submodules':['git','submodule','status'], 'git_dirty':['git','status','--porcelain'],
    'tc':['tc','-V'], 'iperf':['iperf3','--version'],
    'ifogsim_commit':['git','-C','third_party/ifogsim','rev-parse','HEAD'],
    'mininet_commit':['git','-C','third_party/mininet','rev-parse','HEAD'],
    'ifogsim_tag':['git','-C','third_party/ifogsim','tag','--points-at','HEAD'],
}

def capture():
    commands = {name:command(argv) for name,argv in COMMANDS.items()}
    packages = {}
    for name in ('numpy','pandas','scipy','statsmodels','matplotlib','PyYAML','networkx','psutil','os-ken','scapy'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    manifest = dict(captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        platform=platform.platform(),machine=platform.machine(),python=sys.version,
        python_executable=sys.executable,commands=commands,packages=packages,source_sha256=source_digest())
    from scripts.preflight import environment_errors
    manifest['errors'] = environment_errors(manifest)
    manifest['ready'] = not manifest['errors']
    dump(ROOT/'results/environment/environment_manifest.json',manifest)
    (ROOT/'results/environment/environment_capture.txt').write_text('\n\n'.join(
        f'$ {" ".join(COMMANDS[n])}\n{r}' for n,r in commands.items()))
    print(f'Environment ready: {manifest["ready"]}')
    for error in manifest['errors']:
        print('BLOCKED:',error)
    return manifest

if __name__ == '__main__':
    capture()
