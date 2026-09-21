"""Explicit paired run matrix and architecture-independent stochastic realizations."""
import argparse
import hashlib
import json
import random
from scripts.common import ROOT, config, dump

def seeds():
    values = [int(s) for s in (ROOT / config()['seeds_file']).read_text().split()]
    if len(set(values)) != len(values) or len(values) < 30:
        raise ValueError('At least 30 unique seeds required')
    return values

def conditions(supplemental=False):
    c = config()
    for fault in c['faults']['phase1']:
        yield dict(phase=1, scenario=fault, fault=fault, load='nominal', attack=None, architectures=c['architectures'])
    for load in c['loads']:
        yield dict(phase=2, scenario='load_' + load, fault='none', load=load, attack=None, architectures=c['architectures'])
    for load in ('nominal', '3x'):
        yield dict(phase=3, scenario='overhead_' + load, fault='none', load=load, attack=None, architectures=['A2', 'A3'])
    # Each attack replication has both A2 baseline and A3 protection, plus a legitimate control.
    for attack in c['security_attacks']:
        yield dict(phase=4, scenario='security_' + attack, fault='none', load='nominal', attack=attack, architectures=['A2', 'A3'])
    if supplemental:
        for period in c['traffic']['control_periods_ms']:
            yield dict(phase=5, scenario=f'flapping_p{period}', fault='link_flapping', load='nominal', attack=None,
                       period_ms=period, architectures=c['architectures'])

def realization(seed, condition, smoke=False):
    c = config()
    key = f"{seed}:{condition['scenario']}"
    rng = random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big'))
    timing = dict(c['timing'])
    if smoke:
        timing.update(duration_s=12, warmup_s=2, fault_s=4, restore_s=7, recovery_end_s=10)
    alarms = []
    for i in range(c['topology']['cells'] * c['topology']['sensors_per_cell']):
        t, events = 0.0, []
        while True:
            t += rng.expovariate(c['traffic']['C1']['events_per_s'])
            if t >= timing['duration_s']:
                break
            events.append(round(t * 1e9))
        alarms.append(events)
    cell = rng.randrange(1, c['topology']['cells'] + 1)
    return dict(seed=seed, scenario=condition['scenario'], timing=timing,
                fault_cell=cell, fault_link=[f'a{cell}', 'g1'], alarms_ns=alarms,
                flow_phase_ns=[rng.randrange(0, 1000000) for _ in alarms],
                period_ms=condition.get('period_ms', c['traffic']['control_period_ms']),
                load_multiplier=c['loads'][condition['load']])

def workload_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def matrix(supplemental=False):
    for seed in seeds():
        for condition in conditions(supplemental):
            arches = list(condition['architectures'])
            random.Random(f"order:{seed}:{condition['scenario']}").shuffle(arches)
            for order, arch in enumerate(arches):
                item = {k:v for k,v in condition.items() if k != 'architectures'}
                item.update(seed=seed, architecture=arch, order=order,
                            run_id=f"p{condition['phase']}_{condition['scenario']}_{seed}_{arch}")
                yield item

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--supplemental', action='store_true')
    args = parser.parse_args()
    rows = list(matrix(args.supplemental))
    dump(ROOT / 'results/processed/run_matrix.json', rows)
    print(f'{len(rows)} Mininet runs; {len(seeds())} independent paired seeds')
