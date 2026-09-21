"""Shared serialization, configuration, provenance and immutable-run helpers."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]

def config():
    return yaml.safe_load((ROOT / 'config/experiment.yaml').read_text())

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')

def command(args):
    try:
        p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=30)
        return {'argv': args, 'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'argv': args, 'returncode': None, 'error': str(e)}

def provenance():
    return {'config_sha256': digest(ROOT / 'config/experiment.yaml'),
            'source_sha256': source_digest(),
            'git': command(['git', 'rev-parse', 'HEAD']),
            'git_status': command(['git', 'status', '--porcelain']),
            'submodules': command(['git', 'submodule', 'status'])}

def source_digest():
    paths = []
    for folder in ('analysis', 'scripts', 'mininet', 'ifogsim', 'config', 'tests'):
        paths.extend(p for p in (ROOT / folder).rglob('*')
                     if p.is_file() and '__pycache__' not in str(p) and p.suffix != '.pyc')
    paths.extend(ROOT / n for n in ('requirements.txt', 'seeds.txt', 'Makefile'))
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()

def reserve_run(base, run_id):
    path = ROOT / base / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path

def seal(path):
    path = Path(path)
    files = {p.name: digest(p) for p in sorted(path.iterdir()) if p.is_file()}
    dump(path / 'SHA256SUMS.json', files)
    for p in path.iterdir():
        if p.is_file():
            p.chmod(0o444)
    # Hash verification is authoritative. chmod is an accidental-write guard,
    # not a claim of privileged-user-proof or physical WORM storage.

def verify_seal(path):
    path = Path(path)
    expected = json.loads((path / 'SHA256SUMS.json').read_text())
    actual = {p.name for p in path.iterdir() if p.is_file()} - {'SHA256SUMS.json'}
    if actual != set(expected):
        raise ValueError(f'File inventory changed: {path}')
    for name, sha in expected.items():
        if digest(path / name) != sha:
            raise ValueError(f'Raw data modified: {path / name}')

def wait_until(ns):
    while True:
        remaining = (ns - time.monotonic_ns()) / 1e9
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.05))
